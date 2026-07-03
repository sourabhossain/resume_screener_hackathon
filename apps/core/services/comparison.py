"""Candidate comparison helpers (pure, testable — no DB, no request).

Kept out of the template so the best-value and skills-union logic can be
unit-tested directly rather than expressed as template arithmetic.
"""
from collections import Counter


def best_value_flags(values):
    """Mark the position(s) holding the maximum among ``values``.

    - ``None`` entries are excluded from the computation and never marked.
    - Ties: every position equal to the max is marked.
    - All-None (or empty): every position is ``False``.
    """
    present = [v for v in values if v is not None]
    if not present:
        return [False] * len(values)
    top = max(present)
    return [v is not None and v == top for v in values]


def _education_lines(education):
    """Readable one-line-per-entry summary of a resume's education JSON.

    Defensive: entries may be plain strings or dicts of varying shape.
    """
    lines = []
    for item in (education or []):
        if isinstance(item, dict):
            parts = [str(item[k]) for k in ('degree', 'field', 'institution', 'year') if item.get(k)]
            text = ' · '.join(parts) if parts else ' '.join(str(v) for v in item.values() if v)
        else:
            text = str(item)
        text = text.strip()
        if text:
            lines.append(text)
    return lines


def build_skills_matrix(candidates, cap=15):
    """Union of candidates' matched_skills as rows, with per-candidate presence.

    Skills are matched case-insensitively (first-seen casing is displayed).
    Rows are ranked by coverage (how many candidates have the skill) then name,
    and capped at ``cap`` rows; the remainder is reported as ``overflow``.
    """
    counts = Counter()
    display = {}
    per_candidate = []
    for resume in candidates:
        present = set()
        for skill in (resume.matched_skills or []):
            key = str(skill).strip().lower()
            if not key:
                continue
            present.add(key)
            counts[key] += 1
            display.setdefault(key, str(skill).strip())
        per_candidate.append(present)

    ranked = sorted(counts, key=lambda k: (-counts[k], display[k].lower()))
    shown = ranked[:cap]
    rows = [
        {'skill': display[key], 'present': [key in cand for cand in per_candidate]}
        for key in shown
    ]
    return {'rows': rows, 'overflow': max(0, len(ranked) - cap), 'total': len(ranked)}


def _score_row(label, candidates, attr, fmt):
    values = [getattr(c, attr) for c in candidates]
    flags = best_value_flags(values)
    cells = [
        {'display': (fmt(v) if v is not None else None), 'best': flag}
        for v, flag in zip(values, flags)
    ]
    return {'label': label, 'cells': cells}


def build_comparison(candidates):
    """Assemble the comparison table structure for the given resumes (ordered).

    Returns numeric rows (each cell flagged best-value), an education summary
    row (text, not highlighted), and the skills matrix.
    """
    as_int = lambda v: f'{v:.0f}'
    one_dp = lambda v: f'{v:.1f}'

    score_rows = [
        _score_row('Final score', candidates, 'final_score', as_int),
        _score_row('Experience score', candidates, 'experience_score', as_int),
        _score_row('Education score', candidates, 'education_score', as_int),
        _score_row('Skills score', candidates, 'skills_score', as_int),
        _score_row('Certification score', candidates, 'certification_score', as_int),
        _score_row('Achievement score', candidates, 'achievement_score', as_int),
        _score_row('Experience (years)', candidates, 'experience_years', one_dp),
    ]

    # Certifications count: a real count (0 shown as 0), but a 0 is excluded from
    # best-value so an all-zero row highlights nobody.
    cert_counts = [len(c.certifications or []) for c in candidates]
    cert_flags = best_value_flags([c or None for c in cert_counts])
    score_rows.append({
        'label': 'Certifications',
        'cells': [{'display': str(n), 'best': flag} for n, flag in zip(cert_counts, cert_flags)],
    })

    education_cells = [_education_lines(c.education) for c in candidates]

    return {
        'score_rows': score_rows,
        'education_cells': education_cells,
        'skills_matrix': build_skills_matrix(candidates),
    }
