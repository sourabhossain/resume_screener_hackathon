"""Audit Trail UI: superuser guard, filters, search, CSV safety, entity links."""
import csv
import io

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.core.models import AuditLog, Job, Resume
from apps.core.templatetags.audit_extras import audit_badge, audit_category, audit_details
from apps.core.views.audit import _date_group_label, _entity_url


@pytest.fixture
def superuser_client(client, django_user_model):
    django_user_model.objects.create_superuser(
        username='root', email='root@example.com', password='rootpass123'
    )
    client.login(username='root', password='rootpass123')
    return client


@pytest.mark.django_db
class TestAuditAccess:
    def test_anonymous_redirected_to_login(self, client):
        resp = client.get(reverse('core:audit_log'))
        assert resp.status_code == 302
        assert 'login' in resp.url

    def test_regular_user_denied(self, authenticated_client):
        resp = authenticated_client.get(reverse('core:audit_log'))
        assert resp.status_code == 302
        assert reverse('core:dashboard') in resp.url

    def test_superuser_allowed(self, superuser_client):
        resp = superuser_client.get(reverse('core:audit_log'))
        assert resp.status_code == 200


@pytest.mark.django_db
class TestAuditFilters:
    def test_filter_by_action(self, superuser_client):
        AuditLog.objects.create(action='job.created', entity_type='job', entity_id='a')
        AuditLog.objects.create(action='resume.deleted', entity_type='resume', entity_id='b')
        resp = superuser_client.get(reverse('core:audit_log'), {'action': 'job.created'})
        rows = list(resp.context['page_obj'])
        assert len(rows) == 1 and rows[0].action == 'job.created'

    def test_filter_by_actor_system(self, superuser_client, user):
        AuditLog.objects.create(actor=user, action='job.created', entity_type='job', entity_id='a')
        AuditLog.objects.create(actor=None, action='job.auto_closed', entity_type='job', entity_id='b')
        resp = superuser_client.get(reverse('core:audit_log'), {'actor': 'system'})
        rows = list(resp.context['page_obj'])
        assert len(rows) == 1 and rows[0].actor is None

    def test_search_over_details(self, superuser_client):
        AuditLog.objects.create(action='job.created', entity_type='job', entity_id='a',
                                details='title=Needle Engineer')
        AuditLog.objects.create(action='job.created', entity_type='job', entity_id='b',
                                details='title=Other Role')
        resp = superuser_client.get(reverse('core:audit_log'), {'q': 'Needle'})
        rows = list(resp.context['page_obj'])
        assert len(rows) == 1 and 'Needle' in rows[0].details

    def test_search_over_entity_id(self, superuser_client):
        AuditLog.objects.create(action='job.created', entity_type='job', entity_id='unique-slug-xyz')
        AuditLog.objects.create(action='job.created', entity_type='job', entity_id='another')
        resp = superuser_client.get(reverse('core:audit_log'), {'q': 'unique-slug'})
        rows = list(resp.context['page_obj'])
        assert len(rows) == 1

    def test_invalid_date_is_ignored(self, superuser_client):
        AuditLog.objects.create(action='job.created', entity_type='job', entity_id='a')
        resp = superuser_client.get(reverse('core:audit_log'), {'from': 'not-a-date'})
        assert resp.status_code == 200
        assert len(list(resp.context['page_obj'])) == 1


@pytest.mark.django_db
class TestAuditEntityLinks:
    def test_live_job_links_to_detail(self, superuser_client, sample_job):
        AuditLog.objects.create(action='job.created', entity_type='job', entity_id=sample_job.slug)
        resp = superuser_client.get(reverse('core:audit_log'))
        assert reverse('core:job_detail', kwargs={'slug': sample_job.slug}).encode() in resp.content

    def test_deleted_job_renders_plain_text(self, superuser_client, sample_job):
        AuditLog.objects.create(action='job.deleted', entity_type='job', entity_id=sample_job.slug)
        sample_job.soft_delete()
        assert _entity_url('job', sample_job.slug) is None
        resp = superuser_client.get(reverse('core:audit_log'))
        assert reverse('core:job_detail', kwargs={'slug': sample_job.slug}).encode() not in resp.content

    def test_live_resume_links(self, sample_resume):
        assert _entity_url('resume', str(sample_resume.uuid)) == \
            reverse('core:resume_detail', kwargs={'uuid': sample_resume.uuid})

    def test_resume_under_deleted_job_no_link(self, sample_resume):
        sample_resume.job.soft_delete()
        assert _entity_url('resume', str(sample_resume.uuid)) is None


