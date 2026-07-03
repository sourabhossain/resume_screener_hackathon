"""Cross-job screening views: talent pool, needs-review, failed, bulk re-screen."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import redirect, render

from ..models import Resume
from ..services import audit_log
from ._helpers import _get_active_resume

def _failed_resumes_queryset():
    """Resumes whose AI screening did not complete (live jobs only)."""
    return (
        Resume.objects
        .filter(screening_status='failed', is_deleted=False, job__is_deleted=False)
        .select_related('job')
        .order_by('-created_at')
    )

def _needs_review_resumes_queryset():
    """Resumes the AI parked for a human because the job family was uncertain."""
    return (
        Resume.objects
        .filter(screening_status='needs_review', is_deleted=False, job__is_deleted=False)
        .select_related('job')
        .order_by('-created_at')
    )

@login_required
def talent_pool(request):
    from django.core.paginator import Paginator
    resumes_qs = (
        Resume.objects
        .filter(recommendation='talent_pool', is_deleted=False, job__is_deleted=False)
        .select_related('job')
        .order_by('-final_score', '-created_at')
    )
    search_q = request.GET.get('q', '').strip()
    if search_q:
        resumes_qs = resumes_qs.filter(
            Q(candidate_name__icontains=search_q) |
            Q(job__title__icontains=search_q) |
            Q(email__icontains=search_q)
        )
    page_obj = Paginator(resumes_qs, 20).get_page(request.GET.get('page', 1))
    return render(request, 'core/talent_pool.html', {
        'resumes': page_obj,
        'page_obj': page_obj,
        'search_q': search_q,
        'total': resumes_qs.count(),
    })

@login_required
def needs_review_list(request):
    from django.core.paginator import Paginator
    from apps.core.services.job_families import family_choices
    resumes_qs = _needs_review_resumes_queryset()
    search_q = request.GET.get('q', '').strip()
    if search_q:
        resumes_qs = resumes_qs.filter(
            Q(candidate_name__icontains=search_q) |
            Q(job__title__icontains=search_q) |
            Q(email__icontains=search_q)
        )
    page_obj = Paginator(resumes_qs, 20).get_page(request.GET.get('page', 1))
    return render(request, 'core/needs_review.html', {
        'page_obj': page_obj,
        'search_q': search_q,
        'total': resumes_qs.count(),
        'family_choices': family_choices(),
    })

@login_required
def resume_resolve_review(request, uuid):
    """Resolve a needs-review candidate by assigning a recruiter-chosen job
    family, then re-run screening with that family (detection skipped) so the
    candidate reappears in the pipeline with fresh results.

    login_required + _get_active_resume, matching other resume actions.
    """
    from apps.core.tasks import screen_resume_task
    from apps.core.services.job_families import VALID_JOB_TYPES, family_choices

    resume = _get_active_resume(uuid)

    if request.method != 'POST':
        return redirect('core:needs_review')

    if resume.screening_status != 'needs_review':
        messages.error(request, 'This candidate is not awaiting review.')
        return redirect('core:needs_review')

    # Never trust the select: the job family must be in the catalog.
    job_type = (request.POST.get('job_type') or '').strip()
    if job_type not in VALID_JOB_TYPES:
        messages.error(request, 'Please choose a valid job family.')
        return redirect('core:needs_review')

    # Claim the row (guards a double-submit / concurrent resolve).
    updated = Resume.objects.filter(uuid=uuid, screening_status='needs_review').update(
        screening_status='processing',
        verification_status='pending',
        verification_results={},
        verification_score=None,
        verified_at=None,
    )
    if not updated:
        messages.info(request, 'This candidate is no longer awaiting review.')
        return redirect('core:needs_review')

    screen_resume_task.delay(resume.id, job_type=job_type)

    # No dedicated migration-bearing ACTION_CHOICE: reuse rescreen_requested and
    # record the chosen family in details (machine value, no PII).
    audit_log(request.user, 'resume.rescreen_requested', resume,
              details=f'resolved review as {job_type}', request=request)

    label = dict(family_choices()).get(job_type, job_type)
    messages.success(
        request,
        f'Re-screening {resume.candidate_name} as {label}. Results will appear shortly.',
    )
    return redirect('core:needs_review')

@login_required
def screening_failed_list(request):
    from django.core.paginator import Paginator
    resumes_qs = _failed_resumes_queryset()
    search_q = request.GET.get('q', '').strip()
    if search_q:
        resumes_qs = resumes_qs.filter(
            Q(candidate_name__icontains=search_q) |
            Q(job__title__icontains=search_q) |
            Q(email__icontains=search_q)
        )
    page_obj = Paginator(resumes_qs, 20).get_page(request.GET.get('page', 1))
    return render(request, 'core/screening_failed.html', {
        'page_obj': page_obj,
        'search_q': search_q,
        'total': resumes_qs.count(),
    })

@login_required
def screening_rescreen_bulk(request):
    """Re-queue AI screening for all failed resumes, or a selected subset."""
    if request.method != 'POST':
        return redirect('core:screening_failed')

    from apps.core.tasks import screen_resume_task

    scope = request.POST.get('scope', 'selected')
    if scope == 'all':
        targets = _failed_resumes_queryset()
    else:
        uuids = request.POST.getlist('uuids')
        if not uuids:
            messages.warning(request, 'Select at least one candidate to re-screen.')
            return redirect('core:screening_failed')
        targets = _failed_resumes_queryset().filter(uuid__in=uuids)

    ids = list(targets.values_list('id', flat=True))
    if not ids:
        messages.info(request, 'Nothing to re-screen.')
        return redirect('core:screening_failed')

    Resume.objects.filter(id__in=ids, screening_status='failed').update(screening_status='processing')
    for resume in Resume.objects.filter(id__in=ids):
        screen_resume_task.delay(resume.id)
        audit_log(request.user, 'resume.rescreen_requested', resume, details='bulk', request=request)

    n = len(ids)
    messages.success(
        request,
        f'AI screening re-queued for {n} candidate{"s" if n != 1 else ""}. Results will appear shortly.',
    )
    return redirect('core:screening_failed')
