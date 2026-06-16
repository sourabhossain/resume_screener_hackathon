import logging
import os
import re
from datetime import timedelta

from django import forms
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm, SetPasswordForm
from django.db.models import Avg, Case, Count, IntegerField, Prefetch, Q, Value, When
from django.http import JsonResponse, FileResponse, Http404
from django.db import connection
from django.conf import settings
from django_ratelimit.decorators import ratelimit
from .models import Job, Resume
from .forms import JobForm, ResumeForm, ResumeEditForm
from .form_utils import form_errors_to_messages, clean_person_text
from .utils import candidate_initial, compute_file_hash

User = get_user_model()

logger = logging.getLogger(__name__)


def _validate_user_name_fields(request) -> bool:
    """Validate optional first/last name on user create; surfaces toast errors."""
    ok = True
    for label, raw in (
        ('First name', request.POST.get('first_name', '')),
        ('Last name', request.POST.get('last_name', '')),
    ):
        try:
            clean_person_text(raw)
        except forms.ValidationError as exc:
            messages.error(request, f'{label}: {exc.messages[0]}')
            ok = False
    return ok


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
    # Single-company internal tool: every authenticated recruiter sees all data.
    from django.utils import timezone as tz
    from apps.interviews.models import InterviewEvaluation

    job_stats = Job.objects.aggregate(
        total=Count('id'),
        active=Count('id', filter=Q(status='active'))
    )

    resume_stats = Resume.objects.filter(job__is_deleted=False).aggregate(
        total=Count('id'),
        avg_score=Avg('final_score', filter=Q(final_score__isnull=False, screening_status='completed')),
        top_tier=Count('id', filter=Q(tier='top')),
        mid_tier=Count('id', filter=Q(tier='mid')),
        low_tier=Count('id', filter=Q(tier='low')),
        pending=Count('id', filter=Q(screening_status='pending')),
        processing=Count('id', filter=Q(screening_status='processing')),
        screening_failed=Count('id', filter=Q(screening_status='failed')),
        talent_pool_count=Count('id', filter=Q(recommendation='talent_pool')),
    )

    # Actionable alerts: evaluations expiring in <= 3 days, not yet submitted
    expiry_threshold = tz.now() + timedelta(days=3)
    expiring_evals = InterviewEvaluation.objects.filter(
        is_submitted=False,
        token_expires_at__lte=expiry_threshold,
        token_expires_at__gte=tz.now(),
    ).count()

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
        'screening_failed': resume_stats['screening_failed'],
        'talent_pool_count': resume_stats['talent_pool_count'],
        'expiring_evals': expiring_evals,
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
def resume_create(request, job_slug):
    job = get_object_or_404(Job, slug=job_slug)

    if job.status != 'active':
        status_label = 'Draft' if job.status == 'draft' else 'Closed'
        messages.error(request, f'Cannot add resume. This job is currently {status_label}.')
        return redirect('core:job_detail', slug=job_slug)

    if request.method == 'POST':
        form = ResumeForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = request.FILES.get('file')
            file_hash = compute_file_hash(uploaded_file) if uploaded_file else ''

            if file_hash and Resume.objects.filter(job=job, file_hash=file_hash, is_deleted=False).exists():
                messages.error(request, 'This resume file has already been submitted for this job.')
                return render(request, 'core/resume_form.html', {'form': form, 'job': job, 'title': 'Add Resume'})

            resume = form.save(commit=False)
            resume.job = job
            resume.file_hash = file_hash
            resume.screening_status = 'processing'
            resume.save()

            from apps.core.tasks import screen_resume_task
            screen_resume_task.delay(resume.id)

            messages.success(
                request,
                'Resume added. AI screening is running in the background, the pipeline row will refresh automatically.',
            )
            return redirect('core:job_detail', slug=job_slug)
        else:
            form_errors_to_messages(request, form)
    else:
        form = ResumeForm()
    return render(request, 'core/resume_form.html', {'form': form, 'job': job, 'title': 'Add Resume'})


@login_required
def resume_detail(request, uuid):
    resume = get_object_or_404(Resume.objects.select_related('job'), uuid=uuid)
    return render(request, 'core/resume_detail.html', {'resume': resume})