@pytest.mark.django_db
class TestAuditCsvExport:
    def _read(self, resp):
        body = b''.join(resp.streaming_content).decode()
        return list(csv.reader(io.StringIO(body)))

    def test_export_requires_superuser(self, authenticated_client):
        resp = authenticated_client.get(reverse('core:audit_log_export'))
        assert resp.status_code == 302

    def test_export_returns_rows(self, superuser_client):
        AuditLog.objects.create(action='job.created', entity_type='job', entity_id='a', details='x')
        resp = superuser_client.get(reverse('core:audit_log_export'))
        assert resp.status_code == 200
        rows = self._read(resp)
        assert rows[0][0] == 'Timestamp'
        assert len(rows) == 2

    def test_export_neutralizes_formula_injection(self, superuser_client):
        AuditLog.objects.create(action='resume.uploaded', entity_type='resume', entity_id='u',
                                details='=HYPERLINK("http://evil.example","x")')
        resp = superuser_client.get(reverse('core:audit_log_export'))
        rows = self._read(resp)
        details_cell = rows[1][5]
        assert not details_cell.startswith(('=', '+', '-', '@')), details_cell

    def test_export_adds_action_label_column_without_shifting_raw_columns(self, superuser_client):
        AuditLog.objects.create(action='job.created', entity_type='job', entity_id='a', details='x')
        resp = superuser_client.get(reverse('core:audit_log_export'))
        rows = self._read(resp)
        # Raw columns keep their positions; human label is appended last.
        assert rows[0] == ['Timestamp', 'Actor', 'Action', 'Entity Type', 'Entity ID',
                           'Details', 'Request ID', 'Action Label']
        assert rows[1][2] == 'job.created'      # raw action unchanged
        assert rows[1][7] == 'Job created'      # appended human label


@pytest.mark.django_db
class TestAuditIdColumn:
    """The row id is dropped from the on-screen table but kept in the CSV/data-attr."""

    def test_id_not_shown_as_table_column(self, superuser_client):
        row = AuditLog.objects.create(action='job.created', entity_type='job', entity_id='a')
        resp = superuser_client.get(reverse('core:audit_log'))
        html = resp.content.decode()
        # No visible '#<pk>' id cell, and no 'ID' column header.
        assert f'#{row.pk}' not in html
        assert '>ID</th>' not in html

    def test_id_present_as_data_attribute(self, superuser_client):
        row = AuditLog.objects.create(action='job.created', entity_type='job', entity_id='a')
        resp = superuser_client.get(reverse('core:audit_log'))
        assert f'data-audit-id="{row.pk}"' in resp.content.decode()

    def test_csv_export_still_carries_the_record(self, superuser_client):
        """The machine-readable export is unchanged: its Entity ID column stays."""
        AuditLog.objects.create(action='job.created', entity_type='job', entity_id='slug-a')
        resp = superuser_client.get(reverse('core:audit_log_export'))
        rows = list(csv.reader(io.StringIO(b''.join(resp.streaming_content).decode())))
        assert 'Entity ID' in rows[0]
        assert 'slug-a' in rows[1]


