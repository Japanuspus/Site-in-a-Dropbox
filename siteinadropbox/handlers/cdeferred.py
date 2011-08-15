
"""
A version of the cdeferred module, modified to pass a 'controller'
object as the first argument when making deferred calls.
The controller is generated via a factory method specified by
calling CDeferred.set_controller_factory

Example usage:

  def do_something_later(key, amount):
    entity = MyModel.get(key)
    entity.total += amount
    entity.put()

  # Use default URL and queue name, no task name, execute ASAP.
  deferred.defer(do_something_later, 20)

  # Providing non-default task queue arguments
  deferred.defer(do_something_later, 20, _queue="foo", countdown=60)
"""

from __future__ import absolute_import
import traceback
import logging
import os
import pickle
import types

from google.appengine.api import taskqueue
from google.appengine.ext import db
from google.appengine.ext import webapp

import config

_TASKQUEUE_HEADERS = {"Content-Type": "application/octet-stream"}
_DEFAULT_URL = config.ADMIN_URL+"/_cdeferred"
_DEFAULT_QUEUE = "default"

class Error(Exception):
    """Base class for exceptions in this module."""

class PermanentTaskFailure(Error):
    """Indicates that a task failed, and will never succeed."""

class TemporaryTaskFailure(Error):
    """Raise this if you want to retry"""

class _CDeferredTaskEntity(db.Model):
    """Datastore representation of a deferred task.

    This is used in cases when the deferred task is too big to be included as
    payload with the task queue entry.
    """
    data = db.BlobProperty(required=True)


def run_pickle(gov, data):
    """Unpickles and executes a task.

    Args:
      data: A pickled tuple of (function, args, kwargs) to execute.
    Returns:
      The return value of the function invocation.
    """
    try:
        func, args, kwds = pickle.loads(data)
    except Exception, e:
        logging.error('Run_pickle failed to unpickle payload!')
        raise PermanentTaskFailure(e)
    else:
        logging.debug('CDeferred: run_pickle calling %s with args:%s, kwargs:%s'%(func.__name__, args, kwds))
        return func(gov, *args, **kwds)

def run_from_datastore(gov, key):
    """Retrieves a task from the datastore and executes it.

    Args:
      key: The datastore key of a _DeferredTaskEntity storing the task.
    Returns:
      The return value of the function invocation.
    """
    entity = _DeferredTaskEntity.get(key)
    if not entity:

        raise PermanentTaskFailure()
    try:
        ret = run_pickle(gov, entity.data)
        entity.delete()
    except PermanentTaskFailure:
        entity.delete()
        raise

def invoke_member(gov, obj, membername, *args, **kwargs):
    logging.debug('CDeferred: invoke_member: %s on %s'%(membername, obj))
    """Retrieves a member of an object, then calls it with the provided arguments.

    Args:
      obj: The object to operate on.
      membername: The name of the member to retrieve from ojb.
      args: Positional arguments to pass to the method.
      kwargs: Keyword arguments to pass to the method.
    Returns:
      The return value of the method invocation.
    """
    return getattr(obj, membername)(gov, *args, **kwargs)


def invoke_member_by_key(gov, obj_key, membername, *args, **kwargs):
    logging.debug('CDeferred: invoke_member_by_key. member: %s'%membername)
    obj = db.get(obj_key)
    if not obj:
        raise PermanentTaskFailure('Unable to retrieve db instance for %s'%obj_key)
    return invoke_member(gov, obj, membername, *args, **kwargs)

def _curry_callable(obj, *args, **kwargs):
    """Takes a callable and arguments and returns a task queue tuple.

    The returned tuple consists of (callable, args, kwargs), and can be pickled
    and unpickled safely.

    Args:
      obj: The callable to curry. See the module docstring for restrictions.
      args: Positional arguments to call the callable with.
      kwargs: Keyword arguments to call the callable with.
    Returns:
      A tuple consisting of (callable, args, kwargs) that can be evaluated by
      run() with equivalent effect of executing the function directly.
    Raises:
      ValueError: If the passed in object is not of a valid callable type.
    """
    if isinstance(obj, types.MethodType):
        if isinstance(obj.im_self, db.Model):
            return (invoke_member_by_key, (str(obj.im_self.key()), obj.im_func.__name__) + args, kwargs)
        return (invoke_member, (obj.im_self, obj.im_func.__name__) + args, kwargs)
    elif isinstance(obj, types.BuiltinMethodType):
        if not obj.__self__:
            return (obj, args, kwargs)
        else:
            return (invoke_member, (obj.__self__, obj.__name__) + args, kwargs)
    elif isinstance(obj, types.ObjectType) and hasattr(obj, "__call__"):
        return (obj, args, kwargs)
    elif isinstance(obj, (types.FunctionType, types.BuiltinFunctionType,
                          types.ClassType, types.UnboundMethodType)):
        return (obj, args, kwargs)
    else:
        raise ValueError("obj must be callable")


