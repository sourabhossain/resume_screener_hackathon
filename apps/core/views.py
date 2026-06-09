import logging
import os

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Case, Count, IntegerField, Prefetch, Q, Value, When
from django.http import JsonResponse, FileResponse, Http404
from django.db import connection
from django.conf import settings
from django_ratelimit.decorators import ratelimit
from .models import Job, Resume
from .forms import JobForm, ResumeForm, ResumeEditForm
from .utils import candidate_initial

logger = logging.getLogger(__name__)


def _ordered_active_resumes_queryset(resume_qs):
    return resume_qs.filter(is_deleted=False).annotate(
        decision_rank=Case(
            When(recommendation='interview', then=Value(3)),
            When(recommendation='talent_pool', then=Value(2)),
            When(recommendation='reject', then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        ),
    ).order_by('-decision_rank', '-final_score', '-created_at')


def _pipeline_stats(resume_qs):
    # order_by() clears any inherited ordering so it doesn't leak into the
    # implicit GROUP BY; conditional Counts give exact per-decision totals.
    stats = resume_qs.order_by().aggregate(
        total=Count('id'),
        interview=Count('id', filter=Q(recommendation='interview')),
        talent_pool=Count('id', filter=Q(recommendation='talent_pool')),
        reject=Count('id', filter=Q(recommendation='reject')),
    )
    stats['undecided'] = (
        stats['total'] - stats['interview'] - stats['talent_pool'] - stats['reject']
    )
    return stats


def health_check(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({'status': 'healthy', 'database': 'connected', 'version': '1.0.0'})
    except Exception as e:
        logger.error(f"Health check database connectivity failed: {e}")
        return JsonResponse({'status': 'unhealthy', 'database': 'disconnected'}, status=503)


@login_required
def dashboard(request):
    job_stats = Job.objects.aggregate(
        total=Count('id'),
        active=Count('id', filter=Q(status='active'))
    )

    resume_stats = Resume.objects.filter(job__is_deleted=False).aggregate(
        total=Count('id'),
        avg_score=Avg('final_score', filter=Q(final_score__isnull=False)),
        top_tier=Count('id', filter=Q(tier='top')),
        mid_tier=Count('id', filter=Q(tier='mid')),
        low_tier=Count('id', filter=Q(tier='low')),
        pending=Count('id', filter=Q(screening_status='pending')),
        processing=Count('id', filter=Q(screening_status='processing')),
    )

    recent_jobs = Job.objects.annotate(
        resume_count=Count('resumes', filter=Q(resumes__is_deleted=False))
    )[:5]
    recent_resumes = Resume.objects.filter(job__is_deleted=False).select_related('job')[:5]

    context = {
        'total_jobs': job_stats['total'],
        'active_jobs': job_stats['active'],
        'total_resumes': resume_stats['total'],
        'avg_score': round(resume_stats['avg_score'] or 0, 1),
        'recent_jobs': recent_jobs,
        'recent_resumes': recent_resumes,
        'top_tier': resume_stats['top_tier'],
        'mid_tier': resume_stats['mid_tier'],
        'low_tier': resume_stats['low_tier'],
        'pending_screening': resume_stats['pending'],
        'processing_screening': resume_stats['processing'],
    }
    return render(request, 'core/dashboard.html', context)


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
    }
    return render(request, 'core/job_list.html', context)


@login_required
def job_create(request):
    if request.method == 'POST':
        form = JobForm(request.POST, request.FILES)
        if form.is_valid():
            job = form.save()
            messages.success(request, 'Job created successfully!')
            return redirect('core:job_detail', pk=job.pk)
    else:
        form = JobForm()
    return render(request, 'core/job_form.html', {'form': form, 'title': 'Post New Job'})


@login_required
def job_detail(request, pk):
    job = get_object_or_404(Job, pk=pk)
    resumes = _ordered_active_resumes_queryset(job.resumes)
    return render(
        request,
        'core/job_detail.html',
        {
            'job': job,
            'resumes': resumes,
            'pipeline_stats': _pipeline_stats(resumes),
        },
    )


@login_required
def job_edit(request, pk):
    job = get_object_or_404(Job, pk=pk)
    if request.method == 'POST':
        form = JobForm(request.POST, request.FILES, instance=job)
        if form.is_valid():
            form.save()
            messages.success(request, 'Job updated successfully!')
            return redirect('core:job_detail', pk=pk)
    else:
        form = JobForm(instance=job)
    return render(request, 'core/job_form.html', {'form': form, 'title': 'Edit Job', 'job': job})


@login_required
def job_delete(request, pk):
    job = get_object_or_404(Job, pk=pk)
    if request.method == 'POST':
        job.soft_delete()
        messages.success(request, f'Job "{job.title}" deleted successfully!')
        return redirect('core:job_list')
    return render(request, 'core/confirm_delete.html', {'object': job, 'type': 'job'})


@login_required
def resume_create(request, job_pk):
    job = get_object_or_404(Job, pk=job_pk)

    if job.status != 'active':
        status_label = 'Draft' if job.status == 'draft' else 'Closed'
        messages.error(request, f'Cannot add resume. This job is currently {status_label}.')
        return redirect('core:job_detail', pk=job_pk)

    if request.method == 'POST':
        form = ResumeForm(request.POST, request.FILES)
        if form.is_valid():
            resume = form.save(commit=False)
            resume.job = job
            resume.screening_status = 'processing'
            resume.save()

            from apps.core.tasks import screen_resume_task
            screen_resume_task.delay(resume.id)

            messages.success(
                request,
                'Resume added. AI screening is running in the background—the pipeline row will refresh automatically.',
            )
            return redirect('core:job_detail', pk=job_pk)
    else:
        form = ResumeForm()
    return render(request, 'core/resume_form.html', {'form': form, 'job': job, 'title': 'Add Resume'})


@login_required
def resume_detail(request, pk):
    resume = get_object_or_404(Resume.objects.select_related('job'), pk=pk)
    return render(request, 'core/resume_detail.html', {'resume': resume})


@login_required
def resume_edit(request, pk):
    resume = get_object_or_404(Resume.objects.select_related('job'), pk=pk)
    if request.method == 'POST':
        form = ResumeEditForm(request.POST, request.FILES, instance=resume)
        if form.is_valid():
            form.save()
            messages.success(request, 'Resume updated successfully!')
            return redirect('core:resume_detail', pk=pk)
    else:
        form = ResumeEditForm(instance=resume)
    return render(request, 'core/resume_edit_form.html', {'form': form, 'job': resume.job, 'title': 'Edit Resume', 'resume': resume})


@login_required
def resume_delete(request, pk):
    resume = get_object_or_404(Resume, pk=pk)
    job_pk = resume.job.pk
    if request.method == 'POST':
        resume.soft_delete()
        messages.success(request, f'Resume for "{resume.candidate_name}" deleted successfully!')
        return redirect('core:job_detail', pk=job_pk)
    return render(request, 'core/confirm_delete.html', {'object': resume, 'type': 'resume', 'job_pk': job_pk})


@login_required
@ratelimit(key='user', rate='60/m', block=True)
def serve_protected_media(request, path):
    full_path = os.path.join(settings.MEDIA_ROOT, path)
    # os.sep prevents path traversal into sibling directories (e.g. /media/../secrets)
    media_root = os.path.abspath(settings.MEDIA_ROOT) + os.sep
    if not os.path.abspath(full_path).startswith(media_root):
        raise Http404
    if not os.path.exists(full_path):
        raise Http404
    return FileResponse(open(full_path, 'rb'))


@login_required
def resume_status_fragment(request, pk):
    resume = get_object_or_404(Resume.objects.select_related('job'), pk=pk)
    return render(request, 'core/partials/resume_status.html', {'resume': resume})


@login_required
def resume_row_fragment(request, pk):
    resume = get_object_or_404(Resume.objects.select_related('job'), pk=pk)
    # Recompute pipeline stats so the polling response can OOB-refresh the
    # "pending screening" badge as rows finish (otherwise it goes stale).
    pipeline_stats = _pipeline_stats(_ordered_active_resumes_queryset(resume.job.resumes))
    return render(
        request,
        'core/partials/resume_row.html',
        {'resume': resume, 'pipeline_stats': pipeline_stats, 'is_fragment': True},
    )


@login_required
def resume_bulk_create(request, job_pk):
    job = get_object_or_404(Job, pk=job_pk)

    if job.status != 'active':
        status_label = 'Draft' if job.status == 'draft' else 'Closed'
        messages.error(request, f'Cannot add resumes. This job is currently {status_label}.')
        return redirect('core:job_detail', pk=job_pk)

    if request.method == 'POST':
        files = request.FILES.getlist('files')

        if not files:
            messages.error(request, 'Please select at least one file.')
            return render(request, 'core/resume_bulk_form.html', {'job': job})

        if len(files) > 20:
            messages.error(request, 'Maximum 20 files per upload.')
            return render(request, 'core/resume_bulk_form.html', {'job': job})

        from apps.core.tasks import screen_resume_task

        ALLOWED = {'pdf', 'docx'}
        MAX_SIZE = 5 * 1024 * 1024
        MAGIC = {'pdf': b'%PDF', 'docx': b'PK\x03\x04'}

        queued = 0
        skipped = []

        for file in files:
            if file.size > MAX_SIZE:
                skipped.append(f'"{file.name}" exceeds the 5 MB limit')
                continue

            _, raw_ext = os.path.splitext(file.name)
            ext = raw_ext.lstrip('.').lower()
            if ext not in ALLOWED:
                skipped.append(f'"{file.name}" — only PDF or DOCX supported')
                continue

            file.seek(0)
            header = file.read(8)
            file.seek(0)
            if not header.startswith(MAGIC[ext]):
                skipped.append(f'"{file.name}" — file content does not match {ext.upper()} format')
                continue

            candidate_name = os.path.splitext(file.name)[0].replace('_', ' ').replace('-', ' ').strip() or 'Unknown'

            resume = Resume(
                job=job,
                candidate_name=candidate_name,
                file_name=file.name,
                file_type=ext,
                screening_status='processing',
            )
            resume.file.save(file.name, file, save=True)
            screen_resume_task.delay(resume.id)
            queued += 1

        if queued:
            messages.success(request, f'{queued} resume{"s" if queued != 1 else ""} uploaded. AI screening is running in the background.')
        for msg in skipped:
            messages.warning(request, msg)

        return redirect('core:job_detail', pk=job_pk)

    return render(request, 'core/resume_bulk_form.html', {'job': job})


@login_required
def resume_rescreen(request, pk):
    resume = get_object_or_404(Resume, pk=pk)

    if request.method != 'POST':
        return redirect('core:resume_detail', pk=pk)

    from apps.core.tasks import screen_resume_task
    # Atomic update prevents duplicate tasks from concurrent clicks
    updated = Resume.objects.filter(
        pk=pk, screening_status__in=['pending', 'completed', 'failed']
    ).update(screening_status='processing')
    if not updated:
        messages.info(request, 'Screening is already in progress. Please wait for it to complete.')
        return redirect('core:resume_detail', pk=pk)

    screen_resume_task.delay(resume.id)
    messages.success(request, 'AI screening queued! Results will appear shortly.')
    return redirect('core:resume_detail', pk=pk)
