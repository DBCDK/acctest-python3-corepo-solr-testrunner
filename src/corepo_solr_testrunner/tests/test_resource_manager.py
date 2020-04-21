#!/usr/bin/env python
# -*- coding: utf-8 -*-
# -*- mode: python -*-
import logging
import os
import pkg_resources
import shutil
import subprocess
import sys
import tempfile
import unittest
from nose.plugins.skip import SkipTest
from mock import Mock

sys.path.insert( 0, os.path.dirname( os.path.dirname( os.path.dirname( os.path.dirname( os.path.abspath( sys.argv[0] ) ) ) ) ) )
from corepo_solr_testrunner.resource_manager import ResourceManager

from os_python.common.net.iserver import IServer

logging.disable( logging.ERROR )


iserver_pickup = None


def mock_dava( self, download_folder, artifact_name, md5_pre_validate=True ):
    return None


def mock_secure( self, resource, artifact, project ):
    return None


def mock_populate_dbnames( self ):
    return { 1: 'mockDBName1', 2: 'mockDBName2' }


def mock_get_dependencies( self ):
        return { 'mock_resource' : [ 'mock-artifact', 'mock-project-head' ] }

def mock_iserver_init( self ):
    return None

def mock_use_config():
    return ""

class TestResourceManager( unittest.TestCase ):

    def setUp( self ):
        global iserver_pickup
        iserver_pickup = None

        self.test_folder = tempfile.mkdtemp()

        self.tests = [{"build-folder": "foo", "id": 1, "report-file": "foo", "test-suite": "foo", "type": "foo", "type-name": "foo", "verbose": False, "xml": "foo" },
                      {"build-folder": "foo", "id": 2, "report-file": "foo", "test-suite": "foo", "type": "foo", "type-name": "foo", "verbose": False, "xml": "foo" }]

    def tearDown( self ):

        shutil.rmtree( self.test_folder )

    def test_dummy(self):
        pass

    def test_that_resource_folder_is_created_if_not_existing( self ):
        """ Test whether the resource folder is created if it does not exist.
        """
        #mock
        ResourceManager._secure_artifact = mock_secure
        ResourceManager._populate_dbnames = mock_populate_dbnames

        #test
        resource_folder = os.path.join( self.test_folder, "resources" )
        self.assertFalse( os.path.exists( resource_folder ) )
        rm = ResourceManager( resource_folder, self.tests, False, mock_use_config() )

        #self.assertTrue( os.path.exists( "/FOO" ) )
        self.assertTrue( os.path.exists( resource_folder ) )

    def test_that_resource_folder_is_present_after_init( self ):
        """ Test whether the resource folder is present after initialization, if where there already.
        """
        #mock
        ResourceManager._secure_artifact = mock_secure
        ResourceManager._populate_dbnames = mock_populate_dbnames

        #test
        resource_folder = os.path.join( self.test_folder, "resources" )
        os.mkdir( resource_folder )
        self.assertTrue( os.path.exists( resource_folder ) )
        rm = ResourceManager( resource_folder, self.tests, False, mock_use_config() )
        self.assertTrue( os.path.exists( resource_folder ) )

    def test_iserver_used_when_failing_to_find_preloaded_artifact( self ):
        """ Tests whether the iserver is used to retrieve artifact when failing to find preloaded.
        """
        ResourceManager._populate_dbnames = mock_populate_dbnames

        IServer.__init__ = mock_iserver_init
        IServer.download_and_validate_artifact = mock_dava

        use_preloaded_resources = True

        rm = ResourceManager( self.test_folder, self.tests, use_preloaded_resources, mock_use_config() )

        expected_is_url = "DEFAULT"
        expected_project_name = 'mock-project-head'

    def test_artifact_used_when_able_to_md5_verify_preloaded_artifact( self ):
        """ Tests that preloaded artifact is used when able to md5 verify.
        """
        ResourceManager._get_dependencies = mock_get_dependencies
        ResourceManager._populate_dbnames = mock_populate_dbnames

        resource_folder = os.path.join( self.test_folder, "resources" )
        os.mkdir( resource_folder )

        artifact_file = os.path.join( resource_folder, 'mock-artifact' )
        open( artifact_file, 'w' ).close()

        artifact_md5 = os.path.join( resource_folder, 'mock-artifact.md5' )
        f = open( artifact_md5, 'w' )
        f.write( 'd41d8cd98f00b204e9800998ecf8427e' )
        f.close()

        use_preloaded_resources = True

        rm = ResourceManager( resource_folder, self.tests, use_preloaded_resources, mock_use_config() )

        self.assertEqual( iserver_pickup, None )

if __name__ == '__main__':
    unittest.main()
