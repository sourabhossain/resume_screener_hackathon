"""Reshapes a submitted form into blocks built for reviewing, not for filling in.

The source form's structure is a data-entry sequence: 130 questions in the order
they are convenient to type. Rendering that back verbatim gives a recruiter sixty
identical label/value rows with no hierarchy — every optional blank weighted the
same as the NID number.

So the review page is assembled around what a recruiter actually checks:
  * the handful of identity facts, up front
  * education as one comparison table across the four levels
  * each employer and referee as its own card
  * everything else as a plain list, with unanswered optional fields folded away

`EmployeeForm.answered_sections()` stays as the faithful question-by-question
view; this module is the reviewer's lens over the same answers.
"""
from . import schema

# Education levels in the order the form asks for them, highest first.
EDUCATION_LEVELS = [
    {
        'level': "Master's / Postgraduate",
        'optional': True,
        'institution': 'masters_institution',
        'qualification': 'masters_degree_name',
        'major': 'masters_major',
        'result': None,
        'finished': 'masters_completion_date',
        'certificate': 'masters_certificate',
    },
    {
        'level': "Undergraduate / Bachelor's",
        'optional': False,
        'institution': 'bachelors_institution',
        'qualification': 'bachelors_degree_name',
        'major': 'bachelors_major',
        'result': None,
        'finished': 'bachelors_completion_date',
        'certificate': 'bachelors_certificate',
    },
    {
        'level': 'HSC / A Level',
        'optional': False,
        'institution': 'hsc_institution',
        'qualification': 'hsc_board',
        'major': None,
        'result': 'hsc_result',
        'finished': 'hsc_passing_year',
        'certificate': 'hsc_certificate',
    },
    {
        'level': 'SSC / O Level',
        'optional': False,
        'institution': 'ssc_institution',
        'qualification': 'ssc_board',
        'major': None,
        'result': 'ssc_result',
        'finished': 'ssc_passing_year',
        'certificate': 'ssc_certificate',
    },
]

# Questions surfaced in the header strip. Everything here is something a
# recruiter checks against an ID document before anything else.
KEY_FACT_KEYS = [
    ('nid_number', 'NID number'),
    ('date_of_birth', 'Date of birth'),
    ('mobile_number', 'Mobile'),
    ('personal_email', 'Email'),
    ('total_experience_years', 'Experience (years)'),
    ('availability_status', 'Availability'),
]

# Sections rendered by the purpose-built blocks above, so the generic list must
# not repeat them.
SPECIALISED_STEPS = frozenset(
    {'section_b', 'reference_1', 'reference_2'}
    | {f'employer_{i}' for i in range(1, 5)}
)

# Always rendered in the page header, so repeating them lower down is noise.
HEADER_KEYS = frozenset({'candidate_full_name', 'position_applied_for'})


def _files_by_key(form):
    grouped = {}
    for upload in form.documents():
        grouped.setdefault(upload.question_key, []).append(upload)
    return grouped


def _value(form, key):
    question = schema.QUESTIONS_BY_KEY.get(key)
    if not question:
        return ''
    return form.display_value(question)


def key_facts(form):
    """Identity facts for the header strip, skipping any left blank.

    Returns (facts, shown_keys). The caller uses `shown_keys` to drop these from
    the sections below — computed from what was actually rendered, so a blank
    field is never suppressed in both places and lost.
    """
    out, shown = [], set()
    for key, label in KEY_FACT_KEYS:
        value = _value(form, key)
        if value:
            out.append({'label': label, 'value': value})
            shown.add(key)
    return out, shown


def education_table(form):
    """One row per education level, with its certificate attached.

    Optional levels the candidate did not fill in are dropped rather than shown
    as four empty cells.
    """
    files = _files_by_key(form)
    rows = []
    for level in EDUCATION_LEVELS:
        institution = _value(form, level['institution'])
        certificate = files.get(level['certificate'], [])
        if level['optional'] and not institution and not certificate:
            continue
        rows.append({
            'level': level['level'],
            'institution': institution,
            'qualification': _value(form, level['qualification']),
            'major': _value(form, level['major']) if level['major'] else '',
            'result': _value(form, level['result']) if level['result'] else '',
            'finished': _value(form, level['finished']),
            'files': certificate,
        })
    return rows


def training(form):
    """Training and certification names plus their uploads."""
    files = _files_by_key(form)
    return {
        'names': _value(form, 'training_certification_names'),
        'files': files.get('training_certificates', []),
    }


def employers(form):
    """One card per employer the candidate actually declared.

    Employers 2-4 are optional, so a candidate with one previous job produces one
    card rather than three empty ones. `may_contact` matters to whoever runs the
    background check: a "No" means that employer must not be approached.
    """
    out = []
    for index in range(1, 5):
        name = _value(form, f'employer_{index}_name')
        if not name:
            continue
        out.append({
            'index': index,
            'name': name,
            'position': _value(form, f'employer_{index}_position'),
            'start': _value(form, f'employer_{index}_start_date'),
            'end': _value(form, f'employer_{index}_end_date'),
            'reason': _value(form, f'employer_{index}_reason_leaving'),
            'hr_contact': _value(form, f'employer_{index}_hr_contact'),
            'hr_email': _value(form, f'employer_{index}_hr_email'),
            'may_contact': (form.answers or {}).get(
                f'employer_{index}_contact_permission', ''),
        })
    return {
        'items': out,
        'additional': _value(form, 'additional_employment_history'),
    }


def references(form):
    """One card per professional referee."""
    out = []
    for index in (1, 2):
        name = _value(form, f'reference_{index}_name')
        if not name:
            continue
        out.append({
            'index': index,
            'name': name,
            'designation': _value(form, f'reference_{index}_designation'),
            'relationship': _value(form, f'reference_{index}_relationship'),
            'contact': _value(form, f'reference_{index}_contact'),
            'email': _value(form, f'reference_{index}_email'),
            'may_contact': (form.answers or {}).get(
                f'reference_{index}_contact_permission', ''),
        })
    return out


def _has_answer(row) -> bool:
    """Whether a row carries an answer.

    Not a truth test: a numeric answer of 0 -- no notice period, a team of none --
    is an answer, and truthiness would file it under "not answered".
    `display_value` already returns '' for a genuinely empty one.
    """
    return row['value'] != '' or bool(row['files'])


def narrative_sections(form, suppress=frozenset()):
    """The remaining sections as answered/unanswered lists.

    Blank optional answers are separated out so the page shows what the candidate
    said, with the gaps available but folded away. `suppress` drops questions
    already shown in the page header.
    """
    out = []
    for section in form.answered_sections():
        if section['key'] in SPECIALISED_STEPS:
            continue
        rows = [r for r in section['rows'] if r['key'] not in suppress]
        answered = [r for r in rows if _has_answer(r)]
        missing = [r for r in rows if not _has_answer(r)]
        if not answered and not missing:
            continue
        out.append({
            'key': section['key'],
            'section': section['section'],
            'title': section['title'],
            'answered': answered,
            'missing': missing,
        })
    return out


def build(form):
    """Everything the review template needs, in one call."""
    facts, shown = key_facts(form)
    return {
        'key_facts': facts,
        'education': education_table(form),
        'training': training(form),
        'employers': employers(form),
        'references': references(form),
        'narrative': narrative_sections(form, suppress=shown | HEADER_KEYS),
    }
