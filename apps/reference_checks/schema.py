"""The external verification forms, as data.

Source: the client's FINAL PDFs -- "Previous Employer Verification Form" (Q1-Q24)
-> EMPLOYER and "Professional Reference Check Form" (Q1-Q26) -> PROFESSIONAL, one
step per PDF section (A-E), labels, options and required marks as printed.
ACADEMIC is not in the final PDFs; it is kept only so older requests still open.
Branching uses show_if / required_if (apps/core/form_logic.py).
"""
from apps.core.form_logic import when
from apps.employee_form.schema import (  # noqa: F401
    BOOLEAN,
    CHOICE_TYPES,
    DATE,
    EMAIL,
    PHONE,
    RADIO,
    SELECT,
    TEXT,
    TEXTAREA,
    YEAR,
)

EMPLOYER = 'employer'
PROFESSIONAL = 'professional'
ACADEMIC = 'academic'

SENDABLE_KINDS = (EMPLOYER, PROFESSIONAL)

KIND_LABELS = {
    EMPLOYER: 'Previous Employer Verification',
    PROFESSIONAL: 'Professional Reference Check',
    ACADEMIC: 'Academic Reference Check',
}

FORM_TITLES = {
    EMPLOYER: 'Previous Employer Verification Form',
    PROFESSIONAL: 'Professional Reference Check Form',
    ACADEMIC: 'Academic Reference Check Form',
}

HEADERS = {
    EMPLOYER: 'CONFIDENTIAL — For employment background verification purposes only',
    PROFESSIONAL: 'CONFIDENTIAL — For recruitment background verification purposes only',
}

INTROS = {
    EMPLOYER: (
        'SSL Wireless is conducting an employment background verification for the '
        'candidate named below. The candidate has authorised SSL Wireless and/or its '
        'authorised background verification representative to verify employment '
        "information. Please provide factual information from your organisation's "
        'records and only information you are authorised to disclose.'
    ),
    PROFESSIONAL: (
        'SSL Wireless is conducting a professional reference check for the candidate '
        'named below. The candidate has authorised SSL Wireless and/or its authorised '
        'background verification representative to contact the professional '
        'references provided as part of the recruitment process. Please answer based '
        'on your direct professional knowledge of the candidate and provide only '
        'factual information that you are authorised to disclose.'
    ),
}


def _q(key, label, qtype=TEXT, required=False, help='', choices=None, no=None,
       show_if=None, required_if=None, readonly=False, statement=None):
    q = {'key': key, 'label': label, 'type': qtype, 'required': required, 'help': help}
    if statement:
        q['statement'] = statement
    if choices is not None:
        q['choices'] = choices
    if no is not None:
        q['no'] = no
    if show_if:
        q['show_if'] = show_if
    if required_if:
        q['required_if'] = required_if
    if readonly:
        q['readonly'] = True
    return q


def _other(key, choice_key):
    """The "Other: ____" companion, asked only while Other is picked."""
    return _q(key, 'Other: please specify', required=True,
              show_if=when(choice_key, 'other'))


def _step(key, section, title, questions, next_key, description=''):
    return {'key': key, 'section': section, 'title': title,
            'description': description, 'next': next_key, 'questions': questions}


# ── Shared choice sets ───────────────────────────────────────────────────
YES_NO = [('yes', 'Yes'), ('no', 'No')]

CONCERN_CHOICES = [
    ('no', 'No'),
    ('yes', 'Yes'),
    ('unable', 'Not Disclosed / Unable to Comment'),
]

CLARIFICATION_LABEL = (
    'May SSL Wireless HR or its authorised background verification representative '
    'contact you if clarification is required?'
)

