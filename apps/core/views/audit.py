"""Superuser-only Audit Trail: paginated/filterable list + CSV export."""
import csv
from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Q
from django.http import StreamingHttpResponse
from django.shortcuts import render
from django.template.defaultfilters import date as date_filter
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
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


def _resolve_entities(rows):
    """Batch-resolve (entity_type, entity_id) -> (human label, detail URL or None).

    One query per entity type for the whole page (no per-row lookups). Uses
    all_objects/all_with_deleted so soft-deleted names still resolve, but only
    returns a URL when the object is live (mirroring _entity_url visibility).
    """
    from apps.interviews.models import Interview, InterviewEvaluation

    ids = {'resume': set(), 'job': set(), 'user': set(),
           'interview': set(), 'interview_evaluation': set()}
    for r in rows:
        if r.entity_type in ids and r.entity_id:
            ids[r.entity_type].add(r.entity_id)

    def _pks(values):
        return [v for v in values if v.isdigit()]

    resolved = {}

    for res in Resume.all_objects.filter(uuid__in=ids['resume']).select_related('job'):
        live = not res.is_deleted and not res.job.is_deleted
        url = reverse('core:resume_detail', kwargs={'uuid': res.uuid}) if live else None
        resolved[('resume', str(res.uuid))] = (res.candidate_name or str(res.uuid), url)

    for job in Job.all_objects.filter(slug__in=ids['job']):
        url = reverse('core:job_detail', kwargs={'slug': job.slug}) if not job.is_deleted else None
        resolved[('job', job.slug)] = (job.title or job.slug, url)

    for u in User.objects.filter(pk__in=_pks(ids['user'])):
        resolved[('user', str(u.pk))] = (u.username, None)

    for iv in Interview.all_objects.filter(pk__in=_pks(ids['interview'])).select_related('resume'):
        cand = iv.resume.candidate_name if iv.resume_id else ''
        label = f'Interview #{iv.pk}' + (f' · {cand}' if cand else '')
        url = reverse('interviews:detail', kwargs={'pk': iv.pk}) if not iv.is_deleted else None
        resolved[('interview', str(iv.pk))] = (label, url)

    for ev in (InterviewEvaluation.all_objects
               .filter(pk__in=_pks(ids['interview_evaluation']))
               .select_related('interview__resume')):
        cand = ev.interview.resume.candidate_name if ev.interview_id and ev.interview.resume_id else ''
        label = f'Interview #{ev.interview_id} · {cand}' if cand else f'Evaluation #{ev.pk}'
        resolved[('interview_evaluation', str(ev.pk))] = (label, None)

    return resolved


def _date_group_label(dt):
    """Group heading for a row's date: 'Today', 'Yesterday', else a formatted date."""
    today = timezone.localdate()
    d = timezone.localtime(dt).date()
    if d == today:
        return 'Today'
    if d == today - timedelta(days=1):
        return 'Yesterday'
    return date_filter(d, 'F j, Y')


@_superuser_required
def audit_log_list(request):
    qs = _filtered_audit_qs(request).order_by('-created_at')
    page_obj = Paginator(qs, 50).get_page(request.GET.get('page', 1))

    resolved = _resolve_entities(page_obj.object_list)
    prev_group = None
    for row in page_obj.object_list:
        label, url = resolved.get((row.entity_type, row.entity_id), (row.entity_id, None))
        row.entity_label = label
        row.entity_url = url
        group = _date_group_label(row.created_at)
        # Only stamp the heading when the day changes (a page boundary may split a day).
        row.date_group = group if group != prev_group else None
        prev_group = group

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

    # Human label appended as the LAST column so every existing raw column keeps
    # its position/value and the export stays machine-parseable.
    action_labels = dict(AuditLog.ACTION_CHOICES)

    def rows():
        yield ['Timestamp', 'Actor', 'Action', 'Entity Type', 'Entity ID',
               'Details', 'Request ID', 'Action Label']
        for row in qs.iterator():
            yield [
                row.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                _csv_safe(row.actor.username if row.actor else 'System'),
                _csv_safe(row.action),
                _csv_safe(row.entity_type),
                _csv_safe(row.entity_id),
                _csv_safe(row.details),
                _csv_safe(row.request_id or ''),
                _csv_safe(action_labels.get(row.action, row.action)),
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
