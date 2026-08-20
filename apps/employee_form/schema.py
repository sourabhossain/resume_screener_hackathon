"""Declarative definition of the Employee Information Form.

The whole form lives here as data, not as 131 hand-written Django fields or 22
hand-written templates: `forms.py` builds a Django form per step from these
dicts, and one template renders any step. Adding or changing a question means
editing this file only.

Source of truth is the Google Form (22 pages). Where the Google Form's own
question numbering is inconsistent (it skips 2, reuses 39 and 72-74, and drops
90), the numbering shown to candidates is generated sequentially from position
instead -- see `numbered_questions`. Question *content* is reproduced as-is.
"""

# ── Question types ───────────────────────────────────────────────────────
TEXT = 'text'
TEXTAREA = 'textarea'
EMAIL = 'email'
PHONE = 'phone'
DATE = 'date'
RADIO = 'radio'
SELECT = 'select'
CHECKBOX = 'checkbox'   # multi-select
FILE = 'file'
FILES = 'files'         # multiple uploads for one question

FILE_TYPES = frozenset({FILE, FILES})
CHOICE_TYPES = frozenset({RADIO, SELECT, CHECKBOX})

YES_NO = [('yes', 'Yes'), ('no', 'No')]

RELATIONSHIP_CHOICES = [
    ('direct_manager', 'Direct Manager'),
    ('skip_level_manager', 'Skip-level Manager'),
    ('peer', 'Peer'),
    ('direct_report', 'Direct Report'),
    ('hr_other', 'HR / Other'),
]

DEGREE_CHOICES = [
    ('masters', "Master's / Postgraduate Degree"),
    ('bachelors', "Undergraduate / Bachelor's Degree"),
    ('hsc', 'HSC / A Level / Equivalent'),
    ('ssc', 'SSC / O Level / Equivalent'),
    ('other', 'Other'),
]

DEPARTMENT_CHOICES = [
    ('banking_financial_services', 'Banking and Financial Services'),
    ('business_development', 'Business Development'),
    ('data', 'Data'),
    ('digital_communications', 'Digital Communications'),
    ('documentation_external_audit', 'Documentation & External Audit'),
    ('ecommerce_operations', 'E-Commerce Operations'),
    ('ecommerce_services', 'E-Commerce Services'),
    ('engineering', 'Engineering'),
    ('enterprise_risk_management', 'Enterprise Risk Management'),
    ('finance_accounts', 'Finance and Accounts'),
    ('government_project', 'Government Project'),
    ('human_resources', 'Human Resources'),
    ('infrastructure_security', 'Infrastructure and Security'),
    ('innovation_coe', 'Innovation Center of Excellence'),
    ('internal_control_compliance', 'Internal Control & Compliance'),
    ('legal_affairs', 'Legal Affairs'),
    ('management', 'Management'),
    ('partnership_management', 'Partnership Management'),
    ('procurement', 'Procurement'),
    ('project_management_office', 'Project Management Office'),
    ('revenue_assurance', 'Revenue Assurance'),
    ('risk_compliance', 'Risk & Compliance'),
    ('service_assurance_call_center', 'Service Assurance-Call Center'),
    ('service_assurance_quality_assurance', 'Service Assurance-Quality Assurance'),
    ('service_assurance_technical_operations', 'Service Assurance-Technical Operations'),
]

CUSTOMER_SEGMENT_CHOICES = [
    ('b2c', 'B2C / Consumer'),
    ('b2b', 'B2B'),
    ('corporate', 'Corporate'),
    ('government', 'Government'),
    ('enterprise', 'Enterprise'),
    ('sme', 'SME'),
    ('other', 'Other'),
]

AVAILABILITY_CHOICES = [
    ('serving_notice', 'Serving Notice Period'),
    ('not_yet_resigned', 'Not Yet Resigned'),
    ('immediately_available', 'Immediately Available'),
    ('currently_unemployed', 'Currently Unemployed'),
]

# Google Forms allows 100 MB per upload; that is Google's platform ceiling, not
# a business requirement. Candidate documents are ID scans and certificates,
# which are well under 10 MB -- capping here keeps a single applicant from
# filling the media volume.
MAX_UPLOAD_MB = 10
MAX_FILES_PER_QUESTION = 5


