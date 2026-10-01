import uuid
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.db import transaction
from django.contrib import messages

from apps.core.views import form_errors_to_messages
from apps.core.models import Resume
from .models import Interview, InterviewEvaluation, EVALUATION_CRITERIA, CRITERIA_KEYS, MAX_SCORE
from .forms import (EvaluationSubmitForm, InterviewCreateForm, StaffEvaluatorForm,
                    staff_evaluators, staff_label)


def _can_access_interview(user, interview):
    """Single-company internal tool: every authenticated recruiter can access all
    interviews, matching the unscoped access to jobs/resumes in apps.core.
    (Views are @login_required, so this is True for any logged-in user.)
    """
    return user.is_authenticated


def _queue_invites(interview, evaluations, *, candidate):
    """Queue the emails once the rows are committed, so a worker never misses them."""
    from apps.core.utils import queue_task
    from .tasks import send_candidate_invite, send_evaluator_invite

    def send():
        for ev in evaluations:
            if not queue_task(send_evaluator_invite, ev.pk):
                InterviewEvaluation.objects.filter(pk=ev.pk).update(
                    invite_error='Could not queue the email: the background queue is unavailable.')
        if candidate and not queue_task(send_candidate_invite, interview.pk):
            Interview.objects.filter(pk=interview.pk).update(
                candidate_email_error='Could not queue the email: the background queue is unavailable.')
    transaction.on_commit(send)


def _release(kind, pk):
    from django.core.cache import cache
    cache.delete(f'send-claim:{kind}:{pk}')


def _evaluation_for(interview, user):
    return InterviewEvaluation(interview=interview, evaluator=user,
                               interviewer_name=staff_label(user), interviewer_email=user.email,
                               token_expires_at=interview.evaluation_link_expiry())


def _panel_of(interview):
    """Staff on this panel who can still be invited: active, with an email."""
    return list(interview.evaluations.filter(evaluator__is_active=True).exclude(evaluator__email='')
                .values_list('evaluator_id', flat=True))


def _queue_cancellation(interview):
    """Tell the invited panel and candidate, once the change is committed."""
    invited = (interview.candidate_notified_at is not None
               or interview.evaluations.filter(invited_at__isnull=False, is_submitted=False).exists())
    if not invited:
        return False
    from apps.core.utils import queue_task
    from .tasks import send_interview_cancellation
    transaction.on_commit(lambda: queue_task(send_interview_cancellation, interview.pk))
    return True


@login_required
def interview_create(request, resume_uuid):
    resume = get_object_or_404(Resume.objects.select_related('job'), uuid=resume_uuid)
    from apps.core.status import OUTCOMES_THE_SYSTEM_NEVER_MOVES
    if resume.recruiter_status in OUTCOMES_THE_SYSTEM_NEVER_MOVES:
        messages.error(request, f'{resume.candidate_name.title()} is {resume.get_recruiter_status_display()}, '
                                'so an interview cannot be scheduled. Change the status first.')
        return redirect('core:resume_detail', uuid=resume.uuid)
    held = Interview.objects.filter(resume=resume, is_deleted=False).exclude(status=Interview.CANCELLED)
    done_phases = set(held.values_list('phase', flat=True))
    next_phase = next((key for key, _ in Interview.PHASE_CHOICES if key not in done_phases), '3')
    form = InterviewCreateForm(request.POST or None, initial={'phase': next_phase})
    if request.method == 'POST':
        if form.is_valid():
            phase = form.cleaned_data['phase']
            required_prior = {'2': '1', '3': '2'}
            prior_phase = required_prior.get(phase)
            if phase in done_phases:
                # Also stops a double click from booking (and emailing) it twice.
                form.add_error('phase', f'{dict(Interview.PHASE_CHOICES)[phase]} is already scheduled for '
                                        'this candidate. Open it from the candidate page instead.')
            elif prior_phase and prior_phase not in done_phases:
                phase_label = dict(Interview.PHASE_CHOICES).get(prior_phase, f'Phase {prior_phase}')
                form.add_error('phase', f'{phase_label} must be scheduled before this phase.')
            else:
                with transaction.atomic():
                    interview = form.save(commit=False)
                    interview.resume = resume
                    interview.save()
                    evaluations = [_evaluation_for(interview, user) for user in form.cleaned_data['evaluators']]
                    for ev in evaluations:
                        ev.save()
                    _queue_invites(interview, evaluations, candidate=interview.notify_candidate)
                from apps.core.status import advance
                advance(resume, 'interviewing', reason='Interview scheduled', user=request.user)
                sent_to = f'{len(evaluations)} evaluator{"s" if len(evaluations) != 1 else ""}'
                if interview.notify_candidate:
                    sent_to += ' and the candidate'
                messages.success(request, f'Interview scheduled. Invitations are on their way to {sent_to}.')
                return redirect('interviews:detail', pk=interview.pk)
        if form.errors:
            form_errors_to_messages(request, form)

    # Panels to reuse in one click: this candidate's last round, else this job's last interview.
    panels = []
    mine = held.order_by('-scheduled_date', '-created_at').first()
    if mine and _panel_of(mine):
        panels.append({'label': f'Same panel as {mine.get_phase_display()}', 'ids': _panel_of(mine)})
    recent = (Interview.objects.filter(resume__job=resume.job, is_deleted=False).exclude(resume=resume)
              .exclude(status=Interview.CANCELLED).order_by('-created_at'))
    for other in recent[:10]:
        ids = _panel_of(other)
        if ids:
            panels.append({'label': f'Last panel for this job ({other.resume.candidate_name.title()})', 'ids': ids})
            break
    staff = [{'id': u.pk, 'name': staff_label(u), 'email': u.email} for u in staff_evaluators()]
    chosen = [int(pk) for pk in (form['evaluators'].value() or []) if str(pk).isdigit()]
    return render(request, 'interviews/create.html', {
        'form': form, 'resume': resume, 'staff': staff, 'panels': panels, 'chosen': chosen,
    })


