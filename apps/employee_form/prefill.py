"""Values the system already knows, offered as starting answers.

Scope is deliberately narrow: identity and contact details already on the
application, plus the job applied to. The document-backed answers (education,
institutions, GPA, years of experience, certifications) are NOT prefilled even
though `Resume` holds AI-extracted versions of them — this form exists so the
candidate declares those "exactly as shown on your official documents" and signs
for their accuracy in Section D7. Prefilling a model's guess invites a
click-through, and any extraction error would then travel to a background-check
agency as something the candidate personally declared.

Note on provenance, because it is not uniform:
  * `email` / `phone` — genuinely the candidate's own. ResumeService only fills
    these from AI output when they are still blank.
  * `candidate_name` — machine-read from the CV. ResumeService overwrites it with
    the extraction on every screening pass, so it is a guess like any other, and
    often arrives shouty (e.g. "MD. TAUKIR AHMED"). Still worth offering: a wrong
    name is the one error a candidate cannot miss, and a blank field is worse.
  * `position_applied_for` — from the Job record, so authoritative.

Every prefilled value stays editable, and the step template labels it as coming
from the earlier submission so the candidate is prompted to check, not assume.
"""
def prefill_answers(resume) -> dict:
    """Starting answers for a candidate's form, keyed by schema question."""
    values = {
        # Read off the CV by the screener, so treat as a suggestion.
        'candidate_full_name': (resume.candidate_name or '').strip(),
        # The candidate's own, unless they left them off the application.
        'mobile_number': (resume.phone or '').strip(),
        'personal_email': (resume.email or '').strip(),
        # From the Job record.
        'position_applied_for': (resume.job.title or '').strip(),
        # The signature is never prefilled or suggested — that would defeat the
        # point of it. The declaration's date comes from submitted_at, not from
        # anything the candidate can set.
    }
    return {key: value for key, value in values.items() if value}


def pending_prefill(resume, answers: dict) -> dict:
    """Prefill values for questions the candidate has not answered yet.

    Anything already saved wins, so revisiting a step never overwrites what the
    candidate typed with what the system assumed.
    """
    saved = answers or {}
    return {
        key: value
        for key, value in prefill_answers(resume).items()
        if not saved.get(key)
    }
