import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')

app = Celery('config')

app.config_from_object('django.conf:settings', namespace='CELERY')

app.conf.task_routes = {
    'apps.core.tasks.screen_resume_task': {'queue': 'screening'},
    'apps.core.tasks.batch_screen_resumes': {'queue': 'screening'},
    'apps.core.tasks.verify_resume_links_task': {'queue': 'verification'},
    'apps.core.tasks.close_expired_jobs': {'queue': 'screening'},
}
app.conf.task_default_queue = 'screening'

app.conf.worker_prefetch_multiplier = 1

app.autodiscover_tasks()

from celery.schedules import crontab  # noqa: E402

app.conf.beat_schedule = {
    'close-expired-jobs-daily': {
        'task': 'apps.core.tasks.close_expired_jobs',
        'schedule': crontab(hour=0, minute=5),
    },
}

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
