"""
Type definitions for the Resume Screening System.
Provides TypedDict classes for better type hints and IDE support.
"""
from typing import TypedDict, List, Optional, Literal


# Tier and Recommendation literals
TierType = Literal['top', 'mid', 'low']
RecommendationType = Literal['interview', 'talent_pool', 'reject']
ScreeningStatusType = Literal['pending', 'processing', 'completed', 'failed']


class WorkHistoryEntry(TypedDict, total=False):
    """A single raw employment span as returned by extraction (no date math).

    Dates are normalized strings ("YYYY-MM", "YYYY", or "present"); ``raw``
    preserves the original text for auditing.
    """
    title: str
    company: str
    start: str
    end: str
    raw: str


class ExtractionResult(TypedDict, total=False):
    """Result of resume text extraction.

    Note: ``experience_years`` is NOT produced by the LLM; it is computed in
    code from ``work_history`` (see services/experience.py).
    """
    candidate_name: str
    candidate_email: str
    candidate_phone: str
    skills: List[str]
    work_history: List[WorkHistoryEntry]
    education: List[str]
    certifications: List[str]
    achievements: List[str]


class MatchingResult(TypedDict, total=False):
    """Result of resume-job matching (LLM-provided sub-scores, clamped in code)."""
    matched_skills: List[str]
    missing_skills: List[str]
    experience_match_score: float
    education_match_score: float
    certification_match_score: Optional[float]
    achievement_score: float


class ScoringResult(TypedDict):
    """Result of resume scoring."""
    skill_score: float
    experience_score: float
    education_score: float
    certification_score: float
    final_score: float


class RankingResult(TypedDict):
    """Result of resume ranking."""
    tier: str
    recommendation: str
    reasoning: str


class ScreeningResult(TypedDict, total=False):
    """Complete screening result returned by screen_resume()."""
    # Extraction
    candidate_name: str
    candidate_email: str
    candidate_phone: str
    skills: List[str]
    work_history: List[WorkHistoryEntry]
    experience_years: float
    education: List[str]
    certifications: List[str]
    achievements: List[str]

    # Matching
    matched_skills: List[str]
    missing_skills: List[str]
    experience_match_score: float
    education_match_score: float
    certification_match_score: Optional[float]
    achievement_score: float

    # Scoring
    skill_score: float
    experience_score: float
    education_score: float
    certification_score: float
    final_score: float

    # Ranking
    tier: str
    recommendation: str
    reasoning: str

    # Error tracking
    error: Optional[str]


class ResumeCreateData(TypedDict, total=False):
    """Data for creating a resume."""
    candidate_name: str
    file_path: str
    job_id: int


class JobCreateData(TypedDict, total=False):
    """Data for creating a job."""
    title: str
    description: str
    status: Literal['draft', 'active', 'closed']
    posted_date: Optional[str]
    closing_date: Optional[str]
