"""
Prompt Loader - Loads and formats prompt templates from files.
"""
import datetime
from pathlib import Path
from functools import lru_cache
from typing import Any

PROMPTS_DIR = Path(__file__).parent.parent / 'prompts'


@lru_cache(maxsize=10)
def load_prompt(prompt_name: str) -> str:
    """
    Load a prompt template from file.
    
    Args:
        prompt_name: Name of the prompt file (without .txt extension)
        
    Returns:
        Prompt template string
        
    Raises:
        FileNotFoundError: If prompt file doesn't exist
    """
    prompt_path = PROMPTS_DIR / f"{prompt_name}.txt"
    
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt template not found: {prompt_path}")
    
    with open(prompt_path, 'r', encoding='utf-8') as f:
        return f.read()


def format_prompt(prompt_name: str, **kwargs: Any) -> str:
    """
    Load and format a prompt template with provided values.
    
    Args:
        prompt_name: Name of the prompt file (without .txt extension)
        **kwargs: Values to substitute in the template
        
    Returns:
        Formatted prompt string
    """
    template = load_prompt(prompt_name)
    return template.format(**kwargs)


def get_extraction_prompt(resume_text: str) -> str:
    """Get formatted extraction prompt for resume parsing (uses tech/ role by default)."""
    current_year = datetime.date.today().year
    return format_prompt('tech/extraction', resume_text=resume_text, current_year=current_year)


def get_matching_prompt(
    job_description: str,
    candidate_name: str,
    skills: str,
    experience_years: float,
    education: str,
    certifications: str
) -> str:
    """Get formatted matching prompt for job-resume comparison (uses tech/ role by default)."""
    return format_prompt(
        'tech/matching',
        job_description=job_description,
        candidate_name=candidate_name,
        skills=skills,
        experience_years=experience_years,
        education=education,
        certifications=certifications,
        achievements=''
    )


def get_reasoning_prompt(
    candidate_name: str,
    final_score: float,
    tier: str,
    matched_skills: str,
    missing_skills: str,
    experience_years: float
) -> str:
    """Get formatted reasoning prompt for recommendation generation."""
    return format_prompt(
        'reasoning',
        candidate_name=candidate_name,
        final_score=final_score,
        tier=tier,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        experience_years=experience_years
    )


def clear_prompt_cache() -> None:
    """Clear the prompt cache. Useful for development/testing."""
    load_prompt.cache_clear()
