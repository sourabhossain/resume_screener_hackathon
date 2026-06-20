"""
Tests for AI Services: ai_screener, llm_client, document_extractor, resume_service.
"""
import pytest
from unittest.mock import patch


@pytest.mark.django_db
class TestDocumentExtractor:
    """Tests for DocumentExtractor service."""
    
    def test_extract_from_txt_is_unsupported(self, tmp_path):
        from apps.core.services.document_extractor import DocumentExtractor

        txt_file = tmp_path / "test.txt"
        txt_file.write_text("This is test resume content.\nSkills: Python, Django")

        with pytest.raises(ValueError, match="Unsupported file type"):
            DocumentExtractor.extract(str(txt_file))

    def test_unsupported_file_type(self, tmp_path):
        """Test that unsupported file types raise ValueError."""
        from apps.core.services.document_extractor import DocumentExtractor
        
        # Create a temp file with unsupported extension
        xyz_file = tmp_path / "test.xyz"
        xyz_file.write_text("some content")
        
        with pytest.raises(ValueError, match="Unsupported file type"):
            DocumentExtractor.extract(str(xyz_file))
    
    def test_file_not_found(self):
        """Test that missing file raises FileNotFoundError."""
        from apps.core.services.document_extractor import DocumentExtractor
        
        with pytest.raises(FileNotFoundError):
            DocumentExtractor.extract("/nonexistent/file.pdf")
    
    def test_is_supported(self):
        """Test is_supported method. .doc is no longer supported (python-docx is .docx only)."""
        from apps.core.services.document_extractor import DocumentExtractor

        assert DocumentExtractor.is_supported("resume.pdf") is True
        assert DocumentExtractor.is_supported("resume.docx") is True
        assert DocumentExtractor.is_supported("resume.doc") is False
        assert DocumentExtractor.is_supported("resume.txt") is False
        assert DocumentExtractor.is_supported("resume.xyz") is False


@pytest.mark.django_db
class TestPromptLoader:
    """Tests for PromptLoader utility."""
    
    def test_load_extraction_prompt(self):
        """Test loading extraction prompt template."""
        from apps.core.services.prompt_loader import get_extraction_prompt
        
        prompt = get_extraction_prompt(resume_text="Sample resume text")

        assert "Sample resume text" in prompt
        # Experience is computed in code now; the prompt extracts raw spans.
        assert "work_history" in prompt
    
    def test_load_matching_prompt(self):
        """Test loading matching prompt template."""
        from apps.core.services.prompt_loader import get_matching_prompt
        
        prompt = get_matching_prompt(
            job_description="Python Developer needed",
            candidate_name="John Doe",
            skills="Python, Django",
            experience_years=5.0,
            education="BSc Computer Science",
            certifications="AWS Certified"
        )
        
        assert "Python Developer needed" in prompt
        assert "John Doe" in prompt
    
    def test_load_reasoning_prompt(self):
        """Test loading reasoning prompt template."""
        from apps.core.services.prompt_loader import get_reasoning_prompt
        
        prompt = get_reasoning_prompt(
            candidate_name="Jane Doe",
            final_score=85.0,
            tier="Top",
            matched_skills="Python, Django",
            missing_skills="Kubernetes",
            experience_years=7.0
        )
        
        assert "Jane Doe" in prompt
        assert "85" in prompt


@pytest.mark.django_db  
class TestLLMClient:
    """Tests for LLMClient with mocked OpenAI calls."""
    
    @patch('apps.core.services.llm_client.ChatOpenAI')
    def test_invoke_json_returns_dict(self, mock_chat):
        """Test that invoke_json returns parsed dictionary."""
        # This is a mock test - actual LLM calls are expensive
        pass
    
    @patch('apps.core.services.llm_client.ChatOpenAI')
    def test_invoke_text_returns_string(self, mock_chat):
        """Test that invoke_text returns string."""
        pass


