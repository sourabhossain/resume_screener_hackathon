"""Issuing the assessment invitation, and closing sittings the clock ended."""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.core.links import absolute_url

from . import scoring

from .models import SEIAssessment

logger = logging.getLogger(__name__)


class InviteError(Exception):
    """Raised when an invitation cannot be sent, with a recruiter-facing message."""


def assessment_url(assessment) -> str:
    return absolute_url(
        reverse('sei_assessment:entry', kwargs={'token': assessment.token}))


def send_invite(assessment, *, otp: str) -> None:
    recipient = (assessment.resume.email or '').strip()
    if not recipient:
        raise InviteError(
            f'{assessment.resume.candidate_name} has no email address on file, '
            'so the assessment could not be sent.')

    context = {
        'assessment': assessment,
        'candidate_name': assessment.resume.candidate_name,
        'job_title': assessment.resume.job.title,
        'assessment_url': assessment_url(assessment),
        'otp': otp,
        'otp_minutes': SEIAssessment.OTP_VALIDITY_MINUTES,
        'link_days': SEIAssessment.TOKEN_VALIDITY_DAYS,
        'minutes': SEIAssessment.TIME_LIMIT_MINUTES,
        'question_count': len(scoring.ITEMS),
        'minimum': scoring.MINIMUM_VALID_ANSWERS,
    }
    message = EmailMultiAlternatives(
        subject=f'Assessment for your application — {assessment.resume.job.title}',
        body=render_to_string('sei_assessment/email/invite.txt', context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    message.attach_alternative(
        render_to_string('sei_assessment/email/invite.html', context), 'text/html')
    # fail_silently=False so a broken SMTP config surfaces to the recruiter
    # rather than leaving them waiting on a sitting that was never invited.
    message.send(fail_silently=False)

    if 'smtp' not in settings.EMAIL_BACKEND:
        logger.warning(
            'sei.not_delivered assessment=%s backend=%s — written to this '
            "process's output, not sent to %s",
            assessment.pk, settings.EMAIL_BACKEND, recipient)
    logger.info('sei.sent assessment=%s attempt=%s',
                assessment.pk, assessment.invite_count + 1)


def issue_invite(resume, *, user=None, resend=False):
    """Create the sitting if needed and queue its invitation.

    Whether it *may* be sent is decided synchronously so the recruiter learns
    it on the click; the email itself goes to Celery because SMTP is slow.
    """
    from .tasks import send_sei_invite

    if not (resume.email or '').strip():
        raise InviteError(
            f'{resume.candidate_name} has no email address, so the assessment '
            'could not be sent. Add one and try again.')

    assessment = getattr(resume, 'sei_assessment', None)
    if assessment and assessment.is_submitted and assessment.is_valid_result:
        raise InviteError(
            f'{resume.candidate_name} has already completed the assessment.')
    if assessment and assessment.needs_retaking:
        # Too few answers to score. Sending again is the point, so the sitting
        # is reset rather than refused -- but only on an explicit resend, never
        # as a side effect of a status change.
        if not resend:
            raise InviteError(
                f'{resume.candidate_name} did not answer enough of the '
                'assessment. Use Resend to ask them to take it again.')
        assessment.answers = {}
        assessment.started_at = None
        assessment.deadline_at = None
        assessment.is_submitted = False
        assessment.submitted_at = None
        assessment.auto_submitted = False
        assessment.save(update_fields=[
            'answers', 'started_at', 'deadline_at', 'is_submitted',
            'submitted_at', 'auto_submitted', 'updated_at',
        ])
    if assessment and assessment.has_started and not resend:
        raise InviteError(
            f'{resume.candidate_name} has already started the assessment.')
    if assessment and not resend:
        return assessment

    if assessment is None:
        assessment = SEIAssessment(resume=resume)
    elif assessment.is_expired:
        assessment.renew()
    assessment.invited_by = user
    if assessment.pk:
        assessment.save(update_fields=['token_expires_at', 'invited_by', 'updated_at'])
    else:
        assessment.save()

    send_sei_invite.delay(assessment.pk)
    logger.info('sei.queued assessment=%s resume=%s', assessment.pk, resume.pk)
    return assessment


def resend_code(assessment) -> None:
    otp = assessment.issue_otp()
    assessment.save(update_fields=[*SEIAssessment.OTP_FIELDS, 'updated_at'])
    send_invite(assessment, otp=otp)


def finalise_if_time_is_up(assessment) -> bool:
    """Close a sitting whose clock has run out, keeping whatever was answered.

    Needed because the browser is not a reliable witness: a candidate can close
    the tab at minute three, and nothing would ever submit the paper. Called
    both from the pages that read a sitting and from a scheduled sweep, so an
    abandoned one does not sit open forever.
    """
    if assessment.is_submitted or not assessment.has_started:
        return False
    if not assessment.time_is_up:
        return False

    closed = SEIAssessment.objects.filter(
        pk=assessment.pk, is_submitted=False,
    ).update(is_submitted=True, submitted_at=timezone.now(), auto_submitted=True)
    if closed:
        assessment.is_submitted = True
        assessment.auto_submitted = True
        assessment.refresh_from_db(fields=['submitted_at'])
        logger.info('sei.auto_submitted assessment=%s answered=%s',
                    assessment.pk, assessment.answered_count)
    return bool(closed)
