import unittest
import sys
import logging

from google.appengine.api import memcache
from google.appengine.ext import db
from google.appengine.ext import testbed

from siteinadropbox.handlers import dropboxhandlers
from siteinadropbox.handlers import resourcehandlers
from siteinadropbox.handlers import cdeferred
from siteinadropbox import controller
from siteinadropbox import models

from test import dbtools
from test import pickledsites
from test.dbtools import highlight

class ImmediateController(controller.BaseController):
    def handle_metadata_changes(self, created=[], updated=[], removed=[]):
        logging.debug('Handling metadata changed')
        for entry in created+updated:
            models.Resource.update(self, entry)

    def cdefer(self, obj, *args, **kwargs):
        taskargs = dict((x, kwargs.pop(("_%s" % x), None))
                        for x in ("countdown", "eta", "name"))
        taskargs["url"] = kwargs.pop("_url", cdeferred._DEFAULT_URL)
        taskargs["transactional"] = kwargs.pop("_transactional", False)
        taskargs["headers"] = cdeferred._TASKQUEUE_HEADERS
        taskargs["queue"] = kwargs.pop("_queue", cdeferred._DEFAULT_QUEUE)

        logging.debug('Immediately executing cdefer call. Options were: %s'%taskargs)
        logging.debug('Object to call: %s, args: %s, %s'%(obj, args, kwargs))
        obj(self, *args, **kwargs)

class ResourceTestCase(unittest.TestCase):
    def setUp(self):
        # First, create an instance of the Testbed class.
        self.testbed = testbed.Testbed()
        # Then activate the testbed, which prepares the service stubs for use.
        self.testbed.activate()
        # Next, declare which service stubs you want to use.
        self.testbed.init_datastore_v3_stub()
        self.testbed.init_memcache_stub()
        self.testbed.init_taskqueue_stub()
        # self.testbed.init_images_stub()
        # self.testbed.init_urlfetch_stub()
        self.testbed.init_user_stub()
        # self.testbed.init_xmpp_stub()


    def tearDown(self):
        self.testbed.deactivate()

    def syncto(self,name):
        self.gov = ImmediateController(pickledsites.make_fake_site(name))
        self.root = models.DirEntry.get_root_entry()
        models.perform_sync(self.gov, self.root)

    @highlight
    def test_default_attr(self):
        self.syncto('C0')
        attr = self.gov.get_resource_default_attributes('/favicon.ico')
        print attr
        self.assertEqual(attr['resource_class'], 'RawResource')
        
    @highlight
    def test_formatters1(self):
        self.syncto('Dropsite_2011-07-19T145942')
        
        rs=models.Resource.get_resource_by_url('/b/')
        print('RS: %s'%rs)
        print rs.source
        print rs.body 
        self.assertEqual(rs.title, 'An index')
        self.assertTrue(rs.body.startswith('<p>Wonder'))

    @highlight
    def test_precedence(self):
        self.syncto('C0')
        self.syncto('C1')
        rs=models.Resource.get_resource_by_url('/')
        print('URL /: %s'%(rs))
        self.assertEqual(rs.parent().get_path(),'/index.txt')
