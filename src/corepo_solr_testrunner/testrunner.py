#!/usr/bin/env python
# -*- coding: utf-8 -*-
# -*- mode: python -*-
"""
:mod:`corepo_solr_testrunner.testrunner` -- Testrunner for corepo-solr
======================================================================

======================
corepo-solr Testrunner
======================

This class executes xml test files of type 'corepo-solr'.
"""
import logging
import os

from nose.tools import nottest
from os_python.common.utils.init_functions import NullHandler
from os_python.common.utils.cleanupstack import CleanupStack

from acceptance_tester.abstract_testsuite_runner.test_runner import TestRunner as AbstractTestRunner

from os_python.solr.solr_parser import SolrParser
from os_python.opensearch_parser import OpenSearchParser
from os_python.solr.solr_gdih_parser import SolrGDIHParser
from os_python.solr.solr_doc_store import SolrDocStore
from os_python.openagency_parser import OpenAgencyParser
from os_python.corepo.corepo import Corepo
from os_python.corepo.corepo_parser import CorepoParser
from os_python.solr.solr_docker_gdih import SolrDockerGDIH
from os_python.connectors.solr import Solr
from os_python.connectors.opensearch import OpenSearch
from os_python.connectors.corepo import CorepoContentService
from os_python.connectors.openagency_mock import OpenAgencyMock

### define logger
logger = logging.getLogger( "dbc." + __name__ )
logger.addHandler( NullHandler() )

class TestRunner( AbstractTestRunner ):

    @nottest
    def run_test( self, test_xml, build_folder, resource_manager ):
        """
        Runs a 'corepo-solr' test.

        This method runs a test and puts the result into the
        failure/error lists accordingly.

        :param test_xml:
            Xml object specifying test.
        :type test_xml:
            lxml.etree.Element
        :param build_folder:
            Folder to use as build folder.
        :type build_folder:
            string
        :param resource_manager:
            Class used to secure reources.
        :type resource_manager:
            class that inherits from
            acceptance_tester.abstract_testsuite_runner.resource_manager

        """

        container_suite = resource_manager.container_pool.take(log_folder=self.logfolder)
        stop_stack = CleanupStack.getInstance()
        try:
            corepo_db = container_suite.get("corepo-db", build_folder)
            corepo_content_service = container_suite.get("corepo-content-service", build_folder)
            corepo_solr = container_suite.get("corepo-solr", build_folder)
            solr_doc_store_monitor = container_suite.get("solr-doc-store-monitor", build_folder)
            opensearch = container_suite.get("opensearch", build_folder)
            wiremock = container_suite.get("wiremock", build_folder)
            vipcore = container_suite.get("vipcore", build_folder)
            corepo_db = container_suite.get("corepo-db", build_folder)

            gdih = SolrDockerGDIH(corepo_db)

            solr_url = "http://%s:8983/solr" % corepo_solr.get_ip()

            # connectors
            solr_connector = Solr(solr_url, build_folder)
            solr_doc_store_monitor_ip = "http://%s:8080" % solr_doc_store_monitor.get_ip()
            opensearch_connector = OpenSearch("http://%s/opensearch/" % opensearch.get_ip())

            ingest_tool = os.path.join(resource_manager.resource_folder, 'corepo-ingest.jar')
            corepo_connector = Corepo(corepo_db, corepo_content_service, ingest_tool, os.path.join(build_folder, 'ingest'))

            openagency_connector = OpenAgencyMock("http://%s:8080" % wiremock.get_ip(), proxy="https://openagency.addi.dk/test_2.34/")

            ### Setup parsers
            parsers = []
            parsers.append(CorepoParser(self.base_folder, corepo_connector))
            parsers.append(SolrParser(self.base_folder, solr_connector))
            parsers.append(SolrGDIHParser(self.base_folder, gdih, solr_connector, SolrDocStore(solr_doc_store_monitor_ip)))
            parsers.append(OpenSearchParser(self.base_folder, opensearch_connector))
            parsers.append(OpenAgencyParser(openagency_connector))
            for parser in parsers:
                self.parser_functions.update(parser.parser_functions)

            stop_stack.addFunction(self.save_service_logfiles, corepo_connector, 'corepo')
            stop_stack.addFunction(self.save_service_logfiles, solr_connector, 'solr')
            corepo_connector.start()

            ### run the test
            self.parse( test_xml )

        except Exception as err:
            logger.error( "Caught error during testing: %s"%str(err))
            # TODO Restart images container_suite
            #resource_manager.container_pool.shutdown()
            #resource_manager.container_pool.take()
            raise

        finally:
            stop_stack.callFunctions()
            resource_manager.container_pool.release(container_suite)
