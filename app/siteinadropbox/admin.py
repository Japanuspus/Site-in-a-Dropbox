import os
import logging
from cStringIO import StringIO
import cgi
import urllib

from google.appengine.ext.webapp import template #Also fixes Django paths
import wsgiref.handlers
from google.appengine.ext import webapp
from google.appengine.api import users
from google.appengine.api import namespace_manager
import dropbox.auth
import dropbox.client
from oauth.oauth import OAuthToken

import config
from siteinadropbox import models
from siteinadropbox import controller
from siteinadropbox import cache
from siteinadropbox.handlers import dropboxhandlers
from siteinadropbox.handlers.cdeferred import CDeferredHandler

def admin_url(s=None):
    if not s:
        return config.ADMIN_URL
    return config.ADMIN_URL+s

def owneronly(f):
    """
    Decorator to populate self.site and self.user
    If a site record exists, allow only the matching user to be logged in.
    """
    def new_f(self, *args, **kwargs):
        self.site = models.Site.get_current_site()
        self.user = users.get_current_user()
        if self.site and self.site.owner_id != self.user.user_id():
            logging.info('/admin/auth: Denying admin access for %s (id: %s). Owner ID is: %s'%(
                self.user.email(), self.user.user_id(), self.site.owner_id))
            self.response.set_status(403)
            self.render_to_template({},'admin_403.html')
            return
        f(self, *args, **kwargs)
    return new_f

def withgov(f):
    """
    Decorator to populate self.gov and self.user
    """
    def new_f(self, *args, **kwargs):
        try:
            self.gov = controller.get_current_site_controller()
        except models.InvalidSiteError:
            logging.debug('Access to admin page of invalid site attempted')
            self.redirect(admin_url())
            return
        self.user = users.get_current_user()
        if gov and gov.site.owner_id != user.user_id():
            logging.info('/admin/auth: Denying admin access for %s (id: %s). Owner ID is: %s'%(user.email(), user.user_id(), site.owner_id))
            self.redirect(admin_url())
            return
        return f(self, *args, **kwargs)
    return new_f

#def is_namespace_allowed(namespace):
#    """
#    Return True if an account can be established for the given namespace.
#    Currently always returns true
#    """
#    logging.info("Namespace request for %s"%namespace)
#    return True

class BaseHandler(webapp.RequestHandler):
    def render_to_template(self,template_values, template_name=None):
        values ={
            'auth_formurl': admin_url('authorize-dropbox'),
            'formurl': admin_url(),
            'apps_namespace' : namespace_manager.google_apps_namespace(),
            'current_namespace' : namespace_manager.get_namespace(),
            'server_name' :  os.environ['SERVER_NAME'],
            'settings' : config.TEMPLATE_SETTINGS,
            'user' : users.get_current_user(),
            'login_url': users.create_login_url(admin_url()),
            'logout_url': users.create_logout_url(admin_url()),
            'request': self.request, #e.g. for request.url
            }
        values.update(template_values)
        template_path=os.path.join('templates',template_name)
        
        self.response.out.write( template.render(template_path, values))

