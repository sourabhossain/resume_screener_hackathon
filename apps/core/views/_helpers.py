"""Shared helpers for the core views package (not URL-mapped themselves)."""
import logging

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.shortcuts import get_object_or_404, redirect

from ..form_utils import clean_person_text
from ..models import Resume

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

def _csv_safe(value):
    """
    Neutralize CSV/spreadsheet formula injection.

    Candidate-supplied fields (name/email/phone) flow into the CSV export. A
    value beginning with = + - @ (or a control char like tab/CR) is interpreted
    as a formula by Excel/LibreOffice when the recruiter opens the file, enabling
    data exfiltration or DDE command execution. Prefix such values with a single
    quote so they render as literal text.
    """
    if isinstance(value, str) and value and value[0] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + value
    return value

def _get_active_resume(uuid, *, select_job=True):
    """
    Fetch a non-deleted resume whose parent job is ALSO not deleted.

    Soft-deleting a Job does not cascade to its resumes, and Resume.objects only
    filters the resume's own is_deleted flag — so without the job__is_deleted
    guard a 'deleted' job's candidates would stay viewable, editable and
    re-screenable via their uuid URL. Every recruiter-facing resume lookup goes
    through here to keep delete semantics consistent.
    """
    qs = Resume.objects.filter(job__is_deleted=False)
    if select_job:
        qs = qs.select_related('job')
    return get_object_or_404(qs, uuid=uuid)

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
