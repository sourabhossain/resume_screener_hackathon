import logging
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.db import transaction

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, soft_time_limit=120, time_limit=150, acks_late=True)
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
        logger.error(f"Resume {resume_id} screening timed out after 120s")
        try:
            Resume.objects.filter(id=resume_id).update(screening_status='failed')
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
                Resume.objects.filter(id=resume_id).update(screening_status='failed')
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
        resume.save(update_fields=['verification_status'])

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
            'verification_status', 'verified_at'
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

        Resume.objects.filter(id__in=resume_ids).update(screening_status='processing')

    for resume_id in resume_ids:
        screen_resume_task.delay(resume_id)

    return {'queued': len(resume_ids)}


@shared_task(ignore_result=True)
def close_expired_jobs():
    """Auto-close active jobs whose application deadline (closing_date) has passed.

    Mirrors the public apply guard (a job is "over" once today is *after* its
    closing_date), so listings and filters reflect reality without manual edits.
    Scheduled daily via Celery Beat (see config/celery.py).
    """
    from django.utils import timezone
    from apps.core.models import Job

    today = timezone.now().date()
    count = Job.objects.filter(
        status='active',
        closing_date__isnull=False,
        closing_date__lt=today,
    ).update(status='closed', updated_at=timezone.now())

    if count:
        logger.info("Auto-closed %d expired job(s) past their closing date", count)
    return {'closed': count}
