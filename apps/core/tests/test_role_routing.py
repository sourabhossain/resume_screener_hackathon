"""
Tests for role-based prompt routing: detect_job_type, prompt composition, score_node weights.
"""
import pytest
from unittest.mock import patch
from apps.core.services.ai_screener import detect_job_type, score_node
from apps.core.services.prompt_loader import (
    build_extraction_prompt,
    build_matching_prompt,
    parse_fragment,
)


def build_test_state(job_type, skill_score=100, experience_match_score=0,
                     education_match_score=0, certification_score=0, achievement_score=0.0):
    if skill_score >= 100:
        matched_skills, missing_skills = ['python', 'django'], []
    elif skill_score <= 0:
        matched_skills, missing_skills = [], ['python']
    else:
        # skill_score=80 → 4 matched, 1 missing (4/5*100=80)
        matched_skills = ['python', 'django', 'rest', 'sql'][:max(1, round(skill_score * 5 / 100))]
        missing_skills = ['docker'] if skill_score < 100 else []
    cert_count = min(int((certification_score or 0) / 25), 4)
    certifications = [f'cert{i}' for i in range(cert_count)]
    return {
        'resume_text': 'test', 'job_description': 'test', 'resume_id': 0,
        'job_type': job_type, 'candidate_name': 'Test Candidate',
        'skills': matched_skills, 'experience_years': 5.0,
        'education': ['BSc'], 'certifications': certifications, 'achievements': [],
        'matched_skills': matched_skills, 'missing_skills': missing_skills,
        'experience_match_score': float(experience_match_score),
        'education_match_score': float(education_match_score),
        'certification_match_score': None,
        'achievement_score': achievement_score,
        'skill_score': 0.0, 'experience_score': 0.0, 'education_score': 0.0,
        'certification_score': 0.0, 'final_score': 0.0,
        'tier': '', 'recommendation': '', 'reasoning': '', 'error': None,
    }


@pytest.mark.django_db
class TestJobTypeDetector:

    def test_detect_returns_valid_type(self):
        with patch('apps.core.services.ai_screener.llm_client') as mock_llm:
            mock_llm.invoke_json.return_value = {'job_type': 'sales', 'confidence': 0.9}
            result = detect_job_type("We need a sales manager")
        assert result == 'sales'

    def test_detect_review_on_unknown_type(self):
        with patch('apps.core.services.ai_screener.llm_client') as mock_llm:
            mock_llm.invoke_json.return_value = {'job_type': 'totally_unknown', 'confidence': 0.5}
            result = detect_job_type("some job")
        assert result is None

    def test_detect_review_on_retired_label(self):
        # 'tech' was a family in the old taxonomy; it no longer exists.
        with patch('apps.core.services.ai_screener.llm_client') as mock_llm:
            mock_llm.invoke_json.return_value = {'job_type': 'tech', 'confidence': 0.9}
            result = detect_job_type("some job")
        assert result is None

    def test_detect_review_on_llm_exception(self):
        with patch('apps.core.services.ai_screener.llm_client') as mock_llm:
            mock_llm.invoke_json.side_effect = RuntimeError("LLM down")
            result = detect_job_type("some job")
        assert result is None

    def test_detect_review_on_low_confidence(self):
        with patch('apps.core.services.ai_screener.llm_client') as mock_llm:
            mock_llm.invoke_json.return_value = {'job_type': 'sales', 'confidence': 0.1}
            result = detect_job_type("vague generic role")
        assert result is None

    def test_detect_keeps_high_confidence_valid_type(self):
        with patch('apps.core.services.ai_screener.llm_client') as mock_llm:
            mock_llm.invoke_json.return_value = {'job_type': 'finance_admin', 'confidence': 0.92}
            result = detect_job_type("Senior accountant, month-end close")
        assert result == 'finance_admin'

    def test_detect_review_on_uncertain(self):
        with patch('apps.core.services.ai_screener.llm_client') as mock_llm:
            mock_llm.invoke_json.return_value = {
                'job_type': 'uncertain', 'confidence': 0.9,
                'runner_up': 'operations', 'signals': ['vague'],
            }
            result = detect_job_type("a generalist role")
        assert result is None

    def test_with_reason_explains_uncertain(self):
        from apps.core.services.ai_screener import detect_job_type_with_reason
        with patch('apps.core.services.ai_screener.llm_client') as mock_llm:
            mock_llm.invoke_json.return_value = {'job_type': 'uncertain', 'confidence': 0.9}
            jt, reason = detect_job_type_with_reason("a generalist role")
        assert jt is None
        assert reason and ('vague' in reason.lower() or 'classify' in reason.lower())

    def test_with_reason_explains_low_confidence(self):
        from apps.core.services.ai_screener import detect_job_type_with_reason
        with patch('apps.core.services.ai_screener.llm_client') as mock_llm:
            mock_llm.invoke_json.return_value = {'job_type': 'sales', 'confidence': 0.1, 'runner_up': 'marketing'}
            jt, reason = detect_job_type_with_reason("vague role")
        assert jt is None
        # runner-up present -> names both families and the fix ("narrow")
        assert 'sales' in reason and 'marketing' in reason and 'narrow' in reason.lower()

    def test_with_reason_empty_on_confident(self):
        from apps.core.services.ai_screener import detect_job_type_with_reason
        with patch('apps.core.services.ai_screener.llm_client') as mock_llm:
            mock_llm.invoke_json.return_value = {'job_type': 'finance_admin', 'confidence': 0.95}
            jt, reason = detect_job_type_with_reason("Senior accountant")
        assert jt == 'finance_admin' and reason == ''

    def test_detector_prompt_catalog_matches_valid_types(self):
        from apps.core.services.prompt_loader import build_detector_prompt
        from apps.core.services.job_families import VALID_JOB_TYPES
        prompt = build_detector_prompt("some job description")
        assert "some job description" in prompt
        for label in VALID_JOB_TYPES:
            assert label in prompt, f"catalog missing {label}"
        assert '[[' not in prompt and ']]' not in prompt