@pytest.mark.django_db
class TestAuditPagination:
    def _make_rows(self, n, action='job.created'):
        for i in range(n):
            AuditLog.objects.create(action=action, entity_type='job', entity_id=f'slug-{i}')

    def test_page_two_returns_next_slice(self, superuser_client):
        self._make_rows(60)
        p1 = superuser_client.get(reverse('core:audit_log'), {'page': 1})
        p2 = superuser_client.get(reverse('core:audit_log'), {'page': 2})
        pks1 = {r.pk for r in p1.context['page_obj']}
        pks2 = {r.pk for r in p2.context['page_obj']}
        assert len(pks1) == 50
        assert len(pks2) == 10
        assert pks1.isdisjoint(pks2)             # a genuine next slice, no overlap
        assert len(pks1 | pks2) == 60

    def test_links_preserve_active_action_filter(self, superuser_client):
        self._make_rows(60, action='job.created')
        self._make_rows(5, action='resume.deleted')
        resp = superuser_client.get(reverse('core:audit_log'), {'action': 'job.created'})
        assert resp.context['querystring'] == 'action=job.created'
        html = resp.content.decode()
        # The Next / page links carry the filter alongside the page param.
        assert 'page=2&action=job.created' in html
        # Only the 60 filtered rows paginate (2 pages), not the resume.deleted ones.
        assert resp.context['page_obj'].paginator.count == 60

    def test_summary_line_shows_correct_range(self, superuser_client):
        self._make_rows(60)
        resp = superuser_client.get(reverse('core:audit_log'), {'page': 2})
        html = resp.content.decode()
        assert 'Showing' in html
        page_obj = resp.context['page_obj']
        assert page_obj.start_index() == 51
        assert page_obj.end_index() == 60
        assert page_obj.paginator.count == 60
        assert '>51</span>' in html and '>60</span>' in html

    def test_single_page_renders_no_controls(self, superuser_client):
        self._make_rows(10)
        resp = superuser_client.get(reverse('core:audit_log'))
        html = resp.content.decode()
        assert 'aria-label="Pagination"' not in html   # no prev/next/page controls
        assert 'Showing' in html                        # summary still present

    def test_ellipsis_range_present_for_many_pages(self, superuser_client):
        self._make_rows(50 * 12)     # 12 pages
        resp = superuser_client.get(reverse('core:audit_log'), {'page': 6})
        page_range = resp.context['page_range']
        assert resp.context['ellipsis'] in page_range   # truncated with an ellipsis
        assert 1 in page_range and 12 in page_range      # first and last always shown


# --------------------------------------------------------------- polish helpers
class TestBadgeCategory:
    @pytest.mark.parametrize('action,expected', [
        ('job.deleted', 'destructive'),
        ('user.deactivated', 'destructive'),
        ('resume.score_overridden', 'override'),
        ('resume.rescreen_requested', 'override'),
        ('job.created', 'creation'),
        ('user.activated', 'creation'),
        ('resume.screening_completed', 'system'),
        ('job.auto_closed', 'system'),
        ('job.updated', 'neutral'),
        ('interview.evaluation_submitted', 'neutral'),
        ('job.restored', 'neutral'),
    ])
    def test_category_mapping(self, action, expected):
        assert audit_category(action) == expected

    def test_badge_returns_dark_mode_classes(self):
        cls = audit_badge('job.deleted')
        assert 'bg-red-100' in cls and 'dark:' in cls


class TestDateGroupLabel:
    def test_today_yesterday_and_older(self):
        from datetime import timedelta
        from django.utils import timezone
        now = timezone.now()
        assert _date_group_label(now) == 'Today'
        assert _date_group_label(now - timedelta(days=1)) == 'Yesterday'
        assert _date_group_label(now - timedelta(days=30)) not in ('Today', 'Yesterday')


class TestDetailsFilter:
    def test_key_value_pairs_readable(self):
        assert audit_details('old=85 new=42') == 'old: 85 new: 42'

    def test_value_with_spaces_preserved(self):
        assert audit_details('old=85 new=42 reason=panel debrief') == \
            'old: 85 new: 42 reason: panel debrief'

    def test_arbitrary_text_passes_through_unchanged(self):
        assert audit_details('just some free text') == 'just some free text'

    def test_empty_is_blank(self):
        assert audit_details('') == ''

    def test_uuid_is_truncated_with_full_value_in_tooltip(self):
        full = '84694ebc-1111-2222-3333-444455556666'
        out = audit_details(f'resume={full}')
        assert '84694ebc…' in out              # truncated to first 8 chars
        assert f'title="{full}"' in out         # full value kept in the tooltip
        assert full not in out.replace(f'title="{full}"', '')   # not shown inline

    def test_non_uuid_content_is_escaped(self):
        # Details are untrusted; any HTML in them must be escaped, not rendered.
        out = audit_details('note=<script>alert(1)</script>')
        assert '<script>' not in out
        assert '&lt;script&gt;' in out