DECLARATION_CHOICES = [('yes', 'Confirmed'), ('no', 'Not confirmed')]
EMPLOYER_DECLARATION = (
    'I confirm that the information provided above is accurate to the best of my '
    'knowledge, is based on information I am authorised to disclose, and may be used '
    'by SSL Wireless for recruitment background verification. By submitting this form, '
    'I provide my confirmation.'
)
PROFESSIONAL_DECLARATION = (
    'I confirm that the information provided above is accurate to the best of my '
    'knowledge, is based on my direct professional knowledge of the candidate, is '
    'limited to information I am authorised to disclose, and may be used by SSL '
    'Wireless for recruitment background verification. By submitting this form, I '
    'provide my confirmation.'
)

CANDIDATE_NAME = _q('candidate_full_name', 'Candidate Full Name', required=True, no=1,
                    readonly=True)
REFERENCE_ID_LABEL = 'SSL Wireless Verification Reference ID'

# Stored values of the old (pre-FINAL) schema, so older replies still read in words.
LEGACY_CHOICE_LABELS = {
    'resignation': 'Voluntary resignation',
    'end_of_contract': 'End of contract',
    'involuntary': 'Involuntary separation',
    'yes_reservations': 'Yes, with reservations',
    'average': 'Average',
    'below_average': 'Below Average',
    'na': 'N/A',
    'not_known': 'Not known / Not disclosed',
}


# ── Previous Employer Verification Form ──────────────────────────────────
EMPLOYMENT_TYPE_CHOICES = [
    ('full_time', 'Full-time / Permanent'),
    ('contractual', 'Contractual'),
    ('project_based', 'Project-based'),
    ('consultant', 'Consultant'),
    ('internship', 'Internship / Trainee'),
    ('other', 'Other'),
    ('not_disclosed', 'Not Disclosed'),
]
SEPARATION_NATURE_CHOICES = [
    ('currently_employed', 'Currently Employed'),
    ('voluntary_resignation', 'Voluntary Resignation'),
    ('contract_completion', 'Contract Completion'),
    ('redundancy', 'Redundancy / Retrenchment'),
    ('asked_to_resign', 'Asked to Resign'),
    ('termination', 'Termination / Dismissal'),
    ('other', 'Other'),
    ('not_disclosed', 'Not Disclosed'),
]
REHIRE_CHOICES = [
    ('yes', 'Yes'),
    ('no', 'No'),
    ('conditional', 'Conditional / With Reservations'),
    ('not_disclosed', 'Not Disclosed'),
    ('not_applicable', 'Not Applicable'),
]
WAS_EMPLOYED_CHOICES = [('yes', 'Yes'), ('no', 'No'), ('unable', 'Unable to Verify')]

_LEFT = when('currently_employed', 'no')

