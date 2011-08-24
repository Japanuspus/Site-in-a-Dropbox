# Configuration for Django.
# Modified from https://github.com/franciscosouza/gaeseries/blob/django/settings.py
import os
import logging

logging.debug('Reading config_django.py')

#TODO: remove the filesystem loader
TEMPLATE_DIRS = (os.path.join(os.path.dirname(__file__), 'siteinadropbox/templates'),)
TEMPLATE_LOADERS = (
    'siteinadropbox.templateloader.TemplateLoader',
    'django.template.loaders.filesystem.Loader',
    )
logging.debug('Django TEMPLATE_DIRS: '+', '.join(['"%s"'%s for s in TEMPLATE_DIRS]))
logging.debug('Django TEMPLATE_LOADERS: '+', '.join(['"%s"'%s for s in TEMPLATE_LOADERS]))

# from djangoappengine.settings_base import *
INSTALLED_APPS = (
#    'djangoappengine', 
#    'djangotoolbox',
#    'django.contrib.auth',
#    'django.contrib.contenttypes',
#    'django.contrib.sessions',
#    'core',
)
#TEST_RUNNER = 'djangotoolbox.test.CapturingTestSuiteRunner'
#ADMIN_MEDIA_PREFIX = '/media/admin/'
#MEDIA_ROOT = os.path.join(os.path.dirname(__file__), 'media')
#ROOT_URLCONF = 'urls'



