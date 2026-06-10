"""
Base settings for Resume Screening System.
Common settings shared across all environments.
"""
from pathlib import Path
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third-party apps
    'rest_framework',
    'drf_spectacular',
    
    # Local apps
    'apps.core',
    'apps.interviews',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # Serves collected static files directly from the app process so gunicorn
    # works with DEBUG=False without needing nginx in front for static.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.environ.get('DB_NAME'),
        'USER': os.environ.get('DB_USER'),
        'PASSWORD': os.environ.get('DB_PASSWORD'),
        'HOST': os.environ.get('DB_HOST'),
        'PORT': os.environ.get('DB_PORT'),
        # Reuse a DB connection across requests instead of opening a fresh
        # TCP+auth handshake every time. Under load this removes thousands of
        # connection setups/sec. Keep it below the DB server's per-client idle
        # timeout (MySQL wait_timeout). Override with DB_CONN_MAX_AGE if needed.
        'CONN_MAX_AGE': int(os.environ.get('DB_CONN_MAX_AGE', '60')),
        'CONN_HEALTH_CHECKS': True,
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# Internationalization

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# WhiteNoise: compress collected static files. Plain (non-manifest) storage so
# a missing/unreferenced asset never hard-fails a request under DEBUG=False.
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}

# Media files (User uploads)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# Default primary key field type

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Authentication settings

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'core:dashboard'
LOGOUT_REDIRECT_URL = 'login'


# Logging Configuration

LOGS_DIR = BASE_DIR / 'logs'
LOGS_DIR.mkdir(exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            # One file per calendar day: logs/app_YYYY-MM-DD.log (uses TIME_ZONE, UTC in base settings).
            '()': 'config.logging_handlers.DateNamedFileHandler',
            'logs_dir': LOGS_DIR,
            'prefix': 'app',
            'backup_count': 30,
            'encoding': 'utf-8',
            'formatter': 'verbose',
        },
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps.core': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}


# Django REST Framework Configuration

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 10,
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}


# DRF Spectacular Configuration (OpenAPI/Swagger)
SPECTACULAR_SETTINGS = {
    'TITLE': 'Career API',
    'DESCRIPTION': 'AI-powered resume screening API',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'CAMELIZE_NAMES': False,
    'TAGS': [
        {'name': 'Jobs', 'description': 'Job management'},
        {'name': 'Resumes', 'description': 'Resume screening'},
    ],
    'SWAGGER_UI_SETTINGS': {
        'deepLinking': True,
        'persistAuthorization': True,
        'filter': True,
        'docExpansion': 'list',
        'tagsSorter': 'alpha',
        'operationsSorter': 'alpha',
        'displayOperationId': True,
    },
}


# Celery Configuration
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'


# Cache — shared Redis (separate DB index from the Celery broker) so that
# rate limiting and the LLM response cache are consistent across all web/worker
# processes. A per-process LocMemCache would let attackers bypass rate limits
# by spreading requests across workers. (tests override this with LocMemCache)
_REDIS_CACHE_BASE = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0').rsplit('/', 1)[0]
CACHES = {
    'default': {
        # Resilient subclass: degrades (no-op) instead of 500-ing if Redis is down.
        'BACKEND': 'config.cache_backends.ResilientRedisCache',
        'LOCATION': os.environ.get('CACHE_URL', f'{_REDIS_CACHE_BASE}/1'),
        'OPTIONS': {
            # Bound the Redis connection pool so a request/concurrency spike
            # (every request hits Redis for rate-limit + LLM cache) can't open
            # an unbounded number of sockets to Redis.
            'pool_class': 'redis.connection.BlockingConnectionPool',
            'max_connections': int(os.environ.get('REDIS_MAX_CONNECTIONS', '50')),
        },
    }
}

# Availability over strictness: if Redis (the rate-limit store) is briefly
# unreachable, let requests through instead of 500-ing. Without this a Redis
# blip takes down login / careers-apply / API writes entirely. The trade-off is
# that rate limiting is disabled only for the duration of a Redis outage.
RATELIMIT_FAIL_OPEN = True


# OpenAI Configuration
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
OPENAI_MODEL = 'gpt-5-nano-2025-08-07'


# AI Screening Configuration
AI_SCREENING_CONFIG = {
    # Tech role weights (sum = 1.0)
    'SKILL_WEIGHT': 0.40,
    'EXPERIENCE_WEIGHT': 0.30,
    'EDUCATION_WEIGHT': 0.20,
    'CERTIFICATION_WEIGHT': 0.10,
    # Non-tech role weights — includes achievement_score (sum = 1.0)
    'NON_TECH_SKILL_WEIGHT': 0.30,
    'NON_TECH_EXPERIENCE_WEIGHT': 0.25,
    'NON_TECH_EDUCATION_WEIGHT': 0.15,
    'NON_TECH_CERTIFICATION_WEIGHT': 0.10,
    'NON_TECH_ACHIEVEMENT_WEIGHT': 0.20,
    'TOP_TIER_THRESHOLD': 80,
    'MID_TIER_THRESHOLD': 60,
    'MAX_RESUME_CHARS': 4000,
    'MAX_JOB_DESC_CHARS': 3000,
}
