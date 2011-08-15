from __future__ import absolute_import

import os.path
import re
from datetime import datetime
import logging
import yaml
import cgi
import traceback

import aetycoon
import dropbox.auth
import dropbox.client
from google.appengine.ext import db
from google.appengine.ext.db import polymodel

import google.appengine.ext.webapp.template #just to fix django imports
import django.template
import django.template.loader

from siteinadropbox import formatters
import config

"""
This module implements a hierachy of `Resource` classes: a resource knows how
to serve itself.

TODO:
Django needs to be passed an object with access to the computed attributes. We are
currently using a modified __getattr__, but it seems better to implement a cached
`get_page()`
"""

class FormatError(Exception):
    pass

class Resource(polymodel.PolyModel):
    """
    A resource is identified by a unique Uniform Resource Locator and knows how to serve itself.
    """
    revision = db.IntegerProperty()
    url = db.StringProperty()
    queue_name = config.RESOURCE_QUEUENAME

    def __str__(self):
        return '%s@%s backed by %s'%(self.__class__.__name__,self.url, self.parent())

    def serve_request(self, site, handler):
        "Serve according to a web-ob request object"
        raise NotImplementedError()

    def verify_state(self, site, entry, default_attributes):
        """
        Check that the current state of the resource agrees with
        revision and default_attributes.
        If not, schedule whatever actions necesary.
        """
        pass

    def schedule(self, gov, action, new_revision):
        logging.debug('Scheduling %s on %s. New rev.: %d'%(action.__name__, self, new_revision))
        gov.cdefer(action, new_revision, _queue = self.queue_name)

    @classmethod
    def delete_orphans(cls,gov):
        #TODO
        logging.error('Resource.delete_orphan should be implemented')

    @classmethod
    def compute_url_from_entry_path(cls, entry_path):
        #TODO ?? why did I put this here
        return entry_path

    @classmethod
    def get_resource_by_url(cls, url):
        # We cannot use 'get_by_key_name' because that would require knowing the parent
        return cls.all().filter('url =',url).get()

    @classmethod 
    def update(cls, gov, entry):
        """
        Ensures that an updated resource exist for DirEntry entry.
        If a resource (with different parent) already exist at calculated URL,
        the present entry is ignored.
        
        URL clashes
        -----------
        There are several posibilities for url clashes:
        - foo/index.ext <> foo/
        - foo.ext1 <> foo.ext2
        When there is a clash, the alphabetically largest parent path
        takes precedence.
        """

        def delete_descendants():
            """
            Check if entry has any resource descendants, and if so, delete them
            """
            ## run block delete and call the listener
            for rr in  Resource.all().ancestor(entry).run():
                logging.debug('Entry: %s. Old resource deleted, url: %s. Res: %s'%(entry_path, rr.url, rr))
                rr.delete()

        ##Compute a normalized entry path (ends with / for dirs)
        entry_path = entry.get_path().rstrip('/')
        if entry.is_dir:
            entry_path+='/'

        ## Look up default attributes, including resource class if any
        attributes = gov.get_resource_default_attributes(entry_path)
        resource_class = None
        if 'resource_class' in attributes:
            try:
                # resource_class = getattr(resources, attributes['resource_class'])
                resource_class = globals()[attributes['resource_class']]
            except KeyError, AttributeError:
                pass
        if not resource_class:
                logging.debug('Resource %s was not assigned a resource class'%entry)
                return delete_descendants()
        url = resource_class.compute_url_from_entry_path(entry_path)
        logging.debug('Entrye %s, computed attributes: resource_class: %s, url: %s'%(
            entry_path, resource_class, url))
        assert resource_class and url, 'Fishyness!'

        ## Try to find an existing resource object
        resource = Resource.get_resource_by_url(url)
        if resource and (resource.parent().key() != entry.key()):
            # URL occupied: entry backed by alphabetically largest path takes
            # precedence, to insure that /index.txt beats / 
            resource_path = resource.parent().get_path()
            if resource_path > entry_path:
                logging.debug('Entry %s: URL %s taken by %s. Our parent: %s'%(
                    entry_path, url, resource.parent(), entry ))
                delete_descendants()
                return
            else:
                logging.debug('Entry %s: Takes precedence over %s for URL %s'%(entry, resource.parent(), url))
                resource.delete()
                resource=None
        if resource and not isinstance(resource, resource_class):
            logging.debug('Resource for %s deleted as previous type %s did not match %s'%(
                entry_path,type(resource), resource_class))
            resource.delete()
            resource=None

        ## Create resource if needed
        if not resource:
            logging.debug('Entry %s: Creating new resource of class %s for %s'%(
                entry_path, resource_class, url))
            resource = resource_class.get_or_insert(key_name=url, 
                                                    parent=entry,
                                                    url=url)
            resource.put()
        else:
            assert (
                (resource.parent().key() == entry.key()) and
                (resource.key().name() == url) and
                (resource.url == url)), 'LOGIC FAIL'

        ## Finally: let the resource instance decide if anything needs to be done.
        logging.debug('Verifying that state for %s agrees with default_attributes %s'%(resource,attributes))
        resource.verify_state(gov, entry, default_attributes = attributes)


