"""
Prompt Loader - Composes role prompts from a shared base plus a per-role fragment.

Architecture:
    prompts/_base/extraction_base.txt   shared extraction prompt (safety, schema)
    prompts/_base/matching_base.txt     shared matching prompt (safety, schema)
    prompts/roles/<role>.fragment.txt   per-role title, skill taxonomy, score bands
    prompts/job_type_detector.txt       detector (standalone)
    prompts/reasoning.txt               reasoning (standalone)

Bases use [[DOUBLE_BRACKET]] sentinels injected via str.replace (never
str.format) so the literal JSON braces in the schema examples cannot break
composition. Fragments are split into named sections by "@@ SECTION" headers.
"""
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from .job_families import render_catalog, FALLBACK_ROLE

PROMPTS_DIR = Path(__file__).parent.parent / 'prompts'
BASE_DIR = PROMPTS_DIR / '_base'
ROLES_DIR = PROMPTS_DIR / 'roles'

# Defensive fragment fallback only (a valid family with a missing file).
# Routing of uncertain jobs is handled upstream by flagging for manual review.
DEFAULT_ROLE = FALLBACK_ROLE


@lru_cache(maxsize=8)
def _read_text(path: str) -> str:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Prompt file not found: {p}")
    return p.read_text(encoding='utf-8')


def _fragment_path(role: str) -> Path:
    """Role fragment path, falling back to the default role if absent."""
    candidate = ROLES_DIR / f"{role}.fragment.txt"
    if candidate.exists():
        return candidate
    return ROLES_DIR / f"{DEFAULT_ROLE}.fragment.txt"


@lru_cache(maxsize=16)
def parse_fragment(role: str) -> Dict[str, str]:
    """Parse a role fragment into {SECTION_NAME: text}. Falls back to default role."""
    text = _read_text(str(_fragment_path(role)))
    sections: Dict[str, list] = {}
    current = None
    for line in text.splitlines():
        if line.startswith('@@ '):
            current = line[3:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {name: '\n'.join(lines).strip() for name, lines in sections.items()}


def _inject(template: str, replacements: Dict[str, str]) -> str:
    for sentinel, value in replacements.items():
        template = template.replace(f"[[{sentinel}]]", value)
    return template


def build_extraction_prompt(role: str, resume_text: str) -> str:
    """Compose the extraction prompt for a role."""
    base = _read_text(str(BASE_DIR / 'extraction_base.txt'))
    frag = parse_fragment(role)
    return _inject(base, {
        'ROLE_TITLE': frag.get('ROLE_TITLE', ''),
        'ROLE_SKILL_TAXONOMY': frag.get('ROLE_SKILL_TAXONOMY', ''),
        'RESUME_TEXT': resume_text,
    })


def build_matching_prompt(role: str, job_description: str, profile: Dict[str, Any]) -> str:
    """Compose the matching prompt for a role. The candidate profile is the
    only source of candidate facts and is passed as a JSON block."""
    base = _read_text(str(BASE_DIR / 'matching_base.txt'))
    frag = parse_fragment(role)
    return _inject(base, {
        'ROLE_TITLE': frag.get('ROLE_TITLE', ''),
        'ROLE_MATCH_CRITERIA': frag.get('ROLE_MATCH_CRITERIA', ''),
        'JOB_DESCRIPTION': job_description,
        'PROFILE_JSON': json.dumps(profile, ensure_ascii=False, indent=2),
    })


def build_detector_prompt(job_description: str) -> str:
    """Compose the job-type detector prompt, injecting the family catalog from
    the single source of truth so detector labels always match the fragments."""
    template = _read_text(str(PROMPTS_DIR / 'job_type_detector.txt'))
    return _inject(template, {
        'JOB_TYPE_CATALOG': render_catalog(),
        'JOB_DESCRIPTION': job_description,
    })


# --- Backward-compatible convenience wrappers (default role) -----------------

def get_extraction_prompt(resume_text: str, role: str = DEFAULT_ROLE) -> str:
    """Formatted extraction prompt (defaults to the tech role)."""
    return build_extraction_prompt(role, resume_text)


def get_matching_prompt(
    job_description: str,
    candidate_name: str,
    skills: str,
    experience_years: float,
    education: str,
    certifications: str,
    achievements: str = '',
    role: str = DEFAULT_ROLE,
) -> str:
    """Formatted matching prompt (defaults to the tech role)."""
    profile = {
        'candidate_name': candidate_name,
        'skills': skills,
        'experience_years': experience_years,
        'education': education,
        'certifications': certifications,
        'achievements': achievements,
    }
    return build_matching_prompt(role, job_description, profile)


def get_reasoning_prompt(
    candidate_name: str,
    final_score: float,
    tier: str,
    matched_skills: str,
    missing_skills: str,
    experience_years: float,
    education: str = '',
    certifications: str = '',
    achievements: str = '',
) -> str:
    """Formatted reasoning prompt for recommendation generation."""
    template = _read_text(str(PROMPTS_DIR / 'reasoning.txt'))
    return template.format(
        candidate_name=candidate_name,
        final_score=final_score,
        tier=tier,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        experience_years=experience_years,
        education=education,
        certifications=certifications,
        achievements=achievements,
    )


def clear_prompt_cache() -> None:
    """Clear prompt caches. Useful for development/testing."""
    _read_text.cache_clear()
    parse_fragment.cache_clear()