def _q(key, label, qtype=TEXT, required=False, help='', choices=None, max_files=None):
    q = {'key': key, 'label': label, 'type': qtype, 'required': required, 'help': help}
    if choices is not None:
        q['choices'] = choices
    if qtype == FILES:
        q['max_files'] = max_files or MAX_FILES_PER_QUESTION
    return q


# ── Section D routing ────────────────────────────────────────────────────
# Which role-specific section each department is sent to. Only
# banking_financial_services -> D1 is confirmed (visible in the supplied Google
# Form screenshots); the rest are INFERRED from the section titles and must be
# confirmed against the form's Branching Setup Guide before going live.
# Departments pointing at a section that currently has no questions (D2-D6, whose
# Google Form pages 16-21 were not supplied) are skipped automatically by
# `next_step_key`, so those candidates go straight to the declaration.
DEPARTMENT_ROUTING = {
    'banking_financial_services': 'd1_sales',              # confirmed
    'business_development': 'd1_sales',
    'partnership_management': 'd1_sales',
    'ecommerce_services': 'd1_sales',

    'digital_communications': 'd2_marketing',

    'finance_accounts': 'd3_finance',
    'revenue_assurance': 'd3_finance',

    'data': 'd4_technology',
    'engineering': 'd4_technology',
    'infrastructure_security': 'd4_technology',
    'innovation_coe': 'd4_technology',

    'ecommerce_operations': 'd5_operations',
    'government_project': 'd5_operations',
    'project_management_office': 'd5_operations',
    'service_assurance_call_center': 'd5_operations',
    'service_assurance_quality_assurance': 'd5_operations',
    'service_assurance_technical_operations': 'd5_operations',

    'documentation_external_audit': 'd6_corporate',
    'enterprise_risk_management': 'd6_corporate',
    'human_resources': 'd6_corporate',
    'internal_control_compliance': 'd6_corporate',
    'legal_affairs': 'd6_corporate',
    'management': 'd6_corporate',
    'procurement': 'd6_corporate',
    'risk_compliance': 'd6_corporate',
}


def _route_department(answers):
    return DEPARTMENT_ROUTING.get(answers.get('department'), 'd7_declaration')


def _after_employment_gate(answers):
    """Freshers have no employers to declare, so skip straight to references.

    ASSUMPTION -- the supplied screenshots show page 4's "Yes" branch leading to
    Employer 1 but not where "No - I am a Fresher" goes. Confirm this target.
    """
    return 'employer_1' if answers.get('has_employment') == 'yes' else 'reference_1'


def _after_employer(index):
    """Yes on "another previous employer?" opens the next employer step."""
    def _next(answers):
        if answers.get(f'employer_{index}_another') == 'yes':
            return f'employer_{index + 1}'
        return 'reference_1'
    return _next


