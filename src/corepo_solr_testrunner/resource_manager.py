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
import logging
import os
import subprocess
import sys
import requests
import time

from os_python.common.net.iserver import IServer
from os_python.common.utils.init_functions import die
from os_python.common.utils.init_functions import NullHandler

from os_python.docker.docker_container import DockerContainer
from os_python.docker.docker_container import ContainerSuitePool
from configobj import ConfigObj

sys.path.insert( 0, os.path.dirname( os.path.dirname( os.path.dirname( os.path.realpath( sys.argv[0] ) ) ) ) )
from acceptance_tester.abstract_testsuite_runner.resource_manager import AbstractResourceManager
from os_python.wiremock_helper import wiremock_load_rules_from_dir

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

        corepo_db = suite.create_container("corepo-db", image_name=DockerContainer.secure_docker_image('corepo-postgresql-1.2'),
                             name="corepo-db" + suite_name,
                             environment_variables={"POSTGRES_USER": "corepo",
                                                    "POSTGRES_PASSWORD": "corepo",
                                                    "POSTGRES_DB": "corepo"},
                             start_timeout=1200)
        corepo_db.start()
        corepo_db_url = "corepo:corepo@%s:5432/corepo" % corepo_db.get_ip()
        corepo_db.waitFor("database system is ready to accept connections")

        # Migrate corepo before starting services
        ingest_tool = os.path.join(self.resource_folder, 'corepo-ingest-1.1-SNAPSHOT.jar')
        exe_cmd = ["java", "-jar", ingest_tool, "--db=%s"%corepo_db_url, "--allow-fail", "--debug"]

        logger.debug( "Execute ingest to migrate: %s"%' '.join( exe_cmd ) )

        result = subprocess.Popen(exe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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
                                                               "SOLR_DOC_STORE_QUEUE_NAMES": "to-solr"},
                                        
                             start_timeout=1200)
        sds_db.start()
        sds_db_url = "sds:sds@%s:5432/sds" % sds_db.get_ip()


        corepo_solr = suite.create_container("corepo-solr", image_name=DockerContainer.secure_docker_image('corepo-indexer-solr-1.1'),
                             name="corepo-solr" + suite_name,
                             start_timeout=1200,
                             mem_limit=2048)
        corepo_solr.start()
        corepo_solr_ip = corepo_solr.get_ip()

        wiremock = suite.create_container("wiremock", image_name=DockerContainer.secure_docker_image('os-wiremock-1.0-snapshot'),
                             name="wiremock" + suite_name,
                             start_timeout=1200)
        wiremock.start()
        open_agency_url = "http://%s:8080" % wiremock.get_ip()

        wiremock.waitFor("verbose:")
        wiremock_load_rules_from_dir("http://%s:8080" % wiremock.get_ip(), self.resource_folder)

        corepo_content_service = suite.create_container("corepo-content-service",
                                                        image_name=DockerContainer.secure_docker_image('corepo-content-service-1.2'),
                                                        name="corepo-content-service" + suite_name,
                                                        environment_variables={"COREPO_POSTGRES_URL": corepo_db_url,
                                                                               "OPEN_AGENCY_URL": open_agency_url,
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
                                                                                  "OPEN_AGENCY_URL": open_agency_url},
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
                                                                                "OPEN_AGENCY_URL": open_agency_url,
                                                                                "SEARCH_PATH": "file:/javascriptlocal file:/javascript file:/javascript/standard-index-values",
                                                                                "QUEUES": "to-indexer",
                                                                                "EMPTY_QUEUE_SLEEP": "10s",
                                                                                "LOG__dk_dbc": log_level,
                                                                                "LOG__JavaScript_Logger": log_level,
                                                                                "JAVA_MAX_HEAP_SIZE": "2G",
                                                                                "QUEUE_WINDOW": "1000ms"},
                                                         volumes=volumes,
                                                         start_timeout=1200,
                                                         mem_limit=2048)

        solr_doc_store_updater = suite.create_container("solr_doc-store-updater",
                                                           image_name=DockerContainer.secure_docker_image('solr-doc-store-updater-1.0'),
                                                           name="solr-doc-store-updater" + suite_name,
                                                           environment_variables={"SOLR_DOC_STORE_URL": solr_doc_store_url,
                                                                                  "SOLR_DOC_STORE_DATABASE": sds_db_url,
                                                                                  "EMPTY_QUEUE_SLEEP": "2500ms",
                                                                                  "QUEUES": "to-solr",
                                                                                  "COLLECTION": "updater",
                                                                                  "PROFILE_SERVICE_URL": "",
                                                                                  "SCOPE": "updater",
                                                                                  "SCAN_PROFILES": "",
                                                                                  "SCAN_DEFAULT_FIELDS": "",
                                                                                  "SOLR_APPID": "acceptancetest-doc-store-updater",
                                                                                  "SOLR_URL": "http://%s:8983/solr/corepo" % corepo_solr_ip,
                                                                                  "LOG__dk_dbc": "TRACE",
                                                                                  "JAVA_MAX_HEAP_SIZE": "2G",
                                                                                  "OPEN_AGENCY_URL": open_agency_url},
                                                           start_timeout=1200,
                                                           mem_limit=2048)


        corepo_solr.waitFor("Registered new searcher")

        for container in [solr_doc_store_updater, corepo_indexer_worker]:
            container.start()

        opensearch = suite.create_container("opensearch",
                                            image_name=DockerContainer.secure_docker_image('opensearch-4.5'),
                                            name="opensearch" + suite_name,
                                            environment_variables={"FEDORA":"",
                                                                   "AGENCY_PROFILE_FALLBACK": "test",
                                                                   "AGENCY_FALLBACK": 100200,
                                                                   "AGENCY_END_POINT": "http://openagency.addi.dk/test_2.34/",
                                                                   "FEDORA": "http://%s:8080/rest/objects/" % corepo_content_service_ip,
                                                                   "SOLR": "http://%s:8983/solr/corepo/select" % corepo_solr_ip,
                                                                   "HOLDINGS_ITEMS_INDEX": "",
                                                                   "RAW_RECORD_SOLR": "",
                                                                   "RAW_RECORD_CONTENT_SERVICE": "",
                                                                   "HOLDINGS_DB": "",
                                                                   "VERBOSE_LEVEL": "TRACE+WARNING+ERROR+FATAL+STAT+TIMER",
                                                                   "OPEN_FORMAT": ""},
                                            start_timeout=1200)
        # TODO upgrade to 5.0. Needs IP authentication_error fix to work
        #opensearch = suite.create_container("opensearch",
                                            #image_name=DockerContainer.secure_docker_image('opensearch-webservice-5.0'),
                                            #name="opensearch" + suite_name,
                                            #environment_variables={"AAA_IP_RIGHTS_BLOCK": "aaa_ip_rights[dbc][ip_list] = 0.0.0.0-255.255.255.255 aaa_ip_rights[dbc][ressource][opensearch] = 500",
                                                                   #"AGENCY_CACHE_SETTINGS": "",
                                                                   #"AGENCY_END_POINT": "https://openagency.addi.dk/test_2.34/",
                                                                   #"AGENCY_FALLBACK": 100200,
                                                                   #"AGENCY_PROFILE_FALLBACK": "test",
                                                                   #"CACHE_SETTINGS": "",
                                                                   #"FEDORA": "http://%s:8080/rest/" % corepo_content_service_ip,
                                                                   #"HOLDINGS_DB": "",
                                                                   #"HOLDINGS_ITEMS_INDEX": "",
                                                                   #"MY_DOMAIN_IP_LIST": "0.0.0.0-255.255.255.255",
                                                                   #"NETPUNKT_OPEN_FORMAT": "http://php-openformat-prod.mcp1-proxy.dbc.dk/server.php",
                                                                   #"OPEN_FORMAT": "http://openformat.addi.dk/0.2/",
                                                                   #"RAW_RECORD_CONTENT_SERVICE": "http://content-service.rawrepo.fbstest.mcp1.dbc.dk/RawRepoContentService",
                                                                   #"RAW_RECORD_REPOSITORY_NAME": "raw_repo_ext_test",
                                                                   #"RAW_RECORD_SOLR": "http://fbstest:8983/solr/fbstest-rawrepo-searcher/select",
                                                                   #"REPOSITORY_NAME": "external_test",
                                                                   #"SERVICE_LOCATION": "",
                                                                   #"SOLR": "http://%s:8983/solr/corepo/select" % corepo_solr_ip,
                                                                   #"URL_PATH": "fbstest",
                                                                   #"USE_HOLDING_BLOCK_JOIN": "CHECK",
                                                                   #"VERBOSE_LEVEL": "WARNING+ERROR+FATAL+STAT+TIMER+TRACE+DEBUG"},
                                            #start_timeout=1200)
        opensearch.start()

        # Looking for e.g.
        #INFO: Payara Server  5.181 #badassfish (213) startup time : Felix (2,110ms), startup services(9,965ms), total(12,075ms)

        for container in [corepo_indexer_worker, solr_doc_store_updater]:
            container.waitFor("Instance Configuration")

        opensearch.waitFor("resuming normal operations")

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

        self.required_artifacts = {'wiremock-rules-openagency': ['wiremock-rules-openagency.zip', 'os-wiremock-rules']}
        for artifact in self.required_artifacts:
            self.required_artifacts[artifact].append(self._secure_artifact(artifact, *self.required_artifacts[artifact]))

        logger.info( "Fetch corepo-ingest from maven repository." )

        # Must use maven-dependency-plugin:2.8 to support get file
        exe_cmd = ["mvn",
                   "org.apache.maven.plugins:maven-dependency-plugin:2.8:get",
                   "-Ddest=%s" % self.resource_folder,
                   "-Dartifact=dk.dbc:corepo-ingest:1.1-SNAPSHOT",
                   "-DremoteRepositories=http://mavenrepo.dbc.dk/nexus/content/groups/public"]
        result = subprocess.Popen(exe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = result.communicate()
        if result.returncode != 0:
            die("Something went during maven call %s" % stdout + stderr)

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
