"""
Tests for REST API endpoints.
"""
import pytest
from rest_framework import status
from apps.core.models import Job, Resume

@pytest.mark.django_db
class TestJobAPI:
    """Tests for Job ViewSet API."""
    
    def test_list_jobs_requires_auth(self, client):
        """Test that job list requires authentication."""
        response = client.get('/api/jobs/')
        assert response.status_code == status.HTTP_403_FORBIDDEN
    
    def test_list_jobs_authenticated(self, authenticated_client, sample_job):
        """Test listing jobs when authenticated."""
        response = authenticated_client.get('/api/jobs/')
        assert response.status_code == status.HTTP_200_OK
        assert 'results' in response.json()
    
    def test_create_job(self, authenticated_client):
        """Test creating a job via API."""
        data = {
            'title': 'API Test Job',
            'description': 'Created via API test',
            'status': 'draft'
        }
        response = authenticated_client.post(
            '/api/jobs/',
            data=data,
            content_type='application/json'
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert Job.objects.filter(title='API Test Job').exists()
    
    def test_retrieve_job(self, authenticated_client, sample_job):
        """Test retrieving single job."""
        response = authenticated_client.get(f'/api/jobs/{sample_job.pk}/')
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['title'] == sample_job.title
    
    def test_update_job(self, authenticated_client, sample_job):
        """Test updating a job."""
        data = {
            'title': 'Updated API Job',
            'description': sample_job.description,
            'status': sample_job.status
        }
        response = authenticated_client.put(
            f'/api/jobs/{sample_job.pk}/',
            data=data,
            content_type='application/json'
        )
        assert response.status_code == status.HTTP_200_OK
        sample_job.refresh_from_db()
        assert sample_job.title == 'Updated API Job'
    
    def test_delete_job_soft_deletes(self, authenticated_client, sample_job):
        """Test that DELETE performs soft delete."""
        response = authenticated_client.delete(f'/api/jobs/{sample_job.pk}/')
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert Job.objects.filter(pk=sample_job.pk).count() == 0
        assert Job.objects.all_with_deleted().filter(pk=sample_job.pk).count() == 1
    
    def test_filter_by_status(self, authenticated_client, sample_job):
        """Test filtering jobs by status."""
        Job.objects.create(title='Draft Job', status='draft')
        
        response = authenticated_client.get('/api/jobs/', {'status': 'active'})
        assert response.status_code == status.HTTP_200_OK
        results = response.json()['results']
        assert len(results) == 1
        assert results[0]['status'] == 'active'
    
    def test_search_jobs(self, authenticated_client, sample_job):
        """Test searching jobs."""
        response = authenticated_client.get('/api/jobs/', {'search': 'Python'})
        assert response.status_code == status.HTTP_200_OK
        results = response.json()['results']
        assert len(results) == 1

@pytest.mark.django_db
class TestResumeAPI:
    """Tests for Resume ViewSet API."""
    
    def test_list_resumes_requires_auth(self, client):
        """Test that resume list requires authentication."""
        response = client.get('/api/resumes/')
        assert response.status_code == status.HTTP_403_FORBIDDEN
    
    def test_list_resumes_authenticated(self, authenticated_client, sample_resume):
        """Test listing resumes when authenticated."""
        response = authenticated_client.get('/api/resumes/')
        assert response.status_code == status.HTTP_200_OK
        assert 'results' in response.json()
    
    def test_filter_by_job(self, authenticated_client, sample_job, sample_resume):
        """Test filtering resumes by job."""
        response = authenticated_client.get('/api/resumes/', {'job': sample_job.pk})
        assert response.status_code == status.HTTP_200_OK
        results = response.json()['results']
        assert len(results) == 1
    
    def test_filter_by_tier(self, authenticated_client, sample_resume):
        """Test filtering resumes by tier."""
        sample_resume.tier = 'top'
        sample_resume.save()
        
        response = authenticated_client.get('/api/resumes/', {'tier': 'top'})
        assert response.status_code == status.HTTP_200_OK
        results = response.json()['results']
        assert len(results) >= 1
    
    def test_retrieve_resume(self, authenticated_client, sample_resume):
        """Test retrieving single resume by its opaque uuid (not the sequential pk)."""
        response = authenticated_client.get(f'/api/resumes/{sample_resume.uuid}/')
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['candidate_name'] == sample_resume.candidate_name

    def test_retrieve_resume_by_pk_is_404(self, authenticated_client, sample_resume):
        """Sequential-id enumeration is closed: detail routes are uuid-only."""
        response = authenticated_client.get(f'/api/resumes/{sample_resume.pk}/')
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_resume_soft_deletes(self, authenticated_client, sample_resume):
        """Test that DELETE performs soft delete (addressed by uuid)."""
        response = authenticated_client.delete(f'/api/resumes/{sample_resume.uuid}/')
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert Resume.objects.filter(pk=sample_resume.pk).count() == 0
        assert Resume.objects.all_with_deleted().filter(pk=sample_resume.pk).count() == 1

    def test_create_resume(self, authenticated_client, sample_job, monkeypatch):
        """A resume can be created via the API and is linked to its job."""
        from apps.core import tasks

        dispatched = []
        monkeypatch.setattr(tasks.screen_resume_task, 'delay', lambda rid: dispatched.append(rid))

        response = authenticated_client.post('/api/resumes/', {
            'job': sample_job.pk,
            'candidate_name': 'API Candidate',
            'email': 'api.candidate@example.com',
        })
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body['job'] == sample_job.pk
        assert body['candidate_name'] == 'API Candidate'

        resume = Resume.objects.get(pk=body['id'])
        assert resume.job_id == sample_job.pk
        assert resume.screening_status == 'processing'
        assert dispatched == [resume.id]

    def test_create_resume_requires_job(self, authenticated_client, monkeypatch):
        """Creating a resume without a job is rejected (400), not a 500 crash."""
        from apps.core import tasks
        monkeypatch.setattr(tasks.screen_resume_task, 'delay', lambda rid: None)

        response = authenticated_client.post('/api/resumes/', {'candidate_name': 'No Job'})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'job' in response.json()

    def test_patch_score_fields_are_read_only(self, authenticated_client, sample_resume):
        """Scores are AI-derived and read-only on the API. DRF silently drops
        read-only fields, so a PATCH leaves every score unchanged -- the
        mandatory-reason override control cannot be bypassed via the API."""
        score_fields = ['final_score', 'experience_score', 'education_score',
                        'skills_score', 'certification_score', 'achievement_score']
        before = {f: getattr(sample_resume, f) for f in score_fields}

        response = authenticated_client.patch(
            f'/api/resumes/{sample_resume.uuid}/',
            data={'final_score': 1, 'experience_score': 2, 'education_score': 3,
                  'skills_score': 4, 'certification_score': 5, 'achievement_score': 6},
            content_type='application/json',
        )
        # DRF ignores read-only fields rather than erroring -> 200, values persist.
        assert response.status_code == status.HTTP_200_OK
        sample_resume.refresh_from_db()
        for field, original in before.items():
            assert getattr(sample_resume, field) == original, field

    def test_patch_writable_field_still_works(self, authenticated_client, sample_resume):
        """Making scores read-only must not lock the whole resource: a
        legitimately-writable field can still be updated via PATCH."""
        response = authenticated_client.patch(
            f'/api/resumes/{sample_resume.uuid}/',
            data={'candidate_name': 'Renamed Via API'},
            content_type='application/json',
        )
        assert response.status_code == status.HTTP_200_OK
        sample_resume.refresh_from_db()
        assert sample_resume.candidate_name == 'Renamed Via API'

    def test_api_score_patch_writes_no_override_audit(self, authenticated_client, sample_resume):
        """An API attempt to change a score must not produce a
        resume.score_overridden audit row (it never reaches the override path)."""
        from apps.core.models import AuditLog

        authenticated_client.patch(
            f'/api/resumes/{sample_resume.uuid}/',
            data={'final_score': 1},
            content_type='application/json',
        )
        assert not AuditLog.objects.filter(action='resume.score_overridden').exists()

@pytest.mark.django_db
class TestAPIDocumentation:
    """Tests for API documentation endpoints."""

    def test_schema_requires_auth(self, client):
        response = client.get('/api/schema/')
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_swagger_requires_auth(self, client):
        response = client.get('/api/docs/')
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_redoc_requires_auth(self, client):
        response = client.get('/api/redoc/')
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_schema_endpoint(self, authenticated_client):
        response = authenticated_client.get('/api/schema/')
        assert response.status_code == status.HTTP_200_OK
        assert b'openapi' in response.content

    def test_swagger_docs(self, authenticated_client):
        response = authenticated_client.get('/api/docs/')
        assert response.status_code == status.HTTP_200_OK

    def test_redoc_docs(self, authenticated_client):
        response = authenticated_client.get('/api/redoc/')
        assert response.status_code == status.HTTP_200_OK
