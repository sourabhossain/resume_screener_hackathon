"""
Tests for REST API endpoints.
"""
import pytest
from django.urls import reverse
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
        # Should be soft deleted
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
        """Test retrieving single resume."""
        response = authenticated_client.get(f'/api/resumes/{sample_resume.pk}/')
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['candidate_name'] == sample_resume.candidate_name
    
    def test_delete_resume_soft_deletes(self, authenticated_client, sample_resume):
        """Test that DELETE performs soft delete."""
        response = authenticated_client.delete(f'/api/resumes/{sample_resume.pk}/')
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert Resume.objects.filter(pk=sample_resume.pk).count() == 0
        assert Resume.objects.all_with_deleted().filter(pk=sample_resume.pk).count() == 1


@pytest.mark.django_db
class TestAPIDocumentation:
    """Tests for API documentation endpoints."""
    
    def test_schema_endpoint(self, client):
        """Test OpenAPI schema endpoint is accessible."""
        response = client.get('/api/schema/')
        assert response.status_code == status.HTTP_200_OK
        # Schema returns OpenAPI format, check content instead of .json()
        assert b'openapi' in response.content
    
    def test_swagger_docs(self, client):
        """Test Swagger UI is accessible."""
        response = client.get('/api/docs/')
        assert response.status_code == status.HTTP_200_OK
    
    def test_redoc_docs(self, client):
        """Test ReDoc is accessible."""
        response = client.get('/api/redoc/')
        assert response.status_code == status.HTTP_200_OK
