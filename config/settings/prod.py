"""
Production settings for Resume Screening System.
"""
from .base import *
import os
from django.core.exceptions import ImproperlyConfigured

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY')

# Validate that SECRET_KEY is set in production
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "The SECRET_KEY environment variable must be set in production. "
        "Generate one using: python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'"
    )

# Validate that DEBUG is False (defensive check)
if os.environ.get('DEBUG', '').lower() in ('true', '1', 'yes'):
    raise ImproperlyConfigured(
        "DEBUG must be False in production. Remove the DEBUG environment variable or set it to False."
    )

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

# Filter out empties so a missing/empty ALLOWED_HOSTS becomes [] (not ['']),
# then fail fast — mirroring the SECRET_KEY/DEBUG guards above. Otherwise the app
# boots and silently 400s every request, inviting an operator to "fix" it with '*'.
ALLOWED_HOSTS = [h.strip() for h in os.environ.get('ALLOWED_HOSTS', '').split(',') if h.strip()]
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "The ALLOWED_HOSTS environment variable must be set in production "
        "(comma-separated hostnames, e.g. 'careers.example.com')."
    )

# Django 4.0+ checks the Origin header against this list for CSRF on HTTPS.
# Must include every public hostname (and port if non-standard) the app serves.
# Override via CSRF_TRUSTED_ORIGINS env var to avoid baking hostnames into code.
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',')
    if origin.strip()
] or [f'https://{h}' for h in ALLOWED_HOSTS if h]
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True

# HTTPS settings
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# HSTS settings
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True


# Sentry Error Monitoring
SENTRY_DSN = os.environ.get('SENTRY_DSN')
if SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=0.1,  # 10% of transactions
        profiles_sample_rate=0.1,
        environment="production",
        send_default_pii=False,
    )
