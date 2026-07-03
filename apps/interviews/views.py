import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.contrib import messages

from apps.core.views import form_errors_to_messages
from apps.core.models import Resume
from apps.core.services import audit_log
from .models import Interview, InterviewEvaluation, EVALUATION_CRITERIA, CRITERIA_KEYS, MAX_SCORE
from .forms import InterviewCreateForm, InterviewerAddForm, EvaluationSubmitForm

def _can_access_interview(user, interview):
    """Single-company internal tool: every authenticated recruiter can access all
    interviews, matching the unscoped access to jobs/resumes in apps.core.
    (Views are @login_required, so this is True for any logged-in user.)
    """
    return user.is_authenticated

@login_required
def interview_create(request, resume_uuid):
    resume = get_object_or_404(Resume, uuid=resume_uuid)
    form = InterviewCreateForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            phase = form.cleaned_data['phase']
            required_prior = {'2': '1', '3': '2'}
            prior_phase = required_prior.get(phase)
            if prior_phase and not Interview.objects.filter(
                resume=resume, phase=prior_phase, is_deleted=False
            ).exists():
                phase_label = dict(Interview.PHASE_CHOICES).get(prior_phase, f'Phase {prior_phase}')
                form.add_error('phase', f'{phase_label} must be scheduled before this phase.')
            else:
                interview = form.save(commit=False)
                interview.resume = resume
                interview.save()
                details = f'phase={interview.phase} resume={resume.uuid}'
                if interview.scheduled_time is not None:
                    details += f' time={interview.scheduled_time.strftime("%H:%M")}'
                audit_log(request.user, 'interview.created', interview,
                          details=details, request=request)
                messages.success(request, 'Interview scheduled.')
                return redirect('interviews:detail', pk=interview.pk)
        if form.errors:
            form_errors_to_messages(request, form)
    return render(request, 'interviews/create.html', {'form': form, 'resume': resume})

@login_required
def interview_detail(request, pk):
    interview = get_object_or_404(Interview.objects.select_related('resume__job__owner'), pk=pk)
    if not _can_access_interview(request.user, interview):
        messages.error(request, 'You do not have permission to view this interview.')
        return redirect('core:dashboard')
    add_form = InterviewerAddForm(request.POST or None)

    if request.method == 'POST' and add_form.is_valid():
        ev = add_form.save(commit=False)
        ev.interview = interview
        ev.save()
        messages.success(request, f'Evaluation link created for {ev.interviewer_name}.')
        return redirect('interviews:detail', pk=pk)
    elif request.method == 'POST':
        form_errors_to_messages(request, add_form)

    evaluations = interview.evaluations.all()
    return render(request, 'interviews/detail.html', {
        'interview': interview,
        'evaluations': evaluations,
        'add_form': add_form,
        'criteria': EVALUATION_CRITERIA,
    })

@login_required
def interview_calendar(request):
    """Week (Mon-Sun) calendar of scheduled interviews. Navigate with
    ?week=YYYY-MM-DD (any date in the target week). Single-company: every
    authenticated recruiter sees all interviews (matching the rest of the app).
    Soft-deleted interviews, and interviews of soft-deleted resumes/jobs, are
    hidden -- same visibility as the evaluate/rank-report querysets.
    """
    base_day = parse_date(request.GET.get('week', '') or '') or timezone.localdate()
    monday = base_day - timedelta(days=base_day.weekday())
    sunday = monday + timedelta(days=6)

    interviews = list(
        Interview.objects
        .filter(scheduled_date__range=(monday, sunday),
                resume__is_deleted=False, resume__job__is_deleted=False)
        .select_related('resume', 'resume__job')
        # Pending/submitted evaluation counts via annotation (single query, no
        # N+1) so cards can show status without touching the model properties.
        .annotate(
            n_pending=Count('evaluations',
                            filter=Q(evaluations__is_submitted=False,
                                     evaluations__is_deleted=False)),
            n_submitted=Count('evaluations',
                              filter=Q(evaluations__is_submitted=True,
                                       evaluations__is_deleted=False)),
        )
        .order_by('scheduled_date', 'phase')
    )

    by_day = {monday + timedelta(days=i): [] for i in range(7)}
    for iv in interviews:
        by_day[iv.scheduled_date].append(iv)

    # Within each day, timed interviews come first in ascending time order;
    # untimed (all-day) ones sort last. Done in Python on the already-fetched
    # week queryset -- no extra DB ordering.
    for ivs in by_day.values():
        ivs.sort(key=lambda iv: (iv.scheduled_time is None, iv.scheduled_time))

    today = timezone.localdate()
    days = [{'date': d, 'interviews': ivs, 'is_today': d == today}
            for d, ivs in by_day.items()]

    return render(request, 'interviews/calendar.html', {
        'days': days,
        'week_start': monday,
        'week_end': sunday,
        'interview_count': len(interviews),
        'prev_week': (monday - timedelta(days=7)).isoformat(),
        'next_week': (monday + timedelta(days=7)).isoformat(),
        'is_current_week': monday <= today <= sunday,
    })


