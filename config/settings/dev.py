"""
Development settings for Resume Screening System.
"""
import os

from .base import *

# Load the secret from the environment; fall back to an obviously-insecure value
# for local dev only. Never commit a real key here. For production use prod.py.
SECRET_KEY = os.environ.get(
    'SECRET_KEY',
    'django-insecure-LOCAL-DEV-ONLY-do-not-use-in-production',
)

# DEBUG defaults on for local dev but can be forced off via env.
DEBUG = os.environ.get('DEBUG', 'True').lower() in ('1', 'true', 'yes')

# Restrict hosts when provided (e.g. on a shared/remote dev box); '*' only as the local default.
ALLOWED_HOSTS = [h.strip() for h in os.environ.get('ALLOWED_HOSTS', '*').split(',') if h.strip()]

# Django 4+ validates POST origins; without this, admin/login can return 403 on localhost/Docker.
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'http://localhost',
    'http://127.0.0.1',
]

INTERNAL_IPS = ['127.0.0.1']

# Email backend for development
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Force per-request template reloads in dev so .html edits show up without
# restarting gunicorn. Without this, cached.Loader pins compiled templates in
# worker memory until a restart (gunicorn --reload only watches .py files).
TEMPLATES[0]['APP_DIRS'] = False
TEMPLATES[0]['OPTIONS']['loaders'] = [
    'django.template.loaders.filesystem.Loader',
    'django.template.loaders.app_directories.Loader',
]
