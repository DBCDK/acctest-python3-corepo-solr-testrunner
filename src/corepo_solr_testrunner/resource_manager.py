#!/usr/bin/env python
# -*- coding: utf-8 -*-
# -*- mode: python -*-
"""
:mod:`corepo_solr_testrunner.resource_manager` -- Resource manager for corepo-solr
==================================================================================

============================
Fcrepo-solr resource manager
============================

Resource Manager for corepo-service/solr integration
testing.
"""
import json
import logging
import os
import subprocess
import sys
import requests
import time

import os_python.common.net.url

from os_python.common.net.iserver import IServer
from os_python.common.utils.init_functions import die
from os_python.common.utils.init_functions import NullHandler

from os_python.docker.docker_container import DockerContainer
from os_python.docker.docker_container import ContainerSuitePool
from configobj import ConfigObj

sys.path.insert( 0, os.path.dirname( os.path.dirname( os.path.dirname( os.path.realpath( sys.argv[0] ) ) ) ) )
from acceptance_tester.abstract_testsuite_runner.resource_manager import AbstractResourceManager
from os_python.wiremock_helper import wiremock_load_vipcore_from_dir

### define logger
logger = logging.getLogger( "dbc."+__name__ )
logger.addHandler( NullHandler() )

class ContainerPoolImpl(ContainerSuitePool):

    def __init__(self, resource_folder, resource_config):
        super(ContainerPoolImpl, self).__init__()
        self.resource_folder = resource_folder
        self.resource_config = resource_config

    def create_suite(self, suite):

        suite_name = "_corepo_solr_%f" % time.time()

        corepo_db = suite.create_container("corepo-db", image_name=DockerContainer.secure_docker_image('corepo-postgresql-1.4'),
                             name="corepo-db" + suite_name,
                             environment_variables={"POSTGRES_USER": "corepo",
                                                    "POSTGRES_PASSWORD": "corepo",
                                                    "POSTGRES_DB": "corepo"},
                             start_timeout=1200)
        corepo_db.start()
        corepo_db_url = "corepo:corepo@%s:5432/corepo" % corepo_db.get_ip()
        corepo_db.waitFor("database system is ready to accept connections")

        # Migrate corepo before starting services
        ingest_tool = os.path.join(self.resource_folder, 'corepo-ingest.jar')
        exe_cmd = ["java", "-jar", ingest_tool, "--db=%s"%corepo_db_url, "--allow-fail", "--debug"]

        logger.debug( "Execute ingest to migrate: %s"%' '.join( exe_cmd ) )

        result = subprocess.Popen(exe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        stdout, stderr = result.communicate()
        if result.returncode != 0:
            die("Something went during ingest call %s" % stdout + stderr)

        #logger.debug( "Execute ingest to migrate: %s,%s"% (stdout, stderr))
        logger.debug( "Execute ingest to migrate: %s"% stderr)


        sds_db = suite.create_container("solr-doc-store-db",
                                        image_name=DockerContainer.secure_docker_image('solr-doc-store-postgresql-1.0'),
                                        name="solr-doc-store-db" + suite_name,
                                        environment_variables={"POSTGRES_USER": "sds",
                                                               "POSTGRES_PASSWORD": "sds",
                                                               "POSTGRES_DB": "sds",
                                                               "SOLR_DOC_STORE_QUEUES": "to-solr|manifestation|0,to-solr|manifestation_deleted|0"},
                                        
                             start_timeout=1200)
        sds_db.start()
        sds_db_url = "sds:sds@%s:5432/sds" % sds_db.get_ip()


        corepo_solr = suite.create_container("corepo-solr", image_name=DockerContainer.secure_docker_image('corepo-indexer-solr-1.1'),
                             name="corepo-solr" + suite_name,
                             start_timeout=1200,
                             mem_limit=2048)
        corepo_solr.start()
        corepo_solr_ip = corepo_solr.get_ip()

        work_presentation = suite.create_container("work_presentation", image_name=DockerContainer.secure_docker_image('os-wiremock-1.0-snapshot'),
                             name="work_presentation" + suite_name,
                             start_timeout=1200)
        work_presentation.start()
        work_presentation_url = "http://%s:8080" % work_presentation.get_ip()

        work_presentation.waitFor("verbose:")

        work_mock = {
            "request": {
                "urlPattern": "/api/work-presentation/getPersistentWorkId\\?corepoWorkId=.*",
                "method": "GET"
            },
            "response": {
                "status": 200,
                "headers": {
                "Content-Type": "application/json"
                },
                "body": "work-of:foo"
            }
        }

        os_python.common.net.url.doURL( work_presentation_url + "/__admin/mappings/new", data = json.dumps( work_mock ).encode('utf-8'), content_type = 'application/json', timeout=120 )

        vipcore = suite.create_container("vipcore", image_name=DockerContainer.secure_docker_image('os-wiremock-1.0-snapshot'),
                             name="vipcore" + suite_name,
                             start_timeout=1200)
        vipcore.start()
        vip_url = "http://%s:8080" % vipcore.get_ip()

        vipcore.waitFor("verbose:")
        wiremock_load_vipcore_from_dir("http://%s:8080" % vipcore.get_ip(), self.resource_folder)

        corepo_content_service = suite.create_container("corepo-content-service",
                                                        image_name=DockerContainer.secure_docker_image('corepo-content-service-1.4'),
                                                        name="corepo-content-service" + suite_name,
                                                        environment_variables={"COREPO_POSTGRES_URL": corepo_db_url,
                                                                               "VIPCORE_ENDPOINT": vip_url,
                                                                               "LOG__dk_dbc": "TRACE",
                                                                               "JAVA_MAX_HEAP_SIZE": "2G",
                                                                               "PAYARA_STARTUP_TIMEOUT": 1200},
                                                        start_timeout=1200,
                                                        mem_limit=2048)

        solr_doc_store_service = suite.create_container("solr-doc-store-service",
                                                           image_name=DockerContainer.secure_docker_image('solr-doc-store-service-1.0'),
                                                           name="solr-doc-store-service" + suite_name,
                                                           environment_variables={"ALLOW_NON_EMPTY_SCHEMA": "true",
                                                                                  "DOCSTORE_POSTGRES_URL": sds_db_url,
                                                                                  "LOG__dk_dbc": "TRACE",
                                                                                  #"LOG_LEVEL": "TRACE",
                                                                                  "JAVA_MAX_HEAP_SIZE": "2G",
                                                                                  "MAX_POOL_SIZE": "2",
                                                                                  "VIPCORE_ENDPOINT": vip_url},
                                                           start_timeout=1200,
                                                           mem_limit=2048)

        solr_doc_store_monitor = suite.create_container("solr-doc-store-monitor",
                                                           image_name=DockerContainer.secure_docker_image('solr-doc-store-monitor-1.0'),
                                                           name="solr-doc-store-monitor" + suite_name,
                                                           environment_variables={ "DOCSTORE_POSTGRES_URL": sds_db_url,
                                                                                   "JAVA_MAX_HEAP_SIZE": "2G"},
                                                           start_timeout=1200,
                                                           mem_limit=2048)

        sds_db.waitFor("database system is ready to accept connections")
        solr_doc_store_service.start()
        solr_doc_store_url = "http://%s:8080"%solr_doc_store_service.get_ip()
        solr_doc_store_service.waitFor("Instance Configuration")

        solr_doc_store_monitor.start()
        solr_doc_store_monitor.waitFor("Instance Configuration")

        logger.debug("configured resource %s" % (self.resource_config))
        # Use local javascript if .ini file set
        volumes = None
        if 'javascript' in self.resource_config:
            # Copy to an other directory, or jscommon folder will be hidden
            volumes={self.resource_config['javascript']: "/javascriptlocal"}
            logger.debug("configured volumes %s" % (volumes))

        if 'loglevel' in self.resource_config:
            log_level = self.resource_config['loglevel']
        else:
            log_level = "DEBUG"
        logger.debug("Loglevel for worker is %s" % (log_level))

        corepo_content_service.start()
        corepo_content_service_ip = corepo_content_service.get_ip()
        corepo_content_service.waitFor("was successfully deployed in")

        corepo_indexer_worker = suite.create_container( "corepo-indexer-worker",
                                                         image_name=DockerContainer.secure_docker_image('corepo-indexer-worker-1.1'),
                                                         name="corepo-indexer-worker" + suite_name,
                                                         environment_variables={"COREPO_CONTENT_SERVICE_URL": "http://%s:8080" % (corepo_content_service_ip),
                                                                                "COREPO_POSTGRES_URL": corepo_db_url,
                                                                                "SOLR_DOC_STORE_URL": solr_doc_store_url,
                                                                                "FORS_RIGHTS_URL": "http://localhost/forsRights/",
                                                                                "VIPCORE_ENDPOINT": vip_url,
                                                                                "SEARCH_PATH": "file:/javascriptlocal file:/javascript file:/javascript/standard-index-values",
                                                                                "QUEUES": "to-indexer",
                                                                                "EMPTY_QUEUE_SLEEP": "1s",
                                                                                "LOG__dk_dbc": log_level,
                                                                                "LOG__JavaScript_Logger": log_level,
                                                                                "JAVA_MAX_HEAP_SIZE": "3G",
                                                                                "QUEUE_WINDOW": "1000ms"},
                                                         volumes=volumes,
                                                         start_timeout=1200,
                                                         mem_limit=2048)

        solr_doc_store_updater = suite.create_container("solr_doc-store-updater",
                                                           image_name=DockerContainer.secure_docker_image('solr-doc-store-updater-1.0'),
                                                           name="solr-doc-store-updater" + suite_name,
                                                           environment_variables={"SOLR_DOC_STORE_URL": solr_doc_store_url,
                                                                                  "SOLR_DOC_STORE_DATABASE": sds_db_url,
                                                                                  "EMPTY_QUEUE_SLEEP": "1000ms",
                                                                                  "QUEUES": "to-solr",
                                                                                  "COLLECTION": "updater",
                                                                                  "PROFILE_SERVICE_URL": "",
                                                                                  "SCOPE": "updater",
                                                                                  "SCAN_PROFILES": "",
                                                                                  "SCAN_DEFAULT_FIELDS": "",
                                                                                  "SOLR_APPID": "acceptancetest-doc-store-updater",
                                                                                  "SOLR_URL": "http://%s:8983/solr/corepo=all-persistentWorkId" % corepo_solr_ip,
                                                                                  "WORK_PRESENTATION_URL": "http://localhost:1/not-used",
                                                                                  "LOG__dk_dbc": "TRACE",
                                                                                  "JAVA_MAX_HEAP_SIZE": "2G",
                                                                                  "WORK_PRESENTATION_ENDPOINT": work_presentation_url,
                                                                                  "VIPCORE_ENDPOINT": vip_url},
                                                           start_timeout=1200,
                                                           mem_limit=2048)


        corepo_solr.waitFor("Registered new searcher")

        for container in [solr_doc_store_updater, corepo_indexer_worker]:
            container.start()

        # Looking for e.g.
        #INFO: Payara Server  5.181 #badassfish (213) startup time : Felix (2,110ms), startup services(9,965ms), total(12,075ms)
        for container in [corepo_indexer_worker, solr_doc_store_updater]:
            container.waitFor("Instance Configuration")


    def on_release(self, name, container):
        logger.debug("Releasing %s on container %s" % (name, container))
        if name == "corepo-db":
            container.execute("psql -c \"SELECT PG_TERMINATE_BACKEND(pid) FROM pg_stat_activity WHERE state = 'idle in transaction'; TRUNCATE records CASCADE\" corepo")
        if name == "corepo-solr":
            # Save a dump of solr data
            #dump_file_name = container.log_file+".dump.json"
            #logger.debug("Writing dump '%s'" % dump_file_name)
            #dump_file = open(dump_file_name,'w')
            #dump_file.write(json.dumps( "http://%s:8983/solr/corepo/select?q=*:*&wt=json" % container.get_ip(), indent=4))
            # Wipe SOLR
            url = "http://%s:8983/solr/corepo/update?stream.body=<delete><query>*:*</query></delete>&commit=true" % container.get_ip()
            logger.debug(requests.get(url))
        if name == "solr-doc-store-db":
            container.execute("psql -c 'TRUNCATE bibliographicsolrkeys CASCADE' sds")
            container.execute("psql -c 'TRUNCATE holdingsitemssolrkeys CASCADE' sds")
            container.execute("psql -c 'TRUNCATE holdingstobibliographic CASCADE' sds")
            container.execute("psql -c 'TRUNCATE bibliographictobibliographic CASCADE' sds")
            container.execute("psql -c 'TRUNCATE queue CASCADE' sds")
            container.execute("psql -c 'TRUNCATE queue_error CASCADE' sds")
        if name == 'solr-doc-store-service':
            url = "http://%s:8080/api/evict-all" % container.get_ip()
            logger.debug(requests.get(url))

class ResourceManager( AbstractResourceManager ):

    def __init__( self, resource_folder, tests, use_preloaded, use_config, port_range=( 11000, 12000 )):
        self.use_config_resources = use_config
        self.resource_config = ConfigObj(self.use_config_resources)
        self.use_preloaded_resources = use_preloaded

        self.resource_folder = resource_folder
        if not os.path.exists( self.resource_folder ):
            os.mkdir( self.resource_folder )

        self.container_pool = ContainerPoolImpl(self.resource_folder, self.resource_config)

        self.required_artifacts = {'wiremock-vipcore': ['wiremock-vipcore.zip', 'os-wiremock-rules'], 'corepo-ingest': ['corepo-ingest.jar', 'corepo/job/master']}
        for artifact in self.required_artifacts:
            self.required_artifacts[artifact].append(self._secure_artifact(artifact, *self.required_artifacts[artifact]))

    def shutdown(self):
        self.container_pool.shutdown()

    def _secure_artifact(self, name, artifact, project, build_number=None):
        if name in self.resource_config:
            logger.debug("configured resource %s at %s" % (name, self.resource_config[name]))
            return self.resource_config[name]

        if self.use_preloaded_resources == False:
            logger.debug( "Downloading %s artifact from integration server"%artifact )
            iserv = IServer( temp_folder=self.resource_folder, project_name=project )

            return iserv.download_and_validate_artifact( self.resource_folder, artifact, build_number=build_number)

        logger.debug("Using preloaded %s artifact"%artifact)
        preloaded_artifact = os.path.join(self.resource_folder, artifact)

        return preloaded_artifact

