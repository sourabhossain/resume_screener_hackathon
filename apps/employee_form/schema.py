"""Declarative definition of the Employee Information Form.

The whole form lives here as data, not as 131 hand-written Django fields or
seventeen hand-written templates: `forms.py` builds a Django form per step from
these dicts, and one template renders any step. Adding or changing a question
means editing this file only.

Source of truth is SSL_Wireless_Employee_Information_Form_FINAL_UPDATED.pdf —
131 questions across Sections A, B, C, D and D1-D7, in the order and with the
required/optional marks that document gives. The numbers shown to the candidate
are generated from position, which matches the PDF's numbering exactly.

Two deliberate departures from the PDF, both agreed with the client:
  * The PDF's Q1 Requisition ID is dropped -- a candidate has no way to know that
    value. Everything after it shifts up one, so this form has 130 questions and
    our Q1 is the PDF's Q2.
  * No employer is hard-required. The PDF marks Employer 1-4 required, which would
    make the form unsubmittable for a fresher, or for anyone with fewer than four
    previous jobs. Instead each employer is optional *until its name is given*, at
    which point the rest of that employer becomes required -- see
    `_validate_employer_block` in forms.py. That keeps freshers able to submit
    without allowing half-filled employer records.
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
BOOLEAN = 'boolean'     # single tick box; stores 'yes' / 'no'
FILE = 'file'
FILES = 'files'         # multiple uploads for one question
INTEGER = 'integer'     # whole number
DECIMAL = 'decimal'     # number that may carry a fractional part
YEAR = 'year'           # four-digit year, never in the future

FILE_TYPES = frozenset({FILE, FILES})
CHOICE_TYPES = frozenset({RADIO, SELECT, CHECKBOX, BOOLEAN})
NUMERIC_TYPES = frozenset({INTEGER, DECIMAL, YEAR})

# Floor for any passing year. Old enough for any working candidate, low enough
# not to reject anyone, but it still catches a mistyped or nonsense value. The
# ceiling is the current year, applied in forms.py so it cannot go stale in a
# long-running process.
EARLIEST_PASSING_YEAR = 1950

YES_NO = [('yes', 'Yes'), ('no', 'No')]

# The PDF asks this same permission once per employer and once per referee.
CONTACT_PERMISSION = (
    'May SSL Wireless HR or its authorised Background Check Agency contact '
)

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

# Candidate documents are ID scans and certificates, well under 10 MB. Capping
# here keeps a single applicant from filling the media volume.
MAX_UPLOAD_MB = 10
MAX_FILES_PER_QUESTION = 5

_UPLOAD_HELP = f'PDF, document or image. Max {MAX_UPLOAD_MB} MB.'


def _q(key, label, qtype=TEXT, required=False, help='', choices=None, max_files=None,
       min_value=None, max_value=None, decimals=2):
    q = {'key': key, 'label': label, 'type': qtype, 'required': required, 'help': help}
    if choices is not None:
        q['choices'] = choices
    if qtype == FILES:
        q['max_files'] = max_files or MAX_FILES_PER_QUESTION
    if qtype in NUMERIC_TYPES:
        # Bounds are part of the question, not of the widget: they are enforced
        # server-side and mirrored onto the input so the browser catches a bad
        # value before a round trip.
        q['min_value'] = min_value
        q['max_value'] = max_value
        if qtype == DECIMAL:
            q['decimals'] = decimals
    return q


# ── Section D routing ────────────────────────────────────────────────────
# Which role-specific section each department leads to. The PDF defers this to a
# "Branching Setup Guide" that was not supplied, and only
# banking_financial_services -> D1 is confirmed (visible in the client's own
# Google Form). The rest are INFERRED from the section titles and must be
# confirmed before go-live: a wrong entry sends a candidate to the wrong set of
# role questions, and now that D2-D6 carry real questions that is visible.
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


# ── Sections A and B (PDF Q1-38) ─────────────────────────────────────────
STEPS = [
    {
        'key': 'section_a',
        'section': 'Section A — Candidate Identification Information',
        'title': 'Candidate Identification',
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
               help='Full address, for police verification.'),
            _q('permanent_address', 'Permanent Address', TEXTAREA, required=True,
               help='Full address, for police verification.'),
            # Rendered as a tick box between the two address fields: ticking it
            # copies Present into Permanent. A yes/no radio *beside* two free-text
            # addresses let a candidate answer "Yes" while typing two different
            # ones, and that contradiction went to police verification. Not
            # required -- unticked is a complete answer ("no").
            _q('address_same', 'Is your Present Address the same as your Permanent Address?',
               BOOLEAN, choices=YES_NO),
            _q('nid_copy', 'Upload NID Copy', FILE, required=True, help=_UPLOAD_HELP),
            _q('birth_certificate_copy', 'Upload Birth Certificate Copy (if applicable)',
               FILE, help=_UPLOAD_HELP),
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
        'section': 'Section B — Educational Qualifications & Certificate Uploads '
                   '(Highest to Secondary)',
        'title': 'Educational Qualifications & Certificates',
        'description': (
            'Select your highest / last completed degree first, then provide the '
            'applicable qualification details below. Educational levels are arranged '
            'from highest to secondary level.'
        ),
        'next': 'employer_1',
        'questions': [
            _q('highest_degree', 'Highest / Last Completed Degree', SELECT, required=True,
               choices=DEGREE_CHOICES),

            # Tick box rather than a yes/no pair: it reads as the heading for the
            # five fields it gates, and untick hides (and clears) them. Not
            # required -- unticked is a complete answer ("no").
            _q('has_masters',
               "Master's / Postgraduate Degree — Do you have a Master's / Postgraduate "
               "Degree?",
               BOOLEAN, choices=YES_NO),
            _q('masters_institution',
               "Master's / Postgraduate Degree — Institution / University Name"),
            _q('masters_degree_name', "Master's / Postgraduate Degree — Degree Name"),
            _q('masters_major', "Master's / Postgraduate Degree — Major / Subject"),
            _q('masters_completion_date',
               "Master's / Postgraduate Degree — Graduation / Completion Date", DATE),
            _q('masters_certificate', "Master's / Postgraduate Degree — Certificate",
               FILE, help=_UPLOAD_HELP),

            _q('bachelors_institution',
               "Undergraduate / Bachelor's Degree — Institution / University Name",
               TEXT, required=True),
            _q('bachelors_degree_name', "Undergraduate / Bachelor's Degree — Degree Name",
               TEXT, required=True),
            _q('bachelors_major', "Undergraduate / Bachelor's Degree — Major / Subject",
               TEXT, required=True),
            _q('bachelors_completion_date',
               "Undergraduate / Bachelor's Degree — Graduation / Completion Date",
               DATE, required=True),
            _q('bachelors_certificate', "Undergraduate / Bachelor's Degree — Certificate",
               FILE, required=True, help=_UPLOAD_HELP),

            _q('hsc_institution', 'HSC / A Level / Equivalent — Institution / College Name',
               TEXT, required=True),
            _q('hsc_board', 'HSC / A Level / Equivalent — Education Board', TEXT,
               required=True),
            _q('hsc_passing_year', 'HSC / A Level / Equivalent — Passing Year', YEAR,
               required=True),
            _q('hsc_result', 'HSC / A Level / Equivalent — Result / GPA', DECIMAL,
               min_value=0, max_value=5, help='GPA on the 5.00 scale.'),
            _q('hsc_certificate', 'HSC / A Level / Equivalent — Certificate', FILE,
               required=True, help=_UPLOAD_HELP),

            _q('ssc_institution', 'SSC / O Level / Equivalent — Institution / School Name',
               TEXT, required=True),
            _q('ssc_board', 'SSC / O Level / Equivalent — Education Board', TEXT,
               required=True),
            _q('ssc_passing_year', 'SSC / O Level / Equivalent — Passing Year', YEAR,
               required=True),
            _q('ssc_result', 'SSC / O Level / Equivalent — Result / GPA', DECIMAL,
               min_value=0, max_value=5, help='GPA on the 5.00 scale.'),
            _q('ssc_certificate', 'SSC / O Level / Equivalent — Certificate', FILE,
               required=True, help=_UPLOAD_HELP),

            _q('training_certification_names',
               'Relevant Training / Professional Certification Name(s)', TEXTAREA,
               help='List all relevant training and professional certification names '
                    'in one answer.'),
            _q('training_certificates',
               'Upload All Relevant Training / Professional Certification Certificates',
               FILES,
               help=f'Up to {MAX_FILES_PER_QUESTION} files. {_UPLOAD_HELP}'),
        ],
    },
]


# ── Section C: employers (PDF Q39-71) ────────────────────────────────────
def _employer_step(index, *, required, next_key, extra=()):
    """Employers 1-4 ask the same eight questions.

    `required` stays False for every block: a fresher must be able to submit.
    Completeness is enforced conditionally in forms.py instead, so an employer is
    either left entirely blank or filled in properly.
    """
    questions = [
        _q(f'employer_{index}_name', f'Employer {index} Name', TEXT, required=required),
        _q(f'employer_{index}_hr_contact',
           f'Employer {index} HR / Official Contact Number', PHONE, required=required),
        _q(f'employer_{index}_hr_email',
           f'Employer {index} HR / Official Email Address', EMAIL, required=required),
        _q(f'employer_{index}_position',
           f'Your Position / Designation at Employer {index}', TEXT, required=required),
        _q(f'employer_{index}_start_date',
           f"Candidate's Claimed Start Date at Employer {index}", DATE, required=required),
        _q(f'employer_{index}_end_date',
           f"Candidate's Claimed End Date at Employer {index}", DATE, required=required),
        _q(f'employer_{index}_reason_leaving',
           f'Reason for Leaving Employer {index}', TEXTAREA),
        _q(f'employer_{index}_contact_permission',
           f'{CONTACT_PERMISSION}Employer {index} for verification?',
           RADIO, required=required, choices=YES_NO),
    ]
    questions.extend(extra)
    return {
        'key': f'employer_{index}',
        'section': f'Section C — Employer {index}',
        'title': f'Employer {index}',
        'description': (
            'Complete employers in the same order as your CV, starting with your '
            'current or most recent employer. Leave this blank and continue if you '
            'have no previous employment to declare.'
            if index == 1 else
            'Leave this blank and continue if you have no further employers to declare.'
        ),
        'next': next_key,
        'questions': questions,
    }


STEPS += [
    # No employer is hard-required; forms.py makes the rest of a block required
    # once its name is filled in. See the module docstring.
    _employer_step(1, required=False, next_key='employer_2'),
    _employer_step(2, required=False, next_key='employer_3'),
    _employer_step(3, required=False, next_key='employer_4'),
    _employer_step(4, required=False, next_key='reference_1', extra=[
        _q('additional_employment_history',
           'Additional Employment History (if more than four employers)', TEXTAREA,
           help='Employer Name, HR/Official Contact Number, Official Email Address, '
                'Position, Start Date, End Date and Reason for Leaving.'),
    ]),
]


# ── Section C: references (PDF Q72-83) ───────────────────────────────────
def _reference_step(index, next_key):
    return {
        'key': f'reference_{index}',
        'section': f'Section C — Professional Reference {index}',
        'title': f'Professional Reference {index}',
        'description': '',
        'next': next_key,
        'questions': [
            _q(f'reference_{index}_name', f'Reference {index} Name', TEXT, required=True),
            _q(f'reference_{index}_designation',
               f'Reference {index} Designation & Company', TEXT, required=True),
            _q(f'reference_{index}_relationship',
               f'Reference {index} Relationship to You', SELECT, required=True,
               choices=RELATIONSHIP_CHOICES),
            _q(f'reference_{index}_contact', f'Reference {index} Contact Number',
               PHONE, required=True),
            _q(f'reference_{index}_email',
               f'Reference {index} Official / Work Email Address', EMAIL, required=True),
            _q(f'reference_{index}_contact_permission',
               f'{CONTACT_PERMISSION}Reference {index}?',
               RADIO, required=True, choices=YES_NO),
        ],
    }


# ── Sections D, D1-D7 (PDF Q84-131) ──────────────────────────────────────
STEPS += [
    _reference_step(1, 'reference_2'),
    _reference_step(2, 'department'),
    {
        'key': 'department',
        'section': 'Section D — Department Selection / Role Question Routing',
        'title': 'Department',
        'description': (
            'Select the department relevant to the position. You will then be routed '
            'to the appropriate role-specific section.'
        ),
        'next': _route_department,
        'questions': [
            _q('department', 'Department', SELECT, required=True,
               choices=DEPARTMENT_CHOICES),
        ],
    },
    {
        'key': 'd1_sales',
        'section': 'Section D1 — Sales / Business / Partnership',
        'title': 'Sales / Business / Partnership',
        'description': '',
        'next': 'd7_declaration',
        'questions': [
            _q('sales_target_achievement',
               'Revenue / Sales Target Achievement over the Last 12 Months (%)',
               DECIMAL, min_value=0, max_value=1000,
               help='Percentage of target achieved. Over 100 is fine.'),
            _q('sales_key_accounts', 'Key Accounts / Client Types Managed', TEXTAREA),
            _q('sales_portfolio_value', 'Approximate Portfolio Value / Deal Size Managed'),
            _q('sales_cycle_length', 'Average Sales Cycle Length'),
            _q('sales_crm_tools', 'CRM / Sales Tools Used', TEXTAREA),
            _q('sales_new_business',
               'New Business / Partnership Acquisition Responsibility', TEXTAREA),
            _q('sales_largest_achievement',
               'Largest Measurable Sales / Business Development Achievement', TEXTAREA),
        ],
    },
    {
        'key': 'd2_marketing',
        'section': 'Section D2 — Marketing / Communications',
        'title': 'Marketing / Communications',
        'description': '',
        'next': 'd7_declaration',
        'questions': [
            _q('marketing_campaigns', 'Campaigns Led in the Last 12 Months', TEXTAREA),
            _q('marketing_budget', 'Approximate Annual Marketing Budget Managed'),
            _q('marketing_channels', 'Primary Marketing Channels / Areas of Expertise',
               CHECKBOX, choices=MARKETING_CHANNEL_CHOICES, help='Select all that apply.'),
            _q('marketing_kpi', 'Key Marketing KPI / Result Achieved', TEXTAREA),
            _q('marketing_tools', 'Marketing / Analytics / Automation Tools Used', TEXTAREA),
            _q('marketing_achievement',
               'Most Significant Marketing / Communications Achievement', TEXTAREA),
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
               choices=FINANCE_AREA_CHOICES, help='Select all that apply.'),
            _q('finance_audit_exposure',
               'Audit Exposure (Internal / External / Regulatory)', TEXTAREA),
            _q('finance_software', 'ERP / Finance Software Used', TEXTAREA),
            _q('finance_budget_responsibility',
               'Budget / Revenue / Cost Responsibility', TEXTAREA),
            _q('finance_reconciliation',
               'Reconciliation / Control / Revenue Leakage Responsibility', TEXTAREA),
            _q('finance_achievement', 'Key Finance / Revenue Assurance Achievement',
               TEXTAREA),
        ],
    },
    {
        'key': 'd4_technology',
        'section': 'Section D4 — Technology / Engineering / Data',
        'title': 'Technology / Engineering / Data',
        'description': '',
        'next': 'd7_declaration',
        'questions': [
            _q('tech_stack', 'Primary Technology Stack / Tools', TEXTAREA),
            _q('tech_systems_owned', 'Systems / Products Owned or Maintained', TEXTAREA),
            _q('tech_incident_responsibility',
               'Incident / Uptime / Production Responsibility', TEXTAREA),
            _q('tech_data_responsibility',
               'Data / Database / Analytics Responsibility (if relevant)', TEXTAREA),
            _q('tech_infra_responsibility',
               'Infrastructure / Cloud / Security Responsibility (if relevant)', TEXTAREA),
            _q('tech_certifications', 'Relevant Technical Certifications', TEXTAREA),
            _q('tech_achievement', 'Most Significant Technical / Data Achievement', TEXTAREA),
        ],
    },
    {
        'key': 'd5_operations',
        'section': 'Section D5 — Operations / Service / Project',
        'title': 'Operations / Service / Project',
        'description': '',
        'next': 'd7_declaration',
        'questions': [
            _q('ops_processes_owned', 'Processes / SLAs / Projects Owned', TEXTAREA),
            _q('ops_kpis', 'Service / Operational KPIs Managed', TEXTAREA),
            _q('ops_team_size', 'Team / Vendor Size Overseen', INTEGER,
               min_value=0, max_value=100000, help='Number of people.'),
            _q('ops_tools', 'Systems / Tools Used for Operations or Project Management',
               TEXTAREA),
            _q('ops_stakeholder_exposure',
               'Customer / Merchant / Internal Stakeholder Exposure', TEXTAREA),
            _q('ops_achievement',
               'Most Significant Operations / Service / Project Achievement', TEXTAREA),
        ],
    },
    {
        'key': 'd6_corporate',
        'section': 'Section D6 — Corporate / Governance / Support',
        'title': 'Corporate / Governance / Support',
        'description': '',
        'next': 'd7_declaration',
        'questions': [
            _q('corp_functional_areas', 'Primary Functional Areas Managed', TEXTAREA),
            _q('corp_frameworks', 'Policies / Regulations / Frameworks Worked With',
               TEXTAREA),
            _q('corp_audit_exposure', 'Audit / Compliance / Risk Exposure (if relevant)',
               TEXTAREA),
            _q('corp_stakeholder_exposure', 'Stakeholder / Management Exposure', TEXTAREA),
            _q('corp_tools', 'Systems / Tools Used', TEXTAREA),
            _q('corp_achievement',
               'Most Significant Measurable Functional Achievement', TEXTAREA),
        ],
    },
    {
        'key': 'd7_declaration',
        'section': 'Section D7 — Candidate Declaration & Availability',
        'title': 'Declaration & Availability',
        'description': '',
        'next': None,
        'questions': [
            _q('total_experience_years', 'Total Years of Professional Experience',
               DECIMAL, required=True, min_value=0, max_value=60, decimals=1),
            _q('notice_period_days', 'Notice Period (days)', INTEGER,
               min_value=0, max_value=365),
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
            _q('typed_signature', 'Candidate Full Name (typed signature)', TEXT,
               required=True),
            _q('declaration_date', 'Declaration Date', DATE, required=True),
        ],
    },
]


# ── Presentation hints ───────────────────────────────────────────────────
# Kept out of the question dicts so the definitions above stay about *what* is
# asked, not how it is laid out.

# Fields short enough to share a row. Anything unlisted spans the form.
HALF_WIDTH_KEYS = frozenset({
    'mobile_number', 'personal_email', 'nid_number',
    'birth_certificate_number', 'date_of_birth', 'position_applied_for',
    'masters_completion_date', 'bachelors_completion_date',
    'hsc_board', 'hsc_passing_year', 'hsc_result',
    'ssc_board', 'ssc_passing_year', 'ssc_result',
    'total_experience_years', 'notice_period_days', 'earliest_joining_date',
    'declaration_date', 'typed_signature',
    'sales_target_achievement', 'sales_cycle_length', 'sales_portfolio_value',
    'marketing_budget', 'ops_team_size',
    *(f'employer_{i}_hr_contact' for i in range(1, 5)),
    *(f'employer_{i}_hr_email' for i in range(1, 5)),
    *(f'employer_{i}_start_date' for i in range(1, 5)),
    *(f'employer_{i}_end_date' for i in range(1, 5)),
    *(f'reference_{i}_contact' for i in range(1, 3)),
    *(f'reference_{i}_email' for i in range(1, 3)),
})


def _employer_groups(index):
    return [
        (f'Employer {index}', [
            f'employer_{index}_name',
            f'employer_{index}_hr_contact',
            f'employer_{index}_hr_email',
        ]),
        ('Your role there', [
            f'employer_{index}_position',
            f'employer_{index}_start_date',
            f'employer_{index}_end_date',
            f'employer_{index}_reason_leaving',
        ]),
        ('Verification', [f'employer_{index}_contact_permission']),
    ]


def _reference_groups(index):
    return [
        (f'Reference {index}', [
            f'reference_{index}_name',
            f'reference_{index}_designation',
            f'reference_{index}_relationship',
        ]),
        ('How we reach them', [
            f'reference_{index}_contact',
            f'reference_{index}_email',
        ]),
        ('Verification', [f'reference_{index}_contact_permission']),
    ]


# Sub-headings inside a step, so a 24-question page reads as a few short blocks.
# A step absent from here renders as one ungrouped block.
STEP_GROUPS = {
    'section_a': [
        ('Your details', [
            'candidate_full_name', 'date_of_birth',
            'nid_number', 'birth_certificate_number',
        ]),
        ('How we reach you', [
            'mobile_number', 'personal_email', 'position_applied_for',
        ]),
        ('Addresses', ['present_address', 'address_same', 'permanent_address']),
        ('Identity documents', ['nid_copy', 'birth_certificate_copy']),
        ('Consent', ['verification_consent']),
    ],
    'section_b': [
        ('', ['highest_degree']),
        ("Master's / Postgraduate", [
            'has_masters', 'masters_institution', 'masters_degree_name',
            'masters_major', 'masters_completion_date', 'masters_certificate',
        ]),
        ("Undergraduate / Bachelor's", [
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
        ('Training & professional certifications', [
            'training_certification_names', 'training_certificates',
        ]),
    ],
    'employer_1': _employer_groups(1),
    'employer_2': _employer_groups(2),
    'employer_3': _employer_groups(3),
    'employer_4': _employer_groups(4) + [
        ('More than four employers', ['additional_employment_history']),
    ],
    'reference_1': _reference_groups(1),
    'reference_2': _reference_groups(2),
    'd7_declaration': [
        ('Experience & availability', [
            'total_experience_years', 'notice_period_days',
            'earliest_joining_date', 'availability_status',
        ]),
        ('Your current role', ['current_responsibilities', 'measurable_achievements']),
        ('Declaration', ['declaration_agreement', 'typed_signature', 'declaration_date']),
    ],
}


# ── Inline branches ──────────────────────────────────────────────────────
# Steps whose branch target is rendered on the *same* page rather than as a
# separate step. Section D is one dropdown; making the candidate submit a page to
# answer it, only to be shown the role questions next, wasted a page transition.
#
# The server still has to learn the department before it knows which questions to
# ask -- that round trip is unavoidable -- so `views.role_fields` serves just the
# role block and the select swaps it in via htmx.
INLINE_BRANCHES = {'department': _route_department}

# The only sections an inline branch may pull onto its host page. Guards against
# absorbing a resolver's fallback (see `inline_target`).
INLINE_TARGETS = frozenset(DEPARTMENT_ROUTING.values())


def inline_target(step_key, answers):
    """The step whose questions are rendered inside `step_key`, if any.

    Nothing is absorbed until the branch question is actually answered, and only
    a genuine branch destination can be absorbed -- `_route_department` falls back
    to the declaration for an unknown department, and pulling *that* onto the page
    would put the signature block above the role questions.
    """
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
    """Resolve the step after `step_key`, skipping any section with no questions.

    A section absorbed into its host page (see INLINE_BRANCHES) is skipped too --
    its questions were already answered on the host step.
    """
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
    """The ordered step keys these answers lead through.

    Replayed from the start rather than assumed, because Section D branches on
    the chosen department.
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


