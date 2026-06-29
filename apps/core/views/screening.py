"""Cross-job screening views: talent pool, needs-review, failed, bulk re-screen."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import redirect, render

from ..models import Resume

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
    })

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
    for rid in ids:
        screen_resume_task.delay(rid)

    n = len(ids)
    messages.success(
        request,
        f'AI screening re-queued for {n} candidate{"s" if n != 1 else ""}. Results will appear shortly.',
    )
    return redirect('core:screening_failed')
