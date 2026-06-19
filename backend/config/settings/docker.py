"""
Settings for the local Docker Compose demo (docker-compose.yml).

Differences from dev.py:
  - PostgreSQL instead of SQLite (matches the db service in docker-compose.yml)
  - Console email backend (no SMTP credentials required to run the demo)
  - debug_toolbar excluded (not installed in the Docker image)

Do not use for production — see prod.py.
"""
from .base import *
from decouple import config

SECRET_KEY = config('SECRET_KEY', default='docker-demo-insecure-key-replace-before-real-deployment')
DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'backend']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME':     config('DB_NAME',     default='vigil_db'),
        'USER':     config('DB_USER',     default='vigil_user'),
        'PASSWORD': config('DB_PASSWORD', default='vigil_pass'),
        'HOST':     config('DB_HOST',     default='db'),
        'PORT':     config('DB_PORT',     default='5432'),
    }
}

CELERY_BROKER_URL = config('REDIS_URL', default='redis://redis:6379/0')
CELERY_RESULT_BACKEND = 'django-db'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# Emails print to the container log — no SMTP credentials required for the demo.
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

CORS_ALLOWED_ORIGINS = [
    'http://localhost',
    'http://localhost:80',
    'http://127.0.0.1',
]
CORS_ALLOW_CREDENTIALS = True

# Relax throttle limits so the demo is not accidentally rate-limited.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    'DEFAULT_THROTTLE_RATES': {
        'anon':  '10000/hour',
        'user':  '100000/hour',
        'login': '1000/minute',
    },
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
}
