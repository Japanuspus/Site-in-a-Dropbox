import logging
import os.path
import itertools
from datetime import datetime

from google.appengine.ext import db

import config

BEGINNING_OF_TIME = datetime(1900,1,1)

"""
A model for caching filesystem metadata corresponding to a Dropbox subtree.

Syncing of the cache to Dropbox is initiated by call to initiate_sync which
also enforces rate limits.

All manipulating calls include a 'site' parameters which should have
'dropbox_base_dir', 'dropbbox_auth_key' and 'db_client' attributes.

Dropbox error codes:
 Standard Dropbox errors
  507:	User over quota.
  503:	Your app is making too many requests and is being rate limited. per-app and per-user basis.
  5xx	Server error -- our bad
 Standard OAuth layer errors
  401	Bad or expired token. This can happen if the user or Dropbox revoked or expired an access token. To fix, simply re-authenticate the user.
  403	Bad OAuth request (wrong consumer token, bad nonce, expired timestamp, ...). Unfortunately, re-authenticating the user won't help here.
 Standard API layer errors
  400	Bad input parameter. 
  405	Request method not expected (generally should be GET or POST).
"""

class DropboxError(Exception):
    def __init__(self, status, msg=''):
        Exception.__init__(self, msg)
        self.status = status
    def __str__(self):
        return "Dropbox returned status code: %d. %s"%(self.status, Exception.__str__(self))

def parse_dropbox_datetime(s):
    "Format according to https://www.dropbox.com/developers/docs: '%a, %d %b %Y %H:%M:%S %z'"
    assert s.endswith(' +0000'), 'Dropbox have started using time zones!'
    return datetime.strptime(s[:-6],'%a, %d %b %Y %H:%M:%S')

class ListingVisitor(object):
    def format_entry(self, entry):
        return (
            '%s%07d: '%(((entry.is_dir and 'd') or 'f'),entry.revision),
            os.path.split(entry.get_path())[1] or '/'
            )
    def visit_dir(self, entry, responses):
        return (self.format_entry(entry), responses)
    def visit_file(self, entry):
        return (self.format_entry(entry), [])

    def rshow(self,r, idx):
        buf= [r[0][0]+('  '*idx)+r[0][1]]
        for rr in r[1]:
            buf.extend(self.rshow(rr,idx+1))
        return buf
    
    def make_listing(self, entry, idx=0):
        return '\n'.join(self.rshow(entry.accept_visitor(self),0))

class Throttle(db.Model):
    earliest_sync = db.DateTimeProperty(required=True, auto_now_add=False)

    def __str__(self):
        p=self.parent()
        if not p or not isinstance(p, DirEntry):
            raise Exception('Orphan throttle detected!')
        return '%s: %s'%(self.earliest_sync, p.get_path())

        
