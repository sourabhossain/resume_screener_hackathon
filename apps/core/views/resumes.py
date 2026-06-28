"""Recruiter-facing Resume views: CRUD, bulk upload, rescreen, notes, status."""
import os

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render

from ..form_utils import clean_person_text, form_errors_to_messages
from ..forms import ResumeEditForm, ResumeForm
from ..models import Job, Resume
from ..utils import compute_file_hash
from ._helpers import _get_active_resume, _ordered_active_resumes_queryset, _pipeline_stats


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
            try:
                resume.save()
            except IntegrityError:
                # Lost the race against a concurrent identical upload; the unique
                # constraint (job, file_hash) fired. Show the same friendly
                # message as the .exists() pre-check instead of a 500.
                messages.error(request, 'This resume file has already been submitted for this job.')
                return render(request, 'core/resume_form.html', {'form': form, 'job': job, 'title': 'Add Resume'})

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
    resume = _get_active_resume(uuid)
    return render(request, 'core/resume_detail.html', {'resume': resume})


@login_required
def resume_edit(request, uuid):
    resume = _get_active_resume(uuid)
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
    resume = _get_active_resume(uuid)
    job_slug = resume.job.slug
    if request.method == 'POST':
        resume.soft_delete()
        messages.success(request, f'Resume for "{resume.candidate_name}" deleted successfully!')
        return redirect('core:job_detail', slug=job_slug)
    return render(request, 'core/confirm_delete.html', {'object': resume, 'type': 'resume', 'job_slug': job_slug})


@login_required
def resume_status_fragment(request, uuid):
    resume = _get_active_resume(uuid)
    # oob=True so the response also OOB-refreshes the header action button as
    # screening transitions (e.g. processing -> completed/failed).
    return render(request, 'core/partials/resume_status.html', {'resume': resume, 'oob': True})


@login_required
def resume_row_fragment(request, uuid):
    resume = _get_active_resume(uuid)
    ordered = _ordered_active_resumes_queryset(resume.job.resumes)
    # Recompute pipeline stats so the polling response can OOB-refresh the
    # "pending screening" badge as rows finish (otherwise it goes stale).
    pipeline_stats = _pipeline_stats(ordered)
    # Recover this row's rank (its 1-based position in the same ordering the full
    # table uses). The initial page render passes rank=forloop.counter; without
    # recomputing it here, a polled row would lose its rank badge once screening
    # completes and shows "—" until a full reload.
    ordered_ids = list(ordered.values_list('id', flat=True))
    try:
        rank = ordered_ids.index(resume.id) + 1
    except ValueError:
        rank = None
    return render(
        request,
        'core/partials/resume_row.html',
        {'resume': resume, 'rank': rank, 'pipeline_stats': pipeline_stats, 'is_fragment': True},
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
            raw_name = os.path.splitext(safe_basename)[0].replace('_', ' ').replace('-', ' ').strip()[:255]
            # Enforce the same character policy as the single-upload / careers form
            # (clean_person_text) so bulk ingestion can't store names the rest of the
            # app would reject (e.g. "<img src=x>"). Fall back to 'Unknown' on reject.
            try:
                candidate_name = clean_person_text(raw_name) or 'Unknown'
            except forms.ValidationError:
                candidate_name = 'Unknown'

            resume = Resume(
                job=job,
                candidate_name=candidate_name,
                file_name=safe_basename[:255],
                file_type=ext,
                file_hash=file_hash,
                screening_status='processing',
            )
            try:
                resume.file.save(safe_basename, file, save=True)
            except IntegrityError:
                # Same file uploaded twice within one batch (or concurrently);
                # the unique (job, file_hash) constraint fired. Skip gracefully.
                skipped.append(f'"{file.name}" - already submitted for this job')
                continue
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
    resume = _get_active_resume(uuid)

    if request.method != 'POST':
        return redirect('core:resume_detail', uuid=uuid)

    from apps.core.tasks import screen_resume_task

    # When the button is clicked via HTMX (the app is hx-boosted) we swap the
    # status region in place and DON'T redirect. A redirect back to this same
    # detail URL would make HTMX push a duplicate history entry every click,
    # forcing the user to press Back many times to reach the pipeline.
    is_htmx = bool(request.headers.get('HX-Request'))

    def _status_fragment():
        resume.refresh_from_db()
        return render(request, 'core/partials/resume_status.html', {'resume': resume, 'oob': True})

    # Atomic update prevents duplicate tasks from concurrent clicks. Also reset
    # the prior run's link-verification so the detail page doesn't show a stale
    # "verified" panel beside the new "screening in progress" spinner; the new
    # run re-queues verification on completion.
    updated = Resume.objects.filter(
        uuid=uuid, screening_status__in=['pending', 'completed', 'failed', 'needs_review']
    ).update(
        screening_status='processing',
        verification_status='pending',
        verification_results={},
        verification_score=None,
        verified_at=None,
    )

    if not updated:
        if is_htmx:
            # Already running — just reflect current state in place, no toast.
            return _status_fragment()
        messages.info(request, 'Screening is already in progress. Please wait for it to complete.')
        return redirect('core:resume_detail', uuid=uuid)

    screen_resume_task.delay(resume.id)

    if is_htmx:
        return _status_fragment()
    messages.success(request, 'AI screening queued! Results will appear shortly.')
    return redirect('core:resume_detail', uuid=uuid)


@login_required
def resume_note_add(request, uuid):
    resume = _get_active_resume(uuid, select_job=False)
    if request.method == 'POST':
        text = request.POST.get('text', '').strip()
        if text:
            from ..models import ResumeNote
            ResumeNote.objects.create(resume=resume, author=request.user, text=text)
            messages.success(request, 'Note added.')
        else:
            messages.error(request, 'Note cannot be empty.')
    return redirect('core:resume_detail', uuid=uuid)


@login_required
def resume_note_delete(request, uuid, note_id):
    resume = _get_active_resume(uuid, select_job=False)
    from ..models import ResumeNote
    note = get_object_or_404(ResumeNote, pk=note_id, resume=resume)
    if request.method == 'POST':
        note.delete()
        messages.success(request, 'Note deleted.')
    return redirect('core:resume_detail', uuid=uuid)


@login_required
def resume_status_update(request, uuid):
    resume = _get_active_resume(uuid, select_job=False)
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