@login_required
def resume_edit(request, uuid):
    resume = get_object_or_404(Resume.objects.select_related('job'), uuid=uuid)
    SCORE_FIELDS = {'experience_score', 'education_score', 'skills_score',
                    'certification_score', 'achievement_score', 'final_score'}
    if request.method == 'POST':
        form = ResumeEditForm(request.POST, request.FILES, instance=resume)
        if form.is_valid():
            changed = {f for f in form.changed_data if f in SCORE_FIELDS}
            instance = form.save(commit=False)
            if changed:
                from django.utils import timezone as tz
                instance.score_manually_edited = True
                instance.score_edited_at = tz.now()
                instance.score_edited_by = request.user
                # Keep tier + recommendation consistent with the (edited) final score,
                # using the same thresholds the AI screener applies (rank_node).
                cfg = settings.AI_SCREENING_CONFIG
                score = instance.final_score or 0
                if score >= cfg['TOP_TIER_THRESHOLD']:
                    instance.tier, instance.recommendation = 'top', 'interview'
                elif score >= cfg['MID_TIER_THRESHOLD']:
                    instance.tier, instance.recommendation = 'mid', 'talent_pool'
                else:
                    instance.tier, instance.recommendation = 'low', 'reject'
            instance.save()
            messages.success(request, 'Resume updated successfully!')
            return redirect('core:resume_detail', uuid=uuid)
        else:
            form_errors_to_messages(request, form)
    else:
        form = ResumeEditForm(instance=resume)
    return render(request, 'core/resume_edit_form.html', {'form': form, 'job': resume.job, 'title': 'Edit Resume', 'resume': resume})


@login_required
def resume_delete(request, uuid):
    resume = get_object_or_404(Resume, uuid=uuid)
    job_slug = resume.job.slug
    if request.method == 'POST':
        resume.soft_delete()
        messages.success(request, f'Resume for "{resume.candidate_name}" deleted successfully!')
        return redirect('core:job_detail', slug=job_slug)
    return render(request, 'core/confirm_delete.html', {'object': resume, 'type': 'resume', 'job_slug': job_slug})


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
def resume_status_fragment(request, uuid):
    resume = get_object_or_404(Resume.objects.select_related('job'), uuid=uuid)
    return render(request, 'core/partials/resume_status.html', {'resume': resume})


@login_required
def resume_row_fragment(request, uuid):
    resume = get_object_or_404(Resume.objects.select_related('job'), uuid=uuid)
    # Recompute pipeline stats so the polling response can OOB-refresh the
    # "pending screening" badge as rows finish (otherwise it goes stale).
    pipeline_stats = _pipeline_stats(_ordered_active_resumes_queryset(resume.job.resumes))
    return render(
        request,
        'core/partials/resume_row.html',
        {'resume': resume, 'pipeline_stats': pipeline_stats, 'is_fragment': True},
    )


@login_required
def resume_bulk_create(request, job_slug):
    job = get_object_or_404(Job, slug=job_slug)

    if job.status != 'active':
        status_label = 'Draft' if job.status == 'draft' else 'Closed'
        messages.error(request, f'Cannot add resumes. This job is currently {status_label}.')
        return redirect('core:job_detail', slug=job_slug)

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
                skipped.append(f'"{file.name}" - only PDF or DOCX supported')
                continue

            file.seek(0)
            header = file.read(8)
            file.seek(0)
            if not header.startswith(MAGIC[ext]):
                skipped.append(f'"{file.name}" - file content does not match {ext.upper()} format')
                continue

            file_hash = compute_file_hash(file)
            if Resume.objects.filter(job=job, file_hash=file_hash, is_deleted=False).exists():
                skipped.append(f'"{file.name}" - already submitted for this job')
                continue

            safe_basename = os.path.basename(file.name)
            candidate_name = os.path.splitext(safe_basename)[0].replace('_', ' ').replace('-', ' ').strip()[:255] or 'Unknown'

            resume = Resume(
                job=job,
                candidate_name=candidate_name,
                file_name=safe_basename[:255],
                file_type=ext,
                file_hash=file_hash,
                screening_status='processing',
            )
            resume.file.save(safe_basename, file, save=True)
            screen_resume_task.delay(resume.id)
            queued += 1

        if queued:
            messages.success(request, f'{queued} resume{"s" if queued != 1 else ""} uploaded. AI screening is running in the background.')
        for msg in skipped:
            messages.warning(request, msg)

        return redirect('core:job_detail', slug=job_slug)

    return render(request, 'core/resume_bulk_form.html', {'job': job})


@login_required
def resume_rescreen(request, uuid):
    resume = get_object_or_404(Resume, uuid=uuid)

    if request.method != 'POST':
        return redirect('core:resume_detail', uuid=uuid)

    from apps.core.tasks import screen_resume_task
    # Atomic update prevents duplicate tasks from concurrent clicks
    updated = Resume.objects.filter(
        uuid=uuid, screening_status__in=['pending', 'completed', 'failed']
    ).update(screening_status='processing')
    if not updated:
        messages.info(request, 'Screening is already in progress. Please wait for it to complete.')
        return redirect('core:resume_detail', uuid=uuid)

    screen_resume_task.delay(resume.id)
    messages.success(request, 'AI screening queued! Results will appear shortly.')
    return redirect('core:resume_detail', uuid=uuid)


