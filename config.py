import os, sys
import datetime

APP_ROOT_DIR = os.path.abspath(os.path.dirname(__file__))

#Dropbox: Config and throttling
DROPBOX_CONFIG_FILE = os.path.join(APP_ROOT_DIR,'config_dropbox.ini')
DROPBOX_POLL_INTERVAL = datetime.timedelta(seconds=120)     # Min interval between full recursive syncs
DROPBOX_FILE_POLL_INTERVAL = datetime.timedelta(seconds=10) # Min interval between single file syncs

#Restrictions to keep the GAE load down:
FILE_SIZE_LIMIT = 100000
IMAGEFILE_EXTENSIONS = 'jpg|jpeg|png|bmp|gif'
PROXY_MAX_AGE = 3600  #For cache-control in Google's reverse proxy. Only used for *.ico
PROXY_ENABLED = True  #Whether to enable reverse proxy

#Django configuration
TEMPLATE_DIR='/templates'
DJANGO_CONFIG_MODULE = 'config_django'

#URL's for the admin interface
ADMIN_URL='/admin'
FETCHWORKER_URL = ADMIN_URL+'/_fetchworker'
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


DEFAULT_CONFIG_YAML="""\
# All fields in site_constants will be available in your template
# as settings.<foo>
site_constants:
  site_title: No site at all
  subtitle: A site that isn\'t even a site
  keywords: [SiteInADropbox, site-in-a-dropbox, Google App Engine, Dropbox]
  about_url: /about
  contact_url: /contact
  author: Janus
  author_email: janus@halwe.dk
#  google_analytics: xxx
#  disqus: xxx

# All matching fields will be processed in order presented here
# i.e. last match to define a given field wins
# The resource attributes (i.e. the default attributes + what is
# defined by the resource metadata) can be accessed as page.<foo>
# in templates
resource_default_attributes:
- pattern: '.*'
  template: default.html
  
- pattern: '.*\.(ico)$'
  resource_class: RawResource
  content_type: image/x-icon

- pattern: '.*\.(gif)$'
  resource_class: RawResource
  content_type: image/gif

- pattern: '.*\.(svg|css|js|html|xhtml|yaml)$'
  resource_class: TextResource

- pattern: '.*\.(html|xhtml)$'
  resource_class: PageResource

- pattern: '.*\.(txt|md|text)$'
  resource_class: PageResource
  format: markdown
"""

