"""Background delivery, and closing sittings the candidate walked away from."""
import logging

from celery import shared_task
from django.utils import timezone

from .models import SEIAssessment
from .services import finalise_if_time_is_up, send_invite

logger = logging.getLogger(__name__)


@shared_task(
    name='apps.sei_assessment.tasks.send_sei_invite',
    soft_time_limit=60,
    time_limit=90,
)
def send_sei_invite(assessment_id: int) -> str:
    """Issue a fresh code and email the candidate their link.

    Deliberately does not retry: a retry re-issues the code, invalidating one
    the candidate may already be holding. Failures are recorded on the row and
    shown to the recruiter, who can press Resend.
    """
    try:
        assessment = SEIAssessment.objects.select_related(
            'resume', 'resume__job').get(pk=assessment_id)
    except SEIAssessment.DoesNotExist:
        logger.warning('sei.skipped assessment=%s (deleted)', assessment_id)
        return 'missing'

    if assessment.is_submitted:
        logger.info('sei.skipped assessment=%s (already completed)', assessment_id)
        return 'already_submitted'

    otp = assessment.issue_otp()
    assessment.invited_at = timezone.now()
    assessment.invite_count = (assessment.invite_count or 0) + 1
    assessment.last_error = ''
    assessment.last_error_at = None
    # Not a bare save(): the candidate may be answering right now, and a full
    # row write would put back the answers as they were when this task loaded.
    assessment.save(update_fields=[
        *SEIAssessment.OTP_FIELDS,
        'invited_at', 'invite_count', 'last_error', 'last_error_at', 'updated_at',
    ])

    try:
        send_invite(assessment, otp=otp)
    except Exception as exc:
        # Swallowed on purpose: raising would only retry-storm the broker. The
        # recruiter sees the reason on the candidate page and can resend.
        SEIAssessment.objects.filter(pk=assessment.pk).update(
            last_error=str(exc)[:500], last_error_at=timezone.now())
        logger.exception('sei.failed assessment=%s', assessment.pk)
        return 'failed'
    return 'sent'


@shared_task(name='apps.sei_assessment.tasks.close_expired_sittings')
def close_expired_sittings() -> int:
    """Submit sittings whose fifteen minutes ran out while nobody was looking.

    Without this an abandoned tab leaves the paper open indefinitely, and HR
    sees "In progress" for a candidate who left days ago.
    """
    stale = SEIAssessment.objects.filter(
        is_submitted=False,
        started_at__isnull=False,
        deadline_at__lte=timezone.now(),
    )
    closed = sum(1 for sitting in stale if finalise_if_time_is_up(sitting))
    if closed:
        logger.info('sei.swept closed=%s', closed)
    return closed
