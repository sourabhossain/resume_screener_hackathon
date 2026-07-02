"""Audit Trail UI: superuser guard, filters, search, CSV safety, entity links."""
import csv
import io

import pytest
from django.urls import reverse

from apps.core.models import AuditLog, Job
from apps.core.views.audit import _entity_url


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
