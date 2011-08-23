import os.path
import logging

from  django.template import loader
from google.appengine.ext import db

import config
from siteinadropbox.models.resources import TextResource

def get_resource_by_entry_path(p):
    return TextResource.all().ancestor(db.Key.from_path('DirEntry',p.lower())).get()

class TemplateLoader(loader.BaseLoader):
    """
    A template loader class for djanog 1.2
    To use, include the full name of this class as string in TEMPLATE_LOADERS
    """
    is_usable = True

    def load_template_source(self, template_name, template_dirs=None):
        filepath=os.path.join(config.TEMPLATE_DIR,template_name)
        template=get_resource_by_entry_path(filepath)
        if not template:
            logging.debug('Failed to find template %s'%filepath)
            raise  loader.TemplateDoesNotExist('The template %s does not exist'%filepath)
        logging.debug('siteinadropbox.templateloader: found template %s'%template_name)
        return (template.source or '&nbsp;', filepath)
    load_template_source.is_usable = True
#_loader = Loader()




