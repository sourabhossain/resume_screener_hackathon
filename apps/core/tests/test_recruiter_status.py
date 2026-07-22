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
        # recruiter_status=all so the shortlisted rows actually render — the
        # default 'new' filter would hide them and trivialise the guard.
        url = reverse('core:job_detail', args=[job.slug]) + '?recruiter_status=all'
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


@pytest.mark.django_db
class TestRecruiterStatusFilter:
    """Pipeline table filter on job_detail / pipeline_search. Defaults to the
    untriaged ('new') queue; 'all' shows everyone."""

    @pytest.fixture
    def mixed_resumes(self, sample_job):
        new = Resume.objects.create(
            job=sample_job, candidate_name='Newton Fresh',
            screening_status='completed', final_score=60,
        )
        shortlisted = Resume.objects.create(
            job=sample_job, candidate_name='Shorty Listed',
            recruiter_status='shortlisted',
            screening_status='completed', final_score=80,
        )
        return new, shortlisted

    def _detail(self, client, job, query=''):
        return client.get(reverse('core:job_detail', args=[job.slug]) + query)

    def test_default_shows_only_new(self, authenticated_client, sample_job, mixed_resumes):
        response = self._detail(authenticated_client, sample_job)
        assert response.status_code == 200
        assert b'Newton Fresh' in response.content
        assert b'Shorty Listed' not in response.content

    def test_all_shows_everyone(self, authenticated_client, sample_job, mixed_resumes):
        response = self._detail(authenticated_client, sample_job, '?recruiter_status=all')
        assert b'Newton Fresh' in response.content
        assert b'Shorty Listed' in response.content

    def test_specific_status_filters(self, authenticated_client, sample_job, mixed_resumes):
        response = self._detail(authenticated_client, sample_job, '?recruiter_status=shortlisted')
        assert b'Shorty Listed' in response.content
        assert b'Newton Fresh' not in response.content

    def test_invalid_value_falls_back_to_new(self, authenticated_client, sample_job, mixed_resumes):
        response = self._detail(authenticated_client, sample_job, '?recruiter_status=bogus')
        assert response.status_code == 200
        assert b'Newton Fresh' in response.content
        assert b'Shorty Listed' not in response.content

    def test_stats_cards_ignore_filter(self, authenticated_client, sample_job, mixed_resumes):
        response = self._detail(authenticated_client, sample_job)
        assert response.context['pipeline_stats']['total'] == 2

    def test_filtered_empty_state_keeps_table(self, authenticated_client, sample_job, mixed_resumes):
        response = self._detail(authenticated_client, sample_job, '?recruiter_status=hired')
        assert response.status_code == 200
        assert b'No candidates with this recruiter status' in response.content
        assert b'No applicants yet' not in response.content

    def test_pipeline_search_respects_filter(self, authenticated_client, sample_job, mixed_resumes):
        url = reverse('core:pipeline_search', args=[sample_job.slug])
        response = authenticated_client.get(url, {'q': 'o', 'recruiter_status': 'shortlisted'})
        assert b'Shorty Listed' in response.content
        assert b'Newton Fresh' not in response.content

    def test_pipeline_search_all(self, authenticated_client, sample_job, mixed_resumes):
        url = reverse('core:pipeline_search', args=[sample_job.slug])
        response = authenticated_client.get(url, {'q': '', 'recruiter_status': 'all'})
        assert b'Newton Fresh' in response.content
        assert b'Shorty Listed' in response.content