def _ics_escape(text):
    """Escape a value for an RFC 5545 TEXT field. Candidate names are untrusted
    input, so commas/semicolons/backslashes/newlines must be escaped."""
    return (
        str(text or '')
        .replace('\\', '\\\\')
        .replace(';', '\\;')
        .replace(',', '\\,')
        .replace('\r\n', '\\n')
        .replace('\r', '\\n')
        .replace('\n', '\\n')
    )


def _ics_fold(line):
    """Fold a content line to <=75 octets per RFC 5545, without splitting a
    multi-byte UTF-8 character. Continuation lines start with a single space."""
    if len(line.encode('utf-8')) <= 75:
        return line
    chunks, current, limit = [], b'', 75
    for ch in line:
        b = ch.encode('utf-8')
        if len(current) + len(b) > limit:
            chunks.append(current)
            current, limit = b, 74  # continuation lines carry a leading space
        else:
            current += b
    if current:
        chunks.append(current)
    return '\r\n '.join(c.decode('utf-8') for c in chunks)


@login_required
def interview_ics(request, pk):
    """Download a single interview as an .ics (RFC 5545) calendar event. Same
    access rules as interview_detail. Read-only export -- deliberately NOT
    audit-logged (consistent with not logging 'Viewed'). The event carries no
    resume content, scores, email or phone -- only the candidate name, job
    title and phase.
    """
    interview = get_object_or_404(Interview.objects.select_related('resume__job'), pk=pk)
    if not _can_access_interview(request.user, interview):
        raise Http404

    name = interview.resume.candidate_name
    summary = f'Interview - {name} - Phase {interview.phase}'
    description = f'{interview.resume.job.title} - {interview.get_phase_display()}'
    dtstamp = timezone.now().strftime('%Y%m%dT%H%M%SZ')

    if interview.scheduled_time is not None:
        # Timed VEVENT. Emit UTC instants (DTSTART:...Z) rather than a TZID with
        # a hand-written VTIMEZONE: converting to UTC is unambiguous and needs no
        # VTIMEZONE block, so it can't drift out of sync. Combine the local
        # date+time in the project timezone, then convert to UTC.
        local = timezone.make_aware(
            datetime.combine(interview.scheduled_date, interview.scheduled_time),
            timezone.get_current_timezone(),
        )
        start_utc = local.astimezone(dt_timezone.utc)
        end_utc = start_utc + timedelta(hours=1)  # default 1h duration (future setting)
        dtstart_line = f'DTSTART:{start_utc.strftime("%Y%m%dT%H%M%SZ")}'
        dtend_line = f'DTEND:{end_utc.strftime("%Y%m%dT%H%M%SZ")}'
    else:
        # All-day VEVENT: no time component, so DTSTART/DTEND use VALUE=DATE and
        # DTEND is the exclusive next day.
        dtstart_line = f'DTSTART;VALUE=DATE:{interview.scheduled_date.strftime("%Y%m%d")}'
        dtend_line = f'DTEND;VALUE=DATE:{(interview.scheduled_date + timedelta(days=1)).strftime("%Y%m%d")}'

    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//Career//Interview Calendar//EN',
        'CALSCALE:GREGORIAN',
        'BEGIN:VEVENT',
        f'UID:interview-{interview.pk}@{request.get_host()}',
        f'DTSTAMP:{dtstamp}',
        dtstart_line,
        dtend_line,
        f'SUMMARY:{_ics_escape(summary)}',
        f'DESCRIPTION:{_ics_escape(description)}',
        'STATUS:CONFIRMED',
        'END:VEVENT',
        'END:VCALENDAR',
    ]
    body = '\r\n'.join(_ics_fold(line) for line in lines) + '\r\n'

    resp = HttpResponse(body, content_type='text/calendar; charset=utf-8')
    resp['Content-Disposition'] = f'attachment; filename="interview-{interview.pk}.ics"'
    return resp


