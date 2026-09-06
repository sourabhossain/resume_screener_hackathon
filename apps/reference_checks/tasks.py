"""Background delivery of verification requests.

Sending inside the request meant a slow or unreachable SMTP server held a web
worker; the one-time code is generated *inside* the task so no plaintext code is
ever written to the broker.
"""
import logging

from celery import shared_task
from django.utils import timezone

from .models import ReferenceCheck
from .services import send_request

logger = logging.getLogger(__name__)


@shared_task(
    name='apps.reference_checks.tasks.send_reference_check_request',
    soft_time_limit=60,
    time_limit=90,
)
def send_reference_check_request(check_id: int) -> str:
    """Issue a fresh code and email the respondent their link.

    Deliberately does not retry: a retry re-issues the code, invalidating one the
    respondent may already have. Failures are recorded on the row, shown to HR,
    and cleared by pressing Resend.
    """
    try:
        check = ReferenceCheck.objects.select_related(
            'resume', 'resume__job').get(pk=check_id)
    except ReferenceCheck.DoesNotExist:
        logger.warning('reference_checks.skipped check=%s (deleted)', check_id)
        return 'missing'

    if check.is_submitted:
        logger.info('reference_checks.skipped check=%s (already replied)', check_id)
        return 'already_submitted'

    otp = check.issue_otp()
    check.invited_at = timezone.now()
    check.invite_count = (check.invite_count or 0) + 1
    check.last_error = ''
    check.last_error_at = None
    # Not a bare save(): the respondent may be part-way through the form, and a
    # full row write here would put back the answers as they were when this task
    # loaded the row.
    check.save(update_fields=[
        *ReferenceCheck.OTP_FIELDS,
        'invited_at', 'invite_count', 'last_error', 'last_error_at', 'updated_at',
    ])

    try:
        send_request(check, otp=otp)
    except Exception as exc:
        # Swallowed on purpose: raising would only retry-storm the broker. HR
        # sees the reason on the candidate page and can resend.
        ReferenceCheck.objects.filter(pk=check.pk).update(
            last_error=str(exc)[:500], last_error_at=timezone.now())
        logger.exception('reference_checks.failed check=%s', check.pk)
        return 'failed'

    return 'sent'