class DirEntry(db.Model):
    """
    A directory entry from Dropbox or Fake.
    
    Fake entries have no parent_dir and are not files
    Of the real entries, only the unique root (with key '\') has no parent_dir
    """
    parent_dir = db.SelfReferenceProperty(collection_name='dir_members')
    modified = db.DateTimeProperty(required=True, default= BEGINNING_OF_TIME)
    revision = db.IntegerProperty(required=True, default=0)
    is_dir = db.BooleanProperty(required=True, default=False)
    bytes = db.IntegerProperty(required=True, default=0)
    hash_ = db.TextProperty()

    @classmethod
    def get_root_entry(cls):
        return cls.get_or_insert(key_name='/', is_dir=True)

    def accept_visitor(self, visitor):
        """
        Visitor must support
        visitor.visit_dir(entry, member_responses)
        visitor.visit_file(entry)
        """
        if self.is_dir:
            responses= [e.accept_visitor(visitor) for e in self.dir_members ]
            return visitor.visit_dir(self, responses)
        return visitor.visit_file(self)
        

    def __str__(self):
        return '%s %s rev. %d@%s'%(
            ((self.is_dir and 'D') or 'F'),
            self.get_path(),
            self.revision,
            self.modified.isoformat())

    def delete_below(self):
        """
        Delete all nodes below, including descendants.
        Does not delete self.
        TODO: reimplement to use fast delete
        """
        for m in self.dir_members:
            m.delete_below()
            m.delete()
        for d in db.query_descendants(self).run():
            d.delete()

    def get_path(self):
        return self.key().name()

    def download_content(self, gov):
        """
        Download and return the content of the corresponding file
        """
        if self.is_dir:
            return
        site=gov.site
        filename=site.dropbox_base_dir+self.get_path()
        conn=gov.db_client.get_file(site.dropbox_config['root'], filename)
        if conn.status >= 400:
            conn.close()
            msg = 'While reading %s. Reason: %s'%(filename, conn.reason)
            gov.access_error_notify(msg)
            raise DropboxError(conn.status, msg)
        content = conn.read()
        logging.debug('Downloaded revision %s. Status: %s'%(filename, conn.status))
        conn.close()
        return content

    def is_root(self):
        """
        We only allow file entries to be fake
        """
        if self.parent_dir is None and self.is_dir:
            assert self.key().name()=='/', 'DirEntry %s is an orphan directory!'%self
            return True

    def is_fake(self):
        if self.parent_dir is None:
            if self.is_dir:
                assert self.key().name()=='/', 'DirEntry %s is an orphan directory!'%self
            else:
                return True
        
    field_converters=[
        (lambda a: parse_dropbox_datetime(a), 'modified', 'modified'),
        (lambda a: a, 'revision', 'revision'),
        (lambda a: a, 'is_dir', 'is_dir'),
        (lambda a: a, 'bytes', 'bytes'),
        (lambda a: a, 'hash', 'hash_'),
        ]

    @classmethod
    def make_attr_dict(cls, metadata_dict):
        return dict(
            (attr_name, f(metadata_dict.get(meta_name)))
            for (f, meta_name, attr_name) in cls.field_converters
            if meta_name in metadata_dict)
            
    def set_from_dict(self, attr_dict):
        """
        Update an entry according to dict. Return list of changed attributes.

        Note that 'hash' is 'mapped to hash_' to avoid clash with builtin
        """
        modlist = []
        for f, dict_name, attr_name  in self.field_converters:
            new_value = f(attr_dict.get(dict_name,None))
            if new_value != getattr(self, attr_name):
                setattr(self, attr_name, new_value)
                modlist.append(dict_name)
        return modlist

    def _sync(self, response, normalize_path, update, remove, visit):
        """
        A helper for handlers.dropbox.perform_sync
        
        Adds entry objects to update/remove iff datastore put/delete
        is required
        Adds all directories below to 'visit'
        Will append to update, remove and visit.
        """
        data = response.data
        logging.debug('DBSync: Dropbox response data:%s'%data)

        ## Case -A: unknown
        if response.status == 404:
            logging.debug('DBSync: Dropbox returned 404')
            remove.append(self)
            return 

        ## Case A: single file
        if (response.status == 200 and not data['is_dir']) or (response.status == 304 and not self.is_dir):
            logging.debug('DirEntry: Handling a single file %s'%(self))
            ## Corner case -- changed status from dir
            if self.is_dir:
                logging.info('DirEntry %s changed from dir to file'%self)
                remove.append(self)
            ml=self.set_from_dict(data)
            if ml:
                update.append(self)
            return 

        ## Case B: Unmodified directory
        if response.status==304:
            logging.debug('Matching hash for %s'%self)
            visit.extend([de for de in self.dir_members if de.is_dir])
            return

        ## Case C: Directory without matching hash
        ## Corner case: changed status from file to dir:
        if not self.is_dir:
            logging.debug('Entry %s changed from file to dir'%self)
            remove.append(self)
        self_modlist=self.set_from_dict(data)
        assert self.is_dir, 'Somehow %s is not a dir...?'%self
        logging.debug('Parsing full listing for %s'%self)

        ## Build dictionary of current dropbox and datastore entries
        db_contents = dict([(normalize_path(e['path']), e) for e in data['contents'] ])
        ds_contents = dict([(e.get_path(), e) for e in self.dir_members])
        db_keys = set(db_contents.keys())
        ds_keys = set(ds_contents.keys())

        ## Handle the three Venn-sectors one at a time: 
        db_not_ds = db_keys.difference(ds_keys)
        db_and_ds = db_keys.intersection(ds_keys)
        ds_not_db = ds_keys.difference(db_keys)

        # ds_not_db: Removed from dropbox
        remove.extend([ds_contents[k] for k in ds_not_db])

        # db_not_ds: Created in dropbox
        for k, entry in itertools.izip(
                db_not_ds, DirEntry.get_by_key_name(db_not_ds)):
            # First, check that there is no orphan around:
            if not entry:
                entry = DirEntry.get_or_insert(
                    key_name=k, parent_dir = self,
                    **self.make_attr_dict(db_contents[k]))
                logging.debug('Creating entry: %s'%entry)
            else:
                logging.debug('Found orphan entry: %s'%entry)
                modlist = entry.set_from_dict(db_contents[k])
                entry.parent_dir=self
                assert entry.hash_ is None

            if entry.is_dir:
                #Visitor will check is_saved and save
                visit.append(entry)
            else:
                update.append(entry)
            
        # db_and_ds: Existing entries
        for k in db_and_ds:
            entry = ds_contents[k]
            if db_contents[k]['is_dir']:
                if not entry.is_dir:
                    logging.debug('Entry %s changed file->dir, should be handled when visiting'%entry)
                # Visit all dirs.
                # Handle file -> dir corner case when visiting
                visit.append(entry)
            else:
                # only update files now:
                modlist = entry.set_from_dict(db_contents[k])
                if modlist:
                    update.append(entry)
                    if entry.is_dir:
                        # Status change dir -> file
                        remove.append(entry)

        ## Maybe update self (new hash/initial call)
        if self_modlist or not self.is_saved():
            update.append(self)

    @classmethod
    def flush_resources(cls):
        """Flush all resources from database"""
        root=cls.get_root_entry()
        root.delete_below()
        root.delete()

    @classmethod
    def verify_all_resources(cls, gov):
        """
        This function will call the 'handle_metadata_changes' for
        all resources in the exact same order done if everything
        was being resynces from Dropbox after a purge.
        To completely fix the database, a call should be followed
        by a call to Resource.find_orphans
        """

        # Find the root and any fake resources:
        roots = []
        nmax = 0
        while len(roots)==nmax:
            nmax+=100
            roots = cls.all().filter('parent_dir = ', None).order('__key__').fetch(nmax)
        if len(roots)==0:
            logging.debug('verify_all_resources called on empty database')
            return

        root = roots.pop(0)
        assert root.is_root(), "Weirdness - no root!"

        # First the real dropbox files:
        visit = [root]
        while visit:
            visiting = visit.pop()
            logging.debug('VerifyAll: Processing all members of %s'%visiting)
            members = visiting.dir_members
            visit.extend([d for d in members if d.is_dir])
            gov.handle_metadata_changes(updated=[f for f in members if not f.is_dir]+[visiting])

        #only fakes are left in roots:
        if roots:
            assert all(f.is_fake() for f in roots), 'Not all remaining roots are fake!'
            logging.debug('VerifyAll: Processing fake files %s'%', '.join(str(f) for f in roots))
            gov.handle_metadata_changes(updated = roots)


