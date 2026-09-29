"""Declarative definition of the Employee Information Form.

The whole form lives here as data: `forms.py` builds a Django form per step from
these dicts, and one template renders any step.

Source of truth is SSL_Employee_Information_Form_FINAL.pdf -- Q1-Q130 across
Sections A, B, C, D and D1-D7, with the PDF's own numbering, required marks and
branching. Branching is expressed as `show_if` / `required_if` rules
(see apps/core/form_logic.py); a hidden question is never required and is
cleared on save. "Conditional" in the PDF means required while shown, unless the
PDF's own wording makes it optional ("if applicable", "when available").

The PDF's repeatable employer block (Q50/Q61 "Do you have another previous
employer?") is capped at EMPLOYER_MAX employers.
"""
from apps.core.form_logic import all_of, any_of, negate, when

# ── Question types ───────────────────────────────────────────────────────
TEXT = 'text'
TEXTAREA = 'textarea'
EMAIL = 'email'
PHONE = 'phone'
DATE = 'date'
RADIO = 'radio'
SELECT = 'select'
CHECKBOX = 'checkbox'   # multi-select
BOOLEAN = 'boolean'     # single tick box; stores 'yes' / 'no'
FILE = 'file'
FILES = 'files'         # multiple uploads for one question
INTEGER = 'integer'     # whole number
DECIMAL = 'decimal'     # number that may carry a fractional part
YEAR = 'year'           # four-digit year, never in the future
SIGNATURE = 'signature'  # drawn in the browser or uploaded; stored as a file

FILE_TYPES = frozenset({FILE, FILES, SIGNATURE})
CHOICE_TYPES = frozenset({RADIO, SELECT, CHECKBOX, BOOLEAN})
NUMERIC_TYPES = frozenset({INTEGER, DECIMAL, YEAR})

EARLIEST_PASSING_YEAR = 1950

YES_NO = [('yes', 'Yes'), ('no', 'No')]

CONTACT_PERMISSION = (
    'May SSL Wireless HR or its authorised Background Check Agency contact '
)

RELATIONSHIP_CHOICES = [
    ('direct_manager', 'Direct Manager'),
    ('skip_level_manager', 'Skip-level Manager'),
    ('peer', 'Peer'),
    ('direct_report', 'Direct Report'),
    ('hr', 'HR'),
    ('academic', 'Academic Supervisor / Faculty'),
    ('other', 'Other'),
]

# Q15 lists Master's and Bachelor's; Q36 is shown "when Q15 = Other", so Other is
# offered too.
DEGREE_CHOICES = [
    ('masters', "Master's / Postgraduate Degree"),
    ('bachelors', "Undergraduate / Bachelor's Degree"),
    ('other', 'Other'),
]

# Q83, in the PDF's order.
DEPARTMENT_CHOICES = [
    ('banking_financial_services', 'Banking and Financial Services'),
    ('business_development', 'Business Development'),
    ('partnership_management', 'Partnership Management'),
    ('digital_communications', 'Digital Communications'),
    ('finance_accounts', 'Finance and Accounts'),
    ('revenue_assurance', 'Revenue Assurance'),
    ('data', 'Data'),
    ('engineering', 'Engineering'),
    ('infrastructure_security', 'Infrastructure and Security'),
    ('innovation_coe', 'Innovation Center of Excellence'),
    ('ecommerce_operations', 'E-Commerce Operations'),
    ('ecommerce_services', 'E-Commerce Services'),
    ('government_project', 'Government Project'),
    ('project_management_office', 'Project Management Office'),
    ('service_assurance_call_center', 'Service Assurance-Call Center'),
    ('service_assurance_quality_assurance', 'Service Assurance-Quality Assurance'),
    ('service_assurance_technical_operations', 'Service Assurance-Technical Operations'),
    ('documentation_external_audit', 'Documentation & External Audit'),
    ('enterprise_risk_management', 'Enterprise Risk Management'),
    ('human_resources', 'Human Resources'),
    ('internal_control_compliance', 'Internal Control & Compliance'),
    ('legal_affairs', 'Legal Affairs'),
    ('management', 'Management'),
    ('procurement', 'Procurement'),
    ('risk_compliance', 'Risk & Compliance'),
]

EMPLOYMENT_TYPE_CHOICES = [
    ('full_time', 'Full-time / Permanent'),
    ('contractual', 'Contractual'),
    ('project_based', 'Project-based'),
    ('consultant', 'Consultant'),
    ('other', 'Other'),
]

CURRENT_EMPLOYER_SEPARATION_CHOICES = [
    ('currently_employed', 'Currently Employed'),
    ('voluntary_resignation', 'Voluntary Resignation'),
    ('contract_completion', 'Contract Completion'),
    ('redundancy', 'Redundancy / Retrenchment'),
    ('asked_to_resign', 'Asked to Resign'),
    ('termination', 'Termination'),
    ('other', 'Other'),
]
PREVIOUS_EMPLOYER_SEPARATION_CHOICES = CURRENT_EMPLOYER_SEPARATION_CHOICES[1:]

REPORTING_TYPE_CHOICES = [
    ('sales', 'Sales Reporting'),
    ('business', 'Business Reporting'),
    ('operational', 'Operational Reporting'),
    ('financial', 'Financial Reporting'),
    ('performance', 'Performance Reporting'),
    ('management', 'Management Reporting'),
    ('project', 'Project Reporting'),
    ('other', 'Other'),
    ('na', 'N/A'),
]