class TextResource(Resource):
    source = db.TextProperty()

    def serve_request(self, gov, handler):
        handler.response.out.write(self.source)

    def verify_state(self, gov, entry, default_attributes):
        if entry.revision != self.revision:
            logging.debug('Scheduling fetch of new version of %s'%self)
            self.schedule(gov, action=self.fetch, new_revision=entry.revision)

    def fetch(self, gov, new_revision):
        self.fetch_from_dropbox(gov, new_revision)
        self.put()
        gov.handle_resource_changes(updated=[self])

    def fetch_from_dropbox(self, gov, new_revision):
        entry = self.parent()
        self.source=entry.download_content(gov)
        self.revision=new_revision
        
class PageResource(TextResource):
    """
    A page resource can represent a single file or a dir with or without index.
    This means that source format, source, and body can all be None.
    Attributes holds such fields as template, tags (as text), generators, ..
    
    In templates:
       page = attribues.update({'source': source, 'body': body, 'tags': tags})
    """
    source_format = db.StringProperty()
    body = db.TextProperty()
# tags = TODO
# title = TODO
    default_attributes = aetycoon.PickleProperty(default={})
    attributes = aetycoon.PickleProperty(default={})

    @classmethod
    def compute_url_from_entry_path(cls, entry_path):
        if entry_path.endswith('/'):
            return entry_path
        url = os.path.splitext(entry_path)[0]
        if url.endswith('index'):
            return url[:-5]
        return url

    def verify_default_attributes(self, default_attributes):
        """
        Return a list of modified default attributes. Will execute
        put if antyhing has changed
        """
        def dict_diff(d1,d2):
            return [k for k in set(d1.keys() + d2.keys()) if not 
                    (k in d1 and k in d2 and d1[k]==d2[k])]
        
        modlist = []
        format = default_attributes.pop('format', None)
        if format != self.source_format:
            modlist.append('format')
            self.source_format = format
        modlist.extend(dict_diff(self.default_attributes, default_attributes))
        if modlist:
            self.default_attributes = default_attributes
            self.put()
        return modlist            

    def verify_state(self, gov, entry, default_attributes):
        modlist = self.verify_default_attributes(default_attributes)
        # Check that source=None for directory entries
        if entry.is_dir and self.source:
            self.source = None
            modlist.append('source')
        if self.revision != entry.revision and not entry.is_dir:
            self.schedule(gov, action=self.fetch, new_revision=entry.revision) 
        elif modlist:
            if self.source and self.source_format:
                self.schedule(gov, action=self.run_formatter, new_revision=entry.revision)
            elif self.body:
                self.body = None
                modlist.append('body')
        if 'source' in modlist or 'body' in modlist:
            self.put()
            gov.handle_resource_changes(updated=[self])
        
    def fetch(self, gov, new_revision):
        logging.debug('PageResource fetch on %s to rev %d'%(self, new_revision))
        super(PageResource,self).fetch_from_dropbox(gov, new_revision)
        self.run_formatter(gov, new_revision)
        gov.handle_resource_changes(updated=[self])

    def run_formatter(self, gov, new_revision):
        logging.debug('PageResource format %s as %s'%(self, self.source_format))
        def fail(msg):
            self.body = cgi.escape(self.source)
            self.attributes = self.default_attributes
            self.put()

        formatter=formatters.get_formatter_by_name(self.source_format)
        if (not formatter) and (self.source_format is not None):
            fail()
            gov.config_error_notify('Formatter %s specified for %s was not found'%(self.source_format, self))
            return
        if formatter:
            try:
                new_attributes = formatter.format(self.source, self.default_attributes)
            except Exception, e:
                fail()
                gov.format_error_notify('Formatter %s failed on %s: %s'%(self.source_format, self, e), e)
                return
            self.body = new_attributes.pop('body', None)
            self.attributes = new_attributes
        else:
            self.body = cgi.escape(self.source)
            self.attributes = self.default_attributes
            
        self.put()

    def __getattr__(self, k):
        try:
            return self.attributes[k]
        except KeyError:
            raise AttributeError(k)

    def serve_request(self, gov, handler):
        template_path = self.attributes.get('template', None)
        if template_path:
            logging.debug('Serving request to handler: %s. Template: %s, Page:%s'%(
                handler,template_path,self))

            template = django.template.loader.get_template(template_path)
            context = django.template.Context({'site': gov.site_constants,'page': self})
            handler.response.out.write(template.render(context))
        else:
            logging.debug('Serving request with raw body')
            handler.response.out.write(self.body)