def perform_sync_by_key(gov, entry_key):
    entry = db.get(entry_key)
    if not entry:
        raise CDeferred.PermanentTaskFailure('Unable to retrieve %s'%entry_key)
    return perform_sync(gov, entry)

def perform_sync(gov, entry):
    """
    Recursively sync metadata with Dropbox for the tree below `entry`.
    Handlers are called as described below, and all descendants
    of a DirEntry object are deleted before the object itself.

    gov.handle_metadata_changes() will be called
    - update: after an entry has been modified or created
    - remove: before an entry is deleted
    Note that if a dir is deleted, handle_remove will not be called for members.
    A dir entry will always be handled after the (file) members of the dir.
    After update_listener.handle_remove returns, all remaining
    descendants of the entry are deleted. 

    Implementation considerations
    -----------------------------
    Rather than delaying update of Dir resources untill all members
    are valid, our fundamental goal is to save all information
    pertaining to a client request to the datastore before making a new
    request.

    """

    base_dir = gov.site.dropbox_base_dir.lower()
    db_root = gov.site.dropbox_config['root']
    db_client = gov.db_client

    def normalize_path(p):
        pl=p.lower()
        assert pl.startswith(base_dir)
        return pl[len(base_dir):]

    logging.debug('DBSync: Starting sync from %s'%entry)
    visit=[entry]
    while visit:
        update=[]
        remove=[]
        visiting = visit.pop()
        logging.debug('DBSync: Visiting %s'%visiting)
        visiting_path=base_dir+visiting.get_path()
        response=db_client.metadata(db_root,visiting_path,hash=visiting.hash_ )
        if not response.status in [200,304, 404]:
            msg = 'Metadata request for %s failed. %d [%s]: %s'%(visiting_path,response.status,response.reason,response.body)
            gov.access_error_notify(msg)
            raise DropboxError(response.status, msg)
        if response.status == 404:
            msg = 'Metadata request for %s failed. %d [%s]: %s'%(visiting_path,response.status,response.reason,response.body)
            #info=db_client.account_info()
            #msg+='\nDropbox info: %s(%s): %s'%(info.status, info.reason, info.data)
            logging.debug(msg)
            
        visiting._sync(response=response, normalize_path=normalize_path,
                       update=update, remove=remove, visit=visit)

        if remove:
            logging.debug('DBSync: Removing entries:\n -%s'%'\n -'.join([str(e) for e in remove]))
            gov.handle_metadata_changes(removed=remove)
            for e in remove:
                e.delete_below()
            if not remove[0].parent_dir:
                msg='Dropbox base dir not accessible'
                gov.access_error_notify(msg)
                raise DropboxError(0, msg)
            else:
                db.delete(remove)

        if update: 
            logging.debug('DBSync: Updating entries:\n -%s'%'\n -'.join([str(e) for e in update]))
            gov.handle_metadata_changes(updated=update)
            db.put(update)

