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
    from .notifications import send_evaluator_email

    ev = _live(InterviewEvaluation.objects.select_related(
        'interview', 'interview__resume', 'interview__resume__job')).filter(pk=evaluation_id).first()
    if ev is None:
        return 'missing'
    if ev.is_submitted or ev.interview.status != Interview.SCHEDULED:
        return 'closed'
    if not ev.interviewer_email:
        InterviewEvaluation.objects.filter(pk=ev.pk).update(invite_error='No email address for this evaluator.')
        return 'no_email'
    try:
        send_evaluator_email(ev)
    except Exception as exc:
        InterviewEvaluation.objects.filter(pk=ev.pk).update(invite_error=str(exc)[:500])
        logger.exception('interview.evaluator_invite_failed evaluation=%s', ev.pk)
        return 'failed'
    InterviewEvaluation.objects.filter(pk=ev.pk).update(invited_at=timezone.now(), invite_error='')
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


@shared_task(name='apps.interviews.tasks.send_interview_reminders', ignore_result=True)
def send_interview_reminders():
    """The day before: remind each evaluator still to submit, and the candidate.

    Only people who were actually sent the invitation are reminded, and each
    only once: the reminder time is claimed in the database before sending, so
    a second run of the sweep cannot email anyone twice.
    """
    from .models import Interview, InterviewEvaluation
    from .notifications import send_candidate_email, send_evaluator_email

    tomorrow = timezone.localdate() + timedelta(days=1)
    now = timezone.now()
    reminded = {'evaluators': 0, 'candidates': 0}

    evaluations = _live(InterviewEvaluation.objects.select_related(
        'interview', 'interview__resume', 'interview__resume__job')).filter(
        interview__scheduled_date=tomorrow, interview__status=Interview.SCHEDULED,
        is_submitted=False, invited_at__isnull=False, reminded_at__isnull=True).exclude(interviewer_email='')
    for ev in evaluations:
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
