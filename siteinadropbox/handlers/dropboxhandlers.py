import os
import logging
from datetime import datetime

from google.appengine.ext import db
from google.appengine.ext import deferred
from google.appengine.ext import webapp
from google.appengine.api import taskqueue
from google.appengine.api import users
from google.appengine.api import namespace_manager
import dropbox.auth
import dropbox.client
from oauth.oauth import OAuthToken

from siteinadropbox import models

def site_root_url():
    #https doesn't come through from google apps for domains?
    if True or ("Development" in os.environ['SERVER_SOFTWARE']):
        url="http://"+os.environ['HTTP_HOST']
    else:
        url="https://"+os.environ['HTTP_HOST']
    return url

def owneronly(f):
    """
    Populate self.site and self.user
    If a site record exists, allow only the matching user to be logged in.
    """
    def new_f(self, *args, **kwargs):
        self.site = models.Site.get_current_site()
        self.user = users.get_current_user()
        if self.site and self.site.owner_id != self.user.user_id():
            logging.info('/admin/auth: Denying admin access for %s (id: %s). Owner ID is: %s'%(
                self.user.email(), self.user.user_id(), self.site.owner_id))
            self.error(403)
            return
        f(self, *args, **kwargs)
    return new_f
        

class AuthHandler(webapp.RequestHandler):
    """
    Handle authorization via oAuth as described in RFC5849, http://tools.ietf.org/html/rfc5849

    Consumer/Client: This application
    Service Provider/Server: Dropbox
    /Resource Owner: dropbox account holder
    Inspired by code for https://dropdav.appspot.com/

    You must create handler via .new_factory(fornurl=<>, returnurl=<>)
    """
    
    def __init__(self, formurl, returnurl):
        self.formurl = formurl
        self.returnurl = returnurl

    @owneronly
    def get(self):
        logging.debug('Auth/get')
        if not 'oauth_token' in self.request.GET:
            logging.error('Invalid oauth callback')
            self.redirect(self.returnurl)
            return
        self.dropbox_auth_callback(self.site)

    @owneronly
    def post(self):
        logging.debug('Auth/post')
        action = self.request.POST.get('action')
        if not action in ['authorize']:
            logging.error('Invalid oauth form action: %s'%action)
            self.redirect(self.returnurl)
            return
        return self.dropbox_authorize()

    def dropbox_authorize(self):
        """
        Contact the oauth server to obtain a request token.
        Store the token with the user (through a cookie).
        Then forward the user to the server to authorize the token.
        """
        callback_url=site_root_url()+self.formurl
        logging.debug('AuthHandler.setup, setting callback URL to '+callback_url)

        # get a fresh request token containing "oauth_token" and "oauth_token_secret"
        token = models.Site.dropbox_auth.obtain_request_token()
        # send it back to the user via a cookie
        self.response.headers['Set-Cookie'] = 'token=%s' % token 
        # make the user log in at dropbox.com and authorize this token
        self.redirect(models.Site.dropbox_auth.build_authorize_url(token,callback=callback_url))
    
    def dropbox_auth_callback(self,site):
        """
        Handle the server callback after user has granted access.
        This callback contains oauth_token and oauth_verifier. The oauth verifier is
        currently not used by dropbox?
        """
        # First get the token we stored with the user
        cookie = self.request.cookies['token']
        assert cookie, 'No cookie!'
        token = OAuthToken.from_string(cookie)
        self.response.headers['Set-Cookie'] = 'token=' # erase the auth token

        # Then, get the verifier from the get parameters
        request_token=self.request.get('oauth_token')
        request_verifier=self.request.get('oauth_verifier')

        # Something is wrong if the tokens don't match
        if not request_token==token.key:
            logging.error('AuthHandler.dropbox_oauth_callback: request (%s) and cookie (%s) tokens do not match'%(
                request_token,token.key))

        # Now, get an access token to store for future use
        logging.debug('AuthHandler.dropbox_oauth_callback. oauth_verifier: %s'%request_verifier)
        access_token = models.Site.dropbox_auth.obtain_access_token(token, "")
        logging.debug('AuthHandler.dropbox_oauth_callback. Obtained access_token: %s'%access_token.to_string())
        
        # Save the access token for later use
        site=models.Site.get_or_insert_current_site()
        site.dropbox_access_token = access_token.to_string()
        site.put()
        self.redirect(self.returnurl)
                         


