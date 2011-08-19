from __future__ import with_statement
import os, sys
import datetime

APP_ROOT_DIR = os.path.abspath(os.path.dirname(__file__))

#Dropbox: Config and throttling
DROPBOX_CONFIG_FILE = os.path.join(APP_ROOT_DIR,'config_dropbox.ini')
DROPBOX_POLL_INTERVAL = datetime.timedelta(seconds=120)     # Min interval between full recursive syncs
DROPBOX_FILE_POLL_INTERVAL = datetime.timedelta(seconds=10) # Min interval between single file syncs

#Restrictions to keep the GAE load down:
PROXY_MAX_AGE = 3600  #For cache-control in Google's reverse proxy. Currently used for *.ico
PROXY_ENABLED = True  #Whether to enable reverse proxy

#Django configuration
TEMPLATE_DIR='/templates'
DJANGO_CONFIG_MODULE = 'config_django'

#URL's for the admin interface
ADMIN_URL='/admin/'
CDEFERRED_URL = '/admin/_cdeferred'
RESOURCE_QUEUENAME = 'default'

#Constants for the admin templates
TEMPLATE_SETTINGS={
    'lang': 'en-us',
    'title': 'Site in a Dropbox',
    'author': 'Janus H. Wesenberg',
    'email': 'janus@halwe.dk',
    'home' : 'http://siteinadropbox.appspot.com',
    'logo_128': "/admin/media/SiteinaDropbox-128.png",
    'logo_16': "/admin/media/SiteinaDropbox-16.png",
}

with open(os.path.join(APP_ROOT_DIR,'config_site_default.yaml')) as f:
    DEFAULT_CONFIG_YAML=f.read()