# ── Steps ────────────────────────────────────────────────────────────────
STEPS = [
    {
        'key': 'section_a',
        'section': 'Section A — Candidate Identification & Information',
        'title': 'Candidate Identification & Information',
        'description': 'Please provide information exactly as shown on your official documents.',
        'next': 'section_b',
        'questions': [
            _q('candidate_full_name', 'Candidate Full Name', TEXT, required=True),
            _q('mobile_number', 'Mobile Number', PHONE, required=True),
            _q('personal_email', 'Personal Email Address', EMAIL, required=True),
            _q('position_applied_for', 'Position Applied For', TEXT, required=True),
            _q('nid_number', 'National ID (NID) Number', TEXT, required=True),
            _q('birth_certificate_number', 'Birth Certificate Number (if applicable)', TEXT),
            _q('date_of_birth', 'Date of Birth', DATE, required=True),
            _q('present_address', 'Present Address', TEXTAREA, required=True,
               help='Provide the full current address for police/background verification.'),
            _q('permanent_address', 'Permanent Address', TEXTAREA, required=True,
               help='Provide the complete permanent address for police/background verification.'),
            _q('address_same', 'Is your Present Address the same as your Permanent Address?',
               RADIO, required=True, choices=YES_NO),
            _q('nid_copy', 'Upload both sides of your NID Copy', FILE, required=True,
               help=f'Upload 1 supported file: PDF or image. Max {MAX_UPLOAD_MB} MB.'),
            _q('birth_certificate_copy', 'Upload Birth Certificate Copy (if applicable)', FILE,
               help=f'Upload 1 supported file: PDF, document, or image. Max {MAX_UPLOAD_MB} MB.'),
            _q('verification_consent',
               'Do you consent to SSL Wireless conducting identity, police, education, '
               'employment, reference and other lawful background verification as part of '
               'the recruitment process?',
               RADIO, required=True,
               choices=[('yes', 'Yes, I consent'), ('no', 'No')]),
        ],
    },
    {
        'key': 'section_b',
        'section': 'Section B — Educational Qualifications & Certificate Uploads',
        'title': 'Educational Qualifications & Certificate Uploads',
        'description': (
            'Select your highest / last completed degree first and provide the applicable '
            'qualification details below. Educational levels are arranged from highest to '
            'secondary level.'
        ),
        'next': 'employment_gate',
        'questions': [
            _q('highest_degree', 'Highest / Last Completed Degree', SELECT, required=True,
               choices=DEGREE_CHOICES),

            _q('masters_institution', "Master's / Postgraduate Degree — Institution / University Name"),
            _q('masters_degree_name', "Master's / Postgraduate Degree — Degree Name"),
            _q('masters_major', "Master's / Postgraduate Degree — Major / Subject"),
            _q('masters_completion_date',
               "Master's / Postgraduate Degree — Graduation / Completion Date", DATE),
            _q('masters_certificate', "Master's / Postgraduate Degree — Certificate", FILE,
               help=f'Upload 1 supported file: PDF, document, or image. Max {MAX_UPLOAD_MB} MB.'),

            _q('bachelors_institution',
               "Undergraduate / Bachelor's Degree — Institution / University Name",
               TEXT, required=True),
            _q('bachelors_degree_name', "Undergraduate / Bachelor's Degree — Degree Name",
               TEXT, required=True),
            _q('bachelors_major', "Undergraduate / Bachelor's Degree — Major / Subject",
               TEXT, required=True),
            _q('bachelors_completion_date', "Undergraduate / Bachelor's Degree - Completion date.",
               DATE, required=True),
            _q('bachelors_certificate', "Undergraduate / Bachelor's Degree — Certificate Image",
               FILE, required=True,
               help=f'Upload 1 supported file: PDF, document, or image. Max {MAX_UPLOAD_MB} MB.'),

            _q('hsc_institution', 'HSC / A Level / Equivalent — Institution / College Name',
               TEXT, required=True),
            _q('hsc_board', 'HSC / A Level / Equivalent — Education Board', TEXT, required=True),
            _q('hsc_passing_year', 'HSC / A Level / Equivalent — Passing Year', TEXT, required=True),
            _q('hsc_result', 'HSC / A Level / Equivalent — Result / GPA', TEXT, required=True),
            _q('hsc_certificate', 'HSC / A Level / Equivalent — Certificate Image', FILE,
               required=True,
               help=f'Upload 1 supported file: PDF, document, or image. Max {MAX_UPLOAD_MB} MB.'),

            _q('ssc_institution', 'SSC / O Level / Equivalent — Institution / School Name',
               TEXT, required=True),
            _q('ssc_board', 'SSC / O Level / Equivalent — Education Board', TEXT, required=True),
            _q('ssc_passing_year', 'SSC / O Level / Equivalent — Passing Year', TEXT, required=True),
            _q('ssc_result', 'SSC / O Level / Equivalent — Result / GPA', TEXT, required=True),
            _q('ssc_certificate', 'SSC / O Level / Equivalent — Certificate Image', FILE,
               required=True,
               help=f'Upload 1 supported file: PDF, document, or image. Max {MAX_UPLOAD_MB} MB.'),

            _q('training_certification_names',
               'Relevant Training / Professional Certification Name(s)', TEXTAREA,
               help='List all relevant training and professional certification names in one answer.'),
            _q('training_certificates',
               'Upload All Relevant Training / Professional Certification Certificates', FILES,
               help=(f'Upload up to {MAX_FILES_PER_QUESTION} supported files: PDF, document, '
                     f'or image. Max {MAX_UPLOAD_MB} MB per file.')),
        ],
    },
    {
        'key': 'employment_gate',
        'section': 'Section C — Employment History & Professional References',
        'title': 'Employment History & Professional References',
        'description': (
            'Complete employers in the same order as your CV, starting with your current '
            'or most recent employer.'
        ),
        'next': _after_employment_gate,
        'questions': [
            _q('has_employment',
               'Do you have any previous full-time/contractual employment experience?',
               RADIO, required=True,
               choices=[('yes', 'Yes'), ('no', 'No – I am a Fresher')]),
        ],
    },
]


