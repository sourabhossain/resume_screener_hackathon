"""Recruiter-facing Job views: list, CRUD, pipeline search, CSV export."""
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render

from ..form_utils import form_errors_to_messages
from ..forms import JobForm
from ..models import Job, Resume
from ..utils import candidate_initial
from ._helpers import _csv_safe, _ordered_active_resumes_queryset, _pipeline_stats


@login_required
def job_list(request):
    from django.core.paginator import Paginator

    resume_prefetch = Prefetch(
        'resumes',
        queryset=_ordered_active_resumes_queryset(Resume.all_objects.all()),
    )

    jobs = Job.objects.annotate(
        resume_count=Count('resumes', filter=Q(resumes__is_deleted=False))
    ).prefetch_related(resume_prefetch)

    search_query = request.GET.get('q', '').strip()
    if search_query:
        jobs = jobs.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    status_filter = request.GET.get('status', 'active').strip()
    if status_filter in ['active', 'draft', 'closed']:
        jobs = jobs.filter(status=status_filter)

    jobs = jobs.order_by('-created_at')

    paginator = Paginator(jobs, 10)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    for job in page_obj.object_list:
        job.preview_initials = [
            candidate_initial(r.candidate_name)
            for r in list(job.resumes.all())[:3]
        ]

    context = {
        'jobs': page_obj,
        'page_obj': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
        'has_active_filter': 'status' in request.GET,
    }
    return render(request, 'core/job_list.html', context)


@login_required
def job_create(request):
    if request.method == 'POST':
        form = JobForm(request.POST, request.FILES)
        if form.is_valid():
            job = form.save(commit=False)
            job.owner = request.user
            job.save()
            messages.success(request, 'Job created successfully!')
            return redirect('core:job_detail', slug=job.slug)
        else:
            form_errors_to_messages(request, form)
    else:
        form = JobForm()
    return render(request, 'core/job_form.html', {'form': form, 'title': 'Post New Job'})


@login_required
def job_detail(request, slug):
    job = get_object_or_404(Job, slug=slug)
    resumes = _ordered_active_resumes_queryset(job.resumes).prefetch_related('interviews__evaluations')

    search_q = request.GET.get('q', '').strip()
    if search_q:
        resumes = resumes.filter(
            Q(candidate_name__icontains=search_q) |
            Q(email__icontains=search_q) |
            Q(phone__icontains=search_q)
        )

    return render(
        request,
        'core/job_detail.html',
        {
            'job': job,
            'resumes': resumes,
            'pipeline_stats': _pipeline_stats(resumes),
            'search_q': search_q,
        },
    )


@login_required
def job_edit(request, slug):
    job = get_object_or_404(Job, slug=slug)
    if request.method == 'POST':
        form = JobForm(request.POST, request.FILES, instance=job)
        if form.is_valid():
            form.save()
            messages.success(request, 'Job updated successfully!')
            return redirect('core:job_detail', slug=job.slug)
        else:
            form_errors_to_messages(request, form)
    else:
        form = JobForm(instance=job)
    return render(request, 'core/job_form.html', {'form': form, 'title': 'Edit Job', 'job': job})


@login_required
def job_delete(request, slug):
    job = get_object_or_404(Job, slug=slug)
    if request.method == 'POST':
        job.soft_delete()
        messages.success(request, f'Job "{job.title}" deleted successfully!')
        return redirect('core:job_list')
    return render(request, 'core/confirm_delete.html', {'object': job, 'type': 'job'})


@login_required
def pipeline_search(request, job_slug):
    job = get_object_or_404(Job, slug=job_slug)
    search_q = request.GET.get('q', '').strip()
    resumes = _ordered_active_resumes_queryset(job.resumes)
    if search_q:
        resumes = resumes.filter(
            Q(candidate_name__icontains=search_q) |
            Q(email__icontains=search_q) |
            Q(phone__icontains=search_q)
        )
    return render(request, 'core/partials/pipeline_search_results.html', {
        'resumes': resumes,
        'search_q': search_q,
        'job': job,
    })


@login_required
def pipeline_suggestions(request, job_slug):
    job = get_object_or_404(Job, slug=job_slug)
    search_q = request.GET.get('q', '').strip()
    suggestions = []
    if search_q:
        suggestions = list(
            _ordered_active_resumes_queryset(job.resumes).filter(
                Q(candidate_name__icontains=search_q) |
                Q(email__icontains=search_q) |
                Q(phone__icontains=search_q)
            ).values('uuid', 'candidate_name', 'email', 'phone')[:6]
        )
    return render(request, 'core/partials/pipeline_suggestions.html', {
        'suggestions': suggestions,
        'search_q': search_q,
    })


@login_required
def job_export_csv(request, slug):
    import csv
    from django.http import StreamingHttpResponse

    job = get_object_or_404(Job, slug=slug)
    resumes = (
        Resume.objects
        .filter(job=job, is_deleted=False)
        .select_related('job')
        .order_by('-final_score', '-created_at')
    )

    def rows():
        header = [
            'Candidate Name', 'Email', 'Phone', 'Tier', 'AI Recommendation',
            'Recruiter Status', 'Final Score', 'Skills Score', 'Experience Score',
            'Education Score', 'Certification Score', 'Achievement Score',
            'Experience Years', 'Verification Score', 'Screening Status',
            'Manually Edited', 'Applied On',
        ]
        yield header
        for r in resumes:
            yield [
                _csv_safe(r.candidate_name),
                _csv_safe(r.email),
                _csv_safe(r.phone),
                r.get_tier_display(),
                r.get_recommendation_display() if r.recommendation else '',
                r.get_recruiter_status_display() if r.recruiter_status else '',
                r.final_score if r.final_score is not None else '',
                r.skills_score if r.skills_score is not None else '',
                r.experience_score if r.experience_score is not None else '',
                r.education_score if r.education_score is not None else '',
                r.certification_score if r.certification_score is not None else '',
                r.achievement_score if r.achievement_score is not None else '',
                r.experience_years if r.experience_years is not None else '',
                r.verification_score if r.verification_score is not None else '',
                r.get_screening_status_display(),
                'Yes' if r.score_manually_edited else 'No',
                r.created_at.strftime('%Y-%m-%d'),
            ]

    class Echo:
        def write(self, value):
            return value

    writer = csv.writer(Echo())
    response = StreamingHttpResponse(
        (writer.writerow(row) for row in rows()),
        content_type='text/csv',
    )
    safe_title = re.sub(r'[^\w\-]', '_', job.title)[:50]
    response['Content-Disposition'] = f'attachment; filename="{safe_title}_candidates.csv"'
    return response
