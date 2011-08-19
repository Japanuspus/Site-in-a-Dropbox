import os

from google.appengine.api import namespace_manager
from google.appengine.dist import use_library

import config

## Configure Django
os.environ['DJANGO_SETTINGS_MODULE'] = config.DJANGO_CONFIG_MODULE
use_library('django', '1.2')
# # Need to force import of settings, see http://stackoverflow.com/questions/5845607/
#from django.conf import settings

def namespace_manager_default_namespace_for_request():
  """Must return the default namespace for a given request."""
  #google_apps_namespace does not include subdomain -- so not suitable for us
  #return namespace_manager.google_apps_namespace()
  return os.environ['SERVER_NAME']

# Enable google appstats
# http://code.google.com/appengine/docs/python/tools/appstats.html
def webapp_add_wsgi_middleware(app):
    from google.appengine.ext.appstats import recording
    app = recording.appstats_wsgi_middleware(app)
    return app



