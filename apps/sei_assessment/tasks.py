"""Background delivery, and closing sittings the candidate walked away from."""
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from .models import AssessmentInvitation, SEIAssessment
from .services import finalise_if_time_is_up, issue_fresh_code, send_invite

logger = logging.getLogger(__name__)


@shared_task(
    name='apps.sei_assessment.tasks.send_assessment_invite',
    soft_time_limit=60,
    time_limit=90,
)
def send_assessment_invite(invitation_id: int) -> str:
    """Issue a fresh code and email the candidate their one link.

    Deliberately does not retry: a retry re-issues the code, invalidating one
    the candidate may already be holding. Failures are recorded on the row and
    shown to the recruiter, who can press Resend.
    """
    try:
        invitation = AssessmentInvitation.objects.select_related(
            'resume', 'resume__job').get(pk=invitation_id)
    except AssessmentInvitation.DoesNotExist:
        logger.warning('sei.skipped invitation=%s (deleted)', invitation_id)
        return 'missing'

    if invitation.is_complete:
        logger.info('sei.skipped invitation=%s (already completed)', invitation_id)
        return 'already_submitted'
    if invitation.resume.is_deleted or invitation.resume.job.is_deleted:
        logger.info('sei.skipped invitation=%s (candidate deleted)', invitation_id)
        return 'deleted'

    otp = issue_fresh_code(invitation)
    invitation.invited_at = timezone.now()
    invitation.invite_count = (invitation.invite_count or 0) + 1
    invitation.last_error = ''
    invitation.last_error_at = None
    invitation.save(update_fields=[
        *AssessmentInvitation.OTP_FIELDS,
        'invited_at', 'invite_count', 'last_error', 'last_error_at', 'updated_at',
    ])

    try:
        send_invite(invitation, otp=otp)
    except Exception as exc:
        # Swallowed on purpose: raising would only retry-storm the broker. The
        # recruiter sees the reason on the candidate page and can resend.
        AssessmentInvitation.objects.filter(pk=invitation.pk).update(
            last_error=str(exc)[:500], last_error_at=timezone.now())
        logger.exception('sei.failed invitation=%s', invitation.pk)
        return 'failed'
    return 'sent'


@shared_task(name='apps.sei_assessment.tasks.send_sei_invite')
def send_sei_invite(assessment_id: int) -> str:
    """Old per-sitting task name, kept so messages queued before deploy still send."""
    sitting = SEIAssessment.objects.select_related('invitation').filter(
        pk=assessment_id).first()
    if sitting is None:
        logger.warning('sei.skipped assessment=%s (deleted)', assessment_id)
        return 'missing'
    # Both old per-part messages map to one invitation; send it once.
    sent_at = sitting.invitation.invited_at
    if sent_at and timezone.now() - sent_at < timedelta(minutes=10):
        return 'already_sent'
    return send_assessment_invite(sitting.invitation_id)


@shared_task(name='apps.sei_assessment.tasks.close_expired_sittings')
def close_expired_sittings() -> int:
    """Submit sittings whose clock ran out while nobody was looking.

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
