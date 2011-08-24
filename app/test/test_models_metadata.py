import unittest
import sys


from google.appengine.api import memcache
from google.appengine.ext import db
from google.appengine.ext import testbed

from siteinadropbox import models, controller
#from siteinadropbox.handlers import dropboxhandlers
from siteinadropbox.models import metadata
from test import pickledsites
from test.dbtools import highlight


def dump_metadata(nmax=100):
    entries = models.DirEntry.all().fetch(nmax)
    edict = [(
        e.get_path(),
        e.parent_dir and  e.parent_dir.get_path(),
        e.revision,
        e.modified,
        ) for e in entries]
    edict.sort(key=lambda t: t[0])
    for path, parent, rev, mod in edict:
        print '%6s: %-20s r%d@%s'%((
                (not parent and path=='/' and 'root')
                or (parent and path.startswith(parent) and 'ok')
                or parent or 'orphan'
            ),path, rev, mod)

def find_orphans(nmax=100):
    return [e for e in  models.DirEntry.all().fetch(nmax) if e.is_fake()]
    
        
class LoggingController(controller.BaseController):
    def __init__(self, site):
        controller.BaseController.__init__(self, site)
        self.clear()
    
    def clear(self):
        self.calls=[]
    def __str__(self):
        return '\n'.join([
            'Resource handle_%s called for:\n  %s'%(action, ',\n  '.join([str(e) for e in entries]))
            for action, entries in self.calls ])
    def called(self, action, entries):
        if entries:
            self.calls.append((action, entries))
    def handle_metadata_changes(self, created=[], updated=[], removed=[]):
        self.called('created', created)
        self.called('updated', created)
        self.called('removed', created)

class SyncTestCase(unittest.TestCase):
    def setUp(self):
        
        self.testbed = testbed.Testbed()
        self.testbed.activate()
        self.testbed.init_datastore_v3_stub()
        self.testbed.init_memcache_stub()
        # self.testbed.init_taskqueue_stub()
        # self.testbed.init_images_stub()
        # self.testbed.init_urlfetch_stub()
        # self.testbed.init_user_stub()
        # self.testbed.init_xmpp_stub()

        self.root = models.DirEntry.get_root_entry()
        self.lsr = models.ListingVisitor();


    def tearDown(self):
        self.testbed.deactivate()

    def progression_step(self,name, entry = None):
        self.gov = LoggingController(pickledsites.make_fake_site(name))
        if not entry:
            entry = self.root
        models.perform_sync(self.gov,entry)
        self.listing = self.lsr.make_listing(self.root)        
        print('\n%s\nListing:\n%s\n'%(self.gov,self.listing))

    @highlight
    def test_progressionA(self):
        self.progression_step('A0')
        self.progression_step('A1')
        self.progression_step('A2')
        self.assertTrue(self.listing.endswith('f0161748:   a.txt'))

    @highlight
    def test_progressionB(self):
        self.progression_step('B0')
        self.progression_step('B1')
        self.assertTrue(self.listing.split('\n')[2].endswith('a1.txt'))

    @highlight
    def test_single_missing_file(self):
        self.progression_step('B0')
        self.progression_step('B1', models.DirEntry.get_by_key_name('/b/b1.txt')) 
        self.assertTrue(self.listing.endswith("d0161755:   b"))
        
    @highlight
    def test_single_dir(self):
        self.progression_step('A0')
        self.progression_step('A1', models.DirEntry.get_by_key_name('/b')) 
        self.assertTrue(self.listing.endswith("f0161736:     b1.txt"))

    @highlight
    def test_zorphan_capture(self):
        orphans=[models.DirEntry.get_or_insert(key_name=k) for k in ['/a.txt', '/b/b1.txt']]
        dump_metadata()
        orphans = find_orphans()
        print '\nOrphans: \n -%s\n'%'\n -'.join(str(e) for e in orphans)
        self.assertEqual(len(orphans), 2)
        
        self.progression_step('A0')
        self.assertEqual(len(find_orphans()), 0)

        # Now the tricky part: can we catch an orphan
        # If metadata is already up to date?
        b, b1 = models.DirEntry.get_by_key_name(['/b', '/b/b1.txt'])
        b1.parent_dir=None
        b.hash_ = None
        db.put([b, b1])
        self.assertEqual(len(find_orphans()), 1)

        self.progression_step('A0')
        dump_metadata()
        self.assertEqual(len(find_orphans()), 0)

        
        