class ConfigResource(TextResource):
    def fetch(self, gov, new_revision):
        TextResource.fetch(self, gov, new_revision)
        gov.handle_config_changes()

class ImageResource(Resource):
    pass

def debug_headers(response):
    """
    The response.wsgi_write fixes up the headers: Make a fake start_response 
    """
    def logtupples(t):
        logging.debug('header tupples: \n%s'%'\n'.join('%s (%s): %s (%s)'%(k,type(k),v,type(v)) for k,v in t))

    headers=response.headers
    logging.debug('Response header keys: %s'%', '.join('%s (%s)'%(v,type(v)) for v in headers.keys()))
    logging.debug('Response headers: \n%s'%'\n'.join('%s (%s): %s (%s)'%(k,type(k),v,type(v)) for k,v in headers._headers))

    def w(s):
        return
    def sr(s,h):
        logging.debug('Fake start_response called: %s, %s'%(s,h))
        return w
    response.wsgi_write(sr)
    raise Exception('Trying to debug headers')

class RawResource(Resource):
    source = db.BlobProperty()
    content_type = db.StringProperty()

    def serve_request(self, gov, handler):
        handler.response.out.write(self.source)
        if self.content_type:
            handler.response.headers['Content-Type']=str(self.content_type)
        if config.PROXY_ENABLED:
            #The headers field is not quite a dict and does not support `update`
            for k,v in {
                'Cache-Control': 'max-age=%d'%config.PROXY_MAX_AGE,
                'ETag': '"rev%d"'%self.revision,
                }.iteritems():
                handler.response.headers[k]=str(v)
        #debug_headers(handler.response)

    def verify_state(self, gov, entry, default_attributes):
        content_type = default_attributes.get('content_type',None)
        if content_type != self.content_type:
            self.content_type = content_type
            self.put()
            gov.handle_resource_changes(updated = [self])
        if entry.revision != self.revision:
            logging.debug('Scheduling fetch of new version of %s'%self)
            self.schedule(gov, action=self.fetch, new_revision=entry.revision)

    def fetch(self, gov, new_revision):
        self.fetch_from_dropbox(gov, new_revision)
        self.put()
        gov.handle_resource_changes(updated=[self])

    def fetch_from_dropbox(self, gov, new_revision):
        entry = self.parent()
        self.source=entry.download_content(gov)
        self.revision=new_revision