EMPLOYER_STEPS = [
    _step('candidate', 'Section A', 'Candidate & Verification Reference', [
        CANDIDATE_NAME,
        _q('verifier_organisation', 'Organisation / Employer Name', required=True, no=2,
           readonly=True),
        _q('verification_reference_id', REFERENCE_ID_LABEL, required=True, no=3,
           readonly=True),
    ], 'respondent'),
    _step('respondent', 'Section B', 'Respondent / Authorised Representative Details', [
        _q('verifier_name', 'Your Full Name', required=True, no=4),
        _q('verifier_designation', 'Your Designation / Position', required=True, no=5),
        _q('verifier_department', 'Department / Function', no=6),
        _q('verifier_email', 'Official Work Email Address', EMAIL, required=True, no=7),
        _q('verifier_contact', 'Official Contact Number', PHONE, required=True, no=8),
        _q('verifier_authorised',
           'Are you authorised to provide employment verification information on '
           'behalf of this organisation?', RADIO, required=True, choices=YES_NO, no=9),
    ], 'employment'),
    _step('employment', 'Section C', 'Employment Verification', [
        _q('was_employed',
           'Can you confirm that the candidate was / is employed by your organisation?',
           RADIO, required=True, choices=WAS_EMPLOYED_CHOICES, no=10),
        _q('employment_type', 'Confirmed Employment Type', RADIO, required=True,
           choices=EMPLOYMENT_TYPE_CHOICES, no=11),
        _other('employment_type_other', 'employment_type'),
        _q('last_designation', 'Confirmed Most Recent / Final Position or Designation',
           required=True, no=12),
        _q('confirmed_department', 'Confirmed Department / Business Unit (if available)',
           no=13),
        _q('employment_start_date', 'Confirmed Employment Start Date', DATE,
           required=True, no=14),
        _q('currently_employed', 'Is the candidate currently employed by your organisation?',
           RADIO, required=True, choices=YES_NO, no=15),
        _q('employment_end_date', 'Confirmed Employment End Date', DATE, required=True,
           no=16, help='Leave blank if currently employed.', show_if=_LEFT),
        _q('separation_reason', 'Confirmed Reason for Leaving / Separation', TEXTAREA,
           no=17, required_if=_LEFT),
        _q('separation_nature', 'Nature of Separation', RADIO,
           choices=SEPARATION_NATURE_CHOICES, no=18, required_if=_LEFT),
        _other('separation_nature_other', 'separation_nature'),
        _q('rehire_eligible', 'Is the candidate eligible for rehire / re-employment?',
           RADIO, choices=REHIRE_CHOICES, no=19),
        _q('additional_information',
           'Any additional factual employment information or correction you would like '
           'SSL Wireless to note?', TEXTAREA, no=20),
    ], 'conduct', description=(
        'Please answer from official organisational records. SSL Wireless will compare '
        'the information internally; you do not need to assess whether it matches '
        'information provided by the candidate.'
    )),
    _step('conduct', 'Section D', 'Conduct / Integrity Information', [
        _q('conduct_concerns',
           'To your direct knowledge, is there any formal or substantiated performance, '
           'disciplinary, integrity or conduct concern recorded by the organisation that '
           'is relevant to employment verification?', RADIO, required=True,
           choices=CONCERN_CHOICES, no=21),
        _q('conduct_details',
           'If Yes, please provide factual details that you are authorised to disclose.',
           TEXTAREA, required=True, no=22, show_if=when('conduct_concerns', 'yes')),
    ], 'confirmation', description=(
        'Please provide only substantiated information that your organisation is '
        'authorised to disclose. Do not include rumours, speculation or unverified '
        'allegations.'
    )),
    _step('confirmation', 'Section E', 'Verification Confirmation', [
        _q('clarification_contact', CLARIFICATION_LABEL, RADIO, required=True,
           choices=YES_NO, no=23),
        _q('declaration', 'Declaration', BOOLEAN, required=True, no=24,
           choices=DECLARATION_CHOICES, statement=EMPLOYER_DECLARATION),
    ], None),
]


# ── Professional Reference Check Form ────────────────────────────────────
REFEREE_RELATIONSHIP_CHOICES = [
    ('direct_manager', 'Direct Manager'),
    ('skip_level_manager', 'Skip-level Manager'),
    ('peer', 'Peer / Colleague'),
    ('direct_report', 'Direct Report'),
    ('hr', 'HR Representative'),
    ('client', 'Client / Business Stakeholder'),
    ('academic', 'Academic Supervisor / Faculty'),
    ('other', 'Other'),
]
CLOSENESS_CHOICES = [
    ('daily', 'Daily / Very Closely'),
    ('frequently', 'Frequently'),
    ('occasionally', 'Occasionally'),
    ('limited', 'Limited Interaction'),
    ('other', 'Other'),
]
_RATING = [
    ('excellent', 'Excellent'),
    ('very_good', 'Very Good'),
    ('good', 'Good'),
    ('satisfactory', 'Satisfactory'),
    ('needs_improvement', 'Needs Improvement'),
]
RATING_CHOICES = [*_RATING, ('unable', 'Unable to Comment')]
LEADERSHIP_CHOICES = [*_RATING, ('na', 'Not Applicable / Unable to Comment')]
HIRE_AGAIN_CHOICES = [
    ('yes', 'Yes'),
    ('no', 'No'),
    ('conditional', 'Conditional / With Reservations'),
    ('unable', 'Not Applicable / Unable to Comment'),
]

