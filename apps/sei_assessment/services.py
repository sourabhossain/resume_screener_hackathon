"""Issuing the assessment invitation, and closing sittings the clock ended."""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.core.links import absolute_url

from . import instruments
from .models import AssessmentInvitation, SEIAssessment

logger = logging.getLogger(__name__)


class InviteError(Exception):
    """Raised when an invitation cannot be sent, with a recruiter-facing message."""


def assessment_url(invitation) -> str:
    return absolute_url(
        reverse('sei_assessment:entry', kwargs={'token': invitation.token}))


def _labels(sittings) -> str:
    """Instrument names joined for a recruiter-facing message. Never the candidate's."""
    names = [s.instrument_label for s in sittings]
    return names[0] if len(names) == 1 else ', '.join(names[:-1]) + ' and ' + names[-1]


def invitation_for(resume):
    """The candidate's invitation, or None."""
    return AssessmentInvitation.objects.filter(resume=resume).first()


def sitting_for(resume, instrument_key):
    """The candidate's sitting of one instrument, or None."""
    return SEIAssessment.objects.filter(
        resume=resume, instrument=instrument_key).first()


def issue_fresh_code(invitation) -> str:
    """A new code; keeps the session of a candidate whose clock is running."""
    verified_at = invitation.otp_verified_at
    otp = invitation.issue_otp()
    if verified_at and any(
            s.has_started and s.is_open for s in invitation.ordered_sittings()):
        invitation.otp_verified_at = verified_at
    return otp


