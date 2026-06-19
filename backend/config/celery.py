import os
from celery import Celery
from celery.schedules import crontab
from decouple import config

# Force deterministic settings selection
os.environ.setdefault(
    'DJANGO_SETTINGS_MODULE',
    config('DJANGO_SETTINGS_MODULE', default='config.settings.dev')
)

app = Celery('vigil')

# Load Django settings (CELERY_* namespace)
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from installed apps
app.autodiscover_tasks()

# Beat schedule
app.conf.beat_schedule = {
    'check-endpoints-every-5-minutes': {
        'task': 'apps.monitors.tasks.schedule_checks',
        'schedule': crontab(minute='*/5'),
    },
    'retry-failed-emails-every-2-minutes': {
        'task': 'apps.monitors.tasks.retry_failed_emails',
        'schedule': crontab(minute='*/2'),
    },
}

# Optional but recommended for consistency
app.conf.timezone = 'UTC'