CUSTOMER_SEGMENT_CHOICES = [
    ('b2c', 'B2C / Consumer'),
    ('b2b', 'B2B'),
    ('corporate', 'Corporate'),
    ('government', 'Government'),
    ('enterprise', 'Enterprise'),
    ('sme', 'SME'),
    ('bank_fi', 'Bank / Financial Institution'),
    ('internal', 'Internal Stakeholders'),
    ('other', 'Other'),
]

MARKETING_CHANNEL_CHOICES = [
    ('digital_performance', 'Digital / Performance'),
    ('brand', 'Brand'),
    ('content', 'Content'),
    ('events_sponsorship', 'Events & Sponsorship'),
    ('pr_communications', 'PR & Communications'),
    ('other', 'Other'),
]

FINANCE_AREA_CHOICES = [
    ('accounts_payable', 'Accounts Payable'),
    ('accounts_receivable', 'Accounts Receivable'),
    ('treasury', 'Treasury'),
    ('fpa', 'FP&A'),
    ('audit_compliance', 'Audit & Compliance'),
    ('tax', 'Tax'),
    ('financial_reporting', 'Financial Reporting'),
    ('revenue_assurance', 'Revenue Assurance'),
    ('other', 'Other'),
]

AVAILABILITY_CHOICES = [
    ('serving_notice', 'Serving Notice Period'),
    ('not_yet_resigned', 'Not Yet Resigned'),
    ('immediately_available', 'Immediately Available'),
    ('currently_unemployed', 'Currently Unemployed'),
]

# Labels for values stored by earlier versions of this form.
LEGACY_CHOICE_LABELS = {
    'hr_other': 'HR / Other',
    'hsc': 'HSC / A Level / Equivalent',
    'ssc': 'SSC / O Level / Equivalent',
}

MAX_UPLOAD_MB = 10
MAX_FILES_PER_QUESTION = 10
EMPLOYER_MAX = 10
PDF_IMAGE = 'pdf_image'

_UPLOAD_HELP = f'1 file; PDF or image. Max {MAX_UPLOAD_MB} MB.'


def _q(key, label, qtype=TEXT, required=False, help='', choices=None, max_files=None,
       min_value=None, max_value=None, decimals=2, no=None, show_if=None,
       required_if=None, formats=None):
    q = {'key': key, 'label': label, 'type': qtype, 'required': required, 'help': help}
    if choices is not None:
        q['choices'] = choices
    if no is not None:
        q['no'] = no
    if show_if:
        q['show_if'] = show_if
    if required_if:
        q['required_if'] = required_if
    if qtype in FILE_TYPES:
        q['formats'] = formats or PDF_IMAGE
    if qtype == FILES:
        q['max_files'] = max_files or MAX_FILES_PER_QUESTION
    if qtype == SIGNATURE:
        q['drawn_key'] = f'{key}_drawn'
    if qtype in NUMERIC_TYPES:
        q['min_value'] = min_value
        q['max_value'] = max_value
        if qtype == DECIMAL:
            q['decimals'] = decimals
    return q