# ──────────────────────────────────────────────────────────────────────────
# Public candidate (careers) pages — NO login required.
# Candidates browse open jobs and submit their resume; they never see results.
# ──────────────────────────────────────────────────────────────────────────

def careers_list(request):
    """Public list of open (active) jobs candidates can apply to.

    Supports live (HTMX) search: typing in the search box fires a debounced
    request that swaps the results grid and the typeahead suggestions.
    """
    from django.core.paginator import Paginator

    jobs_qs = Job.objects.filter(status='active').order_by('-created_at')

    search_query = request.GET.get('q', '').strip()
    if search_query:
        jobs_qs = jobs_qs.filter(
            Q(title__icontains=search_query) | Q(description__icontains=search_query)
        )

    # Typeahead suggestions (only while searching); same match as the grid.
    suggestions = list(jobs_qs[:6]) if search_query else []

    # Paginate so a public, unauthenticated page never loads every active job
    # (and its full description) into memory on each request.
    page_obj = Paginator(jobs_qs, 12).get_page(request.GET.get('page', 1))

    context = {
        'jobs': page_obj,
        'page_obj': page_obj,
        'search_query': search_query,
        'suggestions': suggestions,
    }

    # HTMX live-search request → return just the results + OOB suggestions.
    if request.headers.get('HX-Request'):
        return render(request, 'careers/_search_response.html', context)

    return render(request, 'careers/job_list.html', context)


@ratelimit(key='ip', rate='10/h', method='POST', block=True)
def careers_apply(request, slug):
    """Public job detail + resume submission form. Only active jobs accept applications."""
    job = get_object_or_404(Job, slug=slug, status='active')

    from django.utils import timezone as tz
    if job.closing_date and tz.now().date() > job.closing_date:
        messages.error(request, 'This position is no longer accepting applications.')
        return redirect('core:careers')

    if request.method == 'POST':
        # require_contact: applicants must give an email so recruiters can reply.
        form = ResumeForm(request.POST, request.FILES, require_contact=True)
        if form.is_valid():
            email = form.cleaned_data.get('email', '').strip().lower()
            # Strip all spaces, dashes, and parentheses so "+880 1711-123456" == "+8801711123456".
            phone = re.sub(r'[\s\-()]+', '', form.cleaned_data.get('phone', ''))
            uploaded_file = request.FILES.get('file')
            file_hash = compute_file_hash(uploaded_file) if uploaded_file else ''

            # Block duplicate submissions: same email, phone, or file already on record for this job.
            if email and Resume.objects.filter(job=job, email__iexact=email, is_deleted=False).exists():
                messages.error(request, 'An application with this email address already exists for this position.')
                return render(request, 'careers/apply.html', {'job': job, 'form': form})

            if phone:
                # Normalize DB values the same way before comparing so formatting differences don't bypass the check.
                from django.db.models import F, Value as V
                from django.db.models.functions import Replace
                existing_phone = (
                    Resume.objects.filter(job=job, is_deleted=False)
                    .annotate(
                        phone_normalized=Replace(
                            Replace(
                                Replace(
                                    Replace(F('phone'), V(' '), V('')),
                                    V('-'), V(''),
                                ),
                                V('('), V(''),
                            ),
                            V(')'), V(''),
                        )
                    )
                    .filter(phone_normalized=phone)
                    .exists()
                )
                if existing_phone:
                    messages.error(request, 'An application with this phone number already exists for this position.')
                    return render(request, 'careers/apply.html', {'job': job, 'form': form})

            if file_hash and Resume.objects.filter(job=job, file_hash=file_hash, is_deleted=False).exists():
                messages.error(request, 'This resume has already been submitted for this position.')
                return render(request, 'careers/apply.html', {'job': job, 'form': form})

            resume = form.save(commit=False)
            resume.job = job
            resume.file_hash = file_hash
            resume.screening_status = 'processing'
            resume.save()

            from apps.core.tasks import screen_resume_task
            screen_resume_task.delay(resume.id)

            return redirect('core:careers_thanks', slug=job.slug)
        else:
            form_errors_to_messages(request, form)
    else:
        form = ResumeForm(require_contact=True)

    return render(request, 'careers/apply.html', {'job': job, 'form': form})


def careers_thanks(request, slug):
    """Confirmation shown after a candidate submits an application."""
    job = get_object_or_404(Job, slug=slug)
    return render(request, 'careers/thanks.html', {'job': job})


# ── User Management (superuser only) ────────────────────────────────────────

def _superuser_required(view_fn):
    """Decorator: must be logged in AND superuser."""
    @login_required
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, "You don't have permission to access user management.")
            return redirect('core:dashboard')
        return view_fn(request, *args, **kwargs)
    wrapped.__name__ = view_fn.__name__
    return wrapped


@_superuser_required
def user_list(request):
    users = User.objects.order_by('-is_superuser', '-is_active', 'username')
    return render(request, 'users/user_list.html', {'users': users})