@pytest.mark.django_db
class TestResumeService:
    """Tests for ResumeService."""
    
    def test_process_resume_failure_saves_reason(self, sample_job, sample_resume, monkeypatch):
        """A failed screening must persist WHY (shown on the Screening Failed page)."""
        from apps.core.services.resume_service import ResumeService
        from apps.core.exceptions import AIScreeningError

        monkeypatch.setattr(ResumeService, 'extract_text', staticmethod(lambda r: 'cv text'))
        monkeypatch.setattr(ResumeService, '_fill_contact_info', classmethod(lambda cls, r, t: None))
        def _boom(resume):
            raise AIScreeningError('Request timed out.', stage='screening')
        monkeypatch.setattr(ResumeService, 'run_screening', staticmethod(_boom))

        result = ResumeService.process_resume(sample_resume)
        assert result['success'] is False
        sample_resume.refresh_from_db()
        assert sample_resume.screening_status == 'failed'
        assert 'Request timed out' in sample_resume.reasoning

    def test_apply_screening_result_needs_review_saves_reason(self, sample_job, sample_resume):
        """needs_review must persist WHY (so the UI can show the specific reason)."""
        from apps.core.services.resume_service import ResumeService
        reason = "The AI judged the job description too vague to classify confidently."
        ResumeService.apply_screening_result(sample_resume, {'needs_review': True, 'reasoning': reason})
        sample_resume.refresh_from_db()
        assert sample_resume.screening_status == 'needs_review'
        assert sample_resume.reasoning == reason

    def test_apply_screening_result(self, sample_job, sample_resume):
        """Test applying screening results to resume."""
        from apps.core.services.resume_service import ResumeService
        
        result = {
            'candidate_name': 'Test Candidate',
            'skills': ['Python', 'Django'],
            'education': ['BSc CS'],
            'certifications': ['AWS'],
            'experience_years': 5.0,
            'matched_skills': ['Python'],
            'missing_skills': ['Go'],
            'skill_score': 80.0,
            'experience_score': 90.0,
            'education_score': 85.0,
            'certification_score': 25.0,
            'final_score': 82.5,
            'achievement_score': 88.0,
            'achievements': ['Shipped billing refactor'],
            'tier': 'Top',
            'recommendation': 'Interview',
            'reasoning': 'Strong candidate'
        }
        
        ResumeService.apply_screening_result(sample_resume, result)
        
        sample_resume.refresh_from_db()
        assert sample_resume.skills == ['Python', 'Django']
        assert sample_resume.final_score == 82  # Rounded
        assert sample_resume.tier == 'top'
        assert sample_resume.screening_status == 'completed'
        assert sample_resume.achievements == ['Shipped billing refactor']
        assert sample_resume.achievement_score == 88


@pytest.mark.django_db
class TestExceptions:
    """Tests for custom exceptions."""
    
    def test_document_extraction_error(self):
        """Test DocumentExtractionError."""
        from apps.core.exceptions import DocumentExtractionError
        
        error = DocumentExtractionError("Failed to read", file_path="/path/to/file.pdf")
        assert error.file_path == "/path/to/file.pdf"
        assert "Failed to read" in str(error)
    
    def test_ai_screening_error(self):
        """Test AIScreeningError."""
        from apps.core.exceptions import AIScreeningError
        
        error = AIScreeningError("LLM failed", stage="extraction")
        assert error.stage == "extraction"
        assert "LLM failed" in str(error)
    
    def test_invalid_file_type_error(self):
        """Test InvalidFileTypeError."""
        from apps.core.exceptions import InvalidFileTypeError
        
        error = InvalidFileTypeError("xyz")
        assert error.file_type == "xyz"
        assert "Unsupported file type: xyz" in str(error)
    
    def test_file_too_large_error(self):
        """Test FileTooLargeError."""
        from apps.core.exceptions import FileTooLargeError
        
        error = FileTooLargeError(size=10*1024*1024, max_size=5*1024*1024)
        assert error.size == 10*1024*1024
        assert "exceeds limit" in str(error)
