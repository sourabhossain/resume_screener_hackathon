"""Background delivery of Employee Information Form invitations.

Sending inside the request meant a slow or unreachable SMTP server held a web
worker for up to EMAIL_TIMEOUT seconds -- long enough for a recruiter's status
click to look broken, and with only a few gunicorn workers, long enough to hurt
everyone else on the site.

The one-time code is generated *inside* the task rather than passed to it, so no
plaintext OTP is ever written to the broker.
"""
import logging

from celery import shared_task
from django.utils import timezone

from .models import EmployeeForm
from .services import send_invite

logger = logging.getLogger(__name__)


@shared_task(
    name='apps.employee_form.tasks.send_employee_form_invite',
    soft_time_limit=60,
    time_limit=90,
)
def send_employee_form_invite(form_id: int) -> str:
    """Issue a fresh one-time code and email the candidate their form link.

    Deliberately does not retry: a retry re-issues the code, which would
    invalidate one the candidate may already have received if only the SMTP
    acknowledgement failed. Failures are recorded on the form instead, shown to
    the recruiter, and cleared by pressing Resend.
    """
    try:
        form = EmployeeForm.objects.select_related('resume', 'resume__job').get(
            pk=form_id
        )
    except EmployeeForm.DoesNotExist:
        logger.warning('employee_form.invite_skipped form=%s (deleted)', form_id)
        return 'missing'

    if form.is_submitted:
        logger.info('employee_form.invite_skipped form=%s (already submitted)', form_id)
        return 'already_submitted'

    otp = form.issue_otp()
    form.invited_at = timezone.now()
    form.invite_count = (form.invite_count or 0) + 1
    form.last_error = ''
    form.last_error_at = None
    form.save()

    try:
        send_invite(form, otp=otp)
    except Exception as exc:
        # Swallowed on purpose: raising here would only retry-storm the broker.
        # The recruiter sees the reason on the candidate page and can resend.
        EmployeeForm.objects.filter(pk=form.pk).update(
            last_error=str(exc)[:500], last_error_at=timezone.now()
        )
        logger.exception('employee_form.invite_failed form=%s', form.pk)
        return 'failed'

    logger.info(
        'employee_form.invite_sent form=%s resume=%s attempt=%s',
        form.pk, form.resume_id, form.invite_count,
    )
    return 'sent'
