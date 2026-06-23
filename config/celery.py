import os
from celery import Celery

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')

app = Celery('config')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Route the two kinds of work to separate queues so they can scale
# independently (see docker-compose):
#   - 'screening'    : LLM calls, I/O-bound (waiting on OpenAI). Run with a
#                      high-concurrency thread pool — many CVs in parallel.
#   - 'verification' : Playwright/Chromium, CPU+RAM-heavy. Run with low
#                      concurrency so many headless browsers don't OOM the box.
app.conf.task_routes = {
    'apps.core.tasks.screen_resume_task': {'queue': 'screening'},
    'apps.core.tasks.batch_screen_resumes': {'queue': 'screening'},
    'apps.core.tasks.verify_resume_links_task': {'queue': 'verification'},
    'apps.core.tasks.close_expired_jobs': {'queue': 'screening'},
}
app.conf.task_default_queue = 'screening'

# Each worker pulls one task at a time instead of greedily hoarding the upload
# spike, so work spreads evenly across worker threads/replicas.
app.conf.worker_prefetch_multiplier = 1

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Requires a running `celery -A config beat` process (see docker-compose).
from celery.schedules import crontab  # noqa: E402

app.conf.beat_schedule = {
    # Every day at 00:05 UTC: flip active jobs past their closing_date to 'closed'.
    'close-expired-jobs-daily': {
        'task': 'apps.core.tasks.close_expired_jobs',
        'schedule': crontab(hour=0, minute=5),
    },
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
