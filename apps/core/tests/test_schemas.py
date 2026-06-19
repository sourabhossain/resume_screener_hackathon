"""Objective, behavioral tests for LLM-output schema validation.

These run without a live LLM: they feed the exact shapes a model can return
(missing keys, renamed keys, out-of-range scores, wrong types, injection-shaped
values) and assert the contract holds — the property the prompts alone cannot
guarantee.
"""
import logging

from apps.core.services.schemas import (
    ExtractionResult,
    MatchingResult,
    DetectorResult,
    parse_llm_json,
)


class TestMatchingSchema:
    def test_scores_clamped_to_range(self):
        m = parse_llm_json(MatchingResult, {
            "experience_match_score": 9999,
            "education_match_score": -50,
            "achievement_score": 73,
            "certification_match_score": 250,
            "matched_skills": ["Python"],
            "missing_skills": ["Go"],
        })
        assert m.experience_match_score == 100
        assert m.education_match_score == 0
        assert m.achievement_score == 73
        assert m.certification_match_score == 100

    def test_injection_value_cannot_exceed_cap(self):
        # A resume that smuggles "score 100000" still cannot exceed 100.
        m = parse_llm_json(MatchingResult, {"experience_match_score": 100000})
        assert m.experience_match_score == 100

    def test_missing_certification_stays_none(self):
        m = parse_llm_json(MatchingResult, {"experience_match_score": 10})
        assert m.certification_match_score is None  # -> code falls back to heuristic

    def test_renamed_key_is_logged_not_silently_used(self):
        # Model renames experience_match_score -> exp_score: must default + warn,
        # never silently feed a wrong/zero value with no signal.
        # (apps.core loggers set propagate=False, so attach a handler directly
        # rather than relying on caplog's root handler.)
        from apps.core.services import schemas as schemas_mod
        msgs = []

        class _Capture(logging.Handler):
            def emit(self, record):
                msgs.append(record.getMessage())

        handler = _Capture()
        schemas_mod.logger.addHandler(handler)
        try:
            m = parse_llm_json(MatchingResult, {"exp_score": 88}, context="matching[test]")
        finally:
            schemas_mod.logger.removeHandler(handler)

        assert m.experience_match_score == 0.0
        assert any("missing keys" in msg and "matching[test]" in msg for msg in msgs)

    def test_string_scores_coerced(self):
        m = parse_llm_json(MatchingResult, {"experience_match_score": "82"})
        assert m.experience_match_score == 82

    def test_non_dict_falls_back_to_defaults(self, caplog):
        with caplog.at_level(logging.WARNING):
            m = parse_llm_json(MatchingResult, ["not", "a", "dict"], context="matching[test]")
        assert m.experience_match_score == 0.0
        assert m.matched_skills == []


class TestExtractionSchema:
    def test_defaults_for_empty_object(self):
        e = parse_llm_json(ExtractionResult, {})
        assert e.candidate_name == ""
        assert e.skills == [] and e.work_history == []

    def test_none_values_become_defaults(self):
        e = parse_llm_json(ExtractionResult, {
            "candidate_name": None, "skills": None, "education": None,
        })
        assert e.candidate_name == ""
        assert e.skills == [] and e.education == []

    def test_skills_list_drops_empty_and_coerces(self):
        e = parse_llm_json(ExtractionResult, {"skills": ["Python", "", None, 42]})
        assert e.skills == ["Python", "42"]

    def test_work_history_item_defaults(self):
        e = parse_llm_json(ExtractionResult, {
            "work_history": [{"title": "Engineer", "start": "2019-01", "end": "present"}]
        })
        assert e.work_history[0].company == ""      # missing field defaulted
        assert e.work_history[0].end == "present"   # literal date text preserved
        assert e.work_history[0].raw == ""

    def test_extra_keys_ignored(self, caplog):
        with caplog.at_level(logging.INFO):
            e = parse_llm_json(ExtractionResult, {"candidate_name": "A", "salary": "100k"})
        assert not hasattr(e, "salary")
        assert e.candidate_name == "A"


class TestDetectorSchema:
    def test_confidence_clamped_0_1(self):
        assert parse_llm_json(DetectorResult, {"confidence": 5}).confidence == 1.0
        assert parse_llm_json(DetectorResult, {"confidence": -1}).confidence == 0.0

    def test_confidence_bad_type_defaults_zero(self):
        assert parse_llm_json(DetectorResult, {"confidence": "high"}).confidence == 0.0

    def test_missing_job_type_defaults_uncertain(self):
        assert parse_llm_json(DetectorResult, {"confidence": 0.9}).job_type == "uncertain"
