import uuid
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.contrib import messages

from apps.core.views import form_errors_to_messages
from apps.core.models import Resume
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
def interview_delete(request, pk):
    interview = get_object_or_404(Interview.objects.select_related('resume__job__owner'), pk=pk)
    if not _can_access_interview(request.user, interview):
        messages.error(request, 'You do not have permission to delete this interview.')
        return redirect('core:dashboard')
    resume_uuid = interview.resume.uuid
    if request.method == 'POST':
        interview.soft_delete()
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
        messages.success(request, f'New link generated for {ev.interviewer_name}.')
    return redirect('interviews:detail', pk=ev.interview_id)


def evaluate(request, token):
    ev = get_object_or_404(InterviewEvaluation, token=token)

    if ev.is_submitted:
        return render(request, 'interviews/already_submitted.html', {'ev': ev})

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
                ev.recommendation = 'yes' if pct >= 75 else ('maybe' if pct >= 55 else 'no')
            ev.is_submitted = True
            ev.submitted_at = timezone.now()
            ev.save()

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
