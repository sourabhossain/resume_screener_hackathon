"""
Pydantic schemas for LLM outputs (extraction, matching, detection).

Why this exists:
The prompts instruct the model to "return exactly one valid JSON object", but an
instruction is not a guarantee. Without code-side validation, a renamed or omitted
key would be silently swallowed by ``response.get(key, default)`` and corrupt a
candidate's scores with no signal. These schemas make the contract enforceable:

  * every field has ONE canonical name, type, and default (single source of truth);
  * numeric scores are coerced and clamped to their valid range in one place;
  * missing/renamed/extra keys are LOGGED as drift instead of failing silently;
  * parsing never raises into the pipeline — on bad input it falls back to
    defaults (matching the resilient-degradation philosophy elsewhere), but the
    fallback is always recorded so drift is observable.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Type, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

logger = logging.getLogger(__name__)

_SCORE_LO, _SCORE_HI = 0.0, 100.0


def _to_str(v) -> str:
    """Coerce any scalar to a stripped string; None/containers -> ''."""
    if v is None or isinstance(v, (list, dict)):
        return ""
    return str(v).strip()


def _to_str_list(v) -> List[str]:
    """Coerce to a list of non-empty strings; tolerate None or a bare string."""
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return []
    out = []
    for item in v:
        s = _to_str(item)
        if s:
            out.append(s)
    return out


def _clamp_score(v, default: float = 0.0) -> float:
    try:
        return max(_SCORE_LO, min(_SCORE_HI, float(v)))
    except (TypeError, ValueError):
        return default


class WorkHistoryItem(BaseModel):
    """One role span. Dates stay as literal text — duration is computed in code."""
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    company: str = ""
    start: str = ""
    end: str = ""
    raw: str = ""

    @field_validator("title", "company", "start", "end", "raw", mode="before")
    @classmethod
    def _coerce_str(cls, v):
        return _to_str(v)


class ExtractionResult(BaseModel):
    """Contract for the extraction prompt. experience_years is intentionally
    absent — it is computed in code from work_history."""
    model_config = ConfigDict(extra="ignore")

    candidate_name: str = ""
    candidate_email: str = ""
    candidate_phone: str = ""
    skills: List[str] = []
    work_history: List[WorkHistoryItem] = []
    education: List[str] = []
    certifications: List[str] = []
    achievements: List[str] = []

    @field_validator("candidate_name", "candidate_email", "candidate_phone", mode="before")
    @classmethod
    def _coerce_str(cls, v):
        return _to_str(v)

    @field_validator("skills", "education", "certifications", "achievements", mode="before")
    @classmethod
    def _coerce_list(cls, v):
        return _to_str_list(v)

    @field_validator("work_history", mode="before")
    @classmethod
    def _coerce_wh(cls, v):
        return v if isinstance(v, list) else []


class MatchingResult(BaseModel):
    """Contract for the matching prompt. Component scores are clamped to 0-100.
    certification_match_score stays Optional: None means "model did not score it"
    so code can fall back to a certification-count heuristic."""
    model_config = ConfigDict(extra="ignore")

    experience_match_score: float = 0.0
    education_match_score: float = 0.0
    certification_match_score: Optional[float] = None
    achievement_score: float = 0.0
    matched_skills: List[str] = []
    missing_skills: List[str] = []

    @field_validator("experience_match_score", "education_match_score", "achievement_score", mode="before")
    @classmethod
    def _clamp(cls, v):
        return _clamp_score(v)

    @field_validator("certification_match_score", mode="before")
    @classmethod
    def _clamp_optional(cls, v):
        if v is None:
            return None
        return _clamp_score(v)

    @field_validator("matched_skills", "missing_skills", mode="before")
    @classmethod
    def _coerce_list(cls, v):
        return _to_str_list(v)


class DetectorResult(BaseModel):
    """Contract for the job-type detector prompt. Label validity against the
    family catalog is enforced by the caller (detect_job_type)."""
    model_config = ConfigDict(extra="ignore")

    job_type: str = "uncertain"
    confidence: float = 0.0
    runner_up: str = ""
    signals: List[str] = []

    @field_validator("job_type", "runner_up", mode="before")
    @classmethod
    def _coerce_str(cls, v):
        return _to_str(v)

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, v):
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0

    @field_validator("signals", mode="before")
    @classmethod
    def _coerce_list(cls, v):
        return _to_str_list(v)


class VerificationItem(BaseModel):
    """Contract for the per-link verification LLM output. Without this, a model
    that returns verified_claims as a bare string would be ``.extend()``-ed
    character-by-character into the aggregate claim list."""
    model_config = ConfigDict(extra="ignore")

    belongs_to_candidate: bool = False
    verified_claims: List[str] = []
    discrepancies: List[str] = []
    additional_insights: List[str] = []
    confidence: float = 0.0

    @field_validator("verified_claims", "discrepancies", "additional_insights", mode="before")
    @classmethod
    def _coerce_list(cls, v):
        return _to_str_list(v)

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, v):
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0

    @field_validator("belongs_to_candidate", mode="before")
    @classmethod
    def _coerce_bool(cls, v):
        if isinstance(v, str):
            return v.strip().lower() in {"true", "1", "yes"}
        return bool(v)


_M = TypeVar("_M", bound=BaseModel)


def parse_llm_json(model_cls: Type[_M], raw, *, context: str = "") -> _M:
    """Validate a parsed LLM JSON object against a schema, logging any drift.

    Never raises into the pipeline: malformed input or a failed validation yields
    a defaults-only instance, but the fallback is always logged so silent schema
    drift can't happen. Missing/renamed keys are surfaced as warnings.
    """
    if not isinstance(raw, dict):
        logger.warning(
            "LLM output for %s was not a JSON object (got %s); using defaults",
            context or model_cls.__name__, type(raw).__name__,
        )
        return model_cls()

    expected = set(model_cls.model_fields)
    present = set(raw)
    missing = expected - present
    unexpected = present - expected
    if missing:
        logger.warning(
            "LLM output for %s is missing keys %s — possible prompt/schema drift; "
            "defaulting them", context or model_cls.__name__, sorted(missing),
        )
    if unexpected:
        logger.info(
            "LLM output for %s had unexpected keys %s (ignored)",
            context or model_cls.__name__, sorted(unexpected),
        )

    try:
        return model_cls.model_validate(raw)
    except ValidationError as e:
        logger.warning(
            "LLM output for %s failed schema validation (%s); using defaults",
            context or model_cls.__name__, e,
        )
        return model_cls()
