"""
A layered cache system.

The goal is to eventually use both memcache (global) and local
memory (instance specific) for caching. The memcache is assumed
to always be valid.
"""

import logging
import functools

from google.appengine.api import memcache

class UncachedResult():
    """
    A wrapper for non-authoritative results that should not be cached
    """
    def __init__(self, result):
        self.result = result

class Layers:
    Datastore = 1
    Memcache = 2
    InAppMemory = 4

class memoize(object):
    """
    Instances of this class can be used as memoizer decorators.

    The max_age is the maximum age of a local memory copy before
    it is validate against the memcache.

    If a key_func is passed, it will be called with all arguments
    passed to fn and should return a string.
    E.g. key_func = lambda *a,**k: repr((a,k)).
    The default key format is defined in default_key which
    can be overridden.


    Returning results that should not be cached
    -------------------------------------------
    Just wrap in UncachedResult

    Flushing cache
    --------------
    If `foo` is memoized, just call
    - foo.flush_cache(...) to flush
    - foo.update_cache(...) to force recalc 
    
    Designed to be subclassed. Namespace safe.
    Inspired by Khan Academy's layer_cache and Simon Willimson's ratelimit
    """
    default_max_age = 60*60
    def __init__(self,
                 key = None,
                 key_func = None,
#                 max_age = default_max_age
                 ):
        self.key=key
        self.key_func = key_func
#        self.max_age = max_age
    
    
    def __call__(self, fn):
        """
        Hmm, we are keeping three references to fn, but storing in self
        will fail if a memoizer is reused.
        In any case, the interface seems solid, so we can always redo.
        """

        def memoized(*args, **kwargs):
            return self.cache_lookup(fn, *args, **kwargs)
        functools.update_wrapper(memoized, fn)

        def flush_cache(*args, **kwargs):
            return self.flush(fn, *args, **kwargs)
        memoized.flush_cache=flush_cache
        def update_cache(*args, **kwargs):
            return self.update(fn, *args, **kwargs)
        memoized.update_cache=update_cache

        return memoized
    
    def default_key(self, fn, *args, **kwargs):
        return  '_memoized_%s.%s:%s'%(fn.__module__,fn.__name__,repr((args,kwargs)))
    
    def get_key(self, fn, *args, **kwargs):
        return (
            self.key or
            (self.key_func and self.key_func(*args, **kwargs)) or
            self.default_key(fn, *args, **kwargs))

    def flush(self, fn, *args, **kwargs):
        key = self.get_key(fn,*args,**kwargs)
        memcache.delete(key)

    def update(self, fn, *args, **kwargs):
        key = self.get_key(fn,*args,**kwargs)
        return self._do_update(key, fn, *args, **kwargs)

    def _do_update(self, key, fn, *args, **kwargs):
        val = fn(*args, **kwargs)
        logging.debug('Setting cache for %s: %s'%(key, repr(val)))
        memcache.set(key, val)
        return val

    def cache_lookup(self, fn, *args, **kwargs):
        key = self.get_key(fn,*args,**kwargs)
        val = memcache.get(key)
        if not val:
            return self._do_update(key, fn, *args, **kwargs)
        logging.debug('Memcache hit for %s'%key)
        return val

def flush_all():
    """
    Flush all cached values for current namespace
    """
    memcache.flush_all()