@_superuser_required
def user_create(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        names_ok = _validate_user_name_fields(request)
        if form.is_valid() and names_ok:
            user = form.save(commit=False)
            user.is_staff = request.POST.get('is_staff') == 'on'
            user.is_superuser = request.POST.get('is_superuser') == 'on'
            user.email = request.POST.get('email', '')
            user.first_name = clean_person_text(request.POST.get('first_name', ''))
            user.last_name = clean_person_text(request.POST.get('last_name', ''))
            user.save()
            messages.success(request, f'User "{user.username}" created successfully.')
            return redirect('core:user_list')
        elif not form.is_valid():
            form_errors_to_messages(request, form)
    else:
        form = UserCreationForm()
    return render(request, 'users/user_form.html', {'form': form, 'action': 'Create'})


@_superuser_required
def user_change_password(request, pk):
    target = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        form = SetPasswordForm(target, request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f'Password for "{target.username}" changed successfully.')
            return redirect('core:user_list')
        else:
            form_errors_to_messages(request, form)
    else:
        form = SetPasswordForm(target)
    return render(request, 'users/user_password.html', {'form': form, 'target': target})


@_superuser_required
def user_toggle_active(request, pk):
    if request.method == 'POST':
        target = get_object_or_404(User, pk=pk)
        if target == request.user:
            messages.error(request, 'You cannot deactivate your own account.')
        else:
            target.is_active = not target.is_active
            target.save()
            state = 'activated' if target.is_active else 'deactivated'
            messages.success(request, f'User "{target.username}" has been {state}.')
    return redirect('core:user_list')


# ── Resume Notes ────────────────────────────────────────────────────────────

@login_required
def resume_note_add(request, uuid):
    resume = get_object_or_404(Resume, uuid=uuid)
    if request.method == 'POST':
        text = request.POST.get('text', '').strip()
        if text:
            from .models import ResumeNote
            ResumeNote.objects.create(resume=resume, author=request.user, text=text)
            messages.success(request, 'Note added.')
        else:
            messages.error(request, 'Note cannot be empty.')
    return redirect('core:resume_detail', uuid=uuid)


@login_required
def resume_note_delete(request, uuid, note_id):
    resume = get_object_or_404(Resume, uuid=uuid)
    from .models import ResumeNote
    note = get_object_or_404(ResumeNote, pk=note_id, resume=resume)
    if request.method == 'POST':
        note.delete()
        messages.success(request, 'Note deleted.')
    return redirect('core:resume_detail', uuid=uuid)


# ── Recruiter Status Update ──────────────────────────────────────────────────

@login_required
def resume_status_update(request, uuid):
    resume = get_object_or_404(Resume, uuid=uuid)
    if request.method == 'POST':
        new_status = request.POST.get('recruiter_status', '').strip()
        valid = {c[0] for c in Resume.RECRUITER_STATUS_CHOICES}
        if new_status in valid:
            resume.recruiter_status = new_status
            resume.save(update_fields=['recruiter_status'])
            messages.success(request, f'Status updated to "{resume.get_recruiter_status_display()}".')
        else:
            messages.error(request, 'Invalid status.')
    return redirect('core:resume_detail', uuid=uuid)


# ── Talent Pool ──────────────────────────────────────────────────────────────

@login_required
def talent_pool(request):
    from django.core.paginator import Paginator
    resumes_qs = (
        Resume.objects
        .filter(recommendation='talent_pool', is_deleted=False)
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


# ── Screening Failed ─────────────────────────────────────────────────────────

def _failed_resumes_queryset():
    """Resumes whose AI screening did not complete (live jobs only)."""
    return (
        Resume.objects
        .filter(screening_status='failed', is_deleted=False, job__is_deleted=False)
        .select_related('job')
        .order_by('-created_at')
    )


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

    # Atomically claim only rows still 'failed' so concurrent clicks can't
    # dispatch the same resume twice.
    Resume.objects.filter(id__in=ids, screening_status='failed').update(screening_status='processing')
    for rid in ids:
        screen_resume_task.delay(rid)

    n = len(ids)
    messages.success(
        request,
        f'AI screening re-queued for {n} candidate{"s" if n != 1 else ""}. Results will appear shortly.',
    )
    return redirect('core:screening_failed')


# ── CSV Export ───────────────────────────────────────────────────────────────

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
                r.candidate_name,
                r.email,
                r.phone,
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


from django.contrib.auth import views as auth_views  # noqa: E402


class ToastLoginView(auth_views.LoginView):
    """Login form errors surface as toasts (consistent with the rest of the app)."""

    template_name = 'auth/login.html'
    redirect_authenticated_user = True

    def form_invalid(self, form):
        form_errors_to_messages(self.request, form)
        return super().form_invalid(form)
