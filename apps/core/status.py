"""Moving a candidate through the recruiter statuses, by hand or automatically.

Every change goes through here so that three things always happen together:
the rules are checked, the change is recorded in the history, and whatever a
status sends (the assessment link, the information form) goes out once.
"""
import logging

from django.db import transaction

from .models import Resume, StatusChange

logger = logging.getLogger(__name__)

OUTCOMES_THE_SYSTEM_NEVER_MOVES = frozenset({'rejected', 'withdrawn', 'hired'})

# From Selected on, the candidate is being hired: HR verification, reference
# checks and candidate mapping open, and the information form is sent.
POST_SELECTION = frozenset({
    'selected', 'info_received', 'bgv_completed', 'offer_extended', 'pre_onboarding', 'hired',
})
# Statuses in which the assessment link may be (re)sent by HR.
ASSESSMENT_OPEN = frozenset({
    'assessment', 'interviewing', 'selected', 'info_received', 'bgv_completed',
    'offer_extended', 'pre_onboarding',
})


class StatusError(Exception):
    """The change is not allowed; the message is shown to the recruiter."""


def rank(status: str) -> int:
    """Position in the pipeline; -1 for Rejected / Withdrawn."""
    try:
        return Resume.PIPELINE_ORDER.index(status or 'new')
    except ValueError:
        return -1


def change_status(resume, new_status, *, user=None, source=StatusChange.MANUAL, reason=''):
    """Set the status, record it, and run what the new status sends.

    Returns a list of (level, text) notes for the recruiter. Raises StatusError
    when a rule forbids the change.
    """
    valid = {key for key, _ in Resume.RECRUITER_STATUS_CHOICES}
    if new_status not in valid:
        raise StatusError('Invalid status.')
    if new_status == 'hired' and not resume.onboarding_complete:
        remaining = len(Resume.ONBOARDING_CHECKLIST) - resume.onboarding_done_count
        raise StatusError(
            f'Complete the Pre-Onboarding checklist first — {remaining} item'
            f'{"s" if remaining != 1 else ""} still open. A candidate can only be marked '
            'Onboarded once every item is done.')

    previous = resume.recruiter_status or 'new'
    if previous == new_status:
        return []

    with transaction.atomic():
        resume.recruiter_status = new_status
        resume.save(update_fields=['recruiter_status', 'updated_at'])
        StatusChange.objects.create(
            resume=resume, from_status=previous, to_status=new_status,
            changed_by=user, source=source, reason=reason[:200])
    logger.info('status.changed resume=%s %s->%s source=%s by=%s',
                resume.pk, previous, new_status, source, getattr(user, 'pk', None))
    return _run_entry_actions(resume, previous, new_status, user)


def advance(resume, target, *, reason, user=None) -> bool:
    """Move forward automatically, never backwards and never out of an outcome."""
    resume.refresh_from_db(fields=['recruiter_status', 'onboarding_checklist'])
    current = resume.recruiter_status or 'new'
    if current in OUTCOMES_THE_SYSTEM_NEVER_MOVES or target in OUTCOMES_THE_SYSTEM_NEVER_MOVES:
        return False
    if rank(target) <= rank(current):
        return False
    try:
        change_status(resume, target, user=user, source=StatusChange.AUTO, reason=reason)
    except StatusError:
        return False
    return True


def _run_entry_actions(resume, previous, new_status, user):
    notes = []
    if new_status == 'assessment':
        notes += _send_assessments(resume, user)
    # The information form goes out when the candidate first reaches Selected,
    # also when a recruiter jumps straight past it.
    if rank(previous) < rank('selected') <= rank(new_status) and new_status in POST_SELECTION:
        notes += _send_information_form(resume, user)
    return notes


def _send_assessments(resume, user):
    from apps.sei_assessment import instruments
    from apps.sei_assessment.services import InviteError, issue_invite
    if not instruments.clean_keys(resume.job.assessments):
        return [('info', f'{resume.job.title} does not ask for an assessment, so nothing was sent.')]
    try:
        issue_invite(resume, user=user)
    except InviteError as exc:
        logger.warning('sei.invite_skipped resume=%s reason=%s', resume.pk, exc)
        return [('error', f'Assessment not sent: {exc}')]
    return [('success', f'Assessment link sent to {resume.email}.')]


def _send_information_form(resume, user):
    from apps.employee_form.services import InviteError, issue_invite
    already = bool(getattr(getattr(resume, 'employee_form', None), 'invited_at', None))
    try:
        issue_invite(resume, user=user)
    except InviteError as exc:
        logger.warning('employee_form.invite_skipped resume=%s reason=%s', resume.pk, exc)
        return [('error', str(exc))]
    if already:
        return [('info', 'The information form was already sent earlier; it was not sent again.')]
    return [('success', f'Information form sent to {resume.email}.')]
