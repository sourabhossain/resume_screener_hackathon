"""
Unit tests for Job and Resume models.
"""
import pytest
from apps.core.models import Job, Resume

@pytest.mark.django_db
class TestJobModel:
    """Tests for Job model."""
    
    def test_job_creation(self):
        """Test creating a job with basic fields."""
        job = Job.objects.create(
            title='Software Engineer',
            description='Full stack developer position',
            status='active'
        )
        assert job.pk is not None
        assert job.title == 'Software Engineer'
        assert job.status == 'active'
        assert job.is_deleted is False
    
    def test_job_str_method(self):
        """Test the __str__ method returns title."""
        job = Job.objects.create(title='Data Scientist')
        assert str(job) == 'Data Scientist'
    
    def test_job_soft_delete(self):
        """Test soft delete functionality."""
        job = Job.objects.create(title='Test Job')
        job.soft_delete()
        
        assert Job.objects.filter(pk=job.pk).count() == 0
        assert Job.objects.all_with_deleted().filter(pk=job.pk).count() == 1
    
    def test_job_restore(self):
        """Test restoring a soft-deleted job."""
        job = Job.objects.create(title='Test Job')
        job.soft_delete()
        job.restore()
        
        assert Job.objects.filter(pk=job.pk).count() == 1
        assert job.is_deleted is False
    
    def test_active_resumes_property(self, sample_job, sample_resume):
        """Test active_resumes property excludes deleted resumes."""
        assert sample_job.active_resumes.count() == 1
        
        sample_resume.soft_delete()
        assert sample_job.active_resumes.count() == 0

@pytest.mark.django_db
class TestResumeModel:
    """Tests for Resume model."""
    
    def test_resume_creation(self, sample_job):
        """Test creating a resume."""
        resume = Resume.objects.create(
            job=sample_job,
            candidate_name='Jane Doe',
            final_score=75
        )
        assert resume.pk is not None
        assert resume.candidate_name == 'Jane Doe'
    
    def test_resume_str_method(self, sample_job):
        """Test the __str__ method."""
        resume = Resume.objects.create(
            job=sample_job,
            candidate_name='John Smith'
        )
        assert 'John Smith' in str(resume)
        assert sample_job.title in str(resume)
    
    def test_auto_tier_top(self, sample_job):
        """Test tier assignment for high score via service layer (logic lives in apply_screening_result)."""
        from apps.core.services.resume_service import ResumeService
        resume = Resume.objects.create(job=sample_job, candidate_name='Top Candidate')
        ResumeService.apply_screening_result(resume, {
            'candidate_name': 'Top Candidate', 'skills': [], 'education': [],
            'certifications': [], 'experience_years': 0,
            'matched_skills': [], 'missing_skills': [],
            'skill_score': 85, 'experience_score': 85, 'education_score': 85,
            'certification_score': 0, 'final_score': 85,
            'tier': 'Top', 'recommendation': 'Interview', 'reasoning': '',
        })
        resume.refresh_from_db()
        assert resume.tier == 'top'
        assert resume.recommendation == 'interview'

    def test_auto_tier_mid(self, sample_job):
        """Test tier assignment for medium score via service layer."""
        from apps.core.services.resume_service import ResumeService
        resume = Resume.objects.create(job=sample_job, candidate_name='Mid Candidate')
        ResumeService.apply_screening_result(resume, {
            'candidate_name': 'Mid Candidate', 'skills': [], 'education': [],
            'certifications': [], 'experience_years': 0,
            'matched_skills': [], 'missing_skills': [],
            'skill_score': 70, 'experience_score': 70, 'education_score': 70,
            'certification_score': 0, 'final_score': 70,
            'tier': 'Mid', 'recommendation': 'Talent Pool', 'reasoning': '',
        })
        resume.refresh_from_db()
        assert resume.tier == 'mid'
        assert resume.recommendation == 'talent_pool'

    def test_auto_tier_low(self, sample_job):
        """Test tier assignment for low score via service layer."""
        from apps.core.services.resume_service import ResumeService
        resume = Resume.objects.create(job=sample_job, candidate_name='Low Candidate')
        ResumeService.apply_screening_result(resume, {
            'candidate_name': 'Low Candidate', 'skills': [], 'education': [],
            'certifications': [], 'experience_years': 0,
            'matched_skills': [], 'missing_skills': [],
            'skill_score': 40, 'experience_score': 40, 'education_score': 40,
            'certification_score': 0, 'final_score': 40,
            'tier': 'Low', 'recommendation': 'Reject', 'reasoning': '',
        })
        resume.refresh_from_db()
        assert resume.tier == 'low'
        assert resume.recommendation == 'reject'
    
    def test_resume_ordering(self, sample_job):
        """Test resumes are ordered by final_score desc."""
        Resume.objects.create(job=sample_job, candidate_name='Low', final_score=50)
        Resume.objects.create(job=sample_job, candidate_name='High', final_score=90)
        Resume.objects.create(job=sample_job, candidate_name='Mid', final_score=70)
        
        resumes = list(Resume.objects.all())
        assert resumes[0].candidate_name == 'High'
        assert resumes[1].candidate_name == 'Mid'
        assert resumes[2].candidate_name == 'Low'

    def test_save_derives_tier_from_final_score(self, sample_job):
        """Tier and recommendation stay aligned with final_score on save."""
        resume = Resume.objects.create(
            job=sample_job,
            candidate_name='Tier Sync',
            final_score=72,
        )
        assert resume.tier == 'mid'
        assert resume.recommendation == 'talent_pool'