def serialize(obj, *args, **kwargs):
    """Serializes a callable into a format recognized by the deferred executor.

    Args:
      obj: The callable to serialize. See module docstring for restrictions.
      args: Positional arguments to call the callable with.
      kwargs: Keyword arguments to call the callable with.
    Returns:
      A serialized representation of the callable.
    """
    curried = _curry_callable(obj, *args, **kwargs)
    cobj, cargs, ckwargs = curried
    result = pickle.dumps(curried, protocol=pickle.HIGHEST_PROTOCOL)
    logging.debug('Cdeferred: Call tupple %s(%s, %s) pickled to %d B'%(cobj, cargs, ckwargs, len(result)))
    return result

def defer(obj, *args, **kwargs):
    """Defers a callable for execution later.

    The default deferred URL of /_ah/queue/deferred will be used unless an
    alternate URL is explicitly specified. If you want to use the default URL for
    a queue, specify _url=None. If you specify a different URL, you will need to
    install the handler on that URL (see the module docstring for details).

    Args:
      obj: The callable to execute. See module docstring for restrictions.
      _countdown, _eta, _name, _transactional, _url, _queue: Passed through to
      the task queue - see the task queue documentation for details.
      args: Positional arguments to call the callable with.
      kwargs: Any other keyword arguments are passed through to the callable.
    Returns:
      A taskqueue.Task object which represents an enqueued callable.
    """
    taskargs = dict((x, kwargs.pop(("_%s" % x), None))
                    for x in ("countdown", "eta", "name"))
    taskargs["url"] = kwargs.pop("_url", _DEFAULT_URL)
    transactional = kwargs.pop("_transactional", False)
    taskargs["headers"] = _TASKQUEUE_HEADERS
    queue = kwargs.pop("_queue", _DEFAULT_QUEUE)
    pickled = serialize(obj, *args, **kwargs)
    try:
        task = taskqueue.Task(payload=pickled, **taskargs)
        return task.add(queue, transactional=transactional)
    except taskqueue.TaskTooLargeError:
        logging.warn('CDeferred: A task with large payload was deferred!')
        key = _DeferredTaskEntity(data=pickled).put()
        pickled = serialize(run_from_datastore, str(key))
        task = taskqueue.Task(payload=pickled, **taskargs)
        return task.add(queue)

class CDeferredHandler(webapp.RequestHandler):
    """A webapp handler class that processes deferred invocations."""
    formurl = _DEFAULT_URL
    controller_factory = None

    @classmethod
    def set_controller_factory(cls, factory):
        cls.controller_factory = staticmethod(factory)

    def post(self):
        headers = ["%s:%s" % (k, v) for k, v in self.request.headers.items()
                   if k.lower().startswith("x-appengine-")]
        logging.info('CDeferred: Task being executed, headers: %s'%", ".join(headers))

        try:
            if not self.controller_factory:
                logging.error('CDeferred handler was called without an initialized controller_factory')
                return
            gov = self.controller_factory()
            logging.info('CDeferred: Obtained controller %s from factory %s.'%(gov, self.controller_factory))
            run_pickle(gov, self.request.body)
        except TemporaryTaskFailure, e:
            logging.info('Temporary failure on task -- will retry')
            raise
        except PermanentTaskFailure, e:
            logging.warning("Permanent failure attempting to execute task")
 #       except (models.InvalidSiteError, models.DropboxError), e:
 #           logging.warning('Unable to access dropbox: %s'%e)
 #       except models.FormatError, e:
 #           logging.debug('Format error %s reported -- notifying owner'%e)
 #           if gov:
 #               gov.handle_format_error(resource, e)
        except BaseException, e:
            logging.error('BUG: Unexpected exception in CdeferredHandler')
            logging.debug('Exception message: %s'%e)
            logging.debug('Stacktrace: \n%s'%traceback.format_exc())
