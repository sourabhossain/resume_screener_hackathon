import uuid
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.contrib import messages
from django.http import Http404

from apps.core.models import Resume
from .models import Interview, InterviewEvaluation, EVALUATION_CRITERIA, CRITERIA_KEYS, MAX_SCORE
from .forms import InterviewCreateForm, InterviewerAddForm, EvaluationSubmitForm


def _can_access_interview(user, interview):
    """Single-company internal tool: every authenticated recruiter can access all
    interviews, matching the unscoped access to jobs/resumes in apps.core.
    (Views are @login_required, so this is True for any logged-in user.)
    """
    return user.is_authenticated


# ── Admin views (login required) ────────────────────────────────────────────

@login_required
def interview_create(request, resume_uuid):
    resume = get_object_or_404(Resume, uuid=resume_uuid)
    form = InterviewCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        interview = form.save(commit=False)
        interview.resume = resume
        interview.save()
        messages.success(request, 'Interview scheduled.')
        return redirect('interviews:detail', pk=interview.pk)
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


# ── Public evaluation form (no login) ───────────────────────────────────────

def evaluate(request, token):
    ev = get_object_or_404(InterviewEvaluation, token=token)

    if ev.is_submitted:
        return render(request, 'interviews/already_submitted.html', {'ev': ev})

    if ev.is_expired:
        return render(request, 'interviews/expired.html', {'ev': ev})

    form = EvaluationSubmitForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
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

    return render(request, 'interviews/evaluate.html', {
        'ev': ev,
        'form': form,
        'criteria': EVALUATION_CRITERIA,
        'score_range': range(1, 6),
    })


def evaluate_done(request, token):
    ev = get_object_or_404(InterviewEvaluation, token=token)
    return render(request, 'interviews/evaluate_done.html', {'ev': ev})
