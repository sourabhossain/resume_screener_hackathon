"""
Regression tests for the full-system hardening pass.

Each test pins a specific fixed behavior so it can't silently regress:
soft-delete cascade, deleted-job access guards, CSV formula-injection escaping,
the LLM reasoning-model temperature fix, and the skill_score subset guard.
"""
import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.core.models import Resume

@pytest.mark.django_db
class TestNoRawTemplateComments:
    """Multi-line {# #} comments silently render as literal text (Django only
    supports single-line {# #}; multi-line needs {% comment %}). These pin that
    the explanatory comments don't leak onto the rendered page."""

    def test_pipeline_row_has_no_raw_comment(self, authenticated_client, sample_resume):
        sample_resume.screening_status = 'completed'
        sample_resume.recruiter_status = 'phone_screen'
        sample_resume.save()
        resp = authenticated_client.get(
            reverse('core:job_detail', kwargs={'slug': sample_resume.job.slug})
        )
        assert resp.status_code == 200
        assert b'SUBORDINATE' not in resp.content
        assert b'Phone Screen' in resp.content

    def test_needs_review_and_failed_pages_have_no_raw_comment(self, authenticated_client):
        r1 = authenticated_client.get(reverse('core:needs_review'))
        r2 = authenticated_client.get(reverse('core:screening_failed'))
        assert b'dark-mode overrides' not in r1.content
        assert b'blinding white' not in r2.content

@pytest.mark.django_db
class TestDuplicateUploadConstraint:
    """The (job, dedup_key) unique constraint is portable (MySQL + SQLite) and
    enforces 'one active copy of a file per job' as a race backstop."""

    def test_duplicate_active_file_hash_rejected(self, sample_job):
        Resume.objects.create(job=sample_job, candidate_name='A', file_hash='deadbeef')
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Resume.objects.create(job=sample_job, candidate_name='B', file_hash='deadbeef')

    def test_reupload_allowed_after_soft_delete(self, sample_job):
        first = Resume.objects.create(job=sample_job, candidate_name='A', file_hash='cafef00d')
        first.soft_delete()
        Resume.objects.create(job=sample_job, candidate_name='A again', file_hash='cafef00d')

    def test_hashless_rows_do_not_collide(self, sample_job):
        Resume.objects.create(job=sample_job, candidate_name='X', file_hash='')
        Resume.objects.create(job=sample_job, candidate_name='Y', file_hash='')

    def test_dedup_key_tracks_active_hashed_state(self, sample_job):
        r = Resume.objects.create(job=sample_job, candidate_name='Z', file_hash='abc123')
        r.refresh_from_db()
        assert r.dedup_key == 'abc123'
        r.soft_delete(); r.refresh_from_db()
        assert r.dedup_key is None

@pytest.mark.django_db
class TestDeletedJobResumeGuard:
    def test_resume_detail_404_when_job_soft_deleted(self, authenticated_client, sample_resume):
        sample_resume.job.soft_delete()
        resp = authenticated_client.get(f'/resumes/{sample_resume.uuid}/')
        assert resp.status_code == 404

    def test_talent_pool_excludes_deleted_job_candidates(self, authenticated_client, sample_resume):
        sample_resume.final_score = 70
        sample_resume.screening_status = 'completed'
        sample_resume.save()
        assert sample_resume.recommendation == 'talent_pool'
        resp = authenticated_client.get('/talent-pool/')
        assert sample_resume.candidate_name.encode() in resp.content
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
            'matched_skills': ['python', 'django', 'rust', 'python'],
            'missing_skills': ['django', 'kubernetes'],
            'experience_match_score': 0,
            'education_match_score': 0,
            'achievement_score': 0,
            'certification_match_score': 0,
            'certifications': [],
            'job_type': 'software_engineering',
        }
        out = score_node(state)
        assert 'rust' not in [s.lower() for s in out['matched_skills']]
        assert 'django' not in [s.lower() for s in out['missing_skills']]
        assert round(out['skill_score']) == 67