class StatusHandler(BaseHandler):
    @owneronly
    def get(self):
        # These should always succeed: Site.get can only fail if
        # there is no logged-in user.
        if self.site:
            client = self.site.get_dropbox_client()
        dropbox_info=None
        account_good=False
        if self.site and client:
            dropbox_info=client.account_info()
            account_good= (dropbox_info.status == 200)
            #dropbox_info.data holds the account info, e.g. {u'referral_link': u'https://www.dropbox.com/referrals/NTM1NTU1Mzg5', u'display_name': u'Janus Wesenberg', u'uid': 3555538, u'country': u'SG', u'quota_info': {u'shared': 40610557, u'quota': 5905580032L, u'normal': 3305647577L}, u'email': u'janus@halwe.dk'}

        if account_good and (
            self.site.dropbox_display_name != dropbox_info.data['display_name']  or
            self.site.dropbox_email != dropbox_info.data['email'] ):

            logging.info('Updating dropbox credentials')
            self.site.dropbox_display_name = dropbox_info.data['display_name']
            self.site.dropbox_email = dropbox_info.data['email'] 
            self.site.put()

        if account_good:
            logging.debug('/admin: Account good')
            return self.status(self.site, dropbox_info)
        logging.debug('/admin: Account not good, showing welcome page')
        return self.welcome(self.site, dropbox_info)

    @owneronly
    def post(self):
        """
        Callers should supply 'action'
        Callers can supply 'redirect_url'
        Action and response will be be delivered to redirect_url 
        """
        if not self.site:
            logging.info('/admin-post: Denying admin access')
            return self.error(403)
        action = self.request.POST.get('action').lower()
        nexturl = self.request.POST.get('redirect_url', admin_url())
        gov = controller.get_current_site_controller()
        logging.debug('Admin/post, action =%s, nexturl: %s'%(action, nexturl))
        response = ''
        assert(action in ['save', 'flush', 'reload', 'verify', 'delete', 'sync'])
        if action == 'save':
            self.save_config_path()
        elif action == 'flush':
            cache.flush_all()
        elif action == 'reload':
            models.flush_resources(self.site)
        elif action == 'verify':
            gov.do_verify_database_consistency()
        elif action == 'sync':
            models.schedule_sync(gov)
        elif action == 'delete':
            #todo
            raise NotImplemented('Delte not implemented')
        
        self.redirect('%s?%s'%(nexturl, urllib.urlencode({'action': action, 'response': response})))

    def save_config_path(self):
        new_config_path = self.request.get('config_path')
        if self.site.set_config_path(new_config_path):
            self.site.put()
            gov = controller.get_current_site_controller()
            gov.handle_config_changes()
        self.redirect(admin_url())

    def welcome(self,site,dropbox_info):
        self.render_to_template({
            'site_raw': site,
            'dropbox_info': dropbox_info,
            },'admin_welcome.html')
        pass 

    def status(self,site,dropbox_info):
        #Namespace listing:
        #http://code.google.com/appengine/docs/python/datastore/metadataqueries.html#Namespace_Queries
        self.render_to_template({
            'site_raw': site,
            'dropbox_info': dropbox_info,
            'config_path': site.get_config_path(),
            },'admin_status.html')

def list_all_resources(nmax=1000):
    """
    Returns a list of tupples (key_name, DirEntry instance, Resource instance),
    so that all objects of class DirEntry and Resource are represented
    """
    resources = [(r.parent(), r) for r in models.Resource.all().fetch(nmax)]
    orphans = [(None, None, r) for (p,r) in resources if not p]

    direntries = dict((d.key().name(), d) for d in models.DirEntry.all().fetch(nmax))
    resources = [(p.key().name(), direntries.pop(p.key().name(),None), r) for (p,r) in resources if p]
    childless = [(d.key().name(), d, None) for d in direntries.values()]
    return orphans+sorted(resources+childless, key= lambda x: x[0])

def direntrytype(de):
    if de:
        return (
            (de.is_root() and 'R') or
            (de.is_fake() and 'P') or
            (de.is_dir and 'D') or
            'F'
            )


class ContentHandler(BaseHandler):
    fields = [
        ('type',    lambda k,d,r: direntrytype(d)),
        ('name',    lambda k,d,r: k),
        ('url',     lambda k,d,r: r and r.url),
        ('db_rev',  lambda k,d,r: d and d.revision),
        ('r_rev',   lambda k,d,r: r and r.revision),
        ]
    
    @owneronly
    def get(self):
        rlist = list_all_resources()
        content_list = [dict((k,f(*r)) for k,f in self.fields ) for r in rlist]
        self.render_to_template(template_name= 'admin_content.html', template_values = {'content_list': content_list})


        
class ConfigHandler(BaseHandler):
    @owneronly
    def get(self):
        gov = controller.get_current_site_controller()
        config_path, config_src = gov.get_config_yaml()
        self.render_to_template(template_name= 'admin_config.html',
                                template_values = {'config_default': config.DEFAULT_CONFIG_YAML,
                                                    'config_path': config_path,
                                                    'config_src': config_src})
        
def main():
    logging.getLogger().setLevel(logging.DEBUG)
    CDeferredHandler.set_controller_factory(controller.get_current_site_controller)

    routes=[
        (admin_url()[:-1], webapp.RedirectHandler.new_factory(admin_url(), permanent=True)),
        (admin_url(), StatusHandler),
        (admin_url('config'), ConfigHandler),
        (admin_url('content'), ContentHandler),
        (admin_url('authorize-dropbox'), dropboxhandlers.AuthHandler.new_factory(formurl = admin_url('authorize-dropbox'), returnurl=admin_url())),
        (config.CDEFERRED_URL, CDeferredHandler)
        ]
    application = webapp.WSGIApplication(routes,debug=True)
    wsgiref.handlers.CGIHandler().run(application)

if __name__ == '__main__':
    main()
