"""Starting values taken from what the candidate already told us.

The source document says the identity questions mirror the Employee Information
Form and that "Employer 1-4 must match the same employer number". Retyping ~40
fields off
another screen is where transcription errors come from -- a mistyped NID or a
shifted employer number sends the background check after the wrong facts -- so
the overlap is carried across and left editable.

Two things are deliberately never prefilled: anything that is HR's own finding
(verified? / discrepancy? / status), and the sign-off fields. A prefilled
judgement is a judgement nobody made.
"""
from django.utils import timezone

# HR question key <- Employee Information Form question key, where the two ask
# for the same fact in the same words.
DIRECT_MAP = {
    'candidate_full_name': 'candidate_full_name',
    'position_applied_for': 'position_applied_for',
    'department': 'department',

    'candidate_nid_number': 'nid_number',
    'candidate_birth_certificate_number': 'birth_certificate_number',
    'candidate_date_of_birth': 'date_of_birth',
    'candidate_present_address': 'present_address',
    'candidate_permanent_address': 'permanent_address',

    'highest_degree': 'highest_degree',
    'masters_institution': 'masters_institution',
    'masters_completion_date': 'masters_completion_date',
    'bachelors_institution': 'bachelors_institution',
    'bachelors_completion_date': 'bachelors_completion_date',
    'hsc_institution': 'hsc_institution',
    'hsc_passing_year': 'hsc_passing_year',
    'ssc_institution': 'ssc_institution',
    'ssc_passing_year': 'ssc_passing_year',
    'training_certification_names': 'training_certification_names',

    'additional_employer_notes': 'additional_employment_history',
}

# The candidate form asks for degree name and major separately; this one asks for
# "Degree / Major (as applicable)" in a single field.
DEGREE_MAJOR_SOURCES = {
    'masters_degree_major': ('masters_degree_name', 'masters_major'),
    'bachelors_degree_major': ('bachelors_degree_name', 'bachelors_major'),
}

# Per employer: HR suffix <- candidate suffix. Everything HR has to establish
# themselves (confirmed dates, verification status) is absent on purpose.
EMPLOYER_MAP = {
    'name': 'name',
    'hr_contact': 'hr_contact',
    'hr_email': 'hr_email',
    'position': 'position',
    'claimed_start_date': 'start_date',
    'claimed_end_date': 'end_date',
    'claimed_reason_leaving': 'reason_leaving',
}

REFERENCE_MAP = {
    'name': 'name',
    'designation': 'designation',
    'relationship': 'relationship',
    'contact': 'contact',
    'email': 'email',
}

EMPLOYER_COUNT = 4
REFERENCE_COUNT = 2


def _candidate_answers(resume) -> dict:
    """The candidate's own answers, or {} if they have no form yet."""
    form = getattr(resume, 'employee_form', None)
    return dict(form.answers or {}) if form else {}


def _joined(answers, keys):
    parts = [str(answers.get(k) or '').strip() for k in keys]
    return ' — '.join(p for p in parts if p)


def prefill_answers(resume, user=None) -> dict:
    """Values to start an HR verification with. Blanks are dropped."""
    candidate = _candidate_answers(resume)
    values = {}

    for hr_key, candidate_key in DIRECT_MAP.items():
        values[hr_key] = candidate.get(candidate_key)

    for hr_key, sources in DEGREE_MAJOR_SOURCES.items():
        values[hr_key] = _joined(candidate, sources)

    for index in range(1, EMPLOYER_COUNT + 1):
        for hr_suffix, candidate_suffix in EMPLOYER_MAP.items():
            values[f'employer_{index}_{hr_suffix}'] = candidate.get(
                f'employer_{index}_{candidate_suffix}'
            )

    for index in range(1, REFERENCE_COUNT + 1):
        for hr_suffix, candidate_suffix in REFERENCE_MAP.items():
            values[f'reference_{index}_{hr_suffix}'] = candidate.get(
                f'reference_{index}_{candidate_suffix}'
            )

    # Fall back to the Resume itself where the candidate never filled the form.
    values.setdefault('candidate_full_name', None)
    if not values.get('candidate_full_name'):
        values['candidate_full_name'] = (resume.candidate_name or '').strip()
    if not values.get('position_applied_for'):
        values['position_applied_for'] = (resume.job.title or '').strip()

    # HR's own starting context, not the candidate's.
    values['verification_start_date'] = timezone.localdate().isoformat()
    if user is not None:
        full_name = (user.get_full_name() or '').strip() or user.get_username()
        values['hr_reviewer_name'] = full_name

    return {key: value for key, value in values.items()
            if value not in (None, '', [])}


def pending_prefill(verification, user=None) -> dict:
    """Prefill values for questions HR has not answered yet.

    Applied on GET only, so a value HR cleared on purpose is not helpfully put
    back the next time they open the section.
    """
    answered = verification.answers or {}
    suggested = prefill_answers(verification.resume, user=user)
    return {
        key: value for key, value in suggested.items()
        if answered.get(key) in (None, '', [])
    }