class TestScoringFairnessAndExperience:
    def test_redact_strips_labeled_fields_keeps_real_content(self):
        from apps.core.services.ai_screener import redact_protected_attributes
        text = ("Maria Gomez\nGender: Female\nDate of Birth: 12/03/1991\n"
                "Nationality: Spanish\n34 years old. Photo attached.\n"
                "Skills: Figma, Spanish, UX research")
        out = redact_protected_attributes(text); low = out.lower()
        assert 'female' not in low
        assert '12/03/1991' not in out
        assert 'years old' not in low
        assert 'photo' not in low
        assert 'maria gomez' in low          # name kept (extraction/display needs it)
        assert 'figma' in low and 'ux research' in low
        assert 'spanish' in low              # the language skill survives

    def _base_state(self, **over):
        s = dict(error=None, skills=['python'], matched_skills=['python'], missing_skills=[],
                 education_match_score=0, achievement_score=0, certification_match_score=0,
                 certifications=[], job_type='software_engineering', experience_match_score=42)
        s.update(over)
        return s

    def test_experience_score_deterministic_from_required(self):
        from apps.core.services.ai_screener import score_node
        out = score_node(self._base_state(experience_years=3.0, required_experience=5.0))
        assert out['experience_score'] == 60          # 3/5, not the LLM's 42
        out = score_node(self._base_state(experience_years=8.0, required_experience=5.0))
        assert out['experience_score'] == 100         # capped

    def test_experience_score_falls_back_to_llm_when_no_required(self):
        from apps.core.services.ai_screener import score_node
        out = score_node(self._base_state(experience_years=3.0, required_experience=None))
        assert out['experience_score'] == 42          # LLM value (no required set)

    def test_matching_profile_excludes_candidate_name(self, monkeypatch):
        import apps.core.services.ai_screener as ai
        captured = {}
        monkeypatch.setattr(ai, 'build_matching_prompt',
                            lambda role, jd, profile: captured.setdefault('p', profile) or 'X')
        monkeypatch.setattr(ai.llm_client, 'invoke_json', lambda *a, **k: {
            'matched_skills': ['python'], 'missing_skills': [],
            'experience_match_score': 50, 'education_match_score': 50,
            'certification_match_score': 50, 'achievement_score': 50,
        })
        ai.match_node(dict(error=None, job_description='Need Python', job_type='software_engineering',
                           candidate_name='Maria Gomez', skills=['python'], experience_years=3.0,
                           education=[], certifications=[], achievements=[], resume_id=1))
        assert 'candidate_name' not in captured['p']
        assert 'skills' in captured['p']

    def test_skill_score_deterministic_from_required_skills(self):
        from apps.core.services.ai_screener import score_node
        out = score_node(self._base_state(
            skills=['python', 'django', 'docker'],
            required_skills=['Python', 'Django', 'Kubernetes', 'MySQL'],
            matched_skills=['ignored'], missing_skills=['ignored'],
            experience_years=0.0, required_experience=None,
        ))
        assert round(out['skill_score']) == 50          # 2 of 4 required matched
        assert {s.lower() for s in out['matched_skills']} == {'python', 'django'}
        assert {s.lower() for s in out['missing_skills']} == {'kubernetes', 'mysql'}

    def test_skill_score_falls_back_to_llm_lists_without_required(self):
        from apps.core.services.ai_screener import score_node
        out = score_node(self._base_state(
            skills=['python'], required_skills=[],
            matched_skills=['python'], missing_skills=['go'],
        ))
        assert round(out['skill_score']) == 50          # 1 matched / (1+1) from LLM lists


@pytest.mark.django_db
class TestJobFormCapturesRequirements:
    def test_required_fields_parsed_to_lists(self):
        from apps.core.forms import JobForm
        f = JobForm(data={
            'title': 'Backend Dev', 'description': 'Build APIs', 'status': 'active',
            'required_skills_text': 'Python, Django , MySQL',
            'required_experience': '5',
            'required_education_text': 'Bachelor, Computer Science',
        })
        assert f.is_valid(), f.errors
        job = f.save(commit=False)
        assert job.required_skills == ['Python', 'Django', 'MySQL']
        assert job.required_education == ['Bachelor', 'Computer Science']
        assert job.required_experience == 5
