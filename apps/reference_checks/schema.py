"""The three external verification forms, as data.

Same approach as the three internal forms: each is a list of sections, one
template renders any of them, and `employee_form.forms.build_field` turns a
question dict into a Django field.

Source documents:
  * SSL_Wireless_Previous_Employer_Employment_Verification_Form_1  -> EMPLOYER
  * SSL_Wireless_Professional_Reference_Check_Form_for_experienced -> PROFESSIONAL
  * SSL_Wireless_Fresher_University_Academic_Reference_Check_Form  -> ACADEMIC

These are filled by someone outside SSL -- a former employer's HR, a referee, a
professor -- reached by an emailed link and a one-time code. They are doing us a
favour on a busy day, so each form is three short sections rather than the five
or six the paper version prints, and nothing is required that the respondent may
legitimately not know: every judgement carries an "N/A" or "Not known" answer.

Section A of the paper forms ("Candidate Details, to be completed by SSL") is not
asked at all. Those facts are already on file, so they are shown to the
respondent as a read-only panel instead -- see `views.step`.
"""
from apps.employee_form.schema import (  # noqa: F401
    CHOICE_TYPES,
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

KIND_LABELS = {
    EMPLOYER: 'Employment Verification',
    PROFESSIONAL: 'Professional Reference Check',
    ACADEMIC: 'Academic Reference Check',
}


def _q(key, label, qtype=TEXT, required=False, help='', choices=None):
    q = {'key': key, 'label': label, 'type': qtype, 'required': required, 'help': help}
    if choices is not None:
        q['choices'] = choices
    return q


# ── Shared choice sets ───────────────────────────────────────────────────
# Every rating scale keeps an escape hatch. A respondent who never saw the
# candidate write a line of code must be able to say so rather than guess.
RATING_NA = [
    ('excellent', 'Excellent'),
    ('good', 'Good'),
    ('average', 'Average'),
    ('below_average', 'Below Average'),
    ('na', 'N/A'),
]
RATING_UNABLE = [
    ('excellent', 'Excellent'),
    ('good', 'Good'),
    ('average', 'Average'),
    ('below_average', 'Below Average'),
    ('unable', 'Unable to Comment'),
]

YES_NO_UNABLE = [
    ('yes', 'Yes'),
    ('no', 'No'),
    ('unable', 'Unable to verify'),
]
YES_NO_NOT_KNOWN = [
    ('yes', 'Yes'),
    ('no', 'No'),
    ('not_known', 'Not known / Not disclosed'),
]
YES_NO_UNABLE_COMMENT = [
    ('yes', 'Yes'),
    ('no', 'No'),
    ('unable', 'Unable to Comment'),
]


def _ratings(prefix, areas, scale):
    """One question per assessment area, all sharing a rating scale."""
    return [
        _q(f'{prefix}_{key}', label, RADIO, choices=scale)
        for key, label in areas
    ]


# ── Previous Employer Employment Verification ────────────────────────────
EMPLOYER_STATUS_CHOICES = [
    ('permanent', 'Permanent'),
    ('contractual', 'Contractual'),
    ('probationer', 'Probationer'),
    ('outsourced', 'Outsourced'),
    ('consultant', 'Consultant'),
    ('other', 'Other'),
    ('not_disclosed', 'Not disclosed'),
]
SEPARATION_NATURE_CHOICES = [
    ('resignation', 'Voluntary resignation'),
    ('end_of_contract', 'End of contract'),
    ('redundancy', 'Redundancy / Restructure'),
    ('involuntary', 'Involuntary separation'),
    ('other', 'Other'),
    ('not_disclosed', 'Not disclosed'),
]
REHIRE_CHOICES = [
    ('yes', 'Yes'),
    ('no', 'No'),
    ('conditional', 'Conditional / With reservations'),
    ('not_disclosed', 'Not disclosed'),
]
VERIFIER_RELATIONSHIP_CHOICES = [
    ('hr', 'HR / People Team'),
    ('direct_manager', 'Direct Manager'),
    ('other_official', 'Other Authorised Official'),
]

EMPLOYER_RATING_AREAS = [
    ('overall', 'Overall job performance'),
    ('quality', 'Quality / accuracy of work'),
    ('reliability', 'Reliability / ownership'),
    ('attendance', 'Attendance / punctuality'),
    ('communication', 'Communication / collaboration'),
    ('professionalism', 'Professional behaviour'),
    ('stakeholders', 'Relationship with customers / stakeholders'),
    ('people_management', 'People management, if applicable'),
]

EMPLOYER_STEPS = [
    {
        'key': 'verifier',
        'title': 'About you',
        'description': 'Please answer using official organisational information '
                       'where possible.',
        'next': 'employment',
        'questions': [
            _q('verifier_name', 'Your name', required=True),
            _q('verifier_organisation', 'Organisation', required=True),
            _q('verifier_designation', 'Your designation', required=True),
            _q('verifier_department', 'Your department'),
            _q('verifier_relationship', 'Your relationship to the candidate', SELECT,
               required=True, choices=VERIFIER_RELATIONSHIP_CHOICES),
        ],
    },
    {
        'key': 'employment',
        'title': 'Employment verification',
        'description': '',
        'next': 'conduct',
        'questions': [
            _q('was_employed', 'Was the candidate employed by your organisation?',
               SELECT, required=True, choices=YES_NO_UNABLE),
            _q('employment_period', "Please confirm the candidate's employment period",
               help='For example: March 2021 to August 2024.'),
            _q('last_designation',
               "Please confirm the candidate's last / most recent designation"),
            _q('employment_status', 'Employment status at the time of separation',
               SELECT, choices=EMPLOYER_STATUS_CHOICES),
            _q('had_promotion',
               'Did the candidate receive any promotion(s) during employment?',
               SELECT, choices=YES_NO_NOT_KNOWN),
            _q('promotion_details', 'Promotion / designation details', TEXTAREA),
            _q('subordinates', 'Number of direct / indirect subordinates, if applicable'),
            _q('last_salary', 'Last salary / compensation information',
               help='Optional, and only if your policy permits disclosure. '
                    'Gross, net or total compensation may be stated.'),
            _q('separation_reason', 'Please confirm the reason for separation / leaving',
               TEXTAREA),
            _q('separation_nature', 'Nature of separation', SELECT,
               choices=SEPARATION_NATURE_CHOICES),
            _q('rehire_eligible', 'Is the candidate eligible for rehire?', SELECT,
               choices=REHIRE_CHOICES),
            _q('rehire_explanation', 'Brief factual explanation', TEXTAREA,
               help='Only if you are authorised to provide one.'),
        ],
    },
    {
        'key': 'conduct',
        'title': 'Performance, conduct & reliability',
        'description': 'Please answer only where your records or direct knowledge '
                       'allow. Choose N/A if you cannot comment.',
        'next': None,
        'questions': [
            *_ratings('rating', EMPLOYER_RATING_AREAS, RATING_NA),
            _q('disciplinary_action',
               'Was any formal disciplinary action taken against the candidate '
               'during employment?', SELECT, choices=YES_NO_NOT_KNOWN),
            _q('disciplinary_details',
               'Substantiated and disclosable details, including the outcome',
               TEXTAREA),
            _q('integrity_concerns',
               'Were there any substantiated integrity, fraud, harassment, '
               'misconduct, confidentiality or serious compliance concerns?',
               SELECT, choices=YES_NO_NOT_KNOWN),
            _q('integrity_details',
               'Factual details you are authorised to disclose', TEXTAREA),
        ],
    },
]


# ── Professional Reference Check (experienced candidates) ────────────────
REFEREE_RELATIONSHIP_CHOICES = [
    ('direct_manager', 'Direct Manager'),
    ('skip_level_manager', 'Skip-level Manager'),
    ('hr', 'HR'),
    ('peer', 'Peer'),
    ('client', 'Client / Stakeholder'),
    ('other', 'Other'),
]
MANAGED_CHOICES = [
    ('yes', 'Yes'),
    ('no', 'No'),
    ('na', 'Not applicable'),
    ('not_known', 'Not known'),
]
HIRE_AGAIN_CHOICES = [
    ('yes', 'Yes'),
    ('yes_reservations', 'Yes, with reservations'),
    ('no', 'No'),
    ('unable', 'Unable to comment'),
]
RECOMMEND_CHOICES = [
    ('yes', 'Yes'),
    ('yes_reservations', 'Yes, with reservations'),
    ('no', 'No'),
    ('unable', 'Unable to assess'),
]

PROFESSIONAL_RATING_AREAS = [
    ('overall', 'Overall performance'),
    ('quality', 'Quality / accuracy of work'),
    ('reliability', 'Reliability / accountability'),
    ('communication', 'Communication skills'),
    ('teamwork', 'Teamwork / collaboration'),
    ('problem_solving', 'Problem-solving / judgement'),
    ('pressure', 'Ability to work under pressure'),
    ('professionalism', 'Professionalism / workplace behaviour'),
    ('integrity', 'Integrity / trustworthiness'),
    ('leadership', 'Leadership / people management, if applicable'),
]

PROFESSIONAL_STEPS = [
    {
        'key': 'referee',
        'title': 'About you',
        'description': '',
        'next': 'performance',
        'questions': [
            _q('referee_name', 'Your name', required=True),
            _q('referee_organisation', 'Organisation', required=True),
            _q('referee_designation', 'Your designation', required=True),
            _q('referee_email', 'Official e-mail', EMAIL, required=True),
            _q('referee_contact', 'Mobile / office contact', PHONE),
            _q('referee_relationship', 'Your relationship to the candidate', SELECT,
               required=True, choices=REFEREE_RELATIONSHIP_CHOICES),
            _q('known_duration',
               'How long have you known / worked with the candidate?',
               help='For example: about three years.'),
        ],
    },
    {
        'key': 'performance',
        'title': 'Working relationship & performance',
        'description': 'Please rate only areas you have directly observed. '
                       'Choose N/A where you cannot comment.',
        'next': 'suitability',
        'questions': [
            _q('candidate_role',
               'What position / role did the candidate hold while you worked '
               'together?'),
            _q('worked_together_when',
               'Approximately when did you work with the candidate?',
               help='For example: 2022 to 2024.'),
            _q('main_responsibilities',
               "What were the candidate's main responsibilities, to the best of "
               'your knowledge?', TEXTAREA),
            _q('managed_others',
               'Did the candidate manage people / vendors / key stakeholders?',
               SELECT, choices=MANAGED_CHOICES),
            _q('managed_scope', 'Please briefly describe the scope', TEXTAREA),
            *_ratings('rating', PROFESSIONAL_RATING_AREAS, RATING_NA),
            _q('strongest_qualities',
               "What would you consider the candidate's strongest professional "
               'qualities?', TEXTAREA),
            _q('development_areas',
               'What development areas would you suggest for the candidate?',
               TEXTAREA),
            _q('response_to_pressure',
               'How did the candidate respond to feedback, pressure or changing '
               'priorities?', TEXTAREA),
        ],
    },
    {
        'key': 'suitability',
        'title': 'Conduct & suitability',
        'description': '',
        'next': None,
        'questions': [
            _q('conduct_concerns',
               'To your direct knowledge, were there any serious conduct, '
               'integrity or disciplinary concerns relevant to employment?',
               SELECT, required=True, choices=YES_NO_UNABLE_COMMENT),
            _q('conduct_details',
               'Factual information you are authorised to disclose', TEXTAREA),
            _q('hire_again', 'Would you work with / hire the candidate again?',
               SELECT, required=True, choices=HIRE_AGAIN_CHOICES),
            _q('hire_again_explanation', 'Please explain any reservations', TEXTAREA),
            _q('recommend',
               'Would you recommend the candidate for the position they have '
               'applied for at SSL Wireless?', SELECT, required=True,
               choices=RECOMMEND_CHOICES),
            _q('recommend_explanation', 'Please explain your recommendation',
               TEXTAREA),
            _q('anything_else',
               "Is there anything else that would help us assess the candidate's "
               'suitability for employment?', TEXTAREA),
        ],
    },
]


# ── Fresher University Academic Reference Check ──────────────────────────
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
    {
        'key': 'referee',
        'title': 'About you',
        'description': '',
        'next': 'assessment',
        'questions': [
            _q('referee_name', 'Your name', required=True),
            _q('referee_institution', 'University / institution', required=True),
            _q('referee_faculty', 'Department / faculty'),
            _q('referee_designation', 'Your designation', required=True),
            _q('referee_email', 'Official e-mail', EMAIL, required=True),
            _q('referee_contact', 'Mobile / office contact', PHONE),
            _q('referee_relationship', 'Your relationship to the candidate', SELECT,
               required=True, choices=ACADEMIC_RELATIONSHIP_CHOICES),
            _q('known_duration', 'How long have you known the candidate?',
               help='For example: two academic years.'),
        ],
    },
    {
        'key': 'assessment',
        'title': 'Academic association & assessment',
        'description': 'Please rate only areas you have directly observed. '
                       'Choose "Unable to Comment" where appropriate.',
        'next': 'recommendation',
        'questions': [
            _q('association',
               'Which course, project, thesis, research activity, internship, '
               'student organisation activity or other work was the candidate '
               'involved in under your supervision?', TEXTAREA),
            _q('interaction_frequency',
               'How frequently did you interact with or directly observe the '
               'candidate?', SELECT, choices=INTERACTION_CHOICES),
            *_ratings('rating', ACADEMIC_RATING_AREAS, RATING_UNABLE),
            _q('showed_leadership',
               'Did the candidate demonstrate leadership, initiative or ownership '
               'in a project / activity?', SELECT, choices=YES_NO_UNABLE_COMMENT),
            _q('leadership_example', 'Please provide a brief example', TEXTAREA),
            _q('response_to_pressure',
               'How did the candidate respond to feedback, pressure, setbacks or '
               'changing priorities?', TEXTAREA),
        ],
    },
    {
        'key': 'recommendation',
        'title': 'Strengths & recommendation',
        'description': '',
        'next': None,
        'questions': [
            _q('strongest_qualities',
               "What would you consider the candidate's strongest qualities?",
               TEXTAREA),
            _q('development_areas',
               'What areas would you recommend the candidate develop further?',
               TEXTAREA),
            _q('integrity_concerns',
               'To your direct knowledge, was there any serious academic '
               'integrity, disciplinary, behavioural or ethical concern involving '
               'the candidate?', SELECT, required=True,
               choices=YES_NO_UNABLE_COMMENT),
            _q('integrity_details',
               'Factual information you are authorised to disclose', TEXTAREA),
            _q('can_adapt',
               'Based on your experience, do you believe the candidate can adapt '
               'successfully to a professional workplace?', SELECT, required=True,
               choices=ADAPT_CHOICES),
            _q('recommend',
               'Would you recommend the candidate for the position they have '
               'applied for at SSL Wireless?', SELECT, required=True,
               choices=ACADEMIC_RECOMMEND_CHOICES),
            _q('recommend_explanation',
               'Please briefly explain your recommendation or reservations',
               TEXTAREA),
        ],
    },
]