def _employer_step(index, *, another_question, another_required):
    """Employers 1-4 ask the same seven questions; only the branch differs."""
    questions = [
        _q(f'employer_{index}_name', f'Employer {index} Name', TEXT, required=True),
        _q(f'employer_{index}_hr_contact', f'Employer {index} HR / Official Contact Number',
           PHONE, required=True),
        _q(f'employer_{index}_hr_email', f'Employer {index} HR / Official Email Address',
           EMAIL, required=True),
        _q(f'employer_{index}_position', f'Your Position / Designation at Employer {index}',
           TEXT, required=True),
        _q(f'employer_{index}_start_date',
           f"Candidate's Claimed Start Date at Employer {index}", DATE,
           required=index != 3),
        _q(f'employer_{index}_end_date',
           f"Candidate's Claimed End Date at Employer {index}", DATE, required=True),
        _q(f'employer_{index}_reason_leaving', f'Reason for Leaving Employer {index}',
           TEXTAREA, required=True),
    ]
    if another_question:
        questions.append(
            _q(f'employer_{index}_another', another_question, RADIO,
               required=another_required, choices=YES_NO)
        )
    return {
        'key': f'employer_{index}',
        'section': f'Employer {index} Information',
        'title': f'Employer {index} Information',
        'description': '',
        'next': _after_employer(index) if another_question else 'reference_1',
        'questions': questions,
    }


STEPS += [
    _employer_step(1, another_question='Do you have another previous employer?',
                   another_required=True),
    _employer_step(2, another_question='Do you have another previous employer to declare?',
                   another_required=True),
    # Google Form leaves Employer 3's start date and its "another employer"
    # question unmarked; reproduced as-is rather than normalised.
    _employer_step(3, another_question='Do you have another previous employer to declare?',
                   another_required=False),
    _employer_step(4, another_question=None, another_required=False),
]


def _reference_step(index, *, relationship_type, next_key):
    return {
        'key': f'reference_{index}',
        'section': f'Professional Reference {index}',
        'title': f'Professional Reference {index}',
        'description': '',
        'next': next_key,
        'questions': [
            _q(f'reference_{index}_name', f'Reference {index} Name', TEXT, required=True),
            _q(f'reference_{index}_designation',
               f'Reference {index} Designation & Company', TEXT, required=True),
            _q(f'reference_{index}_relationship', f'Reference {index} Relationship to You',
               relationship_type, required=True, choices=RELATIONSHIP_CHOICES),
            _q(f'reference_{index}_contact', f'Reference {index} Contact Number',
               PHONE, required=True),
            _q(f'reference_{index}_email',
               f'Reference {index} Official / Work Email Address', EMAIL, required=True),
        ],
    }


