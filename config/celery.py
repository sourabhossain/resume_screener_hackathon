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
    'apps.core.tasks.close_expired_jobs': {'queue': 'notifications'},
    'apps.core.tasks.release_stale_screenings': {'queue': 'notifications'},
    'apps.core.tasks.clear_expired_sessions': {'queue': 'notifications'},
    'apps.core.tasks.draft_job_description_task': {'queue': 'screening'},
    # Invitation emails and the scheduled sweeps: short and I/O-bound, on their
    # own queue and worker so a batch of LLM screening calls never delays them.
    'apps.employee_form.tasks.send_employee_form_invite': {'queue': 'notifications'},
    'apps.reference_checks.tasks.send_reference_check_request': {'queue': 'notifications'},
    'apps.sei_assessment.tasks.send_assessment_invite': {'queue': 'notifications'},
    'apps.sei_assessment.tasks.send_sei_invite': {'queue': 'notifications'},
    'apps.sei_assessment.tasks.close_expired_sittings': {'queue': 'notifications'},
    'apps.core.tasks.send_rejection_email': {'queue': 'notifications'},
    'apps.interviews.tasks.send_evaluator_invite': {'queue': 'notifications'},
    'apps.interviews.tasks.send_candidate_invite': {'queue': 'notifications'},
    'apps.interviews.tasks.send_interview_reminders': {'queue': 'notifications'},
    'apps.interviews.tasks.send_interview_cancellation': {'queue': 'notifications'},
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
    # Every day at 00:05 Dhaka time: flip active jobs past their closing_date to 'closed'.
    'close-expired-jobs-daily': {
        'task': 'apps.core.tasks.close_expired_jobs',
        'schedule': crontab(hour=0, minute=5),
    },
    # A résumé whose screening task was lost is failed after 30 minutes so it
    # appears on the Screening failed page for a re-run.
    'release-stale-screenings': {
        'task': 'apps.core.tasks.release_stale_screenings',
        'schedule': crontab(minute='*/10'),
    },
    # 10:00 Dhaka: the day before each interview, its panel and candidate.
    'interview-reminders-daily': {
        'task': 'apps.interviews.tasks.send_interview_reminders',
        'schedule': crontab(hour=10, minute=0),
    },
    'clear-expired-sessions-daily': {
        'task': 'apps.core.tasks.clear_expired_sessions',
        'schedule': crontab(hour=3, minute=15),
    },
    # The SEI sitting is fifteen minutes long, so a candidate who closes the tab
    # leaves an open paper. Swept every five minutes rather than daily: HR
    # should not see "In progress" for someone who left before lunch.
    'close-expired-sei-sittings': {
        'task': 'apps.sei_assessment.tasks.close_expired_sittings',
        'schedule': crontab(minute='*/5'),
    },
}