FORMS = {
    EMPLOYER: EMPLOYER_STEPS,
    PROFESSIONAL: PROFESSIONAL_STEPS,
    ACADEMIC: ACADEMIC_STEPS,
}


# ── "If Yes, ..." follow-ups ─────────────────────────────────────────────
# The paper forms number these 5A, 10A, 11A. Required only when the answer that
# calls for them is chosen: a recorded concern with no detail cannot be acted on,
# and "Not known" already covers having nothing to say.
CONDITIONAL_RULES = {
    EMPLOYER: [
        {'trigger': 'had_promotion', 'when': ['yes'], 'keys': ['promotion_details']},
        {'trigger': 'rehire_eligible', 'when': ['no', 'conditional'],
         'keys': ['rehire_explanation']},
        {'trigger': 'disciplinary_action', 'when': ['yes'],
         'keys': ['disciplinary_details']},
        {'trigger': 'integrity_concerns', 'when': ['yes'],
         'keys': ['integrity_details']},
    ],
    PROFESSIONAL: [
        {'trigger': 'managed_others', 'when': ['yes'], 'keys': ['managed_scope']},
        {'trigger': 'conduct_concerns', 'when': ['yes'], 'keys': ['conduct_details']},
        {'trigger': 'hire_again', 'when': ['yes_reservations', 'no'],
         'keys': ['hire_again_explanation']},
        {'trigger': 'recommend', 'when': ['yes_reservations', 'no'],
         'keys': ['recommend_explanation']},
    ],
    ACADEMIC: [
        {'trigger': 'showed_leadership', 'when': ['yes'],
         'keys': ['leadership_example']},
        {'trigger': 'integrity_concerns', 'when': ['yes'],
         'keys': ['integrity_details']},
        {'trigger': 'recommend', 'when': ['reservations', 'unable'],
         'keys': ['recommend_explanation']},
    ],
}


