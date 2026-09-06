"""Working out who to ask, and asking them."""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.core.links import absolute_url

from . import schema
from .models import ReferenceCheck

logger = logging.getLogger(__name__)

EMPLOYER_SLOTS = 4
REFERENCE_SLOTS = 2


class SendError(Exception):
    """Raised when a request cannot be sent, with an HR-facing message."""


def is_fresher(resume) -> bool:
    """Whether the candidate declared no previous employment.

    Employers are optional on the Employee Information Form precisely so a
    fresher can submit it, which makes "named no employer" the honest signal.
    It only picks which form is *offered*: HR can switch it before sending.
    """
    answers = _candidate_answers(resume)
    return not any(
        (answers.get(f'employer_{i}_name') or '').strip()
        for i in range(1, EMPLOYER_SLOTS + 1)
    )


def _candidate_answers(resume) -> dict:
    form = getattr(resume, 'employee_form', None)
    return dict(form.answers or {}) if form else {}


def verification_refused(resume) -> bool:
    """Whether the candidate answered No to the blanket consent question.

    The Employee Information Form asks, in one question, whether we may carry
    out "identity, police, education, employment, reference and other lawful
    background verification". A No there covers everything this app does, and
    is not overridden by a Yes further down the same form against an individual
    employer -- the narrower answer cannot widen the broader refusal.

    A blank answer is not a refusal, only an absence; the per-contact gate
    already declines to send on that.
    """
    return _candidate_answers(resume).get('verification_consent') == 'no'


def _permission_given(answers, source_key) -> bool:
    """Did the candidate agree to this employer or referee being contacted?

    The Employee Information Form asks it once per employer and once per
    referee. A blank answer is not consent -- it means they never said yes.
    """
    return answers.get(f'{source_key}_contact_permission') == 'yes'


def candidate_contacts(resume) -> list:
    """Everyone the candidate named, as rows HR can act on.

    Each row is a person to ask, the form they would receive, whether the
    candidate agreed to it, and the request if one already exists.
    """
    answers = _candidate_answers(resume)
    fresher = is_fresher(resume)
    existing = {c.source_key: c for c in resume.reference_checks.all()}
    rows = []

    for i in range(1, EMPLOYER_SLOTS + 1):
        source_key = f'employer_{i}'
        name = (answers.get(f'{source_key}_name') or '').strip()
        if not name:
            continue          # the candidate did not list this employer
        rows.append({
            'source_key': source_key,
            'default_kind': schema.EMPLOYER,
            'title': f'Employer {i}',
            # The candidate gives us the employer's HR email and phone, never a
            # person's name, so address it to the department and let HR correct
            # it before sending if they know who to write to.
            'recipient_name': f'{name} — HR',
            'recipient_email': (answers.get(f'{source_key}_hr_email') or '').strip(),
            'recipient_phone': (answers.get(f'{source_key}_hr_contact') or '').strip(),
            'recipient_organisation': name,
            'organisation_label': 'Organisation',
            'permitted': _permission_given(answers, source_key),
            'check': existing.get(source_key),
        })

    for i in range(1, REFERENCE_SLOTS + 1):
        source_key = f'reference_{i}'
        name = (answers.get(f'{source_key}_name') or '').strip()
        if not name:
            continue
        rows.append({
            'source_key': source_key,
            # A fresher's referees are their teachers, so they get the academic
            # form. Only a default -- HR picks the form when sending.
            'default_kind': schema.ACADEMIC if fresher else schema.PROFESSIONAL,
            'title': f'Reference {i}',
            'recipient_name': name,
            'recipient_email': (answers.get(f'{source_key}_email') or '').strip(),
            'recipient_phone': (answers.get(f'{source_key}_contact') or '').strip(),
            # The candidate gives the referee's job title, never their
            # employer, so this column holds a designation for referee rows.
            'recipient_organisation': (
                answers.get(f'{source_key}_designation') or '').strip(),
            'organisation_label': 'Designation',
            'permitted': _permission_given(answers, source_key),
            'check': existing.get(source_key),
        })

    return rows


