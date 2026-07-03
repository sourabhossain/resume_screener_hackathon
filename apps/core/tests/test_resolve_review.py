"""Tests for the needs-review resolve flow (resume_resolve_review):
assign a recruiter-chosen job family and re-screen with detection skipped."""
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.core.models import AuditLog, Resume


def _url(resume):
    return reverse('core:resume_resolve_review', kwargs={'uuid': resume.uuid})


@pytest.mark.django_db
class TestResolveReview:
    def _needs_review(self, resume, reason='Job family uncertain from the description'):
        resume.screening_status = 'needs_review'
        resume.reasoning = reason
        resume.save(update_fields=['screening_status', 'reasoning'])
        return resume

    def test_requires_login(self, client, sample_resume):
        self._needs_review(sample_resume)
        resp = client.post(_url(sample_resume), {'job_type': 'software_engineering'})
        assert resp.status_code == 302
        assert 'login' in resp.url

    def test_resolve_happy_path(self, authenticated_client, sample_resume):
        self._needs_review(sample_resume)
        with patch('apps.core.tasks.screen_resume_task.delay') as mock_delay:
            resp = authenticated_client.post(_url(sample_resume), {'job_type': 'software_engineering'})

        assert resp.status_code == 302
        sample_resume.refresh_from_db()
        assert sample_resume.screening_status == 'processing'
        # Task dispatched with the chosen family threaded through.
        mock_delay.assert_called_once_with(sample_resume.id, job_type='software_engineering')
        # Audit row records the chosen family in details.
        row = AuditLog.objects.get(action='resume.rescreen_requested',
                                   entity_id=str(sample_resume.uuid))
        assert 'software_engineering' in row.details

    def test_unknown_family_rejected(self, authenticated_client, sample_resume):
        self._needs_review(sample_resume)
        with patch('apps.core.tasks.screen_resume_task.delay') as mock_delay:
            resp = authenticated_client.post(_url(sample_resume), {'job_type': 'not_a_real_family'})

        assert resp.status_code == 302
        sample_resume.refresh_from_db()
        assert sample_resume.screening_status == 'needs_review'   # unchanged
        mock_delay.assert_not_called()
        assert not AuditLog.objects.filter(action='resume.rescreen_requested').exists()

    def test_rejected_when_not_needs_review(self, authenticated_client, sample_resume):
        sample_resume.screening_status = 'completed'
        sample_resume.save(update_fields=['screening_status'])
        with patch('apps.core.tasks.screen_resume_task.delay') as mock_delay:
            resp = authenticated_client.post(_url(sample_resume), {'job_type': 'software_engineering'})

        assert resp.status_code == 302
        sample_resume.refresh_from_db()
        assert sample_resume.screening_status == 'completed'      # untouched
        mock_delay.assert_not_called()

    def test_soft_deleted_resume_404(self, authenticated_client, sample_resume):
        self._needs_review(sample_resume)
        sample_resume.soft_delete()
        with patch('apps.core.tasks.screen_resume_task.delay') as mock_delay:
            resp = authenticated_client.post(_url(sample_resume), {'job_type': 'software_engineering'})

        assert resp.status_code == 404
        mock_delay.assert_not_called()

    def test_list_shows_resolve_control_and_reason(self, authenticated_client, sample_resume):
        self._needs_review(sample_resume, reason='Ambiguous title spanning two families')
        resp = authenticated_client.get(reverse('core:needs_review'))
        content = resp.content.decode()
        assert _url(sample_resume) in content                     # resolve control posts here
        assert 'Ambiguous title spanning two families' in content  # stored reason shown
        assert 'software_engineering' in content                   # a catalog option value