@login_required
def interview_detail(request, pk):
    interview = get_object_or_404(Interview.objects.select_related('resume__job__owner'), pk=pk)
    if not _can_access_interview(request.user, interview):
        messages.error(request, 'You do not have permission to view this interview.')
        return redirect('core:dashboard')
    add_form = StaffEvaluatorForm(request.POST or None, interview=interview)

    if request.method == 'POST' and interview.status == Interview.CANCELLED:
        messages.error(request, 'This interview is cancelled. Reopen it before adding an evaluator.')
        return redirect('interviews:detail', pk=pk)
    if request.method == 'POST' and add_form.is_valid():
        with transaction.atomic():
            ev = _evaluation_for(interview, add_form.cleaned_data['evaluator'])
            ev.save()
            _queue_invites(interview, [ev], candidate=False)
        messages.success(request, f'{ev.interviewer_name} added. Their evaluation link is on its way by email.')
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
@require_POST
def evaluation_resend(request, token):
    """Email an evaluator their link again."""
    from apps.core.utils import claim_send, queue_task
    from .tasks import send_evaluator_invite
    ev = get_object_or_404(InterviewEvaluation.objects.select_related('interview', 'evaluator'), token=token)
    if ev.is_submitted or ev.interview.status != Interview.SCHEDULED:
        messages.error(request, 'Only a pending evaluator on a scheduled interview can be emailed.')
    elif not ev.interviewer_email:
        messages.error(request, f'{ev.interviewer_name} has no email address. Copy the link instead.')
    elif ev.evaluator_id and not ev.evaluator.is_active:
        messages.error(request, f'{ev.interviewer_name} is no longer an active staff account, so the link '
                                'was not sent. Remove them from the panel.')
    elif not claim_send('interview_evaluator', ev.pk, seconds=60):
        messages.info(request, 'The email was sent a moment ago.')
    elif queue_task(send_evaluator_invite, ev.pk):
        InterviewEvaluation.objects.filter(pk=ev.pk).update(invite_error='')
        messages.success(request, f'Evaluation link emailed again to {ev.interviewer_name}.')
    else:
        _release('interview_evaluator', ev.pk)
        messages.error(request, 'The email could not be queued right now. Try again in a minute.')
    return redirect('interviews:detail', pk=ev.interview_id)


