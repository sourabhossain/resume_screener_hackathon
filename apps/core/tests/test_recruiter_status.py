"""
Tests for inline recruiter-status editing (resume_status_update).

Auth model here is the app's actual one (Option A): @login_required only, no
tenant/owner scoping — a recruiter may triage candidates on jobs they did not
post. See views.resume_status_update.
"""
import pytest
from django.urls import reverse

from apps.core.models import Job, Resume

HX = {'HTTP_HX_REQUEST': 'true'}


@pytest.mark.django_db
class TestRecruiterStatusUpdate:
    def _url(self, resume):
        return reverse('core:resume_status_update', args=[resume.uuid])

    def test_successful_status_change(self, authenticated_client, sample_resume):
        assert sample_resume.recruiter_status == 'new'
        before = sample_resume.updated_at

        response = authenticated_client.post(
            self._url(sample_resume), {'recruiter_status': 'shortlisted', 'context': 'cell'}, **HX
        )

        assert response.status_code == 200
        sample_resume.refresh_from_db()
        assert sample_resume.recruiter_status == 'shortlisted'
        # auto_now bumped because we passed it in update_fields
        assert sample_resume.updated_at > before
        assert b'Shortlisted' in response.content

    def test_invalid_status_rejected_with_400(self, authenticated_client, sample_resume):
        response = authenticated_client.post(
            self._url(sample_resume), {'recruiter_status': 'not_a_real_status'}, **HX
        )

        assert response.status_code == 400
        sample_resume.refresh_from_db()
        assert sample_resume.recruiter_status == 'new'

    def test_unauthenticated_request_rejected(self, client, sample_resume):
        response = client.post(
            self._url(sample_resume), {'recruiter_status': 'hired'}, **HX
        )

        assert response.status_code == 302
        assert 'login' in response.url
        sample_resume.refresh_from_db()
        assert sample_resume.recruiter_status == 'new'

    def test_non_owner_recruiter_may_update(self, client, django_user_model, sample_resume):
        """The job owner is the poster, not an ACL. A different logged-in
        recruiter must still be able to triage the candidate."""
        other = django_user_model.objects.create_user(
            username='other', email='other@example.com', password='pw12345678'
        )
        assert sample_resume.job.owner != other
        client.login(username='other', password='pw12345678')

        response = client.post(
            self._url(sample_resume), {'recruiter_status': 'interviewing', 'context': 'cell'}, **HX
        )

        assert response.status_code == 200
        sample_resume.refresh_from_db()
        assert sample_resume.recruiter_status == 'interviewing'

    def test_get_not_allowed(self, authenticated_client, sample_resume):
        response = authenticated_client.get(self._url(sample_resume))
        assert response.status_code == 405


@pytest.mark.django_db
class TestRecruiterStatusColumnQueries:
    """The Recruiter Status column reads only local Resume fields, so adding it
    must not introduce an N+1 on the pipeline table."""

    def _make_resumes(self, job, n):
        for i in range(n):
            Resume.objects.create(
                job=job,
                candidate_name=f'Cand {i}',
                recruiter_status='shortlisted',
                screening_status='completed',
                final_score=70 + i,
                skills_score=70, experience_score=70, education_score=70,
            )

    def _count(self, authenticated_client, job):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        url = reverse('core:job_detail', args=[job.slug])
        with CaptureQueriesContext(connection) as ctx:
            resp = authenticated_client.get(url)
            assert resp.status_code == 200
        return len(ctx.captured_queries)

    def test_no_n_plus_one_from_status_column(self, authenticated_client, sample_job):
        self._make_resumes(sample_job, 3)
        few = self._count(authenticated_client, sample_job)
        self._make_resumes(sample_job, 5)
        more = self._count(authenticated_client, sample_job)
        assert few == more, f'query count grew with rows: {few} -> {more} (N+1)'