PROFESSIONAL_STEPS = [
    _step('candidate', 'Section A', 'Candidate & Reference Details', [
        CANDIDATE_NAME,
        _q('position_applied_for', 'Position Applied For at SSL Wireless', no=2,
           readonly=True),
        _q('verification_reference_id', REFERENCE_ID_LABEL, required=True, no=3,
           readonly=True),
        _q('referee_name', 'Your Full Name', required=True, no=4),
        _q('referee_designation', 'Your Designation / Position', required=True, no=5),
        _q('referee_organisation', 'Your Organisation / Company / Institution',
           required=True, no=6),
        _q('referee_email', 'Official Work Email Address', EMAIL, required=True, no=7),
        _q('referee_contact', 'Contact Number', PHONE, required=True, no=8),
        _q('referee_relationship', 'Your professional relationship with the candidate',
           RADIO, required=True, choices=REFEREE_RELATIONSHIP_CHOICES, no=9),
        _other('referee_relationship_other', 'referee_relationship'),
        _q('known_duration',
           'Approximately how long have you known or worked with the candidate?',
           required=True, no=10),
    ], 'relationship'),
    _step('relationship', 'Section B', 'Working Relationship & Role Context', [
        _q('work_context',
           'In what organisation, team, project or professional context did you work '
           'with the candidate?', TEXTAREA, required=True, no=11),
        _q('main_responsibilities',
           "Please briefly describe the candidate's role and key responsibilities as you "
           'directly observed them.', TEXTAREA, required=True, no=12),
        _q('working_closeness', 'How closely did you work with the candidate?', RADIO,
           required=True, choices=CLOSENESS_CHOICES, no=13),
        _other('working_closeness_other', 'working_closeness'),
    ], 'performance'),
    _step('performance', 'Section C', 'Professional Performance & Behaviour', [
        _q('strongest_qualities',
           "What would you consider the candidate's key professional strengths?",
           TEXTAREA, required=True, no=14),
        _q('rating_reliability',
           "How would you rate the candidate's reliability, ownership and ability to "
           'deliver commitments?', RADIO, required=True, choices=RATING_CHOICES, no=15),
        _q('rating_communication_teamwork',
           "How would you rate the candidate's communication and teamwork?", RADIO,
           required=True, choices=RATING_CHOICES, no=16),
        _q('rating_stakeholders',
           "How would you rate the candidate's ability to work with managers, "
           'colleagues, clients or other stakeholders?', RADIO, required=True,
           choices=RATING_CHOICES, no=17),
        _q('response_to_pressure',
           'How did the candidate respond to feedback, pressure, setbacks or changing '
           'priorities?', TEXTAREA, required=True, no=18),
        _q('rating_leadership',
           "If applicable, how would you describe the candidate's leadership / "
           'people-management capability?', RADIO, choices=LEADERSHIP_CHOICES, no=19),
        _q('development_areas',
           'What areas, if any, would you recommend the candidate develop further?',
           TEXTAREA, no=20),
    ], 'conduct'),
    _step('conduct', 'Section D', 'Conduct, Integrity & Recommendation', [
        _q('conduct_concerns',
           'To your direct knowledge, is there any material performance, disciplinary, '
           "integrity or conduct concern relevant to the candidate's professional "
           'suitability?', RADIO, required=True, choices=CONCERN_CHOICES, no=21),
        _q('conduct_details',
           'If Yes, please provide factual details that you are authorised to disclose.',
           TEXTAREA, required=True, no=22, show_if=when('conduct_concerns', 'yes')),
        _q('hire_again',
           'Would you work with, rehire or professionally recommend the candidate again?',
           RADIO, required=True, choices=HIRE_AGAIN_CHOICES, no=23),
        _q('recommend_explanation',
           'Please explain your overall recommendation or any reservations.', TEXTAREA,
           required=True, no=24),
    ], 'confirmation', description=(
        'Please provide only substantiated information based on your direct knowledge. '
        'Do not include rumours, speculation or information you are not authorised to '
        'disclose.'
    )),
    _step('confirmation', 'Section E', 'Confirmation', [
        _q('clarification_contact', CLARIFICATION_LABEL, RADIO, required=True,
           choices=YES_NO, no=25),
        _q('declaration', 'Declaration', BOOLEAN, required=True, no=26,
           choices=DECLARATION_CHOICES, statement=PROFESSIONAL_DECLARATION),
    ], None),
]