# The first section of every form asks the respondent for their own details --
# name, email, designation -- and we already hold all of it: the candidate gave
# it, and HR confirmed it before sending. Retyping it is pure friction on a
# favour we are asking of a stranger, and friction is how a reply is lost.
#
# Prefilled, not fixed: the candidate may have an old designation, or HR may
# have written to the wrong person. The respondent stays the authority on their
# own details, so every one of these remains editable.
SELF_DETAILS = {
    schema.EMPLOYER: {
        'contact_name': 'verifier_name',
        'organisation': 'verifier_organisation',
    },
    schema.PROFESSIONAL: {
        'contact_name': 'referee_name',
        'email': 'referee_email',
        'designation': 'referee_designation',
        'phone': 'referee_contact',
        'relationship': 'referee_relationship',
    },
    schema.ACADEMIC: {
        'contact_name': 'referee_name',
        'email': 'referee_email',
        'designation': 'referee_designation',
        'phone': 'referee_contact',
        # No institution: the candidate names their own university, not the
        # referee's, and the two are only usually the same.
    },
}

# Both forms ask about the relationship, from different option lists. Only these
# three carry the same meaning in both; the candidate's 'direct_report' and
# 'hr_other' have no honest equivalent, so those are left for the referee to
# answer. The academic list shares nothing at all with the candidate's.
RELATIONSHIP_EQUIVALENTS = {
    'direct_manager': 'direct_manager',
    'skip_level_manager': 'skip_level_manager',
    'peer': 'peer',
}


def prefill_answers(check) -> dict:
    """What the respondent should find already filled in, by question key."""
    row = contact_for(check.resume, check.source_key) or {}
    answers = _candidate_answers(check.resume)

    # The check row wins over the candidate's form: HR may have corrected it on
    # the way out, and that correction is the more recent knowledge.
    contact_name = (check.recipient_name or row.get('recipient_name') or '').strip()
    if contact_name == f"{check.recipient_organisation} — HR".strip():
        # The stand-in used when nobody at the employer is named. It is a
        # department, not a person, so it is not this respondent's name.
        contact_name = ''

    known = {
        'contact_name': contact_name,
        'email': (check.recipient_email or '').strip(),
        'phone': row.get('recipient_phone', ''),
    }

    if check.source_key.startswith('employer_'):
        known['organisation'] = (check.recipient_organisation or '').strip()
    else:
        # For a referee the candidate gives a designation, never an employer.
        known['designation'] = (check.recipient_organisation or '').strip()
        declared = answers.get(f'{check.source_key}_relationship')
        known['relationship'] = RELATIONSHIP_EQUIVALENTS.get(declared, '')

    return {
        question_key: known[source]
        for source, question_key in SELF_DETAILS[check.kind].items()
        if known.get(source)
    }


def contact_for(resume, source_key):
    for row in candidate_contacts(resume):
        if row['source_key'] == source_key:
            return row
    return None


def check_url(check) -> str:
    """Absolute URL of the respondent's entry point.

    Built from SITE_BASE_URL because the email is sent from a Celery task, which
    has no request to build one from.
    """
    path = reverse('reference_checks:entry', kwargs={'token': check.token})
    return absolute_url(path)


