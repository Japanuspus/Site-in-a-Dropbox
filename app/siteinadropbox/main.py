import os
import config
import logging
import wsgiref.handlers
import urllib

from google.appengine.ext import webapp
from google.appengine.api import namespace_manager

import dropbox.auth
import dropbox.client
from siteinadropbox import controller
from siteinadropbox import models

class PageHandler(webapp.RequestHandler):
    #max_age = config.CACHE_MAX_AGE

    #@memoize(key_func=lambda s,g,r,p: p, max_age = s.max_age, tickers = [config.RESOURCE_TICKER, config.CONFIG_TICKER])
    def get_response(self, gov, request, request_path):
        resource=models.Resource.get_resource_by_url(request_path)
        if resource:
            resource.serve_request(gov, request)
            return request.response
        
    def get(self, url):
        # Check if namespace is initialized
        try:
            gov = controller.get_current_site_controller()
        except models.InvalidSiteError, e:
            logging.warning('Access to uninitialized namespace %s. Redirecting to %s'%(
                namespace_manager.get_namespace(), config.ADMIN_URL))
            self.redirect(config.ADMIN_URL)
            return

        #TODO: Handle unicode in path
        request_path = urllib.unquote(self.request.path)

        # Look up response
        logging.debug('Serving %s according to path %s'%(self.request.url, request_path))
        response = self.get_response(gov, self, request_path)
        if response:
            self.response = response
            gov.resource_access_notify(url=request_path)
            return

        # No response: look for friendly rewrites
        if not request_path.endswith('/') and not self.request.query_string:
            new_path = self.request.path+'/'
            if self.get_response(gov, self, new_path):
                logging.debug('Redirecting %s to %s'%(request_path, new_path))
                self.redirect(new_path, permanent = True)
                return

        # Otherwise, it's 404
        logging.debug('Access to non-existing url %s'%request_path)
        gov.resource_access_notify(url=request_path)
        self.error(404)
            

def main():
    logging.getLogger().setLevel(logging.DEBUG)
    routes = [
        #Todo add a max_age=0 handler for config.DRAFT_DIR
        ('(/.*)', PageHandler),
        ]
    application = webapp.WSGIApplication(routes,debug=True)
    wsgiref.handlers.CGIHandler().run(application)

if __name__ == '__main__':
    main()
