"""
Regression tests for the full-system hardening pass.

Each test pins a specific fixed behavior so it can't silently regress:
soft-delete cascade, deleted-job access guards, CSV formula-injection escaping,
the LLM reasoning-model temperature fix, and the skill_score subset guard.
"""
import pytest

from apps.core.models import Resume


@pytest.mark.django_db
class TestDeletedJobResumeGuard:
    def test_resume_detail_404_when_job_soft_deleted(self, authenticated_client, sample_resume):
        sample_resume.job.soft_delete()
        resp = authenticated_client.get(f'/resumes/{sample_resume.uuid}/')
        assert resp.status_code == 404

    def test_talent_pool_excludes_deleted_job_candidates(self, authenticated_client, sample_resume):
        # final_score in the mid band auto-assigns recommendation='talent_pool'
        # (Resume.save derives tier/recommendation from final_score).
        sample_resume.final_score = 70
        sample_resume.screening_status = 'completed'
        sample_resume.save()
        assert sample_resume.recommendation == 'talent_pool'
        # Visible before delete...
        resp = authenticated_client.get('/talent-pool/')
        assert sample_resume.candidate_name.encode() in resp.content
        # ...gone after the parent job is soft-deleted.
        sample_resume.job.soft_delete()
        resp = authenticated_client.get('/talent-pool/')
        assert sample_resume.candidate_name.encode() not in resp.content


@pytest.mark.django_db
class TestSoftDeleteCascade:
    def test_deleting_resume_cascades_to_interviews_and_evaluations(self, sample_resume):
        from django.utils import timezone
        from apps.interviews.models import Interview, InterviewEvaluation

        interview = Interview.objects.create(
            resume=sample_resume, phase='1', scheduled_date=timezone.now().date()
        )
        ev = InterviewEvaluation.objects.create(
            interview=interview, interviewer_name='Panelist One'
        )

        sample_resume.soft_delete()

        # The cascade soft-deletes interview AND its evaluations (hidden from the
        # default managers), so the public evaluation link no longer resolves.
        assert not Interview.objects.filter(pk=interview.pk).exists()
        assert Interview.all_objects.filter(pk=interview.pk, is_deleted=True).exists()
        assert not InterviewEvaluation.objects.filter(pk=ev.pk).exists()
        assert InterviewEvaluation.all_objects.filter(pk=ev.pk, is_deleted=True).exists()

    def test_evaluate_link_404_after_resume_deleted(self, client, sample_resume):
        from django.utils import timezone
        from apps.interviews.models import Interview, InterviewEvaluation

        interview = Interview.objects.create(
            resume=sample_resume, phase='1', scheduled_date=timezone.now().date()
        )
        ev = InterviewEvaluation.objects.create(
            interview=interview, interviewer_name='Panelist One'
        )
        sample_resume.soft_delete()
        resp = client.get(f'/evaluate/{ev.token}/')
        assert resp.status_code == 404


@pytest.mark.django_db
class TestCsvFormulaInjection:
    def test_export_neutralizes_formula_leading_fields(self, authenticated_client, sample_job):
        Resume.objects.create(
            job=sample_job,
            candidate_name='=HYPERLINK("http://evil","x")',
            email='+1234',
            phone='-2+3',
            final_score=50,
        )
        resp = authenticated_client.get(f'/jobs/{sample_job.slug}/export/')
        body = b''.join(resp.streaming_content)
        # Each dangerous lead char must be prefixed with a single quote.
        assert b"'=HYPERLINK" in body
        assert b"'+1234" in body
        assert b"'-2+3" in body


class TestLLMReasoningModelTemperature:
    def test_reasoning_models_detected(self):
        from apps.core.services.llm_client import LLMClient
        assert LLMClient._is_reasoning_model('gpt-5-nano-2025-08-07') is True
        assert LLMClient._is_reasoning_model('o1-mini') is True
        assert LLMClient._is_reasoning_model('o3') is True
        assert LLMClient._is_reasoning_model('gpt-4o-mini') is False
        assert LLMClient._is_reasoning_model('gpt-4.1') is False


@pytest.mark.django_db
class TestSkillScoreSubsetGuard:
    def test_fabricated_matched_skills_dropped_from_score(self):
        from apps.core.services.ai_screener import score_node

        state = {
            'skills': ['python', 'django'],
            'matched_skills': ['python', 'django', 'rust', 'python'],  # rust fabricated, python dup
            'missing_skills': ['django', 'kubernetes'],  # django also "matched" -> overlap
            'experience_match_score': 0,
            'education_match_score': 0,
            'achievement_score': 0,
            'certification_match_score': 0,
            'certifications': [],
            'job_type': 'software_engineering',
        }
        out = score_node(state)
        assert 'rust' not in [s.lower() for s in out['matched_skills']]
        # django can't be in both lists
        assert 'django' not in [s.lower() for s in out['missing_skills']]
        # matched={python,django}=2, missing={kubernetes}=1 -> 2/3*100
        assert round(out['skill_score']) == 67