def review_path(answers):
    """`step_path`, with absorbed sections named in their own right.

    The wizard renders an absorbed section inside its host page, but the
    recruiter view still groups answers by section -- so it walks this instead.
    """
    out = []
    for key in step_path(answers):
        out.append(key)
        target = inline_target(key, answers)
        if target:
            out.append(target)
    return out


def _question_numbers(answers):
    """{question key: number} across the whole path these answers lead through."""
    numbers, n = {}, 1
    for key in review_path(answers):
        for question in STEPS_BY_KEY[key]['questions']:
            numbers[question['key']] = n
            n += 1
    return numbers


def numbered_questions(step_key, answers):
    """A step's own questions, each with the number shown to the candidate."""
    step = STEPS_BY_KEY.get(step_key)
    if not step:
        return []
    numbers = _question_numbers(answers)
    return [
        dict(q, number=numbers.get(q['key'], offset + 1))
        for offset, q in enumerate(step['questions'])
    ]


def numbered_wizard_questions(step_key, answers):
    """Everything the candidate fills in on `step_key`, absorbed sections included."""
    numbers = _question_numbers(answers)
    return [
        dict(q, number=numbers.get(q['key'], offset + 1))
        for offset, q in enumerate(wizard_questions(step_key, answers))
    ]


def question_groups(step_key, answers):
    """A step's questions arranged into titled blocks for rendering.

    Any question missing from STEP_GROUPS is appended rather than dropped -- a
    typo there must not hide a question.
    """
    questions = numbered_wizard_questions(step_key, answers)
    by_key = {q['key']: q for q in questions}

    groups = list(STEP_GROUPS.get(step_key) or [])
    target = inline_target(step_key, answers)
    if target:
        # The absorbed section brings its own sub-headings, or one block titled
        # after the section so the candidate sees what they were routed into.
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
        return value
    return dict(q['choices']).get(value, value)