@pytest.mark.django_db
class TestEntityLabels:
    def test_resume_row_shows_candidate_name(self, superuser_client, sample_resume):
        AuditLog.objects.create(action='resume.uploaded', entity_type='resume',
                                entity_id=str(sample_resume.uuid))
        resp = superuser_client.get(reverse('core:audit_log'))
        row = list(resp.context['page_obj'])[0]
        assert row.entity_label == sample_resume.candidate_name
        assert row.entity_url is not None

    def test_deleted_resume_still_resolves_name_but_no_link(self, superuser_client, sample_resume):
        AuditLog.objects.create(action='resume.deleted', entity_type='resume',
                                entity_id=str(sample_resume.uuid))
        sample_resume.soft_delete()
        resp = superuser_client.get(reverse('core:audit_log'))
        row = list(resp.context['page_obj'])[0]
        assert row.entity_label == 'John Doe'   # resolved via all_objects
        assert row.entity_url is None

    def test_unresolvable_entity_falls_back_to_identifier(self, superuser_client):
        AuditLog.objects.create(action='resume.uploaded', entity_type='resume',
                                entity_id='11111111-1111-1111-1111-111111111111')
        resp = superuser_client.get(reverse('core:audit_log'))
        assert list(resp.context['page_obj'])[0].entity_label == \
            '11111111-1111-1111-1111-111111111111'

    def test_job_label_is_title(self, superuser_client, sample_job):
        AuditLog.objects.create(action='job.created', entity_type='job', entity_id=sample_job.slug)
        resp = superuser_client.get(reverse('core:audit_log'))
        assert list(resp.context['page_obj'])[0].entity_label == sample_job.title

    def test_unknown_candidate_name_falls_back_to_job_title(self, superuser_client, sample_job):
        res = Resume.objects.create(job=sample_job, candidate_name='Unknown', final_score=50)
        AuditLog.objects.create(action='resume.uploaded', entity_type='resume',
                                entity_id=str(res.uuid))
        resp = superuser_client.get(reverse('core:audit_log'))
        label = list(resp.context['page_obj'])[0].entity_label
        assert label == sample_job.title       # never the literal 'Unknown'
        assert label != 'Unknown'

    def test_empty_candidate_name_shows_unnamed_placeholder(self, superuser_client, sample_job):
        # candidate_name empty AND job with no title -> '(unnamed candidate)'.
        job = Job.objects.create(owner=sample_job.owner, title='', description='x', status='active')
        res = Resume.objects.create(job=job, candidate_name='', final_score=50)
        AuditLog.objects.create(action='resume.uploaded', entity_type='resume',
                                entity_id=str(res.uuid))
        resp = superuser_client.get(reverse('core:audit_log'))
        assert list(resp.context['page_obj'])[0].entity_label == '(unnamed candidate)'

    def test_evaluation_label_is_numbered_with_interviewer(self, superuser_client, sample_resume):
        from datetime import date

        from apps.interviews.models import Interview, InterviewEvaluation
        interview = Interview.objects.create(resume=sample_resume, scheduled_date=date(2020, 1, 1))
        ev = InterviewEvaluation.objects.create(interview=interview, interviewer_name='Jane Smith')
        AuditLog.objects.create(action='interview.evaluation_submitted',
                                entity_type='interview_evaluation', entity_id=str(ev.pk))
        resp = superuser_client.get(reverse('core:audit_log'))
        label = list(resp.context['page_obj'])[0].entity_label
        assert label == f'Evaluation #{ev.pk} · Jane Smith'

    def test_entity_resolution_has_no_n_plus_1(self, superuser_client, sample_job):
        """Query count for the list view must not grow with the number of rows."""
        def make_rows(n, start):
            for i in range(start, start + n):
                r = Resume.objects.create(job=sample_job, candidate_name=f'Cand {i}', final_score=50)
                AuditLog.objects.create(action='resume.uploaded', entity_type='resume',
                                        entity_id=str(r.uuid))

        def count_queries():
            with CaptureQueriesContext(connection) as ctx:
                superuser_client.get(reverse('core:audit_log'))
            return len(ctx)

        make_rows(3, 0)
        count_queries()          # warm up (content types, etc.)
        small = count_queries()
        make_rows(12, 100)       # 4x the rows
        large = count_queries()
        assert small == large, f'query count grew with rows: {small} -> {large}'
