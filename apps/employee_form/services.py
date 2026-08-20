"""Issuing and re-sending Employee Information Form invitations."""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import EmployeeForm

logger = logging.getLogger(__name__)


class InviteError(Exception):
    """Raised when an invitation cannot be sent, with a recruiter-facing message."""


def form_url(form) -> str:
    """Absolute URL of the candidate's form entry point.

    Built from SITE_BASE_URL because the invitation is sent from a Celery task
    and from views alike -- neither can rely on a request being available.
    """
    path = reverse('employee_form:entry', kwargs={'token': form.token})
    return f"{settings.SITE_BASE_URL.rstrip('/')}{path}"


def send_invite(form, *, otp: str) -> None:
    """Email the candidate the form link and their one-time code."""
    recipient = (form.resume.email or '').strip()
    if not recipient:
        raise InviteError(
            f'{form.resume.candidate_name} has no email address on file, '
            'so the form invitation could not be sent.'
        )

    context = {
        'candidate_name': form.resume.candidate_name,
        'job_title': form.resume.job.title,
        'form_url': form_url(form),
        'otp': otp,
        'otp_minutes': EmployeeForm.OTP_VALIDITY_MINUTES,
        'link_days': EmployeeForm.TOKEN_VALIDITY_DAYS,
    }

    subject = f"Action required: complete your information form — {form.resume.job.title}"
    text_body = render_to_string('employee_form/email/invite.txt', context)
    html_body = render_to_string('employee_form/email/invite.html', context)

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    message.attach_alternative(html_body, 'text/html')
    # fail_silently=False so a broken SMTP config surfaces as an error the
    # recruiter sees, instead of a silently unsent invitation.
    message.send(fail_silently=False)

    logger.info(
        'employee_form.invite_sent resume=%s form=%s attempt=%s',
        form.resume_id, form.pk, form.invite_count + 1,
    )


def issue_invite(resume, *, user=None, resend=False):
    """Create (or refresh) the candidate's form and email the link plus an OTP.

    Returns the EmployeeForm. Raises InviteError if it should not be sent, so
    the caller can surface the reason rather than failing quietly.
    """
    form = getattr(resume, 'employee_form', None)

    if form is None:
        form = EmployeeForm(resume=resume, invited_by=user)
    elif form.is_submitted:
        raise InviteError(
            f'{resume.candidate_name} has already submitted the information form.'
        )
    elif not resend:
        # First-time-only trigger: a candidate moving back through
        # shortlisted must not silently receive a second invitation.
        return form

    if form.is_expired:
        form.renew()

    otp = form.issue_otp()
    form.invited_at = timezone.now()
    form.invite_count = (form.invite_count or 0) + 1
    if user is not None:
        form.invited_by = user
    form.save()

    try:
        send_invite(form, otp=otp)
    except InviteError:
        raise
    except Exception as exc:
        logger.exception(
            'employee_form.invite_failed resume=%s form=%s', resume.pk, form.pk
        )
        raise InviteError(
            f'Could not send the form invitation to {resume.candidate_name}: {exc}'
        ) from exc

    return form


def issue_otp_only(form) -> None:
    """Re-send just the code, for the candidate's own "Resend code" action."""
    otp = form.issue_otp()
    form.save(update_fields=[
        'otp_hash', 'otp_expires_at', 'otp_attempts', 'otp_verified_at', 'updated_at',
    ])
    send_invite(form, otp=otp)