@login_required
def interview_delete(request, pk):
    interview = get_object_or_404(Interview.objects.select_related('resume__job__owner'), pk=pk)
    if not _can_access_interview(request.user, interview):
        messages.error(request, 'You do not have permission to delete this interview.')
        return redirect('core:dashboard')
    resume_uuid = interview.resume.uuid
    if request.method == 'POST':
        interview.soft_delete()
        audit_log(request.user, 'interview.deleted', interview,
                  details=f'resume={resume_uuid}', request=request)
        messages.success(request, 'Interview deleted.')
    return redirect('core:resume_detail', uuid=resume_uuid)

@login_required
def evaluation_delete(request, token):
    ev = get_object_or_404(InterviewEvaluation.objects.select_related('interview__resume__job__owner'), token=token)
    if not _can_access_interview(request.user, ev.interview):
        messages.error(request, 'You do not have permission to delete this evaluation.')
        return redirect('core:dashboard')
    interview_pk = ev.interview_id
    if request.method == 'POST':
        # Log BEFORE the hard delete so the evaluation pk is still set.
        audit_log(request.user, 'interview.eval_link_deleted', ev,
                  details=f'interviewer={ev.interviewer_name} interview={interview_pk}', request=request)
        ev.delete()
        messages.success(request, 'Evaluation slot removed.')
    return redirect('interviews:detail', pk=interview_pk)

@login_required
def evaluation_renew(request, token):
    from datetime import timedelta
    ev = get_object_or_404(InterviewEvaluation.objects.select_related('interview__resume__job__owner'), token=token)
    if not _can_access_interview(request.user, ev.interview):
        messages.error(request, 'You do not have permission to renew this evaluation link.')
        return redirect('core:dashboard')
    if request.method == 'POST' and not ev.is_submitted:
        ev.token = uuid.uuid4()
        ev.token_expires_at = timezone.now() + timedelta(days=InterviewEvaluation.TOKEN_VALIDITY_DAYS)
        ev.save(update_fields=['token', 'token_expires_at'])
        audit_log(request.user, 'interview.eval_link_renewed', ev,
                  details=f'interviewer={ev.interviewer_name} interview={ev.interview_id}', request=request)
        messages.success(request, f'New link generated for {ev.interviewer_name}.')
    return redirect('interviews:detail', pk=ev.interview_id)

def evaluate(request, token):
    ev = get_object_or_404(
        InterviewEvaluation.objects.select_related('interview__resume__job'), token=token
    )

    if ev.interview.is_deleted or ev.interview.resume.is_deleted or ev.interview.resume.job.is_deleted:
        raise Http404

    if ev.is_submitted:
        return render(request, 'interviews/already_submitted.html', {'ev': ev})

    if ev.is_expired:
        return render(request, 'interviews/expired.html', {'ev': ev})

    form = EvaluationSubmitForm(request.POST or None)

    if request.method == 'POST':
        if form.is_valid():
            d = form.cleaned_data

            scores = {key: int(d[f'score_{key}']) for key in CRITERIA_KEYS}
            manual_rec = d.get('recommendation', '')
            if manual_rec:
                recommendation = manual_rec
            else:
                pct = round((sum(scores.values()) / MAX_SCORE) * 100)
                recommendation = 'yes' if pct >= 75 else ('maybe' if pct >= 55 else 'no')

            submitted_now = False
            with transaction.atomic():
                locked = InterviewEvaluation.objects.select_for_update().get(pk=ev.pk)
                if not locked.is_submitted and not locked.is_expired:
                    locked.scores = scores
                    locked.additional_notes = d.get('additional_notes', '')
                    locked.another_phase_required = d.get('another_phase_required', False)
                    locked.hard_negotiation = d.get('hard_negotiation', False)
                    locked.suitable_other_dept = d.get('suitable_other_dept', False)
                    locked.suitable_higher_position = d.get('suitable_higher_position', False)
                    locked.suitable_junior_position = d.get('suitable_junior_position', False)
                    locked.recommendation = recommendation
                    locked.is_submitted = True
                    locked.submitted_at = timezone.now()
                    locked.save()
                    submitted_now = True

            if submitted_now:
                # Public token form: no authenticated actor (actor=None).
                audit_log(None, 'interview.evaluation_submitted', locked,
                          details=f'interview={locked.interview_id} recommendation={recommendation}')
            return redirect('interviews:evaluate_done', token=token)
        else:
            form_errors_to_messages(request, form)

    return render(request, 'interviews/evaluate.html', {
        'ev': ev,
        'form': form,
        'criteria': EVALUATION_CRITERIA,
        'score_range': range(1, 6),
    })

