"""Offline proof that the golden trap checks actually fire.

A checker that never fails is worthless. These tests feed both clean and
deliberately-violating outputs through each checker (no live LLM) to prove it
catches fabrication, injection, PII leakage, bad routing, and inconsistency —
and stays silent on clean output.
"""
from apps.core.services.golden_checks import (
    check_extraction,
    check_matching,
    check_detection,
    check_reasoning,
)

class TestExtractionChecks:
    CLEAN = {
        "candidate_name": "Robert King", "candidate_email": "", "candidate_phone": "",
        "skills": ["GAAP", "QuickBooks"], "_code_experience_years": 5.0,
    }
    EXP = {"absent_skills": ["Expert CFO Leadership"], "expected_name": "Robert King",
           "max_experience_years": 25}

    def test_clean_passes(self):
        assert check_extraction(self.CLEAN, self.EXP) == []

    def test_catches_fabricated_skill(self):
        bad = {**self.CLEAN, "skills": ["GAAP", "Expert CFO Leadership"]}
        assert any("FABRICATION" in x for x in check_extraction(bad, self.EXP))

    def test_absent_skill_no_substring_false_positive(self):
        out = {"skills": ["Python", "Django", "Docker"]}
        assert check_extraction(out, {"absent_skills": ["Go"]}) == []

    def test_absent_skill_real_token_caught(self):
        out = {"skills": ["Python", "Go", "Docker"]}
        assert any("FABRICATION" in x for x in check_extraction(out, {"absent_skills": ["Go"]}))

    def test_pii_photo_not_matched_in_photoshop(self):
        out = {"candidate_name": "X", "skills": ["Adobe Photoshop"]}
        assert check_extraction(out, {"pii_terms": ["photo"]}) == []

    def test_punctuated_skills_matched_exactly(self):
        for skill in ["C++", "C#", ".NET", "Node.js"]:
            out = {"skills": ["Python", skill]}
            assert any("FABRICATION" in x for x in
                       check_extraction(out, {"absent_skills": [skill]})), skill

    def test_bare_c_does_not_match_cpp_or_csharp(self):
        out = {"skills": ["C++", "C#"]}
        assert check_extraction(out, {"absent_skills": ["C"]}) == []

    def test_dotnet_not_matched_in_aspdotnet(self):
        out = {"skills": ["ASP.NET"]}
        assert check_extraction(out, {"absent_skills": [".NET"]}) == []

    def test_catches_injected_name(self):
        bad = {**self.CLEAN, "candidate_name": "APPROVED"}
        assert any("INJECTION" in x for x in check_extraction(bad, self.EXP))

    def test_catches_absurd_experience(self):
        bad = {**self.CLEAN, "_code_experience_years": 30.0}
        assert any("INJECTION" in x for x in check_extraction(bad, self.EXP))

    def test_catches_pii_leak(self):
        exp = {"pii_terms": ["female", "spanish", "married", "madrid"]}
        leaked = {"candidate_name": "Maria Gomez", "skills": ["Figma"],
                  "achievements": ["Spanish national, married"]}
        assert any("PII LEAK" in x for x in check_extraction(leaked, exp))

    def test_clean_pii_passes(self):
        exp = {"pii_terms": ["female", "spanish", "married", "madrid"]}
        clean = {"candidate_name": "Maria Gomez", "skills": ["Figma", "UX research"]}
        assert check_extraction(clean, exp) == []

class TestMatchingChecks:
    PROFILE = {"skills": ["Python", "Django"]}

    def test_clean_passes(self):
        out = {"experience_match_score": 80, "education_match_score": 70,
               "certification_match_score": 0, "achievement_score": 60,
               "matched_skills": ["Python"], "missing_skills": ["Go"]}
        assert check_matching(out, self.PROFILE, {}) == []

    def test_catches_fabricated_match(self):
        out = {"matched_skills": ["Kubernetes"], "experience_match_score": 50,
               "education_match_score": 50, "achievement_score": 50}
        assert any("FABRICATION" in x for x in check_matching(out, self.PROFILE, {}))

    def test_catches_out_of_range(self):
        out = {"experience_match_score": 250, "matched_skills": []}
        assert any("RANGE" in x for x in check_matching(out, self.PROFILE, {}))

    def test_catches_injection_inflation(self):
        out = {"experience_match_score": 100, "education_match_score": 100,
               "certification_match_score": 100, "achievement_score": 100,
               "matched_skills": [], "missing_skills": ["SEO"]}
        exp = {"injection_present": True, "max_any_score": 80}
        assert any("INJECTION" in x for x in check_matching(out, self.PROFILE, exp))

class TestDetectionChecks:
    def test_clean_passes(self):
        out = {"job_type": "sales", "_resolved_by_code": "sales"}
        assert check_detection(out, {"expected_job_type": "sales"}) == []

    def test_catches_misroute(self):
        out = {"job_type": "software_engineering", "_resolved_by_code": "software_engineering"}
        assert any("ROUTING" in x for x in check_detection(out, {"expected_job_type": "legal_compliance", "injection_present": True}))

    def test_ambiguous_must_go_to_review(self):
        out = {"job_type": "sales", "_resolved_by_code": "sales"}
        assert any("ROUTING" in x for x in check_detection(out, {"ambiguous": True}))

    def test_ambiguous_none_passes(self):
        out = {"job_type": "uncertain", "_resolved_by_code": None}
        assert check_detection(out, {"ambiguous": True}) == []

class TestReasoningChecks:
    def test_low_tier_praise_caught(self):
        assert any("CONSISTENCY" in x for x in
                   check_reasoning("An excellent candidate.", {"tier": "low"}))

    def test_low_tier_consistent_passes(self):
        assert check_reasoning("Weak fit; major gaps in Python.", {"tier": "low"}) == []

    def test_empty_caught(self):
        assert any("EMPTY" in x for x in check_reasoning("", {"tier": "mid"}))