# ── Legacy: Academic Reference Check (no longer sent) ────────────────────
RATING_UNABLE = [
    ('excellent', 'Excellent'),
    ('good', 'Good'),
    ('average', 'Average'),
    ('below_average', 'Below Average'),
    ('unable', 'Unable to Comment'),
]
YES_NO_UNABLE_COMMENT = [('yes', 'Yes'), ('no', 'No'), ('unable', 'Unable to Comment')]
ACADEMIC_RELATIONSHIP_CHOICES = [
    ('course_instructor', 'Course Instructor'),
    ('academic_advisor', 'Academic Advisor'),
    ('thesis_supervisor', 'Thesis / Research Supervisor'),
    ('project_supervisor', 'Project Supervisor'),
    ('department_head', 'Department Head / Coordinator'),
    ('internship_supervisor', 'Internship Supervisor'),
    ('other', 'Other'),
]
INTERACTION_CHOICES = [
    ('regularly', 'Regularly'),
    ('occasionally', 'Occasionally'),
    ('limited', 'Limited interaction'),
    ('unable', 'Unable to estimate'),
]
ADAPT_CHOICES = [
    ('yes', 'Yes'),
    ('yes_development', 'Yes, with some development'),
    ('unable', 'Unable to Assess'),
    ('no', 'No'),
]
ACADEMIC_RECOMMEND_CHOICES = [
    ('strongly', 'Strongly Recommend'),
    ('recommend', 'Recommend'),
    ('reservations', 'Recommend with Reservations'),
    ('unable', 'Unable to Recommend'),
]
ACADEMIC_RATING_AREAS = [
    ('overall', 'Overall academic / professional performance'),
    ('learning', 'Learning ability / ability to grasp new concepts'),
    ('analytical', 'Analytical and problem-solving skills'),
    ('communication', 'Communication skills'),
    ('teamwork', 'Teamwork / collaboration'),
    ('reliability', 'Reliability and sense of responsibility'),
    ('initiative', 'Initiative / willingness to take ownership'),
    ('time_management', 'Time management / meeting deadlines'),
    ('maturity', 'Professional behaviour / maturity'),
    ('integrity', 'Integrity / trustworthiness'),
    ('feedback', 'Ability to accept and act on feedback'),
]

