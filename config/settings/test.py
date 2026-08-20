import tempfile

from .base import *

DEBUG = False
SECRET_KEY = 'test-key-insecure-but-fine-for-tests'

# Uploads go to a throwaway directory, never the real media volume.
# Without this, every test that posts a file (resumes, NID scans, certificates)
# writes into MEDIA_ROOT for real and nothing removes it, so running the suite
# steadily fills the volume with candidate documents that no row points at.
MEDIA_ROOT = tempfile.mkdtemp(prefix='screener-test-media-')

# Avoid LLMClient "OPENAI_API_KEY not configured" noise when .env omits the key; tests mock API calls.
if not OPENAI_API_KEY:
    OPENAI_API_KEY = 'sk-test-dummy-invalid-for-real-calls'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Local in-memory cache for tests (no Redis dependency).
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

# Disable rate limiting for tests to avoid interference, or keep it if we want to test it.
# For now, let's keep it but tests might need to handle it.
# Actually, better to test with it enabled but be aware of limits.

# Speed up tests
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Run Celery tasks synchronously in tests (no broker needed)
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