# ── Section D routing (Q83 table) ────────────────────────────────────────
DEPARTMENT_ROUTING = {
    'banking_financial_services': 'd1_sales',
    'business_development': 'd1_sales',
    'partnership_management': 'd1_sales',

    'digital_communications': 'd2_marketing',

    'finance_accounts': 'd3_finance',
    'revenue_assurance': 'd3_finance',

    'data': 'd4_technology',
    'engineering': 'd4_technology',
    'infrastructure_security': 'd4_technology',
    'innovation_coe': 'd4_technology',

    'ecommerce_operations': 'd5_operations',
    'ecommerce_services': 'd5_operations',
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


def _after_section_a(answers):
    # Q14 "No" routes to the end / HR review path.
    return None if answers.get('verification_consent') == 'no' else 'section_b'


# ── Section A (Q1-14) ────────────────────────────────────────────────────
_ADDRESS_HELP = 'Full address for police verification.'

SECTION_A = [
    _q('candidate_full_name', 'Candidate Full Name', TEXT, required=True, no=2),
    _q('mobile_number', 'Mobile Number', PHONE, required=True, no=3),
    _q('personal_email', 'Personal Email Address', EMAIL, required=True, no=4),
    _q('position_applied_for', 'Position Applied For', TEXT, required=True, no=5),
    _q('nid_number', 'National ID (NID) Number', TEXT, required=True, no=6),
    _q('birth_certificate_number', 'Birth Certificate Number (if applicable)', TEXT, no=7),
    _q('date_of_birth', 'Date of Birth', DATE, required=True, no=8),
    _q('present_address', 'Present Address (full address for police verification)',
       TEXTAREA, required=True, no=9),
    _q('address_same', 'Is your Present Address the same as your Permanent Address?',
       RADIO, required=True, choices=YES_NO, no=10),
    _q('permanent_address', 'Permanent Address (full address for police verification)',
       TEXTAREA, required=True, no=11, show_if=when('address_same', 'no')),
    _q('nid_copy', 'Upload NID Copy', FILE, required=True, help=_UPLOAD_HELP, no=12),
    _q('birth_certificate_copy', 'Upload Birth Certificate Copy (if applicable)',
       FILE, help=_UPLOAD_HELP, no=13),
    _q('verification_consent',
       'Do you consent to SSL Wireless conducting identity, police, education, '
       'employment, reference and other lawful background verification as part of '
       'the recruitment process?',
       RADIO, required=True, choices=[('yes', 'Yes, I consent'), ('no', 'No')], no=14),
]


# ── Section B (Q15-38) ───────────────────────────────────────────────────
_MASTERS = when('highest_degree', 'masters')
_BACHELORS_UP = when('highest_degree', 'masters', 'bachelors')
_SCHOOL = when('highest_degree', 'masters', 'bachelors', 'other')

_M = "Master's / Postgraduate Degree — "
_U = "Undergraduate / Bachelor's Degree — "
_H = 'HSC / A Level / Equivalent — '
_S = 'SSC / O Level / Equivalent — '

SECTION_B = [
    _q('highest_degree', 'Highest / Last Completed Degree', SELECT, required=True,
       choices=DEGREE_CHOICES, no=15),

    _q('masters_institution', f'{_M}Institution / University Name', TEXT,
       required=True, no=16, show_if=_MASTERS),
    _q('masters_degree_name', f'{_M}Degree Name', TEXT, required=True, no=17,
       show_if=_MASTERS),
    _q('masters_major', f'{_M}Major / Subject', TEXT, required=True, no=18,
       show_if=_MASTERS),
    _q('masters_completion_date', f'{_M}Graduation / Completion Date', DATE,
       required=True, no=19, show_if=_MASTERS),
    _q('masters_certificate', f'{_M}Certificate', FILE, required=True,
       help=_UPLOAD_HELP, no=20, show_if=_MASTERS),

    _q('bachelors_institution', f'{_U}Institution / University Name', TEXT,
       required=True, no=21, show_if=_BACHELORS_UP),
    _q('bachelors_degree_name', f'{_U}Degree Name', TEXT, required=True, no=22,
       show_if=_BACHELORS_UP),
    _q('bachelors_major', f'{_U}Major / Subject', TEXT, required=True, no=23,
       show_if=_BACHELORS_UP),
    _q('bachelors_completion_date', f'{_U}Graduation / Completion Date', DATE,
       required=True, no=24, show_if=_BACHELORS_UP),
    _q('bachelors_certificate', f'{_U}Certificate', FILE, required=True,
       help=_UPLOAD_HELP, no=25, show_if=_BACHELORS_UP),

    _q('hsc_institution', f'{_H}Institution / College Name', TEXT, required=True,
       no=26, show_if=_SCHOOL),
    _q('hsc_board', f'{_H}Education Board', TEXT, required=True, no=27, show_if=_SCHOOL),
    _q('hsc_passing_year', f'{_H}Passing Year', YEAR, required=True, no=28,
       show_if=_SCHOOL),
    _q('hsc_result', f'{_H}Result / GPA', TEXT, required=True, no=29, show_if=_SCHOOL),
    _q('hsc_certificate', f'{_H}Certificate', FILE, required=True, help=_UPLOAD_HELP,
       no=30, show_if=_SCHOOL),

    _q('ssc_institution', f'{_S}Institution / School Name', TEXT, required=True,
       no=31, show_if=_SCHOOL),
    _q('ssc_board', f'{_S}Education Board', TEXT, required=True, no=32, show_if=_SCHOOL),
    _q('ssc_passing_year', f'{_S}Passing Year', YEAR, required=True, no=33,
       show_if=_SCHOOL),
    _q('ssc_result', f'{_S}Result / GPA', TEXT, required=True, no=34, show_if=_SCHOOL),
    _q('ssc_certificate', f'{_S}Certificate', FILE, required=True, help=_UPLOAD_HELP,
       no=35, show_if=_SCHOOL),

    _q('other_qualification_details', 'Other / Equivalent Highest Qualification Details',
       TEXTAREA, required=True, no=36, show_if=when('highest_degree', 'other'),
       help='Include qualification name, institution, subject, completion year and '
            'result (if relevant).'),

    _q('training_certification_names',
       'Relevant Training / Professional Certification Name(s)', TEXTAREA, no=37,
       help='List all relevant training / professional certifications in one response.'),
    _q('training_certificates',
       'Upload All Relevant Training / Professional Certification Certificates',
       FILES, no=38, help=f'Multiple files; PDF or image. Max {MAX_UPLOAD_MB} MB each.'),
]


# ── Section C: employment history (Q39-61, repeating) ────────────────────
def employer_shown(index):
    """Rule for "employer `index` is part of the candidate's history"."""
    rule = when('has_employment', 'yes')
    if index == 1:
        return rule
    return all_of(employer_shown(index - 1), when(f'employer_{index - 1}_another', 'yes'))


def _employer_questions(index):
    shown = employer_shown(index)
    first = index == 1
    base = 40 if first else 51
    number = (lambda offset: base + offset) if index <= 2 else (lambda offset: None)
    still_there = when(f'employer_{index}_separation', 'currently_employed')
    questions = [
        _q(f'employer_{index}_name', f'Employer {index} Name', TEXT, required=True,
           no=number(0), show_if=shown),
        _q(f'employer_{index}_employment_type', f'Employment Type at Employer {index}',
           SELECT, required=True, choices=EMPLOYMENT_TYPE_CHOICES, no=number(1),
           show_if=shown),
        _q(f'employer_{index}_hr_contact', f'Employer {index} HR / Official Contact Number',
           PHONE, required=True, no=number(2), show_if=shown),
        _q(f'employer_{index}_hr_email', f'Employer {index} HR / Official Email Address',
           EMAIL, required=True, no=number(3), show_if=shown),
        _q(f'employer_{index}_position', f'Your Position / Designation at Employer {index}',
           TEXT, required=True, no=number(4), show_if=shown),
        _q(f'employer_{index}_start_date', f'Your Start Date at Employer {index}', DATE,
           required=True, no=number(5), show_if=shown),
    ]
    if first:
        questions += [
            _q('employer_1_end_date', 'Your End Date at Employer 1', DATE, no=46,
               show_if=shown, required_if=negate(still_there),
               help='Leave blank if currently employed.'),
            _q('employer_1_reason_leaving', 'Reason for Leaving Employer 1', TEXTAREA,
               no=47, show_if=shown, required_if=negate(still_there),
               help='Not required if currently employed.'),
            _q('employer_1_separation', 'Nature of Separation from Employer 1', SELECT,
               required=True, choices=CURRENT_EMPLOYER_SEPARATION_CHOICES, no=48,
               show_if=shown),
        ]
    else:
        questions += [
            _q(f'employer_{index}_end_date', f'Your End Date at Employer {index}', DATE,
               required=True, no=number(6), show_if=shown),
            _q(f'employer_{index}_reason_leaving', f'Reason for Leaving Employer {index}',
               TEXTAREA, no=number(7), show_if=shown),
            _q(f'employer_{index}_separation', f'Nature of Separation from Employer {index}',
               SELECT, required=True, choices=PREVIOUS_EMPLOYER_SEPARATION_CHOICES,
               no=number(8), show_if=shown),
        ]
    questions.append(
        _q(f'employer_{index}_contact_permission',
           f'{CONTACT_PERMISSION}Employer {index} for verification?', RADIO,
           required=True, choices=YES_NO, no=number(9), show_if=shown))
    if index < EMPLOYER_MAX:
        questions.append(
            _q(f'employer_{index}_another', 'Do you have another previous employer?',
               RADIO, required=True, choices=YES_NO, no=number(10), show_if=shown))
    return questions


EMPLOYMENT = [
    _q('has_employment',
       'Do you have any previous full-time / contractual employment experience?',
       RADIO, required=True, choices=[('yes', 'Yes'), ('no', 'No — I am a fresher')],
       no=39),
]
for _index in range(1, EMPLOYER_MAX + 1):
    EMPLOYMENT += _employer_questions(_index)


def declared_employer_indices(answers):
    """Employers on the candidate's path, in CV order (current / most recent first).

    Answers saved before the Q39 gate existed have no `has_employment`; there any
    named employer 1-4 counts.
    """
    answers = answers or {}
    if 'has_employment' not in answers:
        return [i for i in range(1, 5) if (answers.get(f'employer_{i}_name') or '').strip()]
    if answers.get('has_employment') != 'yes':
        return []
    out = []
    for index in range(1, EMPLOYER_MAX + 1):
        if not (answers.get(f'employer_{index}_name') or '').strip():
            break
        out.append(index)
        if answers.get(f'employer_{index}_another') != 'yes':
            break
    return out


# ── Section C: references (Q62-73) ───────────────────────────────────────
def _reference_questions(index):
    base = 62 if index == 1 else 68
    help_name = ('Freshers may provide an academic supervisor / faculty reference where '
                 'appropriate.') if index == 1 else ''
    return [
        _q(f'reference_{index}_name', f'Reference {index} Name', TEXT, required=True,
           no=base, help=help_name),
        _q(f'reference_{index}_designation',
           f'Reference {index} Designation & Company / Institution', TEXT, required=True,
           no=base + 1),
        _q(f'reference_{index}_relationship', f'Reference {index} Relationship to You',
           SELECT, required=True, choices=RELATIONSHIP_CHOICES, no=base + 2),
        _q(f'reference_{index}_contact', f'Reference {index} Contact Number', PHONE,
           required=True, no=base + 3),
        _q(f'reference_{index}_email', f'Reference {index} Official / Work Email Address',
           EMAIL, required=True, no=base + 4),
        _q(f'reference_{index}_contact_permission', f'{CONTACT_PERMISSION}Reference {index}?',
           RADIO, required=True, choices=YES_NO, no=base + 5),
    ]


# ── Section C: team and reporting (Q74-82) ───────────────────────────────
_MANAGES = when('manages_team', 'yes')

TEAM_REPORTING = [
    _q('manages_team',
       'Did you manage or directly supervise a team in your current / most recent role?',
       RADIO, required=True, choices=YES_NO, no=74),
    _q('team_structure', 'What type of team / team structure did you manage or work with?',
       TEXTAREA, required=True, no=75, show_if=_MANAGES),
    _q('team_size', 'How many people were under your direct and/or indirect supervision?',
       TEXT, required=True, no=76, show_if=_MANAGES,
       help='Direct: ____  Indirect: ____'),
    _q('team_functions', 'What were the key functions and responsibilities of the team?',
       TEXTAREA, required=True, no=77, show_if=_MANAGES),
    _q('team_authority', 'Describe your level of authority and decision-making responsibility.',
       TEXTAREA, required=True, no=78, show_if=_MANAGES),
    _q('reporting_head',
       'Who was your immediate reporting head? Please provide the name and designation, '
       'where appropriate.', TEXT, no=79, help='Freshers may enter N/A.'),
    _q('reporting_head_manager',
       'To whom did your immediate reporting head report? Please provide the designation '
       '/ reporting level.', TEXT, no=80, help='N/A if not applicable.'),
    _q('direct_reports',
       'Who reported directly to you? Please provide role/designation and number of '
       'direct reports, if applicable.', TEXTAREA, no=81, help='N/A if none.'),
    _q('reporting_types', 'What type of reporting did you prepare or maintain?', CHECKBOX,
       choices=REPORTING_TYPE_CHOICES, no=82),
]


# ── Steps ────────────────────────────────────────────────────────────────
_CUSTOMER_FACING = when('customer_facing', 'yes')
_EMPLOYED = when('availability_status', 'serving_notice', 'not_yet_resigned')

STEPS = [
    {
        'key': 'section_a',
        'section': 'Section A — Candidate Identification & Verification',
        'title': 'Candidate Identification & Verification',
        'description': 'Please provide information exactly as shown on your official documents.',
        'next': _after_section_a,
        'questions': SECTION_A,
    },
    {
        'key': 'section_b',
        'section': 'Section B — Educational Qualifications & Certificate Uploads',
        'title': 'Educational Qualifications & Certificate Uploads',
        'description': (
            'Your highest / last completed degree determines which education blocks are '
            'shown; the lower qualifications then follow in sequence.'
        ),
        'next': 'employment',
        'questions': SECTION_B,
    },
    {
        'key': 'employment',
        'section': 'Section C — Employment History',
        'title': 'Employment History',
        'description': (
            'Employer details are collected in CV order, beginning with your current / '
            'most recent employer. Each employer must include verification contact '
            'details and contact permission.'
        ),
        'next': 'reference_1',
        'questions': EMPLOYMENT,
    },
    {
        'key': 'reference_1',
        'section': 'Professional Reference 1',
        'title': 'Professional Reference 1',
        'description': '',
        'next': 'reference_2',
        'questions': _reference_questions(1),
    },
    {
        'key': 'reference_2',
        'section': 'Professional Reference 2',
        'title': 'Professional Reference 2',
        'description': '',
        'next': 'team_reporting',
        'questions': _reference_questions(2),
    },
    {
        'key': 'team_reporting',
        'section': 'Previous Team & People Management / Reporting Structure',
        'title': 'Previous Team & Reporting Structure',
        'description': '',
        'next': 'department',
        'questions': TEAM_REPORTING,
    },
    {
        'key': 'department',
        'section': 'Section D — Department Selection / Role Question Routing',
        'title': 'Department',
        'description': (
            'Select your department. You will then be shown exactly one role-specific '
            'section.'
        ),
        'next': _route_department,
        'questions': [
            _q('department', 'Department', SELECT, required=True,
               choices=DEPARTMENT_CHOICES, no=83),
        ],
    },
    {
        'key': 'd1_sales',
        'section': 'Section D1 — Sales / Business / Partnership',
        'title': 'Sales / Business / Partnership',
        'description': '',
        'next': 'd7_declaration',
        'questions': [
            _q('customer_facing',
               'Was your current / most recent role customer- or client-facing?',
               RADIO, required=True, choices=YES_NO, no=84),
            _q('customer_segments',
               'What type of customers / customer segments did you deal with?', CHECKBOX,
               required=True, choices=CUSTOMER_SEGMENT_CHOICES, no=85,
               show_if=_CUSTOMER_FACING),
            _q('sales_key_accounts',
               'Describe the scale and nature of the customer / account portfolio you '
               'handled.', TEXTAREA, required=True, no=86, show_if=_CUSTOMER_FACING),
            _q('sales_portfolio_value',
               'Approximate customer portfolio value / business volume handled (if '
               'applicable and known).', TEXT, no=87, show_if=_CUSTOMER_FACING,
               help='Amount + unit / period'),
            _q('sales_products',
               'What type of products / services did you sell, manage or support?',
               TEXTAREA, required=True, no=88, show_if=_CUSTOMER_FACING),
            _q('sales_business_type', 'What type of sales / business did you generate or manage?',
               TEXTAREA, required=True, no=89),
            _q('sales_target', 'Annual / Quarterly Sales Target', TEXT, no=90,
               help='Amount + period. Use the most relevant target period.'),
            _q('sales_actual', 'Actual Sales / Revenue Achieved', TEXT, no=91,
               help='Amount + period. Use the same period as the target where possible.'),
            _q('sales_target_achievement', 'Target Achievement Percentage', TEXT, no=92,
               help='Example: 118%. N/A if not a target-based role.'),
            _q('sales_major_accounts',
               'Major accounts / clients / projects acquired or significantly developed',
               TEXTAREA, no=93, help='Do not disclose restricted confidential information.'),
            _q('sales_cycle_length', 'Average Sales Cycle Length', TEXT, no=94,
               help='Days / weeks / months'),
            _q('sales_crm_tools',
               'CRM / Sales Tools Used and New Business / Partnership Acquisition '
               'Responsibility', TEXTAREA, no=95,
               help='Tools used + your direct responsibility / ownership'),
            _q('sales_largest_achievement',
               'Specific measurable and verifiable success indicators / key business '
               'achievement', TEXTAREA, required=True, no=96,
               help='Include measurable result, target, revenue, growth, conversion, '
                    'retention, cost saving or other relevant metric.'),
        ],
    },
    {
        'key': 'd2_marketing',
        'section': 'Section D2 — Marketing / Communications',
        'title': 'Marketing / Communications',
        'description': '',
        'next': 'd7_declaration',
        'questions': [
            _q('marketing_campaigns', 'Campaigns Led in the Last 12 Months', TEXTAREA, no=97),
            _q('marketing_budget', 'Approximate Annual Marketing Budget Managed', TEXT,
               no=98, help='Amount + currency'),
            _q('marketing_channels', 'Primary Marketing Channels / Areas of Expertise',
               CHECKBOX, choices=MARKETING_CHANNEL_CHOICES, no=99,
               help='Select all that apply.'),
            _q('marketing_kpi', 'Key Marketing KPI / Result Achieved', TEXTAREA, no=100,
               help='Include measurable result where possible.'),
            _q('marketing_achievement',
               'Most Significant Marketing / Communications Achievement, including '
               'analytics / automation tools used', TEXTAREA, no=101),
        ],
    },
    {
        'key': 'd3_finance',
        'section': 'Section D3 — Finance / Revenue Assurance',
        'title': 'Finance / Revenue Assurance',
        'description': '',
        'next': 'd7_declaration',
        'questions': [
            _q('finance_areas', 'Functional Areas Handled', CHECKBOX,
               choices=FINANCE_AREA_CHOICES, no=102, help='Select all that apply.'),
            _q('finance_audit_exposure', 'Audit Exposure (Internal / External / Regulatory)',
               TEXTAREA, no=103),
            _q('finance_software', 'ERP / Finance Software Used', TEXTAREA, no=104),
            _q('finance_budget_responsibility',
               'Budget / Revenue / Cost Responsibility and Reconciliation / Control / '
               'Revenue Leakage Responsibility', TEXTAREA, no=105,
               help='Describe scope, values where appropriate, and control responsibility.'),
            _q('finance_achievement', 'Key Finance / Revenue Assurance Achievement',
               TEXTAREA, no=106, help='Include a measurable result where possible.'),
        ],
    },
    {
        'key': 'd4_technology',
        'section': 'Section D4 — Technology / Engineering / Data',
        'title': 'Technology / Engineering / Data',
        'description': '',
        'next': 'd7_declaration',
        'questions': [
            _q('tech_stack', 'Primary Technology Stack / Tools', TEXTAREA, no=107),
            _q('tech_systems_owned', 'Systems / Products Owned or Maintained', TEXTAREA,
               no=108),
            _q('tech_incident_responsibility', 'Incident / Uptime / Production Responsibility',
               TEXTAREA, no=109),
            _q('tech_data_responsibility',
               'Data / Database / Analytics and Infrastructure / Cloud / Security '
               'Responsibility (if relevant)', TEXTAREA, no=110,
               help='Describe applicable areas only.'),
            _q('tech_certifications', 'Relevant Technical Certifications', TEXTAREA, no=111),
            _q('tech_achievement', 'Most Significant Technical / Data Achievement', TEXTAREA,
               no=112, help='Include a measurable result where possible.'),
        ],
    },
    {
        'key': 'd5_operations',
        'section': 'Section D5 — Operations / Service / Project',
        'title': 'Operations / Service / Project',
        'description': '',
        'next': 'd7_declaration',
        'questions': [
            _q('ops_processes_owned', 'Processes / SLAs / Projects Owned', TEXTAREA, no=113),
            _q('ops_kpis', 'Service / Operational KPIs Managed', TEXTAREA, no=114),
            _q('ops_team_vendor_exposure',
               'Team / Vendor Size Overseen and Customer / Merchant / Internal Stakeholder '
               'Exposure', TEXTAREA, no=115,
               help='Describe team/vendor scale and stakeholder exposure.'),
            _q('ops_tools', 'Systems / Tools Used for Operations or Project Management',
               TEXTAREA, no=116),
            _q('ops_achievement', 'Most Significant Operations / Service / Project Achievement',
               TEXTAREA, no=117, help='Include a measurable result where possible.'),
        ],
    },
    {
        'key': 'd6_corporate',
        'section': 'Section D6 — Corporate / Governance / Support',
        'title': 'Corporate / Governance / Support',
        'description': '',
        'next': 'd7_declaration',
        'questions': [
            _q('corp_functional_areas', 'Primary Functional Areas Managed', TEXTAREA, no=118),
            _q('corp_frameworks', 'Policies / Regulations / Frameworks Worked With',
               TEXTAREA, no=119),
            _q('corp_audit_exposure', 'Audit / Compliance / Risk Exposure (if relevant)',
               TEXTAREA, no=120),
            _q('corp_stakeholder_exposure',
               'Stakeholder / Management Exposure and Systems / Tools Used', TEXTAREA,
               no=121, help='Describe stakeholder level and systems/tools used.'),
            _q('corp_achievement', 'Most Significant Measurable Functional Achievement',
               TEXTAREA, no=122, help='Include a measurable result where possible.'),
        ],
    },
    {
        'key': 'd7_declaration',
        'section': 'Section D7 — Candidate Declaration & Availability',
        'title': 'Candidate Declaration & Availability',
        'description': '',
        'next': None,
        'questions': [
            _q('total_experience_years', 'Total Years of Professional Experience', DECIMAL,
               required=True, min_value=0, max_value=60, decimals=1, no=123,
               help='Years; decimals allowed, e.g. 7.5'),
            _q('availability_status', 'Current Notice / Availability Status', SELECT,
               required=True, choices=AVAILABILITY_CHOICES, no=124),
            _q('notice_period', 'Notice Period (days / months)', TEXT, required=True,
               no=125, show_if=_EMPLOYED),
            _q('remaining_notice_period',
               'If currently serving notice, remaining notice period (days / months)',
               TEXT, required=True, no=126,
               show_if=when('availability_status', 'serving_notice')),
            _q('last_working_day',
               'Last Working Day at Current Employer (if already resigned)', DATE,
               required=True, no=127, show_if=when('availability_status', 'serving_notice')),
            _q('earliest_joining_date', 'Earliest Possible Joining Date', DATE, no=128),
            _q('declaration_agreement',
               'I declare that the information and documents provided in this form are '
               'true, accurate and complete to the best of my knowledge and I authorise SSL '
               'Wireless and/or its authorised Background Check Agency to verify them for '
               'recruitment purposes.',
               RADIO, required=True,
               choices=[('agree', 'I Agree'), ('disagree', 'I Do Not Agree')], no=129),
            _q('signature', "Candidate's Signature (Online / Attach File)", SIGNATURE,
               required=True, no=130, show_if=when('declaration_agreement', 'agree'),
               help='Sign in the box, or upload 1 signature file (image or PDF). The '
                    'submission date and time are recorded automatically.'),
        ],
    },
]


# ── Answers saved by earlier versions of this form ───────────────────────
LEGACY_LABELS = {
    'has_masters': "Do you have a Master's / Postgraduate Degree?",
    'additional_employment_history': 'Additional Employment History (if more than four employers)',
    'notice_period_days': 'Notice Period (days)',
    'current_responsibilities': 'Briefly describe your current / most recent key responsibilities',
    'measurable_achievements': 'List up to 3 measurable achievements',
    'sales_new_business': 'New Business / Partnership Acquisition Responsibility',
    'marketing_tools': 'Marketing / Analytics / Automation Tools Used',
    'finance_reconciliation': 'Reconciliation / Control / Revenue Leakage Responsibility',
    'tech_infra_responsibility': 'Infrastructure / Cloud / Security Responsibility (if relevant)',
    'ops_team_size': 'Team / Vendor Size Overseen',
    'ops_stakeholder_exposure': 'Customer / Merchant / Internal Stakeholder Exposure',
    'corp_tools': 'Systems / Tools Used',
}


def legacy_view(answers):
    """Answers with the gates earlier versions never asked filled in, for reading back."""
    view = dict(answers or {})
    if 'has_employment' not in view:
        named = declared_employer_indices(view)
        if named:
            view['has_employment'] = 'yes'
            for index in named[:-1]:
                view.setdefault(f'employer_{index}_another', 'yes')
    if 'customer_facing' not in view and any(
            view.get(k) for k in ('sales_key_accounts', 'sales_portfolio_value')):
        view['customer_facing'] = 'yes'
    return view


# ── Presentation hints ───────────────────────────────────────────────────
HALF_WIDTH_KEYS = frozenset({
    'mobile_number', 'personal_email', 'nid_number',
    'birth_certificate_number', 'date_of_birth', 'position_applied_for',
    'masters_completion_date', 'bachelors_completion_date',
    'hsc_board', 'hsc_passing_year', 'hsc_result',
    'ssc_board', 'ssc_passing_year', 'ssc_result',
    'total_experience_years', 'availability_status', 'notice_period',
    'remaining_notice_period', 'last_working_day', 'earliest_joining_date',
    'sales_target', 'sales_actual', 'sales_target_achievement', 'sales_cycle_length',
    'sales_portfolio_value', 'marketing_budget',
    *(f'employer_{i}_{s}' for i in range(1, EMPLOYER_MAX + 1)
      for s in ('employment_type', 'hr_contact', 'hr_email', 'start_date', 'end_date',
                'separation')),
    *(f'reference_{i}_contact' for i in range(1, 3)),
    *(f'reference_{i}_email' for i in range(1, 3)),
})


def _employer_group(index):
    keys = [q['key'] for q in _employer_questions(index)]
    title = f'Employer {index}' + (' — Current / Most Recent Employer' if index == 1 else
                                   ' — Previous Employer')
    return (title, keys)


def _reference_group(index):
    return (f'Reference {index}', [q['key'] for q in _reference_questions(index)])


STEP_GROUPS = {
    'section_a': [
        ('Your details', [
            'candidate_full_name', 'mobile_number', 'personal_email',
            'position_applied_for', 'nid_number', 'birth_certificate_number',
            'date_of_birth',
        ]),
        ('Addresses', ['present_address', 'address_same', 'permanent_address']),
        ('Identity documents', ['nid_copy', 'birth_certificate_copy']),
        ('Consent', ['verification_consent']),
    ],
    'section_b': [
        ('', ['highest_degree']),
        ("Master's / Postgraduate Degree", [
            'masters_institution', 'masters_degree_name', 'masters_major',
            'masters_completion_date', 'masters_certificate',
        ]),
        ("Undergraduate / Bachelor's Degree", [
            'bachelors_institution', 'bachelors_degree_name', 'bachelors_major',
            'bachelors_completion_date', 'bachelors_certificate',
        ]),
        ('HSC / A Level / Equivalent', [
            'hsc_institution', 'hsc_board', 'hsc_passing_year', 'hsc_result',
            'hsc_certificate',
        ]),
        ('SSC / O Level / Equivalent', [
            'ssc_institution', 'ssc_board', 'ssc_passing_year', 'ssc_result',
            'ssc_certificate',
        ]),
        ('Other / Equivalent Qualification', ['other_qualification_details']),
        ('Training & professional certifications', [
            'training_certification_names', 'training_certificates',
        ]),
    ],
    'employment': [('', ['has_employment'])] + [
        _employer_group(i) for i in range(1, EMPLOYER_MAX + 1)
    ],
    'reference_1': [_reference_group(1)],
    'reference_2': [_reference_group(2)],
    'team_reporting': [
        ('Previous Team & People Management', [
            'manages_team', 'team_structure', 'team_size', 'team_functions',
            'team_authority',
        ]),
        ('Reporting Structure', [
            'reporting_head', 'reporting_head_manager', 'direct_reports', 'reporting_types',
        ]),
    ],
    'd1_sales': [
        ('Customer Profile & Exposure', [
            'customer_facing', 'customer_segments', 'sales_key_accounts',
            'sales_portfolio_value', 'sales_products',
        ]),
        ('Sales / Business Performance & Measurable Success', [
            'sales_business_type', 'sales_target', 'sales_actual',
            'sales_target_achievement', 'sales_major_accounts', 'sales_cycle_length',
            'sales_crm_tools', 'sales_largest_achievement',
        ]),
    ],
    'd7_declaration': [
        ('Experience & availability', [
            'total_experience_years', 'availability_status', 'notice_period',
            'remaining_notice_period', 'last_working_day', 'earliest_joining_date',
        ]),
        ('Declaration', ['declaration_agreement', 'signature']),
    ],
}


# ── Inline branches ──────────────────────────────────────────────────────
# Section D's role block renders on the department page itself, swapped in via
# htmx once the department is chosen.
INLINE_BRANCHES = {'department': _route_department}
INLINE_TARGETS = frozenset(DEPARTMENT_ROUTING.values())


def inline_target(step_key, answers):
    """The step whose questions are rendered inside `step_key`, if any."""
    resolve = INLINE_BRANCHES.get(step_key)
    if not resolve:
        return None
    if not (answers or {}).get(step_key):
        return None
    target = resolve(answers)
    if target not in INLINE_TARGETS:
        return None
    step = STEPS_BY_KEY.get(target)
    return target if step and step['questions'] else None


def wizard_questions(step_key, answers):
    """A step's own questions plus any it absorbs, in render order."""
    step = STEPS_BY_KEY.get(step_key)
    if not step:
        return []
    questions = list(step['questions'])
    target = inline_target(step_key, answers)
    if target:
        questions += STEPS_BY_KEY[target]['questions']
    return questions


# ── Lookups and traversal ────────────────────────────────────────────────
STEPS_BY_KEY = {step['key']: step for step in STEPS}
FIRST_STEP = STEPS[0]['key']
FINAL_STEP = 'd7_declaration'

QUESTIONS_BY_KEY = {q['key']: q for step in STEPS for q in step['questions']}

FILE_QUESTION_KEYS = frozenset(
    q['key'] for q in QUESTIONS_BY_KEY.values() if q['type'] in FILE_TYPES
)


def get_step(step_key):
    return STEPS_BY_KEY.get(step_key)


def next_step_key(step_key, answers):
    """Resolve the step after `step_key`, skipping any section with no questions."""
    seen = set()
    current = step_key
    absorbed = inline_target(step_key, answers)
    if absorbed:
        current = absorbed
    while True:
        step = STEPS_BY_KEY.get(current)
        if step is None:
            return None
        nxt = step['next']
        nxt = nxt(answers) if callable(nxt) else nxt
        if nxt is None:
            return None
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
    """The ordered step keys these answers lead through."""
    path = [FIRST_STEP]
    guard = 0
    while guard < len(STEPS) + 5:
        guard += 1
        nxt = next_step_key(path[-1], answers)
        if nxt is None or nxt in path:
            break
        path.append(nxt)
    return path


def review_path(answers):
    """`step_path`, with absorbed sections named in their own right."""
    out = []
    for key in step_path(answers):
        out.append(key)
        target = inline_target(key, answers)
        if target:
            out.append(target)
    return out


def numbered_questions(step_key, answers):
    """A step's own questions, each with the PDF's question number."""
    step = STEPS_BY_KEY.get(step_key)
    if not step:
        return []
    return [dict(q, number=q.get('no')) for q in step['questions']]


def numbered_wizard_questions(step_key, answers):
    """Everything the candidate fills in on `step_key`, absorbed sections included."""
    return [dict(q, number=q.get('no')) for q in wizard_questions(step_key, answers)]


def question_groups(step_key, answers):
    """A step's questions arranged into titled blocks for rendering."""
    questions = numbered_wizard_questions(step_key, answers)
    by_key = {q['key']: q for q in questions}

    groups = list(STEP_GROUPS.get(step_key) or [])
    target = inline_target(step_key, answers)
    if target:
        groups += STEP_GROUPS.get(target) or [
            (STEPS_BY_KEY[target]['title'],
             [q['key'] for q in STEPS_BY_KEY[target]['questions']]),
        ]

    if not groups:
        return [{'title': '', 'questions': questions}]

    out, placed = [], set()
    for title, keys in groups:
        block = [by_key[k] for k in keys if k in by_key]
        placed.update(k for k in keys if k in by_key)
        if block:
            out.append({'title': title, 'questions': block})

    leftover = [q for q in questions if q['key'] not in placed]
    if leftover:
        out.append({'title': '', 'questions': leftover})
    return out


def is_half_width(question) -> bool:
    """Whether a control should share its row with the next one."""
    if question['type'] in FILE_TYPES or question['type'] in (TEXTAREA, CHECKBOX, RADIO):
        return False
    return question['key'] in HALF_WIDTH_KEYS


def choice_label(question_key, value):
    """Human-readable label for a stored choice value."""
    q = QUESTIONS_BY_KEY.get(question_key)
    if not q or 'choices' not in q:
        return LEGACY_CHOICE_LABELS.get(value, value)
    return dict(q['choices']).get(value, LEGACY_CHOICE_LABELS.get(value, value))


def _short_labels():
    out = {}
    for prefix, keys in [
        (_M, ['masters_institution', 'masters_degree_name', 'masters_major',
              'masters_completion_date', 'masters_certificate']),
        (_U, ['bachelors_institution', 'bachelors_degree_name', 'bachelors_major',
              'bachelors_completion_date', 'bachelors_certificate']),
        (_H, ['hsc_institution', 'hsc_board', 'hsc_passing_year', 'hsc_result',
              'hsc_certificate']),
        (_S, ['ssc_institution', 'ssc_board', 'ssc_passing_year', 'ssc_result',
              'ssc_certificate']),
    ]:
        for key in keys:
            label = QUESTIONS_BY_KEY[key]['label']
            if label.startswith(prefix):
                out[key] = label[len(prefix):]
    return out


SHORT_LABELS = _short_labels()


def wizard_label(question) -> str:
    """The label to show on the candidate form."""
    return SHORT_LABELS.get(question['key'], question['label'])
