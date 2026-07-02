"""Superuser-only Audit Trail: paginated/filterable list + CSV export."""
import csv

from django.core.paginator import Paginator
from django.db.models import Q
from django.http import StreamingHttpResponse
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse
from django.utils.dateparse import parse_date

from ..models import AuditLog, Job, Resume
from ._helpers import User, _csv_safe, _superuser_required


def _filtered_audit_qs(request):
    """Apply the shared actor/action/date-range/search filters (used by list + CSV)."""
    qs = AuditLog.objects.select_related('actor')

    actor = request.GET.get('actor', '').strip()
    if actor == 'system':
        qs = qs.filter(actor__isnull=True)
    elif actor.isdigit():
        qs = qs.filter(actor_id=actor)

    action = request.GET.get('action', '').strip()
    if action:
        qs = qs.filter(action=action)

    date_from = parse_date(request.GET.get('from', '').strip())
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    date_to = parse_date(request.GET.get('to', '').strip())
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(details__icontains=q) | Q(entity_id__icontains=q))

    return qs


def _entity_url(entity_type, entity_id):
    """URL to the entity's detail page if it still exists and is visible, else None.

    Respects soft-delete visibility (a deleted job/resume/interview renders as plain
    text), mirroring the recruiter-facing lookup guards.
    """
    if not entity_id:
        return None
    try:
        if entity_type == 'resume':
            if Resume.objects.filter(uuid=entity_id, job__is_deleted=False).exists():
                return reverse('core:resume_detail', kwargs={'uuid': entity_id})
        elif entity_type == 'job':
            if Job.objects.filter(slug=entity_id, is_deleted=False).exists():
                return reverse('core:job_detail', kwargs={'slug': entity_id})
        elif entity_type == 'interview':
            from apps.interviews.models import Interview
            if Interview.objects.filter(pk=entity_id, is_deleted=False).exists():
                return reverse('interviews:detail', kwargs={'pk': entity_id})
    except (ValueError, NoReverseMatch):
        return None
    return None


@_superuser_required
def audit_log_list(request):
    qs = _filtered_audit_qs(request).order_by('-created_at')
    page_obj = Paginator(qs, 50).get_page(request.GET.get('page', 1))

    for row in page_obj.object_list:
        row.entity_url = _entity_url(row.entity_type, row.entity_id)

    querystring = request.GET.copy()
    querystring.pop('page', None)

    return render(request, 'core/audit_log.html', {
        'page_obj': page_obj,
        'actors': User.objects.filter(audit_logs__isnull=False).distinct().order_by('username'),
        'action_choices': AuditLog.ACTION_CHOICES,
        'querystring': querystring.urlencode(),
        'filters': {
            'actor': request.GET.get('actor', ''),
            'action': request.GET.get('action', ''),
            'from': request.GET.get('from', ''),
            'to': request.GET.get('to', ''),
            'q': request.GET.get('q', ''),
        },
    })


@_superuser_required
def audit_log_export_csv(request):
    qs = _filtered_audit_qs(request).order_by('-created_at')

    def rows():
        yield ['Timestamp', 'Actor', 'Action', 'Entity Type', 'Entity ID',
               'Details', 'Request ID']
        for row in qs.iterator():
            yield [
                row.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                _csv_safe(row.actor.username if row.actor else 'System'),
                _csv_safe(row.action),
                _csv_safe(row.entity_type),
                _csv_safe(row.entity_id),
                _csv_safe(row.details),
                _csv_safe(row.request_id or ''),
            ]

    class Echo:
        def write(self, value):
            return value

    writer = csv.writer(Echo())
    response = StreamingHttpResponse(
        (writer.writerow(row) for row in rows()),
        content_type='text/csv',
    )
    response['Content-Disposition'] = 'attachment; filename="audit_log.csv"'
    return response