# ── Rendering hints ──────────────────────────────────────────────────────
# Short answers pair two to a row. Rating questions are excluded on purpose: a
# column of them reads as a table when each sits on its own row.
_HALF_WIDTH_SUFFIXES = (
    'name', 'organisation', 'designation', 'department', 'institution',
    'faculty', 'email', 'contact', 'relationship', 'duration',
    'employment_period', 'last_designation', 'subordinates', 'last_salary',
    'candidate_role', 'worked_together_when',
)


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


def conditional_rules(kind, step_key):
    """Follow-up rules whose trigger and targets are both on this section."""
    keys = {q['key'] for q in questions(kind, step_key)}
    return [
        {**rule, 'keys': [k for k in rule['keys'] if k in keys]}
        for rule in CONDITIONAL_RULES.get(kind, [])
        if rule['trigger'] in keys and any(k in keys for k in rule['keys'])
    ]


def is_half_width(question) -> bool:
    if question['key'].startswith('rating_'):
        return False
    return question['key'].endswith(_HALF_WIDTH_SUFFIXES)


def choice_label(kind, question_key, value):
    question = questions_by_key(kind).get(question_key)
    if not question or 'choices' not in question:
        return value
    for choice_value, label in question['choices']:
        if choice_value == value:
            return label
    return value
