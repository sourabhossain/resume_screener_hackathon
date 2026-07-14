"""
Base settings for Resume Screening System.
Common settings shared across all environments.
"""
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent.parent

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',

    'rest_framework',
    'drf_spectacular',

    'apps.core',
    'apps.interviews',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'config.middleware.RequestCorrelationMiddleware',
    'config.middleware.ContentSecurityPolicyMiddleware',
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

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.environ.get('DB_NAME'),
        'USER': os.environ.get('DB_USER'),
        'PASSWORD': os.environ.get('DB_PASSWORD'),
        'HOST': os.environ.get('DB_HOST'),
        'PORT': os.environ.get('DB_PORT'),
        'CONN_MAX_AGE': int(os.environ.get('DB_CONN_MAX_AGE', '60')),
        'CONN_HEALTH_CHECKS': True,
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'core:dashboard'
LOGOUT_REDIRECT_URL = 'login'

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
        'apps.interviews': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}

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
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.UserRateThrottle',
        'rest_framework.throttling.AnonRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'user': '120/min',
        'anon': '30/min',
    },
}

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

CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'

_REDIS_CACHE_BASE = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0').rsplit('/', 1)[0]
CACHES = {
    'default': {
        'BACKEND': 'config.cache_backends.ResilientRedisCache',
        'LOCATION': os.environ.get('CACHE_URL', f'{_REDIS_CACHE_BASE}/1'),
        'OPTIONS': {
            'pool_class': 'redis.connection.BlockingConnectionPool',
            'max_connections': int(os.environ.get('REDIS_MAX_CONNECTIONS', '50')),
            'socket_connect_timeout': 1,
            'socket_timeout': 1,
        },
    }
}

RATELIMIT_FAIL_OPEN = True

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
OPENAI_MODEL = 'gpt-5-nano-2025-08-07'

AI_SCREENING_CONFIG = {
    'TOP_TIER_THRESHOLD': 80,
    'MID_TIER_THRESHOLD': 60,
    # Extraction truncates the resume to this many chars BEFORE parsing. Real
    # 2-3 page resumes run 8-11k chars, so a 4000 cap silently dropped the
    # second half (experience/education/achievements) and starved the scorer,
    # pushing long resumes to artificially low scores. gpt-5-nano handles the
    # larger input cheaply, especially with extraction on reasoning_effort=minimal.
    'MAX_RESUME_CHARS': 16000,
    # Same truncation trap as MAX_RESUME_CHARS, on the job side. The JD is cut to
    # this length for BOTH job-type detection and candidate matching, so a long
    # multi-domain JD (e.g. a Head-of-Data role spanning 7 areas) lost its tail
    # requirements -> misrouted family and candidates scored against a partial
    # spec. 8000 covers realistic JDs; cheap for gpt-5-nano.
    'MAX_JOB_DESC_CHARS': 8000,
    # Detector results below this confidence are flagged for manual review
    # rather than routed to a guessed family.
    'JOB_TYPE_CONFIDENCE_THRESHOLD': 0.4,
}

FAMILY_WEIGHTS = {
    'software_engineering': {'skill': 0.40, 'experience': 0.25, 'education': 0.15, 'certification': 0.10, 'achievement': 0.10},
    'devops_sre':          {'skill': 0.40, 'experience': 0.25, 'education': 0.10, 'certification': 0.15, 'achievement': 0.10},
    'qa_test':             {'skill': 0.40, 'experience': 0.25, 'education': 0.15, 'certification': 0.10, 'achievement': 0.10},
    'data_ai':             {'skill': 0.40, 'experience': 0.25, 'education': 0.15, 'certification': 0.10, 'achievement': 0.10},
    'security':            {'skill': 0.35, 'experience': 0.25, 'education': 0.10, 'certification': 0.20, 'achievement': 0.10},
    'product_management':  {'skill': 0.30, 'experience': 0.25, 'education': 0.15, 'certification': 0.05, 'achievement': 0.25},
    'design_creative':     {'skill': 0.35, 'experience': 0.20, 'education': 0.10, 'certification': 0.05, 'achievement': 0.30},
    'project_management':  {'skill': 0.30, 'experience': 0.30, 'education': 0.10, 'certification': 0.15, 'achievement': 0.15},
    'sales':               {'skill': 0.25, 'experience': 0.25, 'education': 0.05, 'certification': 0.05, 'achievement': 0.40},
    'marketing':           {'skill': 0.30, 'experience': 0.20, 'education': 0.10, 'certification': 0.10, 'achievement': 0.30},
    'customer_success':    {'skill': 0.30, 'experience': 0.25, 'education': 0.10, 'certification': 0.10, 'achievement': 0.25},
    'customer_support':    {'skill': 0.40, 'experience': 0.25, 'education': 0.10, 'certification': 0.10, 'achievement': 0.15},
    'finance_admin':       {'skill': 0.30, 'experience': 0.25, 'education': 0.15, 'certification': 0.20, 'achievement': 0.10},
    'hr_recruitment':      {'skill': 0.35, 'experience': 0.25, 'education': 0.15, 'certification': 0.10, 'achievement': 0.15},
    'legal_compliance':    {'skill': 0.30, 'experience': 0.25, 'education': 0.20, 'certification': 0.15, 'achievement': 0.10},
    'it_internal':         {'skill': 0.40, 'experience': 0.25, 'education': 0.10, 'certification': 0.15, 'achievement': 0.10},
    'operations':          {'skill': 0.35, 'experience': 0.25, 'education': 0.10, 'certification': 0.10, 'achievement': 0.20},
}