def send_invite(invitation, *, otp: str) -> None:
    resume = invitation.resume
    recipient = (resume.email or '').strip()
    if not recipient:
        raise InviteError(
            f'{resume.candidate_name} has no email address on file, '
            'so the assessments could not be sent.')

    sittings = invitation.ordered_sittings()
    pending = [s for s in sittings if not s.is_submitted]
    if not pending:
        raise InviteError(
            f'{resume.candidate_name} has already completed every assessment.')

    # Numbered over every sitting, so "Part 2" in the email is "Part 2" on the
    # portal even when Part 1 is already done. Never named: see instruments.
    parts = [{
        'number': i,
        'noun_plural': s.spec.noun_plural,
        'minutes': s.spec.time_limit_minutes,
        'question_count': s.spec.total_items,
        'minimum': s.spec.minimum_answers,
        'all_required': s.spec.minimum_answers >= s.spec.total_items,
    } for i, s in enumerate(sittings, start=1) if not s.is_submitted]
    context = {
        'invitation': invitation,
        'candidate_name': resume.candidate_name,
        'job_title': resume.job.title,
        'assessment_url': assessment_url(invitation),
        'otp': otp,
        'otp_minutes': AssessmentInvitation.OTP_VALIDITY_MINUTES,
        'link_days': AssessmentInvitation.TOKEN_VALIDITY_DAYS,
        'deadline': invitation.token_expires_at,
        'parts': parts,
        'part_count': len(parts),
        'multi': len(sittings) > 1,
        'total_minutes': sum(p['minutes'] for p in parts),
        'completed': [i for i, s in enumerate(sittings, start=1) if s.is_submitted],
    }
    if len(sittings) > 1:
        subject = f'Your assessments for your application — {resume.job.title}'
    else:
        subject = f'Your assessment for your application — {resume.job.title}'
    message = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string('sei_assessment/email/invite.txt', context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    message.attach_alternative(
        render_to_string('sei_assessment/email/invite.html', context), 'text/html')
    # fail_silently=False so a broken SMTP config surfaces to the recruiter
    # rather than leaving them waiting on an invitation that never went out.
    message.send(fail_silently=False)

    if 'smtp' not in settings.EMAIL_BACKEND:
        logger.warning(
            'sei.not_delivered invitation=%s backend=%s — written to this '
            "process's output, not sent to %s",
            invitation.pk, settings.EMAIL_BACKEND, recipient)
    logger.info('sei.sent invitation=%s parts=%s attempt=%s',
                invitation.pk, [s.instrument for s in pending],
                invitation.invite_count)


def issue_invite(resume, *, user=None, resend=False):
    """Sync the invitation with the job and queue its one email.

    Without `resend` an invitation already sent is returned untouched.
    """
    from .tasks import send_assessment_invite

    keys = instruments.clean_keys(resume.job.assessments)

    if not (resume.email or '').strip():
        raise InviteError(
            f'{resume.candidate_name} has no email address, so the '
            'assessments could not be sent. Add one and try again.')

    # Created outside the lock: a locking read on a missing row takes a gap lock
    # on MySQL, and two first sends would deadlock on the insert.
    AssessmentInvitation.objects.get_or_create(resume=resume)
    with transaction.atomic():
        invitation = AssessmentInvitation.objects.select_for_update().get(resume=resume)
        existing = {s.instrument: s for s in invitation.sittings.all()}
        missing = [key for key in keys if key not in existing]
        retakes = [s for s in existing.values()
                   if s.needs_retaking and s.instrument in keys]
        unfinished = [s for s in existing.values() if not s.is_submitted]
        dropped = [s.pk for key, s in existing.items()
                   if key not in keys and not s.has_started and not s.is_submitted]

        if not missing and not retakes and not unfinished:
            if not existing:
                raise InviteError(
                    f'{resume.job.title} does not ask for any assessment.')
            raise InviteError(
                f'{resume.candidate_name} has already completed the '
                f'{_labels(invitation.ordered_sittings())} assessment'
                f'{"s" if len(existing) > 1 else ""}.')

        if not resend:
            if retakes:
                raise InviteError(
                    f'{resume.candidate_name} did not answer enough of the '
                    f'{_labels(retakes)} assessment. Use Resend to ask them to '
                    'take it again.')
            if any(s.has_started for s in unfinished):
                raise InviteError(
                    f'{resume.candidate_name} has already started the assessments.')
            if invitation.invited_at:
                return invitation

        running = invitation.running_sitting()
        if retakes and running is not None and running.is_open:
            raise InviteError(
                f'{resume.candidate_name} is taking the {running.instrument_label} '
                'assessment right now. Ask for the retake once it is finished.')
        for sitting in retakes:
            # Too few answers to score. Sending again is the point, so the
            # sitting is reset rather than refused -- but only on an explicit
            # resend, never as a side effect of a status change.
            sitting.reset()
            sitting.save(update_fields=[*SEIAssessment.RESET_FIELDS, 'updated_at'])
        # Drop never-opened parts the job no longer asks for.
        if dropped:
            SEIAssessment.objects.filter(pk__in=dropped).delete()
        for key in missing:
            SEIAssessment.objects.create(
                resume=resume, invitation=invitation, instrument=key)
        if not invitation.sittings.filter(is_submitted=False).exists():
            raise InviteError(
                f'{resume.job.title} no longer asks for any assessment that '
                f'{resume.candidate_name} still has to take.')

        if invitation.is_expired:
            invitation.renew()
        invitation.invited_by = user
        invitation.save(update_fields=['token_expires_at', 'invited_by', 'updated_at'])

    send_assessment_invite.delay(invitation.pk)
    logger.info('sei.queued invitation=%s resume=%s instruments=%s',
                invitation.pk, resume.pk, keys)
    return invitation


def resend_code(invitation) -> None:
    otp = issue_fresh_code(invitation)
    invitation.save(update_fields=[*AssessmentInvitation.OTP_FIELDS, 'updated_at'])
    send_invite(invitation, otp=otp)


def finalise_if_time_is_up(assessment) -> bool:
    """Close a sitting whose clock has run out, keeping whatever was answered.

    Needed because the browser is not a reliable witness: a candidate can close
    the tab at minute three, and nothing would ever submit the paper. Called
    both from the pages that read a sitting and from a scheduled sweep, so an
    abandoned one does not sit open forever.
    """
    if assessment.is_submitted or not assessment.has_started:
        return False
    if not assessment.past_grace:
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