def send_request(check, *, otp: str) -> None:
    """Email the respondent their link and one-time code."""
    recipient = (check.recipient_email or '').strip()
    if not recipient:
        raise SendError(
            f'{check.recipient_name} has no email address on file, so the '
            'request could not be sent.'
        )

    context = {
        'check': check,
        'candidate_name': check.resume.candidate_name,
        'job_title': check.resume.job.title,
        'recipient_name': check.recipient_name,
        'form_title': schema.KIND_LABELS[check.kind],
        'check_url': check_url(check),
        'otp': otp,
        'otp_minutes': ReferenceCheck.OTP_VALIDITY_MINUTES,
        'link_days': ReferenceCheck.TOKEN_VALIDITY_DAYS,
    }
    subject = (f'{schema.KIND_LABELS[check.kind]} request — '
               f'{check.resume.candidate_name}')
    message = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string('reference_checks/email/request.txt', context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    message.attach_alternative(
        render_to_string('reference_checks/email/request.html', context), 'text/html')
    # fail_silently=False so a broken SMTP config surfaces to HR rather than
    # leaving them waiting on a reply that was never asked for.
    message.send(fail_silently=False)

    if 'smtp' not in settings.EMAIL_BACKEND:
        logger.warning(
            'reference_checks.not_delivered check=%s backend=%s — written to this '
            "process's output, not sent to %s",
            check.pk, settings.EMAIL_BACKEND, recipient,
        )
    logger.info('reference_checks.sent check=%s kind=%s attempt=%s',
                check.pk, check.kind, check.invite_count + 1)


def issue_request(resume, source_key, *, kind, recipient_name, recipient_email,
                  recipient_organisation='', user=None, resend=False):
    """Create or refresh a request and queue the email.

    Whether it *may* be sent is decided here, synchronously, so HR learns that on
    the click. The email itself goes to Celery: SMTP can take tens of seconds.
    """
    from .tasks import send_reference_check_request

    contact = contact_for(resume, source_key)
    if contact is None:
        raise SendError('That employer or referee is not on the candidate\'s form.')

    if verification_refused(resume):
        raise SendError(
            f'{resume.candidate_name} did not consent to background '
            'verification, so no request can be sent to anyone.'
        )

    if not contact['permitted']:
        raise SendError(
            f'{resume.candidate_name} did not agree to {contact["title"]} being '
            'contacted, so no request can be sent.'
        )

    check = resume.reference_checks.filter(source_key=source_key).first()
    if check and check.is_submitted:
        raise SendError(f'{contact["title"]} has already replied.')
    if check and not resend:
        return check

    if check is None:
        check = ReferenceCheck(resume=resume, source_key=source_key)

    check.kind = kind
    check.recipient_name = recipient_name.strip()
    check.recipient_email = recipient_email.strip()
    check.recipient_organisation = recipient_organisation.strip()
    if check.pk and check.is_expired:
        check.renew()
    if not check.recipient_email:
        raise SendError(
            f'{contact["title"]} has no email address, so the request could not '
            'be sent. Add one and try again.'
        )
    check.invited_by = user
    if check.pk:
        # Same reason as the task: never write back a stale `answers` over a
        # respondent who is part-way through.
        check.save(update_fields=[
            'kind', 'recipient_name', 'recipient_email', 'recipient_organisation',
            'token_expires_at', 'invited_by', 'updated_at',
        ])
    else:
        check.save()

    send_reference_check_request.delay(check.pk)
    logger.info('reference_checks.queued check=%s resume=%s source=%s',
                check.pk, resume.pk, source_key)
    return check


def resend_code(check) -> None:
    """Re-send just the code, for the respondent's own "Resend" action."""
    otp = check.issue_otp()
    check.save(update_fields=[*ReferenceCheck.OTP_FIELDS, 'updated_at'])
    send_request(check, otp=otp)


def summarise(resume) -> dict:
    """Counts for the card on the candidate page."""
    checks = list(resume.reference_checks.all())
    return {
        # People the candidate named *and* agreed we may contact -- the honest
        # denominator, since the rest can never be asked.
        'contactable': sum(1 for row in candidate_contacts(resume) if row['permitted']),
        'total': len(checks),
        'sent': sum(1 for c in checks if c.invited_at),
        'completed': sum(1 for c in checks if c.is_submitted),
        'flagged': sum(1 for c in checks if c.is_submitted and c.flagged),
    }
