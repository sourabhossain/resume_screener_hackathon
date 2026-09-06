"""Read-only go-live check: the settings that break things silently.

Every item here has cost a real outage or a dead email. None of them raises an
error at start-up, and none is visible on any page -- a wrong SITE_BASE_URL
just means every candidate gets a button that does nothing, and an un-restarted
worker just means invitations are accepted and never sent.

    docker compose exec web python manage.py preflight

Exits non-zero when something is wrong, so it can gate a deploy.
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.core.links import has_scheme, is_local, site_base_url

# Dispatched from the web process; each must be registered on a live worker.
REQUIRED_TASKS = (
    'apps.core.tasks.screen_resume_task',
    'apps.core.tasks.verify_resume_links_task',
    'apps.core.tasks.draft_job_description_task',
    'apps.employee_form.tasks.send_employee_form_invite',
    'apps.reference_checks.tasks.send_reference_check_request',
)


class Command(BaseCommand):
    help = 'Check the settings and workers that fail silently in production.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--skip-workers', action='store_true',
            help='Do not try to reach Celery (useful before the workers start).')

    def handle(self, *args, **options):
        good, bad = [], []

        self._check_site_url(good, bad)
        self._check_debug(good, bad)
        self._check_email(good, bad)
        self._check_openai(good, bad)
        if not options['skip_workers']:
            self._check_workers(good, bad)

        self.stdout.write('')
        for line in good:
            self.stdout.write(self.style.SUCCESS(f'  ok     {line}'))
        for line in bad:
            self.stdout.write(self.style.ERROR(f'  BROKEN {line}'))
        self.stdout.write('')

        if bad:
            self.stdout.write(self.style.ERROR(
                f'{len(bad)} problem(s) — fix before going live.'))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS('Ready to go live.'))

    # ── individual checks ────────────────────────────────────────────────
    def _check_site_url(self, good, bad):
        raw = (getattr(settings, 'SITE_BASE_URL', '') or '').strip()
        resolved = site_base_url()

        if not raw:
            bad.append('SITE_BASE_URL is empty — no emailed link can be built.')
        elif is_local(raw):
            bad.append(
                f'SITE_BASE_URL is {raw!r}. Every emailed button would point at '
                "the recipient's own machine, so none of them can work.")
        elif not has_scheme(raw):
            bad.append(
                f'SITE_BASE_URL is {raw!r} with no https://. A mail client reads '
                f'that as a relative link and strips it, leaving a dead button. '
                f'Write it as {resolved}.')
        elif not resolved.startswith('https://'):
            bad.append(
                f'SITE_BASE_URL is {resolved} — plain HTTP for links that carry '
                'NID numbers and ID scans.')
        else:
            good.append(f'SITE_BASE_URL {resolved}')

    def _check_debug(self, good, bad):
        if settings.DEBUG:
            bad.append('DEBUG is True — never serve real candidates with this on.')
        else:
            good.append('DEBUG False')

    def _check_email(self, good, bad):
        backend = getattr(settings, 'EMAIL_BACKEND', '')
        if 'smtp' not in backend:
            bad.append(
                f'EMAIL_BACKEND is {backend!r} — invitations and verification '
                'requests are written to a log, not delivered.')
            return
        good.append('EMAIL_BACKEND smtp')
        if not getattr(settings, 'EMAIL_HOST', ''):
            bad.append('EMAIL_HOST is empty, so nothing can be sent.')

        user = (getattr(settings, 'EMAIL_HOST_USER', '') or '').strip().lower()
        sender = (getattr(settings, 'DEFAULT_FROM_EMAIL', '') or '').strip().lower()
        if user and sender and user not in sender:
            bad.append(
                f'DEFAULT_FROM_EMAIL ({sender}) is not the authenticated mailbox '
                f'({user}); Microsoft 365 answers that with SendAsDenied.')

    def _check_openai(self, good, bad):
        if getattr(settings, 'OPENAI_API_KEY', ''):
            good.append(f'OPENAI_API_KEY set, model {settings.OPENAI_MODEL}')
        else:
            bad.append(
                'OPENAI_API_KEY is empty — CV screening and AI job-description '
                'drafting are both off.')

    def _check_workers(self, good, bad):
        """Celery registers tasks at start-up.

        A worker that booted before a task existed accepts the message and never
        runs it: no error, no retry, nothing in any log the operator watches.
        This has caught it twice.
        """
        from config.celery import app as celery_app

        try:
            registered = celery_app.control.inspect(timeout=5).registered() or {}
        except Exception as exc:
            bad.append(f'Could not reach any Celery worker ({type(exc).__name__}). '
                       'Nothing queued will run.')
            return

        if not registered:
            bad.append('No Celery worker answered. Nothing queued will run.')
            return

        known = {task for tasks in registered.values() for task in tasks}
        missing = [task for task in REQUIRED_TASKS if task not in known]
        if missing:
            for task in missing:
                bad.append(
                    f'No running worker knows {task} — it will be queued and '
                    'silently dropped. Restart the workers.')
        else:
            good.append(f'{len(registered)} worker(s), all {len(REQUIRED_TASKS)} '
                        'tasks registered')
