from .base import *

DEBUG = False
SECRET_KEY = 'test-key-insecure-but-fine-for-tests'

if not OPENAI_API_KEY:
    OPENAI_API_KEY = 'sk-test-dummy-invalid-for-real-calls'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
