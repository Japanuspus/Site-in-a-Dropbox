from __future__ import absolute_import
from __future__ import with_statement

import os.path
import re
from datetime import datetime
import logging
import pickle
import copy
import subprocess
import zipfile
import functools
import traceback

import dropbox.auth
import dropbox.client
from oauth import oauth
import dropbox.auth
import config
import types


default_token_file_name = '/Users/janus/Desktop/dbtoken.txt'

class FakeResponse(object):
    def __init__(self, r = None, **kwds):
        for f in ['body', 'status', 'reason','data']:
            if r:
                setattr(self, f, getattr(r,f))
            else:
                setattr(self, f, None)
        for k,v in kwds.items():
            setattr(self, k, v)

    def __str__(self):
        return "Response %s (%s), body: %s"%(self.status, self.reason, self.body)

class DBTool(object):
    """
    A simple db access tool for testing
    """
    dropbox_config = dropbox.auth.Authenticator.load_config(config.DROPBOX_CONFIG_FILE)
    dropbox_auth = dropbox.auth.Authenticator(dropbox_config)
    dropbox_root = dropbox_config['root']

    def __init__(self, token_file_name = default_token_file_name, local_dropbox_root = None):
        self.local_dropbox_root = local_dropbox_root
        if not self.local_dropbox_root:
            self.local_dropbox_root = os.path.expanduser('~/Dropbox')
            
        with open(token_file_name) as f:
            tokenstr = f.read().strip()
        self.token = oauth.OAuthToken.from_string(tokenstr)
        self.client = dropbox.client.DropboxClient(
            DBTool.dropbox_config['server'],
            DBTool.dropbox_config['content_server'],
            80,
            DBTool.dropbox_auth, 
            self.token)

    def metadata(self, path, **kwargs):
        return self.client.metadata(DBTool.dropbox_root, path, **kwargs)

    def build_response_dict_pickle(self, base_path = '/Dropsite'):
        """
        Build a pickle for populating a fake client
        """
        visit = [base_path]
        d={}
        while visit:
            path = visit.pop()
            response = self.metadata(path)
            assert response.status == 200
            key = path.lower()
            val = FakeResponse(response)
            d[key] = val
            print 'Retrieved metatadata: %s -> %s'%(key, val)
            if response.data['is_dir']:
                visit.extend([ c['path'] for c in response.data['contents']  ])
        return pickle.dumps(d)

    def make_state_zip(self, base_path = '/Dropsite', output_file_name = None):
        if not output_file_name:
            timestamp=datetime.isoformat(datetime.now()).replace(':','')[:-7]
            output_file_name = '%s_%s.zip'%(base_path[1:].replace('/','-'),timestamp)
        sp= subprocess.Popen(['zip','-rD','--exclude=*.DS_Store',   os.path.abspath(output_file_name), base_path[1:]], cwd = self.local_dropbox_root)
        (so,se) = sp.communicate()
        assert sp.returncode >=0, "Zipping failed: %s"%se
        response_pickle = self.build_response_dict_pickle(base_path)
        zf=zipfile.ZipFile(output_file_name,'a')
        zf.writestr('_response_pickle.txt', response_pickle)
        
        

class FakeConnection(object):
    def __init__(self, content, status=200):
        self._content=content
        self.status=status
    def read(self):
        return self._content
    def close(self):
        pass
    
class FakeClient(object):

    def __init__(self, response_dict_pickle=None, content_dict = None, state_zip = None):
        if state_zip:
            zf = zipfile.ZipFile(state_zip)
            response_dict_pickle=zf.read('_response_pickle.txt')
            content_dict = {}
            for k in zf.namelist():
                content_dict['/%s'%k.lower()] = zf.read(k)
            zf.close()    
        self.rd = pickle.loads(response_dict_pickle)
        self.content_dict = content_dict

    def metadata(self, dummy, path, hash = None):
        
        if len(path)>1 and path.endswith('/'):
            path=path[0:-1]
        path = path.lower()

        if path in self.rd:
            resp = copy.copy(self.rd[path])
            if resp.status is None:
                print 'State zip as unpickled: %s'%self.rd
                print '\n'.join('%s: %s'%(k,v) for k,v in self.rd.iteritems())
                raise Exception('State zip is bad!')
            if hash and resp.data['hash'] == hash:
                resp.status = 304
                resp.body = ''
                resp.data = {}
                resp.reason = 'Not Modified'
        else:
            resp = FakeResponse(status = 404, reason = 'Not Found', data = {'error': 'Path %s not found'%path})
        return resp

    def get_file(self, dummy, path):
        path=path.lower()
        if path in self.content_dict:
            return FakeConnection(self.content_dict[path])
        else:
            logging.debug('Request for non-existing file!')
            return FakeConnection('',404)

class FakeSite(object):
    dropbox_config = dropbox.auth.Authenticator.load_config(config.DROPBOX_CONFIG_FILE)
    dropbox_auth = dropbox.auth.Authenticator(dropbox_config)
    
    def __init__(self, db_client, base_dir='/Dropsite', site_yaml='site.yaml'):
        from google.appengine.ext import db
        from google.appengine.api import users

        self._db_client = db_client
        self.dropbox_access_token ='oauth_token_secret=fakesecret&oauth_token=vc1okyqpio7irgy'
        self.dropbox_base_dir = base_dir.lower()
        self.dropbox_site_yaml = site_yaml.lower()
        self.dropbox_display_name = 'DB Owner'
        self.dropbox_email = db.Email('dbowner@nil.nil')
        self.owner = users.User(email='onwer@nil.nil')
        self.owner_id = 'ownerid'
        
    def get_dropbox_client(self):
        return self._db_client
        
def make_fake_controller(db_client = None, base_dir='/dropsite', site_yaml='site.yaml'):
    """
    Will insert a real-looking 'Site' entry, so get_current_site_controller works
    """
    from google.appengine.api import users
    from siteinadropbox import models, controller
    owner = users.User('fake@halwe.dk')
    site = models.Site.get_or_insert(key_name=models.Site.the_key_name,
                                     owner = owner,
                                     owner_id = 'abekat',
                                     dropbox_access_token = 'oauth_token_secret=fakesecret&oauth_token=vc1okyqpio7irgy',
                                     dropbox_base_dir=base_dir,
                                     dropbox_site_yaml = site_yaml)
    gov = controller.BaseController(site)
    gov.db_client = db_client
    return gov

def getClipboardData():
  p = subprocess.Popen(['pbpaste'], stdout=subprocess.PIPE)
  retcode = p.wait()
  data = p.stdout.read()
  return data

def setClipboardData(data):
  p = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
  p.stdin.write(data)
  p.stdin.close()
  retcode = p.wait()

def write_for_paste(s):
    setClipboardData(s.replace('\n',r'\n'))

def highlight(f):
    """ see e.g. http://stackoverflow.com/questions/2365701 """
    def new_f(self):
        print '\n\n*** Begin %s ***\n'%f.__name__
        try:
            f(self)
        except:
            print '\n*** End  %s -- Exception ***\n\n'%f.__name__
            print traceback.format_exc()
            raise
        else:
            print '\n*** End  %s ***\n\n'%f.__name__
    functools.update_wrapper(new_f,f)
    return new_f

        
