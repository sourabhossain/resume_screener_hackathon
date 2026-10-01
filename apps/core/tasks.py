import logging
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.db import transaction

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, soft_time_limit=180, time_limit=210, acks_late=True)
def screen_resume_task(self, resume_id: int):
    from apps.core.models import Resume
    from apps.core.services.resume_service import ResumeService

    try:
        resume = Resume.objects.select_related('job').get(id=resume_id)
        logger.info(f"Starting screening for resume {resume_id}")

        result = ResumeService.process_resume(resume)

        if result.get('success'):
            logger.info(f"Completed screening for resume {resume_id}: Score={result.get('final_score')}, Tier={result.get('tier')}")
        else:
            logger.error(f"Screening failed for resume {resume_id}: {result.get('error')}")
        return result

    except SoftTimeLimitExceeded:
        logger.error(f"Resume {resume_id} screening timed out after 180s")
        try:
            Resume.objects.filter(id=resume_id).update(
                screening_status='failed',
                reasoning='Screening timed out — the AI took too long to respond. Re-run to try again.',
            )
        except Exception as update_err:
            logger.warning(f"Could not update status after timeout for resume {resume_id}: {update_err}")
        return {'error': 'timeout', 'resume_id': resume_id}

    except Resume.DoesNotExist:
        logger.error(f"Resume {resume_id} not found — may have been deleted")
        # all_objects reaches soft-deleted rows to prevent them staying 'processing'
        Resume.all_objects.filter(id=resume_id).update(screening_status='failed')
        return {'error': 'Resume not found'}

    except Exception as e:
        logger.exception(f"Error screening resume {resume_id}: {e}")

        retries_left = self.max_retries - self.request.retries
        if retries_left > 0:
            # Keep as pending so UI shows it queued, not failed, while retrying
            try:
                Resume.objects.filter(id=resume_id).update(screening_status='pending')
            except Exception as update_err:
                logger.warning(f"Could not reset status to pending for resume {resume_id}: {update_err}")
        else:
            try:
                Resume.objects.filter(id=resume_id).update(
                    screening_status='failed',
                    reasoning=f'Screening failed repeatedly — {e}. Re-run to try again.',
                )
            except Exception as update_err:
                logger.warning(f"Could not update status to failed for resume {resume_id}: {update_err}")
            logger.error(f"Resume {resume_id} permanently failed after {self.max_retries} retries")

        raise self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=2, soft_time_limit=180, time_limit=210, acks_late=True)
def verify_resume_links_task(self, resume_id: int):
    from apps.core.models import Resume
    from apps.core.services.link_verifier import LinkVerifier

    try:
        resume = Resume.objects.get(id=resume_id)
    except Resume.DoesNotExist:
        logger.warning(
            "Resume %s not found for link verification — skipping (deleted or invalid id)",
            resume_id,
        )
        Resume.all_objects.filter(id=resume_id).update(verification_status='failed')
        return {'error': 'Resume not found'}

    try:
        resume.verification_status = 'processing'
        resume.save(update_fields=['verification_status', 'updated_at'])

        result = LinkVerifier.verify_resume(resume)

        status = result.get('status', 'completed')
        if status == 'skipped':
            resume.verification_status = 'skipped'
        elif status == 'failed':
            resume.verification_status = 'failed'
        else:
            resume.verification_status = status

        resume.verification_results = result
        resume.verification_score = result.get('verification_score')

        from django.utils import timezone
        resume.verified_at = timezone.now() if resume.verification_status == 'completed' else None

        resume.save(update_fields=[
            'verification_results', 'verification_score',
            'verification_status', 'verified_at', 'updated_at'
        ])

        return result

    except SoftTimeLimitExceeded:
        logger.error(f"Link verification timed out for resume {resume_id}")
        Resume.objects.filter(id=resume_id).update(verification_status='failed', verified_at=None)
        return {'error': 'timeout'}
    except Exception as e:
        logger.exception(f"Link verification failed for resume {resume_id}: {e}")
        try:
            Resume.objects.filter(id=resume_id).update(verification_status='failed', verified_at=None)
        except Exception as update_err:
            logger.warning(f"Could not update verification status: {update_err}")
        raise self.retry(exc=e, countdown=30)


@shared_task
def batch_screen_resumes(job_id: int):
    from django.utils import timezone
    from apps.core.models import Resume

    # skip_locked=True prevents concurrent calls from dispatching the same resumes twice
    with transaction.atomic():
        resume_ids = list(
            Resume.objects.select_for_update(skip_locked=True).filter(
                job_id=job_id,
                screening_status='pending',
                is_deleted=False,
            ).values_list('id', flat=True)[:500]
        )

        if not resume_ids:
            return {'queued': 0}

        Resume.objects.filter(id__in=resume_ids).update(
            screening_status='processing', updated_at=timezone.now())

    from apps.core.services.screening_queue import queue_screening
    for resume_id in resume_ids:
        queue_screening(resume_id)

    return {'queued': len(resume_ids)}


