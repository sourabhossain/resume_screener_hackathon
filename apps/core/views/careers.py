"""Public candidate (careers) pages — NO login required.

Candidates browse open jobs and submit their resume; they never see results.
"""
import re

from django.contrib import messages
from django.db import IntegrityError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django_ratelimit.decorators import ratelimit

from ..form_utils import form_errors_to_messages
from ..forms import ResumeForm
from ..models import Job, Resume
from ..utils import compute_file_hash

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

    suggestions = list(jobs_qs[:6]) if search_query else []

    page_obj = Paginator(jobs_qs, 12).get_page(request.GET.get('page', 1))

    context = {
        'jobs': page_obj,
        'page_obj': page_obj,
        'search_query': search_query,
        'suggestions': suggestions,
    }

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
        form = ResumeForm(request.POST, request.FILES, require_contact=True)
        if form.is_valid():
            email = form.cleaned_data.get('email', '').strip().lower()
            phone = re.sub(r'[\s\-()]+', '', form.cleaned_data.get('phone', ''))
            uploaded_file = request.FILES.get('file')
            file_hash = compute_file_hash(uploaded_file) if uploaded_file else ''

            if email and Resume.objects.filter(job=job, email__iexact=email, is_deleted=False).exists():
                messages.error(request, 'An application with this email address already exists for this position.')
                return render(request, 'careers/apply.html', {'job': job, 'form': form})

            if phone:
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
            try:
                resume.save()
            except IntegrityError:
                messages.error(request, 'This resume has already been submitted for this position.')
                return render(request, 'careers/apply.html', {'job': job, 'form': form})

            from apps.core.tasks import screen_resume_task
            screen_resume_task.delay(resume.id)

            from ..services import audit_log
            audit_log(None, 'resume.uploaded', resume,
                      details=f'candidate={resume.candidate_name} job={job.slug} public', request=request)
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
