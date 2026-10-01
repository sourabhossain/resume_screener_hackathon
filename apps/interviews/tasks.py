"""Interview emails, sent on the notifications queue.

Not retried, like the other invitations: a retry after an SMTP timeout could
send the same email twice. A failure is kept on the row, shown on the
interview page, and cleared by pressing Resend.
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


def _live(qs):
    return qs.filter(interview__is_deleted=False, interview__resume__is_deleted=False,
                     interview__resume__job__is_deleted=False)


@shared_task(name='apps.interviews.tasks.send_evaluator_invite', soft_time_limit=60, time_limit=90)
def send_evaluator_invite(evaluation_id: int) -> str:
    from .models import Interview, InterviewEvaluation
    from .notifications import evaluator_address, send_evaluator_email

    ev = _live(InterviewEvaluation.objects.select_related(
        'evaluator', 'interview', 'interview__resume', 'interview__resume__job')).filter(pk=evaluation_id).first()
    if ev is None:
        return 'missing'
    if ev.is_submitted:
        return 'closed'
    if ev.interview.status == Interview.CANCELLED:
        InterviewEvaluation.objects.filter(pk=ev.pk).update(invite_error='Not sent: the interview is cancelled.')
        return 'closed'
    address = evaluator_address(ev)
    if not address:
        reason = ('Not sent: this staff account is no longer active.' if ev.evaluator_id
                  else 'No email address for this evaluator.')
        InterviewEvaluation.objects.filter(pk=ev.pk).update(invite_error=reason)
        return 'no_email'
    try:
        send_evaluator_email(ev)
    except Exception as exc:
        InterviewEvaluation.objects.filter(pk=ev.pk).update(invite_error=str(exc)[:500])
        logger.exception('interview.evaluator_invite_failed evaluation=%s', ev.pk)
        return 'failed'
    InterviewEvaluation.objects.filter(pk=ev.pk).update(
        invited_at=timezone.now(), invite_error='', interviewer_email=address)
    return 'sent'


@shared_task(name='apps.interviews.tasks.send_candidate_invite', soft_time_limit=60, time_limit=90)
def send_candidate_invite(interview_id: int) -> str:
    from .models import Interview
    from .notifications import send_candidate_email

    interview = Interview.objects.select_related('resume', 'resume__job').filter(
        pk=interview_id, resume__is_deleted=False, resume__job__is_deleted=False).first()
    if interview is None:
        return 'missing'
    if interview.status != Interview.SCHEDULED:
        Interview.objects.filter(pk=interview.pk).update(
            candidate_email_error='Not sent: the interview is no longer scheduled.')
        return 'closed'
    if not (interview.resume.email or '').strip():
        Interview.objects.filter(pk=interview.pk).update(
            candidate_email_error='The candidate has no email address on file.')
        return 'no_email'
    try:
        send_candidate_email(interview)
    except Exception as exc:
        Interview.objects.filter(pk=interview.pk).update(candidate_email_error=str(exc)[:500])
        logger.exception('interview.candidate_invite_failed interview=%s', interview.pk)
        return 'failed'
    Interview.objects.filter(pk=interview.pk).update(candidate_notified_at=timezone.now(), candidate_email_error='')
    return 'sent'


@shared_task(name='apps.interviews.tasks.send_interview_cancellation', soft_time_limit=120, time_limit=150)
def send_interview_cancellation(interview_id: int) -> dict:
    """Tell everyone who was invited that the interview is off.

    Also runs for a deleted interview, so all_objects: the people holding a
    calendar entry for it must still hear.
    """
    from .models import Interview, InterviewEvaluation
    from .notifications import evaluator_address, send_candidate_email, send_evaluator_email

    interview = Interview.all_objects.select_related('resume', 'resume__job').filter(pk=interview_id).first()
    if interview is None:
        return {'missing': True}
    sent = {'evaluators': 0, 'candidate': 0}
    evaluations = (InterviewEvaluation.objects.select_related('evaluator')
                   .filter(interview=interview, invited_at__isnull=False, is_submitted=False))
    for ev in evaluations:
        ev.interview = interview
        if not evaluator_address(ev):
            continue
        try:
            send_evaluator_email(ev, cancelled=True)
            sent['evaluators'] += 1
        except Exception as exc:
            InterviewEvaluation.objects.filter(pk=ev.pk).update(invite_error=f'Cancellation failed: {exc}'[:500])
            logger.exception('interview.evaluator_cancel_failed evaluation=%s', ev.pk)
    if interview.candidate_notified_at and (interview.resume.email or '').strip():
        try:
            send_candidate_email(interview, cancelled=True)
            sent['candidate'] = 1
        except Exception as exc:
            Interview.all_objects.filter(pk=interview.pk).update(
                candidate_email_error=f'Cancellation failed: {exc}'[:500])
            logger.exception('interview.candidate_cancel_failed interview=%s', interview.pk)
    logger.info('interview.cancellation_sent interview=%s %s', interview.pk, sent)
    return sent


@shared_task(name='apps.interviews.tasks.send_interview_reschedule', soft_time_limit=120, time_limit=150)
def send_interview_reschedule(interview_id: int, previous: str) -> dict:
    """Tell everyone already invited the interview's new time and place.

    Evaluators whose first invitation never went out get the ordinary
    invitation instead; the candidate hears only if they had been told before.
    """
    from .models import Interview, InterviewEvaluation
    from .notifications import evaluator_address, send_candidate_email, send_evaluator_email

    interview = Interview.objects.select_related('resume', 'resume__job').filter(
        pk=interview_id, status=Interview.SCHEDULED).first()
    if interview is None:
        return {'closed': True}
    sent = {'evaluators': 0, 'candidate': 0}
    for ev in InterviewEvaluation.objects.select_related('evaluator').filter(interview=interview, is_submitted=False):
        ev.interview = interview
        if not evaluator_address(ev):
            continue
        try:
            send_evaluator_email(ev, previous=previous if ev.invited_at else None)
            InterviewEvaluation.objects.filter(pk=ev.pk).update(invited_at=timezone.now(), invite_error='')
            sent['evaluators'] += 1
        except Exception as exc:
            InterviewEvaluation.objects.filter(pk=ev.pk).update(invite_error=f'Update failed: {exc}'[:500])
            logger.exception('interview.evaluator_reschedule_failed evaluation=%s', ev.pk)
    if interview.candidate_notified_at and (interview.resume.email or '').strip():
        try:
            send_candidate_email(interview, previous=previous)
            sent['candidate'] = 1
        except Exception as exc:
            Interview.objects.filter(pk=interview.pk).update(candidate_email_error=f'Update failed: {exc}'[:500])
            logger.exception('interview.candidate_reschedule_failed interview=%s', interview.pk)
    logger.info('interview.reschedule_sent interview=%s %s', interview.pk, sent)
    return sent


@shared_task(name='apps.interviews.tasks.send_interview_reminders', ignore_result=True)
def send_interview_reminders():
    """The day before: remind each evaluator still to submit, and the candidate.

    Only people who were actually sent the invitation are reminded, and each
    only once: the reminder time is claimed in the database before sending, so
    a second run of the sweep cannot email anyone twice.
    """
    from apps.core.models import Resume
    from .models import Interview, InterviewEvaluation
    from .notifications import send_candidate_email, send_evaluator_email

    tomorrow = timezone.localdate() + timedelta(days=1)
    now = timezone.now()
    reminded = {'evaluators': 0, 'candidates': 0}

    evaluations = _live(InterviewEvaluation.objects.select_related(
        'evaluator', 'interview', 'interview__resume', 'interview__resume__job')).filter(
        interview__scheduled_date=tomorrow, interview__status=Interview.SCHEDULED,
        is_submitted=False, invited_at__isnull=False, reminded_at__isnull=True).exclude(interviewer_email='').exclude(
        interview__resume__recruiter_status__in=('rejected', 'withdrawn'))
    from .notifications import evaluator_address
    for ev in evaluations:
        if not evaluator_address(ev):
            continue
        if ev.is_expired:
            InterviewEvaluation.objects.filter(pk=ev.pk).update(
                invite_error='Reminder not sent: the link has expired. Renew it to email a new one.')
            continue
        if not InterviewEvaluation.objects.filter(pk=ev.pk, reminded_at__isnull=True).update(reminded_at=now):
            continue
        try:
            send_evaluator_email(ev, reminder=True)
            reminded['evaluators'] += 1
        except Exception as exc:
            InterviewEvaluation.objects.filter(pk=ev.pk).update(invite_error=f'Reminder failed: {exc}'[:500])
            logger.exception('interview.evaluator_reminder_failed evaluation=%s', ev.pk)

    interviews = Interview.objects.select_related('resume', 'resume__job').filter(
        scheduled_date=tomorrow, status=Interview.SCHEDULED, is_deleted=False,
        resume__is_deleted=False, resume__job__is_deleted=False, notify_candidate=True,
        resume__recruiter_status__in=[k for k, _ in Resume.RECRUITER_STATUS_CHOICES
                                      if k not in ('rejected', 'withdrawn')],
        candidate_notified_at__isnull=False, candidate_reminded_at__isnull=True)
    for interview in interviews:
        if not Interview.objects.filter(pk=interview.pk, candidate_reminded_at__isnull=True).update(
                candidate_reminded_at=now):
            continue
        try:
            send_candidate_email(interview, reminder=True)
            reminded['candidates'] += 1
        except Exception as exc:
            Interview.objects.filter(pk=interview.pk).update(candidate_email_error=f'Reminder failed: {exc}'[:500])
            logger.exception('interview.candidate_reminder_failed interview=%s', interview.pk)

    if any(reminded.values()):
        logger.info('interview.reminders_sent %s', reminded)
    return reminded