# Labels shortened for the wizard only, where the group heading already carries
# the context ("MASTER'S / POSTGRADUATE" above "Institution / University Name").
# The full label stays authoritative everywhere the heading is absent -- the
# recruiter review page, CSV export, the admin.
def _short_labels():
    out = {}
    for prefix, keys in [
        ("Master's / Postgraduate Degree — ", [
            'has_masters', 'masters_institution', 'masters_degree_name',
            'masters_major', 'masters_completion_date', 'masters_certificate']),
        ("Undergraduate / Bachelor's Degree — ", [
            'bachelors_institution', 'bachelors_degree_name', 'bachelors_major',
            'bachelors_completion_date', 'bachelors_certificate']),
        ('HSC / A Level / Equivalent — ', [
            'hsc_institution', 'hsc_board', 'hsc_passing_year', 'hsc_result',
            'hsc_certificate']),
        ('SSC / O Level / Equivalent — ', [
            'ssc_institution', 'ssc_board', 'ssc_passing_year', 'ssc_result',
            'ssc_certificate']),
    ]:
        for key in keys:
            label = QUESTIONS_BY_KEY[key]['label']
            if label.startswith(prefix):
                out[key] = label[len(prefix):]

    out['address_same'] = 'Same as my Present Address'
    out['has_masters'] = "I have a Master's / Postgraduate degree"

    for index in range(1, 5):
        out[f'employer_{index}_name'] = 'Employer name'
        out[f'employer_{index}_hr_contact'] = 'HR / official contact number'
        out[f'employer_{index}_hr_email'] = 'HR / official email address'
        out[f'employer_{index}_position'] = 'Your position / designation'
        out[f'employer_{index}_start_date'] = 'Claimed start date'
        out[f'employer_{index}_end_date'] = 'Claimed end date'
        out[f'employer_{index}_reason_leaving'] = 'Reason for leaving'
        out[f'employer_{index}_contact_permission'] = (
            'May we contact this employer for verification?'
        )

    for index in (1, 2):
        out[f'reference_{index}_name'] = 'Name'
        out[f'reference_{index}_designation'] = 'Designation & company'
        out[f'reference_{index}_relationship'] = 'Relationship to you'
        out[f'reference_{index}_contact'] = 'Contact number'
        out[f'reference_{index}_email'] = 'Official / work email address'
        out[f'reference_{index}_contact_permission'] = 'May we contact this reference?'

    return out


SHORT_LABELS = _short_labels()


def wizard_label(question) -> str:
    """The label to show on the candidate form."""
    return SHORT_LABELS.get(question['key'], question['label'])
