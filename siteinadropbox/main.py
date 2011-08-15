import os
import config
import logging
import wsgiref.handlers

from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.api import namespace_manager

import dropbox.auth
import dropbox.client
from siteinadropbox import controller
from siteinadropbox import models

class BaseHandler(webapp.RequestHandler):
    def render_to_template(self, template_values,template_name=None):
        values={
            'site': self.gov.site_constants,
            }
        values.update(template_values)
        template_path=os.path.join('templates',template_name)
        self.response.out.write( template.render(template_path, values))

class PageHandler(BaseHandler):
    def get(self,url):
        try:
            self.gov = controller.get_current_site_controller()
        except models.InvalidSiteError, e:
            ns = namespace_manager.get_namespace()
            logging.info('Access to uninitialized namespace: %s'%ns)
            self.response.set_status(503)
            values = {'namespace': ns,
                      'url': url,
                      'settings': config.TEMPLATE_SETTINGS}
            self.response.out.write(
                template.render('templates/admin_uninitialized.html',
                                values))
            return 

        #Todo: this needs to be much more clever!
        resource=models.Resource.get_resource_by_url(url)
        if (not resource and not url.endswith('/') and
                models.Resource.get_resource_by_url(url+'/')):
            logging.debug('Redirecting %s to %s'%(url, url+'/'))
            self.redirect(url+'/', permanent = True)
            return
        if resource:
            self.gov.resource_access_notify(resource)
            resource.serve_request(self.gov, self)
        else:
            logging.debug('Access to non-existing url %s'%url)
            self.gov.resource_access_notify()
            self.error(404)
            

def main():
    logging.getLogger().setLevel(logging.DEBUG)
    routes = [
        ('(/.*)', PageHandler),
        ]
    application = webapp.WSGIApplication(routes,debug=True)
    wsgiref.handlers.CGIHandler().run(application)

if __name__ == '__main__':
    main()