STEPS += [
    # The Google Form renders Reference 1's relationship as a dropdown and
    # Reference 2's as radio buttons; kept as-is. Reference 2's page also repeats
    # "Designation & Company" twice (as 73 and 79) -- included once.
    _reference_step(1, relationship_type=SELECT, next_key='reference_2'),
    _reference_step(2, relationship_type=RADIO, next_key='team_management'),
    {
        'key': 'team_management',
        'section': 'Previous Team & People Management',
        'title': 'Previous Team & People Management',
        'description': '',
        'next': 'department',
        'questions': [
            _q('team_structure', 'What type of team / team structure do you manage or work with?',
               TEXTAREA, required=True),
            _q('team_headcount',
               'How many people are/were under your direct and indirect supervision?',
               TEXT, required=True),
            _q('team_functions', 'What were the key functions and responsibilities of the team?',
               TEXTAREA, required=True),
            _q('team_authority',
               'What was your level of authority and decision-making responsibility?',
               TEXTAREA, required=True),
        ],
    },
    {
        'key': 'department',
        'section': 'Section D — Department Selection / Role Question Routing',
        'title': 'Department Selection',
        'description': (
            'Select the department relevant to the position. You will then be routed to '
            'the appropriate role-specific section.'
        ),
        'next': _route_department,
        'questions': [
            _q('department', 'Department', RADIO, required=True, choices=DEPARTMENT_CHOICES),
        ],
    },
    {
        'key': 'd1_sales',
        'section': 'Section D1 — Sales / Business / Partnership',
        'title': 'Sales / Business / Partnership',
        'description': '',
        'next': 'd1_customer_profile',
        'questions': [
            _q('sales_target_achievement',
               'Revenue / Sales Target Achievement over the Last 12 Months (%)',
               TEXT, required=True),
            _q('sales_key_accounts', 'Key Accounts / Client Types Managed', TEXTAREA, required=True),
            _q('sales_portfolio_value', 'Approximate Portfolio Value / Deal Size Managed',
               TEXT, required=True),
            _q('sales_cycle_length', 'Average Sales Cycle Length', TEXT, required=True),
            _q('sales_crm_tools', 'CRM / Sales Tools Used', TEXTAREA, required=True),
            _q('sales_largest_achievement',
               'Largest Measurable Sales / Business Development Achievement',
               TEXTAREA, required=True),
        ],
    },
    {
        'key': 'd1_customer_profile',
        'section': 'Customer Profile & Exposure',
        'title': 'Customer Profile & Exposure',
        'description': '',
        'next': 'd1_performance',
        'questions': [
            _q('customer_types', 'What type of customers do you deal with?', TEXTAREA, required=True),
            _q('customer_segments', 'Primary customer segment (select all that apply):',
               CHECKBOX, required=True, choices=CUSTOMER_SEGMENT_CHOICES),
            _q('customer_portfolio_scale', 'What is the scale and nature of the customer portfolio?',
               TEXTAREA, required=True),
            _q('customer_products', 'What type of products / services do you sell or manage?',
               TEXTAREA, required=True),
        ],
    },
    {
        'key': 'd1_performance',
        'section': 'Sales / Business Performance & Measurable Success',
        'title': 'Sales / Business Performance & Measurable Success',
        'description': '',
        'next': 'd7_declaration',
        'questions': [
            _q('perf_sales_type', 'What type of sales / business do you generate?',
               TEXTAREA, required=True),
            _q('perf_revenue_volume',
               'Revenue or business volume handled / generated (where verifiable):', TEXTAREA),
            _q('perf_key_achievements', 'Key achievements and major accounts / projects acquired',
               TEXTAREA, required=True),
            _q('perf_target_vs_achievement', 'Target versus achievement', TEXTAREA, required=True),
            _q('perf_success_indicators', 'Specific measurable and verifiable success indicators.',
               TEXTAREA),
        ],
    },

    # ── D2-D6: awaiting Google Form pages 16-21 ──────────────────────────
    # These sections exist so DEPARTMENT_ROUTING has real targets, but their
    # questions were not in the supplied screenshots. A step with no questions is
    # skipped by `next_step_key`, so departments routed here currently continue
    # straight to the declaration. Fill in `questions` to activate a section --
    # no other code changes needed.
    {
        'key': 'd2_marketing',
        'section': 'Section D2 — Marketing / Communications',
        'title': 'Marketing / Communications',
        'description': '',
        'next': 'd7_declaration',
        'questions': [],
    },
    {
        'key': 'd3_finance',
        'section': 'Section D3 — Finance / Revenue Assurance',
        'title': 'Finance / Revenue Assurance',
        'description': '',
        'next': 'd7_declaration',
        'questions': [],
    },
    {
        'key': 'd4_technology',
        'section': 'Section D4 — Technology / Engineering / Data',
        'title': 'Technology / Engineering / Data',
        'description': '',
        'next': 'd7_declaration',
        'questions': [],
    },
    {
        'key': 'd5_operations',
        'section': 'Section D5 — Operations / Service / Project',
        'title': 'Operations / Service / Project',
        'description': '',
        'next': 'd7_declaration',
        'questions': [],
    },
    {
        'key': 'd6_corporate',
        'section': 'Section D6 — Corporate / Governance / Support',
        'title': 'Corporate / Governance / Support',
        'description': '',
        'next': 'd7_declaration',
        'questions': [],
    },

    {
        'key': 'd7_declaration',
        'section': 'Section D7 — Candidate Declaration & Availability',
        'title': 'Candidate Declaration & Availability',
        'description': '',
        'next': None,
        'questions': [
            _q('total_experience_years', 'Total Years of Professional Experience',
               TEXT, required=True),
            _q('notice_period_days', 'Notice Period (days)', TEXT),
            _q('earliest_joining_date', 'Earliest Possible Joining Date', DATE),
            _q('current_responsibilities',
               'Briefly describe your current / most recent key responsibilities',
               TEXTAREA, required=True),
            _q('measurable_achievements', 'List up to 3 measurable achievements',
               TEXTAREA, required=True),
            _q('availability_status', 'Current Notice / Availability Status', RADIO,
               required=True, choices=AVAILABILITY_CHOICES),
            _q('declaration_agreement',
               'I declare that the information and documents provided in Sections A–D are '
               'true, accurate and complete to the best of my knowledge and I authorise SSL '
               'Wireless and/or its authorised Background Check Agency to verify them for '
               'recruitment purposes.',
               RADIO, required=True,
               choices=[('agree', 'I Agree'), ('disagree', 'I Do Not Agree')]),
            _q('typed_signature', 'Candidate Full Name (typed signature)', TEXT, required=True),
            _q('declaration_date', 'Declaration Date', DATE, required=True),
        ],
    },
]