@login_required
@require_POST
def candidate_resend(request, pk):
    """Email the candidate the interview details again."""
    from apps.core.utils import claim_send, queue_task
    from .tasks import send_candidate_invite
    interview = get_object_or_404(Interview.objects.select_related('resume'), pk=pk)
    if interview.status != Interview.SCHEDULED:
        messages.error(request, 'Only a scheduled interview can be sent to the candidate.')
    elif not (interview.resume.email or '').strip():
        messages.error(request, 'The candidate has no email address on file.')
    elif not claim_send('interview_candidate', interview.pk, seconds=60):
        messages.info(request, 'The email was sent a moment ago.')
    elif queue_task(send_candidate_invite, interview.pk):
        Interview.objects.filter(pk=interview.pk).update(candidate_email_error='', notify_candidate=True)
        messages.success(request, f'Interview details emailed to {interview.resume.email}.')
    else:
        _release('interview_candidate', interview.pk)
        messages.error(request, 'The email could not be queued right now. Try again in a minute.')
    return redirect('interviews:detail', pk=interview.pk)


@login_required
def interview_delete(request, pk):
    interview = get_object_or_404(Interview.objects.select_related('resume__job__owner'), pk=pk)
    if not _can_access_interview(request.user, interview):
        messages.error(request, 'You do not have permission to delete this interview.')
        return redirect('core:dashboard')
    resume_uuid = interview.resume.uuid
    if request.method == 'POST':
        with transaction.atomic():
            told = interview.status == Interview.SCHEDULED and _queue_cancellation(interview)
            interview.soft_delete()
        messages.success(request, 'Interview deleted.' + (
            ' Everyone who was invited is being told it is cancelled.' if told else ''))
    return redirect('core:resume_detail', uuid=resume_uuid)


@login_required
@require_POST
def interview_status(request, pk):
    """Cancel, complete or reopen an interview."""
    interview = get_object_or_404(Interview, pk=pk)
    if not _can_access_interview(request.user, interview):
        messages.error(request, 'You do not have permission to change this interview.')
        return redirect('core:dashboard')
    action = request.POST.get('action')
    target = {'cancel': Interview.CANCELLED, 'complete': Interview.COMPLETED,
              'reopen': Interview.SCHEDULED}.get(action)
    if target is None:
        messages.error(request, 'Unknown action.')
    elif target == interview.status:
        messages.info(request, f'The interview is already {interview.get_status_display().lower()}.')
    else:
        was = interview.status
        with transaction.atomic():
            interview.status = target
            interview.save(update_fields=['status'])
            told = target == Interview.CANCELLED and was == Interview.SCHEDULED and _queue_cancellation(interview)
        messages.success(request, {
            Interview.CANCELLED: 'Interview cancelled. Evaluation links that were not used no longer work.'
                                 + (' Everyone who was invited is being told by email.' if told else ''),
            Interview.COMPLETED: 'Interview marked as completed.',
            Interview.SCHEDULED: 'Interview reopened. Use Resend email and Send again to tell the panel '
                                 'and the candidate.',
        }[target])
    return redirect('interviews:detail', pk=pk)


@login_required
def evaluation_delete(request, token):
    ev = get_object_or_404(InterviewEvaluation.objects.select_related('interview__resume__job__owner'), token=token)
    if not _can_access_interview(request.user, ev.interview):
        messages.error(request, 'You do not have permission to delete this evaluation.')
        return redirect('core:dashboard')
    interview_pk = ev.interview_id
    if request.method == 'POST':
        ev.delete()
        messages.success(request, 'Evaluation slot removed.')
    return redirect('interviews:detail', pk=interview_pk)


@login_required
def evaluation_renew(request, token):
    from apps.core.utils import claim_send
    ev = get_object_or_404(InterviewEvaluation.objects.select_related('interview__resume__job__owner'), token=token)
    if not _can_access_interview(request.user, ev.interview):
        messages.error(request, 'You do not have permission to renew this evaluation link.')
        return redirect('core:dashboard')
    if request.method == 'POST' and ev.interview.status == Interview.CANCELLED:
        messages.error(request, 'This interview is cancelled. Reopen it before renewing a link.')
        return redirect('interviews:detail', pk=ev.interview_id)
    if request.method == 'POST' and not ev.is_submitted and not claim_send('interview_renew', ev.pk, seconds=30):
        messages.info(request, 'A new link was made a moment ago.')
    elif request.method == 'POST' and not ev.is_submitted:
        ev.token = uuid.uuid4()
        ev.token_expires_at = ev.interview.evaluation_link_expiry()
        ev.save(update_fields=['token', 'token_expires_at'])
        if ev.interviewer_email:
            # The old link stops working, so the new one goes out at once.
            _queue_invites(ev.interview, [ev], candidate=False)
            messages.success(request, f'New link generated and emailed to {ev.interviewer_name}.')
        else:
            messages.success(request, f'New link generated for {ev.interviewer_name}.')
    return redirect('interviews:detail', pk=ev.interview_id)


