import yaml
import logging
import re
import traceback
import types
import os.path

import config
from siteinadropbox import models
from siteinadropbox import cache
from siteinadropbox.handlers import cdeferred
from siteinadropbox.handlers import dropboxhandlers

"""
This module should be imported by all entry points, and the current_site_controller should
be passed along to the models.
This object contains site-specific data and establishes responsibilities. The latter part
both to allow more modular code and to avoid circular import problems...

"""

class BaseController(object):

    def __init__(self, site):
        self.site = site
        self._update_from_site()

    def _update_from_site(self):
        self.db_client = self.site.get_dropbox_client()
        if not self.db_client:
             raise models.InvalidSiteError('Unable to initialize dropbox client')
        self._parse_config_yaml()

    def _parse_config_yaml(self):
        self.site_constants, self.resource_default_attributes = self._do_parse_config_yaml()
        
    def get_config_yaml(self):
        """
        Returns (full config file name, contents)
        """
        config_path = os.path.join('/',self.site.dropbox_site_yaml)
        cfg_resource = models.Resource.get_resource_by_url(config_path)
        return (os.path.join(self.site.dropbox_base_dir, config_path), cfg_resource and cfg_resource.source)
        
        
    #Relies on cache.flush_all at config change
    @cache.memoize(key='Controller._do_parse_config_yaml')
    def _do_parse_config_yaml(self):
        """
        Parses config.DEFAULT_CONFIG_YAML and site.get_config_path() (if exists).
        Returns tupple: (site_constant, resource_default_attributes)
        """
        default=yaml.load(config.DEFAULT_CONFIG_YAML)
        config_path = os.path.join('/',self.site.dropbox_site_yaml)
        
        # Look for the config file:
        config_path, cfg_src = self.get_config_yaml()
        cfg = None
        if cfg_src:
            try:
                cfg=yaml.load(cfg_src)
            except Exception, e:
                logging.debug('Parsing of config file failed: %s'%e)
                logging.debug('Exception traceback: %s'%traceback.format_exc())
                self.config_error_notify('Error in config file %s: %s'%(config_path, e))
        else:
            self.config_error_notify('The config file %s was not found (might be a timing issue)'%config_path)

        ## site_constants
        sc_key = 'site_constants'
        if cfg and (sc_key in cfg):
            sc = cfg[sc_key]
        else:
            sc = default[sc_key]
        if not type(sc) is types.DictType:
            self.config_error_notify('The %s field in %s is not a dict but has the form: %s'%(sc_key, config_path, repr(sc)))
            sc=default[sc_key]

        ## resource attributes
        rda_key = 'resource_default_attributes'
        rda = default[rda_key]
        logging.debug('Default resource_default_attributes as parsed: \n%s'%repr(rda))
        if cfg and (rda_key in cfg):
            rda.extend(cfg[rda_key])
        if not type(rda) is types.ListType:
            self.config_error_notify('The %s field in %s is not a list but has the form: %s'%(rda_key, config_path, repr(rda)))
            rda=default[rda_key]

        ## process regexps patterns in rda
        try:
            rda = [ (re.compile(d.pop('pattern'),re.IGNORECASE), d) for d in rda if 'pattern' in d]
        except Exception, e:
            self.config_error_notify('Resource default attributes are invalid: %s\n%s'%(e,repr(rda)))
            logging.debug('Exception while processing config yaml: %s\n%s'%(e, traceback.format_exc()))
            rda=[]
        return (sc, rda)
                                    
            
    def handle_resource_changes(self, created=[], updated=[], removed=[]):
        """
        Should be called whenever a resource has been modified.
        For remove, it is enough to call with root of the tree to
        be removed.
        """
        logging.debug('handle_resource_change called.')
    
    def handle_metadata_changes(self, created=[], updated=[], removed=[]):
        """
        Should be called whenever metadata has been modified.
        """
        
        logging.debug('handle_metadata_changes called.')

    def handle_config_changes(self):
        logging.debug('Config has changed')
        cache.flush_all()
        self.cdefer(verify_database_consistency, _countdown =2)

    def format_error_notify(self, resource, exception):
        """
        Should be called if a resource cannot be parsed
        by the specified formatter.
        """
        logging.debug('format_error_notify called.')

    def config_error_notify(self, message):
        """
        Should be called if the specified config file cannot
        be parsed.
        """
        logging.debug('config_error_notify called: %s'%message)

    def access_error_notify(self, message):
        """
        Should be called if an external resource cannot be accessed
        """
        logging.debug('access_error_notify called')

    def resource_access_notify(self, resource = None, url = None):
        logging.debug('Resource accessed: %s'%(resource or (url and '%s by url'%url) ))

    def do_verify_database_consistency(self):
        models.DirEntry.verify_all_resources(self)
        models.Resource.delete_orphans(self)

    #Relies on cache.flush_all at config change
    @cache.memoize(key_func=lambda self, path: 'controller.get_resource_default_attributes:%s'%path)
    def get_resource_default_attributes(self, path):
        """
        Calculate the default attributes for a given resource.
        Path should be '/' terminated for dirs
        """
        da={}
        for patterncomp,alist in self.resource_default_attributes:
            if patterncomp.match(path):
                da.update(alist)
        # We can't rely on patterns for finding the ConfigResource
        if '/'+self.site.dropbox_site_yaml.lower()==path.lower():
            da['resource_class'] = 'ConfigResource'
        else:
            assert da.get('resource_class',None)!='ConfigResource'
                
        logging.debug('Default attributes for path %s computed to %s'%(
                path, da))
        return da

    def cdefer(self, obj, *args, **kwargs):
        """
        gov.cdefer(obj,*args, **kwargs) will do a deferred execution of
        obj(gov, *args, **kwargs).
        You can pass extra arguments for the defer library:
        _countdown, _eta, _name, _transactional, _url, _queue
        """
        logging.debug('cdefer called')

class Controller(BaseController):
    def handle_metadata_changes(self, created=[], updated=[], removed=[]):
        cu = created + updated
        logging.debug('Updating resources for %s'%', '.join(str(e) for e in cu))
        
        for entry in created+updated:
            models.Resource.update(self, entry)

    def cdefer(self, obj, *args, **kwargs):
        """
        gov.cdefer(obj,*args, **kwargs) will do a deferred execution of
        obj(gov, *args, **kwargs).
        You can pass extra arguments for the defer library:
        _countdown, _eta, _name, _transactional, _url, _queue
        """
        cdeferred.defer(obj, *args, **kwargs)

    def resource_access_notify(self, resource = None, url = None):
        BaseController.resource_access_notify(self, resource, url)
        #TODO cache here!
        entry = None
        if (not resource) and url:
            resource = models.Resource.get_resource_by_url(url)
        if resource:
            entry = resource.parent()
        models.schedule_sync(self, entry=entry)

#@cache.memoize()
#Can't cache the whole controller as the site-object doesn't pickle
def get_current_site_controller():
    site = models.Site.get_current_site()
    if not site:
        raise models.InvalidSiteError('Site not registered')
    # This might also raise InvalidSiteError
    return Controller(site)

def verify_database_consistency(gov):
    return gov.do_verify_database_consistency()
