import logging
import traceback

from google.appengine.ext import webapp
from google.appengine.ext import db
from google.appengine.ext import deferred
from google.appengine.api import taskqueue

import config
from siteinadropbox import models
from siteinadropbox import controller

class FetchWorker(webapp.RequestHandler):
    def post(self):
        """
        implementation note:
        If a push task request handler returns an HTTP status code within the range 200 - 299,
        App Engine considers the task to have completed successfully. If the task returns a
        status code outside of this range, App Engine retries the task until it succeeds.

        We treat FormatErrors and DropboxErrors specially.
        All other errors are assumed to be bad code: An error is logged and status 200 is returned
        """
        resource=db.get(self.request.get('key'))
        if not resource:
            logging.info('FetchWorker failed to find resource for %s'%self.request.get('key'))
            return #Do not fail: we want the queue item to die
        new_revision=self.request.get_range('new_revision')
        action=self.request.get('action', 'fetch')
        if not hasattr(resource, action):
            logging.info('FetchWorker: Resource object %s does not have method %s'%(resource, action))
            return
        logging.debug('Fetchworker, will initiate %s on %s (new revision: %d)'%(action, resource, new_revision))
        gov = None
        try:
            gov = controller.get_current_site_controller()
            getattr(resource,action)(gov, new_revision=new_revision)
        except (models.InvalidSiteError, models.DropboxError), e:
            logging.warn('Unable to access dropbox: %s'%e)
        except models.FormatError, e:
            logging.debug('Format error %s reported -- notifying owner'%e)
            if gov:
                gov.handle_format_error(resource, e)
        except BaseException, e:
            logging.error('BUG: Unexpected exception while executing %s on %s'%(action,resource))
            logging.debug('Exception message: %s'%e)
            logging.debug('Stacktrace: \n%s'%traceback.format_exc())
                         


    
    
    