@shared_task(ignore_result=True)
def release_stale_screenings():
    """Fail résumés whose screening task was lost, so they show up for a re-run.

    A row saved as 'processing' whose message never reached a worker (broker
    down, worker killed) would otherwise sit in 'processing' for ever, and
    neither the candidate nor the recruiter could get it screened.
    """
    from django.utils import timezone
    from apps.core.models import Resume
    from apps.core.services.screening_queue import (
        STALE_REASON, stale_filter, stale_verification_filter)

    count = Resume.objects.filter(stale_filter()).update(
        screening_status='failed', reasoning=STALE_REASON, updated_at=timezone.now())
    if count:
        logger.warning('screening.released_stale count=%s', count)
    # A lost link check would otherwise keep the row polling for ever.
    links = Resume.objects.filter(stale_verification_filter()).update(
        verification_status='failed', verified_at=None, updated_at=timezone.now())
    if links:
        logger.warning('verification.released_stale count=%s', links)
    return {'released': count, 'links_released': links}


@shared_task(ignore_result=True)
def clear_expired_sessions():
    """Delete expired login and candidate sessions; Django never does this itself."""
    from django.core.management import call_command
    call_command('clearsessions')


@shared_task(ignore_result=True)
def close_expired_jobs():
    """Auto-close active jobs whose application deadline (closing_date) has passed.

    Mirrors the public apply guard (a job is "over" once today is *after* its
    closing_date), so listings and filters reflect reality without manual edits.
    Scheduled daily via Celery Beat (see config/celery.py).
    """
    from django.utils import timezone
    from apps.core.models import Job

    today = timezone.localdate()
    count = Job.objects.filter(
        status='active',
        closing_date__isnull=False,
        closing_date__lt=today,
    ).update(status='closed', updated_at=timezone.now())

    if count:
        logger.info("Auto-closed %d expired job(s) past their closing date", count)
    return {'closed': count}


@shared_task(soft_time_limit=120, time_limit=150)
def draft_job_description_task(token: str, title: str, brief: str = '',
                               archetype: str = '') -> str:
    """Write one job description draft and leave it in the cache to be polled.

    Not done in the request: gunicorn is started with --timeout 30 while a
    reasoning-model call is allowed 60s, so a synchronous draft would have the
    web worker killed mid-generation and the recruiter shown nothing.
    """
    from apps.core.services import job_description

    try:
        text, used = job_description.generate(title, brief, archetype)
    except job_description.DraftError as exc:
        job_description.store_result(token, error=str(exc))
        return 'failed'
    except Exception:
        logger.exception('job_description.task_crashed token=%s', token)
        job_description.store_result(
            token, error='The draft could not be written just now. '
                         'Try again in a moment.')
        return 'failed'

    job_description.store_result(token, text=text, archetype=used)
    return 'done'


@shared_task(name='apps.core.tasks.send_rejection_email', soft_time_limit=60, time_limit=90)
def send_rejection_email(resume_id: int, user_id=None) -> str:
    """Email a rejected candidate once, and record who sent it and when.

    Not retried: a retry after an SMTP timeout could send the same letter twice.
    A failure is kept on the row and shown on the candidate page.
    """
    from django.core.cache import cache
    from apps.core.utils import claim_send

    # Two clicks far enough apart can queue two tasks; only one may send, and
    # the second then finds the first one's sent_at.
    if not claim_send('rejection-sending', resume_id, seconds=600):
        return 'in_progress'
    try:
        return _send_rejection_email(resume_id, user_id)
    finally:
        cache.delete(f'send-claim:rejection-sending:{resume_id}')


def _send_rejection_email(resume_id, user_id):
    from django.conf import settings
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string
    from django.utils import timezone
    from apps.core.models import Resume

    resume = Resume.objects.select_related('job').filter(pk=resume_id).first()
    if resume is None:
        return 'missing'
    if resume.rejection_email_sent_at:
        return 'already_sent'
    if resume.recruiter_status != 'rejected':
        Resume.all_objects.filter(pk=resume_id).update(
            rejection_email_error='Not sent: the candidate is no longer marked Rejected.')
        return 'not_rejected'

    context = {'candidate_name': ' '.join((resume.candidate_name or '').split()).title() or 'Candidate',
               'job_title': resume.job.title}
    message = EmailMultiAlternatives(
        subject=' '.join(f'Your application for {resume.job.title} at SSL Wireless'.split()),
        body=render_to_string('core/email/rejection.txt', context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[resume.email],
        reply_to=[settings.CAREERS_REPLY_TO],
    )
    message.attach_alternative(render_to_string('core/email/rejection.html', context), 'text/html')
    try:
        message.send(fail_silently=False)
    except Exception as exc:
        Resume.all_objects.filter(pk=resume_id).update(rejection_email_error=str(exc)[:500])
        logger.exception('rejection_email.failed resume=%s', resume_id)
        return 'failed'
    Resume.all_objects.filter(pk=resume_id).update(
        rejection_email_sent_at=timezone.now(), rejection_email_sent_by_id=user_id,
        rejection_email_error='')
    logger.info('rejection_email.sent resume=%s by=%s', resume_id, user_id)
    return 'sent'
