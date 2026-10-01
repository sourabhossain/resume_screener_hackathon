"""Interview emails: the invitation, the day-before reminder, and the calendar file.

Evaluators are office staff and get their own evaluation link; the candidate
gets the time and place. Internal notes go to neither. Every email carries an
.ics file so the interview lands in Outlook or Google Calendar in one click.
"""
import logging
from datetime import timezone as dt_timezone
from email.mime.text import MIMEText

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.core.links import absolute_url

logger = logging.getLogger(__name__)


def _ics_text(value: str) -> str:
    return (value or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,') \
        .replace('\r\n', '\\n').replace('\n', '\\n')


def _fold(line: str) -> str:
    """RFC 5545 lines are at most 75 octets; longer ones continue after CRLF + space."""
    out, chunk = [], ''
    for ch in line:
        if len((chunk + ch).encode('utf-8')) > (75 if not out else 74):
            out.append(chunk)
            chunk = ''
        chunk += ch
    out.append(chunk)
    return '\r\n '.join(out)


def calendar_file(interview, *, for_evaluator=None, cancel=False) -> str:
    """One VEVENT for this interview, in UTC, safe for Outlook and Google.

    A cancellation carries the same UID with a higher SEQUENCE, so a calendar
    that took the invitation can match it and mark the slot cancelled.
    """
    start, end = interview.starts_at, interview.ends_at
    stamp = '%Y%m%dT%H%M%SZ'
    job = interview.resume.job.title
    if for_evaluator is not None:
        summary = f'Interview: {interview.resume.candidate_name.title()} · {job}'
        description = (f'{interview.get_phase_display()} for {job}.\n'
                       f'Evaluation form: {evaluation_url(for_evaluator)}')
    else:
        summary = f'Interview with SSL Wireless · {job}'
        description = f'Your interview for {job} at SSL Wireless.'
    if interview.location and interview.is_online:
        description += f'\nJoin: {interview.location}'
    lines = [
        'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//SSL Wireless//Careers//EN',
        'CALSCALE:GREGORIAN', f'METHOD:{"CANCEL" if cancel else "PUBLISH"}', 'BEGIN:VEVENT',
        f'UID:interview-{interview.pk}-{interview.created_at:%Y%m%d%H%M%S}@sslwireless.com',
        f'SEQUENCE:{(interview.schedule_version or 0) + (1 if cancel else 0)}',
        f'STATUS:{"CANCELLED" if cancel else "CONFIRMED"}',
        f'DTSTAMP:{timezone.now().astimezone(dt_timezone.utc).strftime(stamp)}',
        f'DTSTART:{start.astimezone(dt_timezone.utc).strftime(stamp)}',
        f'DTEND:{end.astimezone(dt_timezone.utc).strftime(stamp)}',
        f'SUMMARY:{_ics_text(("Cancelled: " if cancel else "") + summary)}',
        f'DESCRIPTION:{_ics_text(description)}',
    ]
    if interview.location:
        lines.append(f'LOCATION:{_ics_text(interview.location)}')
    lines += ['END:VEVENT', 'END:VCALENDAR']
    return '\r\n'.join(_fold(line) for line in lines) + '\r\n'


def evaluation_url(evaluation) -> str:
    return absolute_url(reverse('interviews:evaluate', kwargs={'token': evaluation.token}))


def cv_url(evaluation) -> str:
    return absolute_url(reverse('interviews:evaluation_cv', kwargs={'token': evaluation.token}))


def _context(interview):
    return {
        'interview': interview,
        'candidate_name': ' '.join((interview.resume.candidate_name or '').split()).title() or 'Candidate',
        'job_title': interview.resume.job.title,
        'starts_at': interview.starts_at,
        'ends_at': interview.ends_at,
        'support_email': settings.CAREERS_REPLY_TO,
    }


def _calendar_part(calendar, method):
    # Built by hand: attach() with a mimetype string repeats the charset
    # parameter, which strict mail gateways reject.
    part = MIMEText(calendar, 'calendar', 'utf-8')
    part.set_param('method', method)
    part.add_header('Content-Disposition', 'attachment', filename='interview.ics')
    return part


def _send(subject, template, context, recipient, calendar, method='PUBLISH'):
    message = EmailMultiAlternatives(
        subject=' '.join(subject.split()),
        body=render_to_string(f'interviews/email/{template}.txt', context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
        reply_to=[settings.CAREERS_REPLY_TO],
    )
    message.attach_alternative(render_to_string(f'interviews/email/{template}.html', context), 'text/html')
    if calendar:
        message.attach(_calendar_part(calendar, method))
    message.send(fail_silently=False)


def evaluator_address(evaluation):
    """Where an evaluator's email goes now, or '' when they must not get it.

    A linked staff account decides: a deactivated account gets nothing (they
    have left, and the link exposes a candidate's details), and a changed
    address is followed.
    """
    user = evaluation.evaluator
    if user is not None:
        return user.email if user.is_active else ''
    return evaluation.interviewer_email


def send_evaluator_email(evaluation, *, reminder=False, cancelled=False, previous=None):
    """`previous` is the old start time as text, for a reschedule notice."""
    interview = evaluation.interview
    context = {**_context(interview), 'evaluation': evaluation,
               'evaluator_name': evaluation.interviewer_name, 'evaluation_url': evaluation_url(evaluation),
               'cv_url': cv_url(evaluation) if interview.resume.file else '',
               'reminder': reminder, 'cancelled': cancelled, 'previous': previous}
    when = timezone.localtime(interview.starts_at).strftime('%-d %b, %-I:%M %p') if interview.starts_at else ''
    prefix = ('Cancelled: interview' if cancelled else 'Rescheduled: interview' if previous else
              'Reminder: interview tomorrow' if reminder else 'Interview panel')
    subject = f'{prefix} · {context["candidate_name"]} · {context["job_title"]} · {when}'
    calendar = calendar_file(interview, for_evaluator=evaluation, cancel=cancelled) if interview.starts_at else None
    _send(subject, 'evaluator', context, evaluator_address(evaluation), calendar,
          method='CANCEL' if cancelled else 'PUBLISH')


def send_candidate_email(interview, *, reminder=False, cancelled=False, previous=None):
    context = {**_context(interview), 'reminder': reminder, 'cancelled': cancelled, 'previous': previous}
    if cancelled:
        subject = f'Interview cancelled: {context["job_title"]} at SSL Wireless'
    elif previous:
        subject = f'Interview rescheduled: {context["job_title"]} at SSL Wireless'
    elif reminder:
        subject = f'Reminder: your interview tomorrow for {context["job_title"]} at SSL Wireless'
    else:
        subject = f'Interview invitation: {context["job_title"]} at SSL Wireless'
    calendar = calendar_file(interview, cancel=cancelled) if interview.starts_at else None
    _send(subject, 'candidate', context, interview.resume.email, calendar,
          method='CANCEL' if cancelled else 'PUBLISH')