# ── Lookups and traversal ────────────────────────────────────────────────
STEPS_BY_KEY = {step['key']: step for step in STEPS}
FIRST_STEP = STEPS[0]['key']
FINAL_STEP = 'd7_declaration'

QUESTIONS_BY_KEY = {
    q['key']: q for step in STEPS for q in step['questions']
}

FILE_QUESTION_KEYS = frozenset(
    q['key'] for q in QUESTIONS_BY_KEY.values() if q['type'] in FILE_TYPES
)


def get_step(step_key):
    return STEPS_BY_KEY.get(step_key)


def next_step_key(step_key, answers):
    """Resolve the step after `step_key`, skipping sections that have no questions.

    Empty sections are the D2-D6 placeholders; skipping them here means a
    candidate never lands on a blank page while those pages are still missing.
    """
    seen = set()
    current = step_key
    while True:
        step = STEPS_BY_KEY.get(current)
        if step is None:
            return None
        nxt = step['next']
        nxt = nxt(answers) if callable(nxt) else nxt
        if nxt is None:
            return None
        # Guard against a malformed schema looping forever.
        if nxt in seen:
            return FINAL_STEP
        seen.add(nxt)
        target = STEPS_BY_KEY.get(nxt)
        if target is None:
            return None
        if target['questions']:
            return nxt
        current = nxt


def step_path(answers):
    """The ordered list of step keys this candidate's answers actually lead through.

    Used for Back navigation and progress ("step 4 of 12"): with branching, the
    path length depends on the answers, so it is replayed from the start rather
    than assumed.
    """
    path = [FIRST_STEP]
    guard = 0
    while guard < len(STEPS) + 5:
        guard += 1
        nxt = next_step_key(path[-1], answers)
        if nxt is None or nxt in path:
            break
        path.append(nxt)
    return path


def numbered_questions(step_key, answers):
    """Questions for a step, each with the number shown to the candidate.

    Numbering is sequential over the candidate's own path so it always reads
    1, 2, 3... with no gaps, regardless of the Google Form's numbering quirks.
    """
    path = step_path(answers)
    number = 1
    for key in path:
        step = STEPS_BY_KEY[key]
        if key != step_key:
            number += len(step['questions'])
            continue
        return [dict(q, number=number + offset) for offset, q in enumerate(step['questions'])]
    # Step is off the current path (e.g. answers changed) -- number from 1.
    step = STEPS_BY_KEY.get(step_key)
    if not step:
        return []
    return [dict(q, number=offset + 1) for offset, q in enumerate(step['questions'])]


def choice_label(question_key, value):
    """Human-readable label for a stored choice value."""
    q = QUESTIONS_BY_KEY.get(question_key)
    if not q or 'choices' not in q:
        return value
    return dict(q['choices']).get(value, value)
