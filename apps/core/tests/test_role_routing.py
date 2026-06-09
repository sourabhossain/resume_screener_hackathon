"""
Tests for role-based prompt routing: detect_job_type, get_prompt_path, score_node weights.
"""
import pytest
from unittest.mock import patch
from apps.core.services.ai_screener import detect_job_type, get_prompt_path, score_node


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
            mock_llm.invoke_json.return_value = {'job_type': 'sales_marketing', 'confidence': 0.9}
            result = detect_job_type("We need a sales manager")
        assert result == 'sales_marketing'

    def test_detect_falls_back_on_unknown_type(self):
        with patch('apps.core.services.ai_screener.llm_client') as mock_llm:
            mock_llm.invoke_json.return_value = {'job_type': 'totally_unknown', 'confidence': 0.5}
            result = detect_job_type("some job")
        assert result == 'tech'

    def test_detect_falls_back_on_llm_exception(self):
        with patch('apps.core.services.ai_screener.llm_client') as mock_llm:
            mock_llm.invoke_json.side_effect = RuntimeError("LLM down")
            result = detect_job_type("some job")
        assert result == 'tech'

    def test_detect_falls_back_on_whitespace_input(self):
        with patch('apps.core.services.ai_screener.llm_client') as mock_llm:
            mock_llm.invoke_json.return_value = {'job_type': 'tech', 'confidence': 0.9}
            result = detect_job_type("   ")
        assert result == 'tech'


@pytest.mark.django_db
class TestGetPromptPath:

    def test_returns_role_specific_path(self):
        path = get_prompt_path('sales_marketing', 'extraction')
        assert 'sales_marketing' in str(path)
        assert path.exists()

    def test_falls_back_to_tech_for_unknown_role(self):
        path = get_prompt_path('nonexistent_role', 'extraction')
        assert 'tech' in str(path)
        assert path.exists()

    def test_all_8_roles_have_both_prompt_files(self):
        roles = [
            'tech', 'sales_marketing', 'hr_recruitment', 'finance_admin',
            'design_creative', 'operations_support', 'project_management', 'product_management',
        ]
        for role in roles:
            for prompt in ['extraction', 'matching']:
                path = get_prompt_path(role, prompt)
                assert path.exists(), f"Missing: {role}/{prompt}.txt"


@pytest.mark.django_db
class TestScoreNodeWeights:

    def test_tech_role_uses_tech_weights(self):
        state = build_test_state(
            job_type='tech', skill_score=100, experience_match_score=100,
            education_match_score=100, certification_score=0, achievement_score=0,
        )
        result = score_node(state)
        expected = 100 * 0.40 + 100 * 0.30 + 100 * 0.20 + 0 * 0.10
        assert abs(result['final_score'] - expected) < 0.1

    def test_non_tech_role_uses_achievement_weight(self):
        state = build_test_state(
            job_type='sales_marketing', skill_score=100,
            experience_match_score=100, education_match_score=100,
            certification_score=0, achievement_score=100,
        )
        result = score_node(state)
        expected = 100 * 0.30 + 100 * 0.25 + 100 * 0.15 + 0 * 0.10 + 100 * 0.20
        assert abs(result['final_score'] - expected) < 0.1

    def test_missing_achievement_score_defaults_to_zero(self):
        state = build_test_state(
            job_type='hr_recruitment', skill_score=80,
            experience_match_score=70, education_match_score=60,
            certification_score=50, achievement_score=None,
        )
        result = score_node(state)
        assert result['final_score'] is not None
        assert result['final_score'] >= 0