def _closed_by_deletion(ev):
    return (ev.interview.is_deleted or ev.interview.resume.is_deleted
            or ev.interview.resume.job.is_deleted)


def evaluate(request, token):
    ev = get_object_or_404(InterviewEvaluation.objects.select_related(
        'interview', 'interview__resume', 'interview__resume__job'), token=token)

    # A deleted interview or candidate closes the panel's links with it, with
    # a page that says so rather than a bare "not found".
    if _closed_by_deletion(ev):
        return render(request, 'interviews/cancelled.html', {'ev': ev}, status=410)

    if ev.is_submitted:
        return render(request, 'interviews/already_submitted.html', {'ev': ev})

    # A cancelled interview needs no scores: its open links stop working.
    if ev.interview.status == Interview.CANCELLED:
        return render(request, 'interviews/cancelled.html', {'ev': ev})

    if ev.is_expired:
        return render(request, 'interviews/expired.html', {'ev': ev})

    form = EvaluationSubmitForm(request.POST or None)

    if request.method == 'POST':
        if form.is_valid():
            d = form.cleaned_data

            # Collect scores
            ev.scores = {key: int(d[f'score_{key}']) for key in CRITERIA_KEYS}
            ev.additional_notes = d.get('additional_notes', '')
            ev.another_phase_required = d.get('another_phase_required', False)
            ev.hard_negotiation = d.get('hard_negotiation', False)
            ev.suitable_other_dept = d.get('suitable_other_dept', False)
            ev.suitable_higher_position = d.get('suitable_higher_position', False)
            ev.suitable_junior_position = d.get('suitable_junior_position', False)

            # Use manual recommendation if given, otherwise auto-calculate
            manual_rec = d.get('recommendation', '')
            if manual_rec:
                ev.recommendation = manual_rec
            else:
                total = sum(ev.scores.values())
                pct = round((total / MAX_SCORE) * 100)
                # Same cut-offs as the Good / Satisfactory line the interviewer saw.
                ev.recommendation = 'yes' if pct >= 80 else ('maybe' if pct >= 60 else 'no')
            ev.is_submitted = True
            ev.submitted_at = timezone.now()
            with transaction.atomic():
                # A double submit (two tabs, a retried request) must not let the
                # second overwrite the first, and a link renewed meanwhile keeps
                # its new token: only the answer columns are written.
                if InterviewEvaluation.objects.select_for_update().filter(
                        pk=ev.pk, is_submitted=True).exists():
                    return render(request, 'interviews/already_submitted.html', {'ev': ev})
                ev.save(update_fields=[
                    'scores', 'additional_notes', 'another_phase_required', 'hard_negotiation',
                    'suitable_other_dept', 'suitable_higher_position', 'suitable_junior_position',
                    'recommendation', 'is_submitted', 'submitted_at'])
            ev.interview.complete_if_all_submitted()

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
    ev = get_object_or_404(InterviewEvaluation.objects.select_related(
        'interview', 'interview__resume', 'interview__resume__job'), token=token)
    if _closed_by_deletion(ev):
        return render(request, 'interviews/cancelled.html', {'ev': ev}, status=410)
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
        .exclude(status=Interview.CANCELLED)
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
        # Composite: interview 65%, AI score 25%, link-verification 10%.
        # Gracefully degrades when verification is absent (skipped/failed).
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
            # Strict majority: tied votes go to 'review', not 'hire'
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

    # Available phases for filter tabs
    all_phases = (
        Interview.objects
        .filter(resume__job=job, resume__is_deleted=False, is_deleted=False,
                evaluations__is_submitted=True)
        .exclude(status=Interview.CANCELLED)
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