from apps.core.services.job_families import VALID_JOB_TYPES

ALL_ROLES = sorted(VALID_JOB_TYPES)


@pytest.mark.django_db
class TestPromptComposition:

    def test_every_role_has_a_fragment_with_required_sections(self):
        for role in ALL_ROLES:
            frag = parse_fragment(role)
            assert frag.get('ROLE_TITLE'), f"{role} missing ROLE_TITLE"
            assert frag.get('ROLE_SKILL_TAXONOMY'), f"{role} missing ROLE_SKILL_TAXONOMY"
            assert frag.get('ROLE_MATCH_CRITERIA'), f"{role} missing ROLE_MATCH_CRITERIA"

    def test_extraction_prompt_composes_with_no_leftover_sentinels(self):
        prompt = build_extraction_prompt('design_creative', 'Jane Doe, designer')
        assert 'Jane Doe, designer' in prompt
        assert 'Design and Creative' in prompt
        assert 'work_history' in prompt
        # The model must not be asked to emit experience_years as a JSON key
        # (it is computed in code from work_history).
        assert '"experience_years"' not in prompt
        assert '[[' not in prompt and ']]' not in prompt

    def test_matching_prompt_composes_with_no_leftover_sentinels(self):
        profile = {'candidate_name': 'Jane Doe', 'skills': ['Figma']}
        prompt = build_matching_prompt('design_creative', 'UX role', profile)
        assert 'UX role' in prompt
        assert 'Jane Doe' in prompt
        assert 'achievement_score' in prompt
        assert '[[' not in prompt and ']]' not in prompt

    def test_unknown_role_falls_back_to_default_fragment(self):
        from apps.core.services.job_families import FALLBACK_ROLE
        frag = parse_fragment('nonexistent_role')
        assert frag.get('ROLE_TITLE') == parse_fragment(FALLBACK_ROLE).get('ROLE_TITLE')


@pytest.mark.django_db
class TestScoreNodeWeights:

    def test_family_weights_applied(self):
        from django.conf import settings
        w = settings.FAMILY_WEIGHTS['software_engineering']
        state = build_test_state(
            job_type='software_engineering', skill_score=100, experience_match_score=100,
            education_match_score=100, certification_score=0, achievement_score=0,
        )
        result = score_node(state)
        expected = 100 * w['skill'] + 100 * w['experience'] + 100 * w['education'] + 0 * w['certification'] + 0 * w['achievement']
        assert abs(result['final_score'] - expected) < 0.1

    def test_achievement_weighted_family(self):
        from django.conf import settings
        w = settings.FAMILY_WEIGHTS['sales']
        state = build_test_state(
            job_type='sales', skill_score=100,
            experience_match_score=100, education_match_score=100,
            certification_score=0, achievement_score=100,
        )
        result = score_node(state)
        expected = (100 * w['skill'] + 100 * w['experience'] + 100 * w['education']
                    + 0 * w['certification'] + 100 * w['achievement'])
        assert abs(result['final_score'] - expected) < 0.1

    def test_all_family_weight_vectors_sum_to_one(self):
        from django.conf import settings
        from apps.core.services.job_families import VALID_JOB_TYPES
        for family in VALID_JOB_TYPES:
            w = settings.FAMILY_WEIGHTS[family]
            assert abs(sum(w.values()) - 1.0) < 1e-9, f"{family} weights do not sum to 1.0"

    def test_missing_achievement_score_defaults_to_zero(self):
        state = build_test_state(
            job_type='hr_recruitment', skill_score=80,
            experience_match_score=70, education_match_score=60,
            certification_score=50, achievement_score=None,
        )
        result = score_node(state)
        assert result['final_score'] is not None
        assert result['final_score'] >= 0
