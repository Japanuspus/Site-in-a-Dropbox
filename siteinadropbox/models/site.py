from __future__ import absolute_import
import os.path
import re
from datetime import datetime
import logging
import yaml

import aetycoon
import dropbox.auth
import dropbox.client
from oauth import oauth
from google.appengine.ext import db
from google.appengine.ext.db import polymodel
from google.appengine.api import users
from google.appengine.api import namespace_manager  

import config

class InvalidSiteError(Exception):
    pass

class Site(db.Model):
    """
    This model should only have one instance per namespace.
    dropbox_base_dir: Must have leading slash, no trailing slash
    """
    # Class variables
    dropbox_config = dropbox.auth.Authenticator.load_config(config.DROPBOX_CONFIG_FILE)
    dropbox_auth = dropbox.auth.Authenticator(dropbox_config)
    the_key_name = 'the_key_name'

    # Datastore-based member variables
    dropbox_base_dir = db.StringProperty(required=True) 
    dropbox_site_yaml = db.StringProperty(required=True, default = 'site.yaml')

    dropbox_access_token = db.StringProperty()
    dropbox_display_name = db.StringProperty()
    dropbox_email = db.EmailProperty()
    owner = db.UserProperty(required=True)
    owner_id = db.StringProperty(required=True)

    @classmethod
    def get_current_site(cls):
        """
        Get the current site, if one is defined.
        """
        return cls.get_by_key_name(cls.the_key_name)

    @classmethod
    def get_or_insert_current_site(cls):
        """
        Assumes that a user is logged in.
        Always returns a site. Current user is owner for new sites
        """
        user=users.get_current_user()
        if not user:
            logging.error('Get or insert site called with no user available')
            raise InvalidSiteError('No user logged in')

        default_base_dir = '/Public/%s'%namespace_manager.get_namespace()
        return cls.get_or_insert(key_name=cls.the_key_name,
                                 owner=user,
                                 owner_id=user.user_id(),
                                 dropbox_base_dir=default_base_dir)
    
    def get_dropbox_client(self):
        if not self.dropbox_access_token:
            return None
        return dropbox.client.DropboxClient(
            Site.dropbox_config['server'],
            Site.dropbox_config['content_server'],
            80, Site.dropbox_auth, 
            oauth.OAuthToken.from_string(self.dropbox_access_token))

    def get_config_path(self):
        return os.path.join(self.dropbox_base_dir, self.dropbox_site_yaml)
    def set_config_path(self, new_config_path):
        """
        Will return the old config path if it was changed
        """
        oldpath = self.get_config_path()
        cdir, cfile = os.path.split(new_config_path.lower())
        
        if not cdir.startswith('/'):
            cdit='/'+cdir
        if not cfile:
            cfile = 'site.yaml'

        self.dropbox_base_dir = cdir
        self.dropbox_site_yaml = cfile
        newpath = self.get_config_path()
        if newpath !=oldpath:
            return oldpath