def evaluate_done(request, token):
    ev = get_object_or_404(InterviewEvaluation, token=token)
    return render(request, 'interviews/evaluate_done.html', {'ev': ev})

@login_required
def rank_report(request, job_slug):
    from apps.core.models import Job
    job = get_object_or_404(Job, slug=job_slug)
    phase_filter = request.GET.get('phase', '')

    interviews_qs = (
        Interview.objects
        .filter(resume__job=job, resume__is_deleted=False, is_deleted=False,
                evaluations__is_submitted=True)
        .prefetch_related('evaluations', 'resume')
        .select_related('resume')
        .distinct()
    )
    if phase_filter:
        interviews_qs = interviews_qs.filter(phase=phase_filter)

    resume_map = {}
    for iv in interviews_qs:
        r = iv.resume
        if r.id not in resume_map:
            resume_map[r.id] = {
                'resume': r,
                'phases': [],
                'evals': [],
                'yes': 0, 'no': 0, 'maybe': 0,
                'interview_pct': None,
                'composite': None,
            }
        d = resume_map[r.id]
        d['phases'].append(iv.phase)
        for ev in iv.evaluations.all():
            if ev.is_submitted:
                d['evals'].append(ev)
                if ev.recommendation == 'yes':   d['yes']   += 1
                elif ev.recommendation == 'no':  d['no']    += 1
                elif ev.recommendation == 'maybe': d['maybe'] += 1

    candidates = []
    for d in resume_map.values():
        pcts = [e.percentage for e in d['evals'] if e.percentage is not None]
        if pcts:
            d['interview_pct'] = round(sum(pcts) / len(pcts))

        ai = d['resume'].final_score
        iv_pct = d['interview_pct']
        v_score = d['resume'].verification_score
        if iv_pct is not None and ai is not None and v_score is not None:
            d['composite'] = round(iv_pct * 0.65 + float(ai) * 0.25 + float(v_score) * 0.10)
        elif iv_pct is not None and ai is not None:
            d['composite'] = round(iv_pct * 0.70 + float(ai) * 0.30)
        elif iv_pct is not None:
            d['composite'] = iv_pct
        elif ai is not None:
            d['composite'] = round(float(ai))

        total_votes = d['yes'] + d['no'] + d['maybe']
        if total_votes == 0:
            d['verdict'] = 'pending'
        elif d['yes'] > d['no'] and d['yes'] > d['maybe'] and d['yes'] > 0:
            d['verdict'] = 'hire'
        elif d['no'] > d['yes']:
            d['verdict'] = 'reject'
        else:
            d['verdict'] = 'review'

        d['phases'] = sorted(set(d['phases']))
        d['eval_count'] = len(d['evals'])
        candidates.append(d)

    candidates.sort(key=lambda x: (x['composite'] or 0), reverse=True)
    for i, c in enumerate(candidates, 1):
        c['rank'] = i

    all_phases = (
        Interview.objects
        .filter(resume__job=job, resume__is_deleted=False, is_deleted=False,
                evaluations__is_submitted=True)
        .values_list('phase', flat=True)
        .distinct()
        .order_by('phase')
    )

    top = candidates[0]['composite'] if candidates else 0
    avg = round(sum(c['composite'] or 0 for c in candidates) / len(candidates)) if candidates else 0

    return render(request, 'interviews/rank_report.html', {
        'job': job,
        'candidates': candidates,
        'phase_filter': phase_filter,
        'all_phases': list(all_phases),
        'top_score': top,
        'avg_score': avg,
        'hire_count': sum(1 for c in candidates if c['verdict'] == 'hire'),
    })
