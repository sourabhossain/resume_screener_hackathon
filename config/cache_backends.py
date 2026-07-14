"""Resilient Redis cache backend.

Django's built-in RedisCache (and django-ratelimit on top of it) raise when Redis
is unreachable, which turns a brief Redis blip into a hard 500 on every
rate-limited endpoint (login, careers-apply, API writes, protected media).

This subclass degrades instead of failing: reads return the default and writes
become no-ops when Redis can't be reached, so the site stays up. Rate limiting
is effectively disabled for the (hopefully short) duration of a Redis outage.
"""
import logging

from django.core.cache.backends.redis import RedisCache
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

_warned = False

def _warn(exc):
    global _warned
    if not _warned:
        logger.warning("Cache backend (Redis) unavailable; degrading gracefully: %s", exc)
        _warned = True

def _reset_warned():
    global _warned
    _warned = False

class ResilientRedisCache(RedisCache):
    def get(self, key, default=None, version=None):
        try:
            value = super().get(key, default, version)
            _reset_warned()
            return value
        except RedisError as e:
            _warn(e)
            return default

    def set(self, key, value, timeout=None, version=None, client=None):
        try:
            super().set(key, value, timeout, version)
            _reset_warned()
            return True
        except RedisError as e:
            _warn(e)
            return False

    def add(self, key, value, timeout=None, version=None):
        try:
            result = super().add(key, value, timeout, version)
            _reset_warned()
            return result
        except RedisError as e:
            _warn(e)
            return True

    def incr(self, key, delta=1, version=None):
        try:
            return super().incr(key, delta, version)
        except RedisError as e:
            _warn(e)
            return delta

    def decr(self, key, delta=1, version=None):
        try:
            return super().decr(key, delta, version)
        except RedisError as e:
            _warn(e)
            return 0

    def delete(self, key, version=None):
        try:
            return super().delete(key, version)
        except RedisError as e:
            _warn(e)
            return False

    def touch(self, key, timeout=None, version=None):
        try:
            return super().touch(key, timeout, version)
        except RedisError as e:
            _warn(e)
            return False

    def has_key(self, key, version=None):
        try:
            return super().has_key(key, version)
        except RedisError as e:
            _warn(e)
            return False

    def get_many(self, keys, version=None):
        try:
            return super().get_many(keys, version)
        except RedisError as e:
            _warn(e)
            return {}

    def set_many(self, data, timeout=None, version=None):
        try:
            return super().set_many(data, timeout, version)
        except RedisError as e:
            _warn(e)
            return list(data)

    def is_available(self):
        """Return True if Redis is reachable, False if the connection fails.
        Calls the unguarded parent so RedisError is not swallowed here."""
        try:
            super().get('__health_check__')
            return True
        except RedisError:
            return False