def schedule_sync(gov, entry=None):
    """
    Schedule a sync of either resource or the whole tree.
    Returns earliest sync time (or True for fake resources) if
    sync could not be scheduled.
    """
    def do_schedule(entry, now):
        tt=Throttle.all().ancestor(entry).filter('earliest_sync >=',now).get()
        if tt:
            logging.debug('Earliest_sync of %s: in %s'%(
                entry.get_path(),
                tt.earliest_sync-now))
            return tt
        # We are not throttled!
        if entry.is_dir:
            polint=config.DROPBOX_POLL_INTERVAL
        else:
            polint=config.DROPBOX_FILE_POLL_INTERVAL

        # Attach new throttle    
        tt = Throttle(parent=entry, earliest_sync=now+polint)
        tt.put()
        old_throttles=Throttle.all(keys_only=True).ancestor(entry).filter('earliest_sync <=',now)
        db.delete(old_throttles.fetch(100))

        # Schedule the fetch
        # taskqueue.add(url=DirEntry, params={'key':str(entry.key())})
        logging.debug('Sync of %s: scheduled'%entry.get_path())
        gov.cdefer(perform_sync_by_key, str(entry.key()))

    now = datetime.now()

    ## Start by checking if we can sync root
    root = DirEntry.get_root_entry()
    if do_schedule(root,now) is None:
        # Root was scheduled for sync
        return
    if not entry or entry.is_dir:
        # schedule was called for root or a directory
        return
    if entry.is_fake():
        logging.debug('Not scheduling sync for fake entry')
        return True
    ## We have a file sub-entry. Try to sync
    do_schedule(entry, now)