ACADEMIC_STEPS = [
    _step('referee', '', 'About you', [
        _q('referee_name', 'Your name', required=True),
        _q('referee_institution', 'University / institution', required=True),
        _q('referee_faculty', 'Department / faculty'),
        _q('referee_designation', 'Your designation', required=True),
        _q('referee_email', 'Official e-mail', EMAIL, required=True),
        _q('referee_contact', 'Mobile / office contact', PHONE),
        _q('referee_relationship', 'Your relationship to the candidate', SELECT,
           required=True, choices=ACADEMIC_RELATIONSHIP_CHOICES),
        _q('known_duration', 'How long have you known the candidate?'),
    ], 'assessment'),
    _step('assessment', '', 'Academic association & assessment', [
        _q('association',
           'Which course, project, thesis, research activity, internship, student '
           'organisation activity or other work was the candidate involved in under '
           'your supervision?', TEXTAREA),
        _q('interaction_frequency',
           'How frequently did you interact with or directly observe the candidate?',
           SELECT, choices=INTERACTION_CHOICES),
        *[_q(f'rating_{key}', label, RADIO, choices=RATING_UNABLE)
          for key, label in ACADEMIC_RATING_AREAS],
        _q('showed_leadership',
           'Did the candidate demonstrate leadership, initiative or ownership in a '
           'project / activity?', SELECT, choices=YES_NO_UNABLE_COMMENT),
        _q('leadership_example', 'Please provide a brief example', TEXTAREA,
           required_if=when('showed_leadership', 'yes')),
        _q('response_to_pressure',
           'How did the candidate respond to feedback, pressure, setbacks or changing '
           'priorities?', TEXTAREA),
    ], 'recommendation'),
    _step('recommendation', '', 'Strengths & recommendation', [
        _q('strongest_qualities',
           "What would you consider the candidate's strongest qualities?", TEXTAREA),
        _q('development_areas',
           'What areas would you recommend the candidate develop further?', TEXTAREA),
        _q('integrity_concerns',
           'To your direct knowledge, was there any serious academic integrity, '
           'disciplinary, behavioural or ethical concern involving the candidate?',
           SELECT, required=True, choices=YES_NO_UNABLE_COMMENT),
        _q('integrity_details', 'Factual information you are authorised to disclose',
           TEXTAREA, required_if=when('integrity_concerns', 'yes')),
        _q('can_adapt',
           'Based on your experience, do you believe the candidate can adapt '
           'successfully to a professional workplace?', SELECT, required=True,
           choices=ADAPT_CHOICES),
        _q('recommend',
           'Would you recommend the candidate for the position they have applied for '
           'at SSL Wireless?', SELECT, required=True, choices=ACADEMIC_RECOMMEND_CHOICES),
        _q('recommend_explanation',
           'Please briefly explain your recommendation or reservations', TEXTAREA,
           required_if=when('recommend', 'reservations', 'unable')),
    ], None),
]


FORMS = {
    EMPLOYER: EMPLOYER_STEPS,
    PROFESSIONAL: PROFESSIONAL_STEPS,
    ACADEMIC: ACADEMIC_STEPS,
}

_HALF_WIDTH_KEYS = frozenset({
    'candidate_full_name', 'verifier_organisation', 'verification_reference_id',
    'position_applied_for', 'verifier_name', 'verifier_designation',
    'verifier_department', 'verifier_email', 'verifier_contact', 'referee_name',
    'referee_designation', 'referee_organisation', 'referee_email', 'referee_contact',
    'employment_start_date', 'employment_end_date', 'last_designation',
    'confirmed_department', 'referee_institution', 'referee_faculty',
})


def steps(kind):
    return FORMS.get(kind, [])


def step_keys(kind):
    return [s['key'] for s in steps(kind)]


def get_step(kind, step_key):
    for step in steps(kind):
        if step['key'] == step_key:
            return step
    return None


def first_step(kind):
    keys = step_keys(kind)
    return keys[0] if keys else None


def final_step(kind):
    keys = step_keys(kind)
    return keys[-1] if keys else None


def total_steps(kind):
    return len(steps(kind))


def step_number(kind, step_key):
    keys = step_keys(kind)
    return keys.index(step_key) + 1 if step_key in keys else 0


def next_step_key(kind, step_key):
    step = get_step(kind, step_key)
    return step['next'] if step else None


def previous_step_key(kind, step_key):
    index = step_number(kind, step_key) - 1
    return step_keys(kind)[index - 1] if index > 0 else None


def questions(kind, step_key):
    step = get_step(kind, step_key)
    return list(step['questions']) if step else []


def questions_by_key(kind):
    return {q['key']: q for step in steps(kind) for q in step['questions']}


def readonly_keys(kind):
    return {key for key, q in questions_by_key(kind).items() if q.get('readonly')}


def step_heading(step) -> str:
    return f"{step['section']} — {step['title']}" if step.get('section') else step['title']


def is_half_width(question) -> bool:
    return question['key'] in _HALF_WIDTH_KEYS


def choice_label(kind, question_key, value):
    question = questions_by_key(kind).get(question_key)
    if not question or 'choices' not in question:
        return LEGACY_CHOICE_LABELS.get(value, value)
    return dict(question['choices']).get(value, LEGACY_CHOICE_LABELS.get(value, value))
