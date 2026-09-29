"""HR Background Verification & Joining Form, declared as data.

Source: "SSL Wireless – HR Background Verification & Joining Form" (PDF), Q1-Q99
in seven sections, same wording, types, required marks and option order.
Short→TEXT, Paragraph→TEXTAREA, Dropdown→SELECT, Multiple choice→RADIO,
Checkboxes→CHECKBOX, File→FILE (PDF or image). Branching is `show_if` /
`required_if` from apps.core.form_logic; grids become one field per row × column.
"""
from apps.core.form_logic import all_of, any_of, filled, negate, when
from apps.employee_form.schema import (  # noqa: F401
    BOOLEAN,
    CHECKBOX,
    CHOICE_TYPES,
    DATE,
    DEPARTMENT_CHOICES,
    EMPLOYER_MAX,
    FILE,
    FILE_TYPES,
    MAX_UPLOAD_MB,
    PDF_IMAGE,
    RADIO,
    RELATIONSHIP_CHOICES,
    SELECT,
    TEXT,
    TEXTAREA,
)

REFERENCE_COUNT = 2


def _q(key, label, qtype=TEXT, required=False, help='', choices=None, no=None,
       show_if=None, required_if=None):
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
        q['formats'] = PDF_IMAGE
    return q


# ── Choice sets (PDF order) ──────────────────────────────────────────────
YES_NO = [('yes', 'Yes'), ('no', 'No')]
YES_NO_NA = [('yes', 'Yes'), ('no', 'No'), ('na', 'Not Applicable')]

_DEPARTMENT_ORDER = [
    'banking_financial_services', 'business_development', 'data',
    'digital_communications', 'documentation_external_audit', 'ecommerce_operations',
    'ecommerce_services', 'engineering', 'finance_accounts', 'government_project',
    'human_resources', 'infrastructure_security', 'innovation_coe',
    'internal_control_compliance', 'legal_affairs', 'enterprise_risk_management',
    'management', 'partnership_management', 'procurement',
    'project_management_office', 'revenue_assurance', 'risk_compliance',
    'service_assurance_call_center', 'service_assurance_quality_assurance',
    'service_assurance_technical_operations',
]
HR_DEPARTMENT_CHOICES = [(v, dict(DEPARTMENT_CHOICES)[v]) for v in _DEPARTMENT_ORDER]

VERIFICATION_ROUTE = [
    ('internal_hr', 'Internal HR'),
    ('agency', 'Background Check Agency'),
    ('both', 'Both Internal HR and Background Check Agency'),
]
IDENTITY_STATUS = [('yes', 'Verified'), ('no', 'Not Verified'), ('na', 'N/A')]
IDENTITY_DOC_METHOD = [
    ('document', 'Document'), ('official_source', 'Official Source'),
    ('agency', 'Agency'), ('other', 'Other'),
]
ADDRESS_METHOD = [
    ('document', 'Document'), ('field', 'Field'), ('agency', 'Agency'), ('other', 'Other'),
]
POLICE_ROUTE = [
    ('direct_internal', 'Direct / Internal'),
    ('agency', 'Background Check Agency'),
    ('other', 'Other'),
]
POLICE_STATUS = [
    ('not_started', 'Not Started'),
    ('in_progress', 'In Progress'),
    ('clear', 'Clear / Satisfactory'),
    ('concern', 'Concern / Adverse Finding'),
]

HIGHEST_DEGREE_CHOICES = [
    ('masters', "Master's / Postgraduate Degree"),
    ('bachelors', "Undergraduate / Bachelor's Degree"),
    ('hsc', 'HSC / A Level / Equivalent'),
    ('ssc', 'SSC / O Level / Equivalent'),
    ('other', 'Other'),
]
CONSISTENCY_CHOICES = [('yes', 'Yes'), ('no', 'No'),
                       ('further_review', 'Further Review Required')]
CERTIFICATE_RECEIVED = [('yes', 'Yes'), ('no', 'No'), ('na', 'N/A')]
EDUCATION_STATUS = [
    ('verified', 'Verified'), ('partially', 'Partially'),
    ('unable', 'Unable'), ('na', 'N/A'),
]
UNIVERSITY_METHOD = [
    ('document_review', 'Document'), ('institution_confirmation', 'Institution'),
    ('online', 'Online'), ('agency', 'Agency'), ('other', 'Other'),
]
BOARD_METHOD = [
    ('document_review', 'Document'), ('institution_confirmation', 'Board'),
    ('online', 'Online'), ('agency', 'Agency'), ('other', 'Other'),
]
TRAINING_STATUS = [
    ('verified', 'Verified'),
    ('partially_verified', 'Partially Verified'),
    ('unable', 'Unable to Verify'),
    ('na', 'Not Applicable'),
]
TRAINING_METHOD = [
    ('certificate_review', 'Certificate Review'),
    ('issuing_organisation', 'Issuing Organisation Confirmation'),
    ('online', 'Online Verification'),
    ('agency', 'Background Check Agency'),
    ('other', 'Other'),
]

HAS_EMPLOYMENT = [('yes', 'Yes'), ('no', 'No — Fresher / no applicable employment history')]
EMPLOYER_STATUS = [
    ('verified', 'Verified'),
    ('partially_verified', 'Partially Verified'),
    ('unable', 'Unable to Verify'),
    ('not_attempted', 'Not Yet Attempted'),
]
EMPLOYER_METHOD = [
    ('direct_call', 'Direct Call to Employer HR'),
    ('official_email', 'Official Email Confirmation'),
    ('written_reference', 'Written Reference / Service Letter'),
    ('agency', 'Background Check Agency'),
    ('other', 'Other'),
]
REASON_CONSISTENT = [
    ('yes', 'Yes'), ('no', 'No'),
    ('not_disclosed', 'Employer Would Not Disclose'), ('na', 'Not Applicable'),
]
REHIRE_CHOICES = [
    ('yes', 'Yes'), ('no', 'No'), ('not_disclosed', 'Not Disclosed'), ('na', 'Not Applicable'),
]

REFERENCE_STATUS = [
    ('verified', 'Verified'), ('unable', 'Unable to Verify'),
    ('not_attempted', 'Not Yet Attempted'),
]
REFERENCE_METHOD = [
    ('direct_call', 'Direct Call'), ('official_email', 'Official Email'),
    ('agency', 'Agency'), ('other', 'Other'),
]
REFERENCE_RECOMMEND = [
    ('yes', 'Yes'), ('no', 'No'),
    ('conditional', 'Conditional / With Reservations'),
    ('not_asked', 'Not Asked / Not Disclosed'),
]
ROLE_CONSISTENCY = [('yes', 'Yes'), ('no', 'No'), ('partially', 'Partially'),
                    ('na', 'Not Applicable')]

FINDING_CATEGORIES = [
    ('performance', 'Performance'),
    ('disciplinary', 'Disciplinary'),
    ('integrity', 'Integrity / Conduct'),
    ('legal_police', 'Legal / Police'),
    ('involuntary_separation', 'Involuntary Separation'),
    ('employment_discrepancy', 'Employment Discrepancy'),
    ('education_document', 'Education / Document Discrepancy'),
    ('reference_concern', 'Reference Concern'),
    ('other', 'Other'),
]
FINDING_SOURCE = [
    ('former_employer_hr', 'Former Employer HR'),
    ('former_manager', 'Former Direct Manager'),
    ('professional_reference', 'Professional Reference'),
    ('agency', 'Background Check Agency'),
    ('police', 'Police Verification'),
    ('document', 'Document Verification'),
    ('other', 'Other'),
]
SOURCE_RELIABILITY = [
    ('verified', 'Verified / Documented'),
    ('corroborated', 'Corroborated by 2+ Independent Sources'),
    ('single_source', 'Single Source, Plausible'),
    ('unverified', 'Unverified / Rumour'),
]
CLARIFY_CHOICES = [('yes', 'Yes'), ('no', 'No'), ('not_required', 'Not Required')]
RISK_RATING = [
    ('green', 'Green – No Material Concern'),
    ('amber', 'Amber – Minor / Explainable Concern'),
    ('red', 'Red – Material Concern Requiring Escalation'),
    ('critical', 'Critical – Serious / Disqualifying Concern'),
]
RECOMMENDATION_CHOICES = [
    ('cleared', 'Cleared'),
    ('cleared_conditions', 'Cleared with Conditions / Clarification'),
    ('further_review', 'Further Review Required'),
    ('not_cleared', 'Not Cleared'),
]

FINAL_STATUS_CHOICES = [
    ('cleared', 'Cleared'),
    ('conditionally_cleared', 'Conditionally Cleared'),
    ('pending_exception', 'Pending Approved Exception'),
    ('not_cleared', 'Not Cleared'),
]
OFFER_ACCEPTED_CHOICES = [('yes', 'Yes'), ('no', 'No'), ('pending', 'Pending')]
CHECKLIST_STATUS = [
    ('complete', 'Complete'),
    ('pending', 'Pending'),
    ('not_required', 'Not Required'),
    ('not_available', 'Not Available / Concern'),
]
JOINING_CLEARANCE = [
    ('cleared_to_join', 'Cleared to Join / Joined'),
    ('cleared_followup', 'Cleared with Follow-up'),
    ('hold', 'Hold'),
    ('do_not_proceed', 'Do Not Proceed'),
]


# ── Grids: one field per row × column ────────────────────────────────────
def _grid(title, no, rows, columns):
    """rows: (prefix, row label, extra); columns: (suffix, label, type, choices|callable)."""
    return {'title': title, 'no': no, 'rows': rows, 'columns': columns}


def _grid_questions(grid, show_if_for=None, required_suffixes=()):
    out = []
    for prefix, row_label, extra in grid['rows']:
        show = show_if_for(prefix) if show_if_for else None
        for suffix, col_label, qtype, choices in grid['columns']:
            if callable(choices):
                choices = choices(prefix, extra)
            if callable(qtype):
                qtype = qtype(prefix, extra)
            out.append(_q(f'{prefix}_{suffix}', f'{row_label} — {col_label}', qtype,
                          required=suffix in required_suffixes, choices=choices,
                          no=grid['no'], show_if=show))
    return out


def _grid_keys(grid, prefix):
    return [f'{prefix}_{suffix}' for suffix, *_ in grid['columns']]


IDENTITY_GRID = _grid(
    'Identity & Address Verification Record', 19,
    rows=[
        ('nid', 'NID', 'document'),
        ('birth_certificate', 'Birth Certificate', 'document'),
        ('dob', 'Date of Birth', 'document'),
        ('present_address', 'Present Address', 'address'),
        ('permanent_address', 'Permanent Address', 'address'),
    ],
    columns=[
        ('submitted_value', 'Candidate-submitted value',
         lambda p, kind: TEXTAREA if kind == 'address' else TEXT, None),
        ('verified', 'Verification status', SELECT, IDENTITY_STATUS),
        ('method', 'Method / Source', SELECT,
         lambda p, kind: ADDRESS_METHOD if kind == 'address' else IDENTITY_DOC_METHOD),
        ('remarks', 'Discrepancy / Remarks', TEXT, None),
    ],
)

EDUCATION_GRID = _grid(
    'Qualification Verification Record', 29,
    rows=[
        ('masters', "Master's / Postgraduate", 'university'),
        ('bachelors', "Undergraduate / Bachelor's", 'university'),
        ('hsc', 'HSC / A Level / Equivalent', 'board'),
        ('ssc', 'SSC / O Level / Equivalent', 'board'),
        ('other', 'Other', 'university'),
    ],
    columns=[
        ('details', 'Candidate details / institution / degree / date', TEXTAREA, None),
        ('certificate_received', 'Certificate received?', SELECT, CERTIFICATE_RECEIVED),
        ('verification_status', 'Verification status', SELECT, EDUCATION_STATUS),
        ('verification_method', 'Verification method', SELECT,
         lambda p, kind: BOARD_METHOD if kind == 'board' else UNIVERSITY_METHOD),
        ('remarks', 'Discrepancy / Remarks', TEXT, None),
    ],
)

JOINING_GRID = _grid(
    'Joining Document Verification Checklist', 90,
    rows=[
        ('joining_certificates', 'Original / required educational certificates', None),
        ('joining_nid', 'Original NID / identity document', None),
        ('joining_employment_documents', 'Employment / release / experience documents', None),
        ('joining_police_report', 'Police / background check report', None),
    ],
    columns=[
        ('status', 'Status', SELECT, CHECKLIST_STATUS),
        ('notes', 'Notes', TEXT, None),
    ],
)

# Q27 decides which Q29 rows apply: only qualifications the candidate declared.
EDUCATION_ROWS_FOR_DEGREE = {
    'masters': ('masters', 'bachelors', 'hsc', 'ssc'),
    'bachelors': ('bachelors', 'hsc', 'ssc'),
    'hsc': ('hsc', 'ssc'),
    'ssc': ('ssc',),
    'other': ('other', 'hsc', 'ssc'),
}


def education_row_shown(prefix):
    degrees = [d for d, rows in EDUCATION_ROWS_FOR_DEGREE.items() if prefix in rows]
    return when('highest_degree', *degrees)


# ── Rules reused across questions ────────────────────────────────────────
_AGENCY = when('verification_route', 'agency', 'both')
_POLICE = when('police_verification_required', 'yes')
_TRAINING = filled('training_certification_names')
_ADVERSE = when('adverse_concern_raised', 'yes')

IDENTITY_ROWS = [p for p, _, _ in IDENTITY_GRID['rows']]
EDUCATION_ROWS = [p for p, _, _ in EDUCATION_GRID['rows']]
JOINING_ROWS = [p for p, _, _ in JOINING_GRID['rows']]

Q99_TRIGGER = any_of(
    when('risk_rating', 'red', 'critical'),
    when('verification_recommendation', 'further_review', 'not_cleared'),
    when('exception_required', 'yes'),
    when('adverse_concern_raised', 'yes'),
    when('police_verification_status', 'concern'),
)


# ── Employment: Q36 gate, then a chain of employer blocks (Q37-Q52) ──────
def employer_shown(index):
    rule = when('has_employment', 'yes')
    if index == 1:
        return rule
    return all_of(employer_shown(index - 1), when(f'employer_{index - 1}_another', 'yes'))


def _employer_block(index):
    p = f'employer_{index}'
    e = f'Employer {index} — '
    shown = employer_shown(index)
    status = f'{p}_verification_status'
    questions = [
        _q(f'{p}_name', f'{e}Employer Name', required=True, no=37, show_if=shown),
        _q(f'{p}_hr_contact', f'{e}Employer HR / Official Verification Contact', TEXTAREA,
           required=True, no=38, show_if=shown,
           help='Official contact number and official email.'),
        _q(f'{p}_position', f'{e}Candidate-claimed Position / Designation',
           required=True, no=39, show_if=shown),
        _q(f'{p}_claimed_start_date', f'{e}Candidate-claimed Employment Period — Start',
           DATE, required=True, no=40, show_if=shown),
        _q(f'{p}_claimed_current', f'{e}Candidate-claimed Employment Period — Current',
           BOOLEAN, no=40, show_if=shown),
        _q(f'{p}_claimed_end_date', f'{e}Candidate-claimed Employment Period — End',
           DATE, required=True, no=40,
           show_if=all_of(shown, negate(when(f'{p}_claimed_current', 'yes')))),
        _q(f'{p}_confirmed_position', f'{e}Employer-confirmed Position / Designation',
           no=41, show_if=shown, help='Enter "Not Disclosed" if the employer refuses.'),
        _q(f'{p}_confirmed_start_date', f'{e}Employer-confirmed Employment Period — Start',
           DATE, no=42, show_if=shown),
        _q(f'{p}_confirmed_current', f'{e}Employer-confirmed Employment Period — Current',
           BOOLEAN, no=42, show_if=shown),
        _q(f'{p}_confirmed_end_date', f'{e}Employer-confirmed Employment Period — End',
           DATE, no=42,
           show_if=all_of(shown, negate(when(f'{p}_confirmed_current', 'yes')))),
        _q(status, f'{e}Employment Verification Status', SELECT, required=True,
           choices=EMPLOYER_STATUS, no=43, show_if=shown),
        _q(f'{p}_verification_method', f'{e}Employment Verification Method', SELECT,
           choices=EMPLOYER_METHOD, no=44, show_if=shown,
           required_if=when(status, 'verified', 'partially_verified', 'unable'),
           help='Required once verification has been attempted.'),
        _q(f'{p}_verifier_name', f'{e}Verifier Name & Designation', no=45, show_if=shown),
        _q(f'{p}_claimed_reason_leaving', f"{e}Candidate's Stated Reason for Leaving",
           TEXTAREA, no=46, show_if=shown),
        _q(f'{p}_confirmed_reason_leaving', f"{e}Employer's Confirmed Reason for Leaving",
           TEXTAREA, no=47, show_if=shown, help='Or "Not Disclosed".'),
        _q(f'{p}_reason_consistent',
           f'{e}Reason for Leaving Consistent with Candidate Statement?', RADIO,
           choices=REASON_CONSISTENT, no=48, show_if=shown),
        _q(f'{p}_rehire_eligible', f'{e}Eligible for Rehire?', RADIO,
           choices=REHIRE_CHOICES, no=49, show_if=shown),
        _q(f'{p}_tenure_discrepancy', f'{e}Employment Discrepancy Found?', RADIO,
           required=True, choices=YES_NO, no=50, show_if=shown),
        _q(f'{p}_remarks', f'{e}Employer Verification Remarks / Discrepancy Details',
           TEXTAREA, no=51, show_if=shown,
           required_if=any_of(when(f'{p}_tenure_discrepancy', 'yes'),
                              when(f'{p}_reason_consistent', 'no')),
           help='Required when a discrepancy is found or the reason for leaving is '
                'inconsistent.'),
    ]
    if index < EMPLOYER_MAX:
        questions.append(
            _q(f'{p}_another', f'{e}Is there another employer to verify?', RADIO,
               required=True, choices=YES_NO, no=52, show_if=shown))
    return questions


def _reference_block(index):
    p = f'reference_{index}'
    r = f'Reference {index}'
    base = 53 if index == 1 else 60
    return [
        _q(f'{p}_name', f'{r} Name', required=True, no=base),
        _q(f'{p}_designation', f'{r} Designation & Company / Institution', required=True,
           no=base + 1),
        _q(f'{p}_relationship', f'{r} Relationship to Candidate', SELECT,
           choices=RELATIONSHIP_CHOICES, no=base + 2),
        _q(f'{p}_contact', f'{r} Contact Details', TEXTAREA, no=base + 3,
           help='Phone and official / work email.'),
        _q(f'{p}_verification_status', f'{r} Verification Status', SELECT, required=True,
           choices=REFERENCE_STATUS, no=base + 4),
        _q(f'{p}_verification_method', f'{r} Verification Method', SELECT,
           choices=REFERENCE_METHOD, no=base + 4,
           required_if=negate(when(f'{p}_verification_status', 'not_attempted'))),
        _q(f'{p}_feedback', f'{r} Feedback Summary', TEXTAREA, no=base + 5),
        _q(f'{p}_recommend', f'Would {r} Rehire / Recommend the Candidate?', RADIO,
           choices=REFERENCE_RECOMMEND, no=base + 6),
    ]


# ── Sections 1-7 ─────────────────────────────────────────────────────────
STEPS = [
    {
        'key': 'hr_review',
        'section': 'Candidate Link, HR Review & Verification Route',
        'title': 'HR Review & Verification Route',
        'description': 'Use the same Candidate Full Name and Department as the Employee '
                       'Information Form.',
        'next': 'identity',
        'questions': [
            _q('candidate_full_name', 'Candidate Full Name', required=True, no=2,
               help='Must match the Employee Information Form.'),
            _q('position_applied_for', 'Position Applied For', required=True, no=3),
            _q('department', 'Department', SELECT, required=True,
               choices=HR_DEPARTMENT_CHOICES, no=4,
               help='Must match the candidate form.'),
            _q('hr_reviewer_name', 'HR Reviewer Name', required=True, no=5),
            _q('hr_reviewer_designation', 'HR Reviewer Designation', required=True, no=6),
            _q('verification_start_date', 'Verification Start Date', DATE, required=True,
               no=7),
            _q('verification_route', 'Verification Route', SELECT, required=True,
               choices=VERIFICATION_ROUTE, no=8),
            _q('agency_name', 'Background Check Agency Name', required=True, no=9,
               show_if=_AGENCY),
            _q('agency_contact', 'Agency Contact Person / Contact Details', TEXTAREA,
               required=True, no=10, show_if=_AGENCY, help='Name, phone, email.'),
            _q('agency_report_reference', 'Agency Report Reference Number', no=11,
               show_if=_AGENCY, help='When the agency report is available.'),
            _q('agency_report_date', 'Agency Report Date', DATE, no=12, show_if=_AGENCY,
               help='When the agency report is available.'),
            _q('agency_report_file', 'Agency Report / Supporting Evidence', FILE, no=13,
               show_if=_AGENCY,
               help=f'PDF or image. Optional until received. Max {MAX_UPLOAD_MB} MB.'),
        ],
    },
    {
        'key': 'identity',
        'section': 'Identity, Address & Police Verification',
        'title': 'Identity, Address & Police',
        'description': 'Copied from the Employee Information Form. Cross-check each '
                       'against the candidate\'s documents.',
        'next': 'education',
        'questions': [
            _q('candidate_nid_number', 'Candidate NID Number', required=True, no=14),
            _q('candidate_birth_certificate_number',
               'Candidate Birth Certificate Number (if applicable)', no=15),
            _q('candidate_date_of_birth', 'Candidate Date of Birth', DATE, required=True,
               no=16),
            _q('candidate_present_address', 'Candidate Present Address', TEXTAREA,
               required=True, no=17),
            _q('candidate_permanent_address', 'Candidate Permanent Address', TEXTAREA,
               no=18, help='Only if different from the present address.'),
            *_grid_questions(IDENTITY_GRID, required_suffixes=('verified',)),
            _q('identity_remarks', 'Overall Identity / Address Verification Remarks',
               TEXTAREA, no=20,
               required_if=any_of(*(when(f'{p}_verified', 'no') for p in IDENTITY_ROWS)),
               help='Complete if any item is Not Verified.'),
            _q('police_verification_required', 'Police Verification Required?', RADIO,
               required=True, choices=YES_NO, no=21),
            _q('police_verification_route', 'Police Verification Route', SELECT,
               required=True, choices=POLICE_ROUTE, no=22, show_if=_POLICE),
            _q('police_verification_status', 'Police Verification Status', SELECT,
               required=True, choices=POLICE_STATUS, no=23, show_if=_POLICE),
            _q('police_verification_reference',
               'Police Verification Reference / Report Number', no=24, show_if=_POLICE),
            _q('police_verification_date', 'Police Verification Date', DATE, no=25,
               show_if=_POLICE),
            _q('police_verification_remarks', 'Police Verification Remarks', TEXTAREA,
               no=26, show_if=_POLICE,
               required_if=when('police_verification_status', 'concern'),
               help='Required if the status is Concern / Adverse Finding; carry it to '
                    'Adverse Findings.'),
        ],
    },
    {
        'key': 'education',
        'section': 'Educational Qualification & Training Verification',
        'title': 'Education & Training',
        'description': 'Verify only qualifications actually declared by the candidate.',
        'next': 'employment',
        'questions': [
            _q('highest_degree', 'Candidate Highest / Last Completed Degree', SELECT,
               required=True, choices=HIGHEST_DEGREE_CHOICES, no=27,
               help='Determines which qualification rows apply.'),
            _q('highest_degree_consistent',
               'Highest / Last Completed Degree Consistent with Submitted Documents?',
               RADIO, required=True, choices=CONSISTENCY_CHOICES, no=28),
            *_grid_questions(EDUCATION_GRID, show_if_for=education_row_shown,
                             required_suffixes=('verification_status',)),
            _q('education_remarks',
               'Overall Education Verification Remarks / Discrepancy Details', TEXTAREA,
               no=30,
               required_if=any_of(
                   when('highest_degree_consistent', 'no', 'further_review'),
                   *(when(f'{p}_verification_status', 'partially', 'unable')
                     for p in EDUCATION_ROWS)),
               help='Complete when the degree is not consistent / needs further review, '
                    'or any row is not fully verified.'),
            _q('training_certification_names',
               'Relevant Training / Professional Certification Name(s) — as provided by '
               'candidate', TEXTAREA, no=31),
            _q('training_certificates_received',
               'Training / Professional Certification Certificates Received?', RADIO,
               required=True, choices=YES_NO_NA, no=32, show_if=_TRAINING),
            _q('training_verification_status',
               'Training / Professional Certification Verification Status', SELECT,
               required=True, choices=TRAINING_STATUS, no=33, show_if=_TRAINING),
            _q('training_verification_method',
               'Training / Certification Verification Method', SELECT, required=True,
               choices=TRAINING_METHOD, no=34,
               show_if=all_of(_TRAINING, when('training_verification_status', 'verified',
                                              'partially_verified', 'unable'))),
            _q('training_remarks',
               'Training / Certification Verification Remarks / Discrepancy Details',
               TEXTAREA, no=35, show_if=_TRAINING,
               required_if=when('training_verification_status', 'partially_verified',
                                'unable', 'na')),
        ],
    },
    {
        'key': 'employment',
        'section': 'Employment Verification',
        'title': 'Employment',
        'description': 'Verify every employer in the same order as the candidate form.',
        'next': 'references',
        'questions': [
            _q('has_employment',
               'Does the candidate have previous full-time / contractual employment '
               'experience to verify?', RADIO, required=True, choices=HAS_EMPLOYMENT,
               no=36),
            *[q for i in range(1, EMPLOYER_MAX + 1) for q in _employer_block(i)],
        ],
    },
    {
        'key': 'references',
        'section': 'Professional Reference Verification & Role Profile Review',
        'title': 'References & Role Profile',
        'description': 'Reference numbering matches the Employee Information Form.',
        'next': 'findings',
        'questions': [
            *[q for i in range(1, REFERENCE_COUNT + 1) for q in _reference_block(i)],
            _q('role_profile_reviewed',
               'Candidate Department / Role Profile Information Reviewed?', RADIO,
               required=True, choices=YES_NO_NA, no=67),
            _q('role_claims_consistent',
               'Role-Specific Claims Reasonably Consistent with CV / Interview / '
               'Available Evidence?', RADIO, choices=ROLE_CONSISTENCY, no=68),
            _q('role_further_validation',
               'Role-Specific Information Requiring Further Validation', TEXTAREA,
               required=True, no=69,
               show_if=when('role_claims_consistent', 'no', 'partially')),
        ],
    },
    {
        'key': 'findings',
        'section': 'Adverse Findings, Discrepancy & BGV Outcome',
        'title': 'Adverse Findings & BGV Outcome',
        'description': '',
        'next': 'clearance',
        'questions': [
            _q('adverse_concern_raised',
               'Any performance, disciplinary, integrity, legal, employment-separation or '
               'other material concern raised?', RADIO, required=True, choices=YES_NO,
               no=70),
            _q('finding_categories', 'Finding Category', CHECKBOX, required=True,
               choices=FINDING_CATEGORIES, no=71, show_if=_ADVERSE),
            _q('finding_source', 'Source of Finding', SELECT, required=True,
               choices=FINDING_SOURCE, no=72, show_if=_ADVERSE),
            _q('source_reliability', 'Reliability of Source', SELECT, required=True,
               choices=SOURCE_RELIABILITY, no=73, show_if=_ADVERSE),
            _q('finding_details', 'Evidence / Finding Details', TEXTAREA, required=True,
               no=74, show_if=_ADVERSE),
            _q('candidate_clarification_opportunity',
               'Was the Candidate Given an Opportunity to Clarify?', RADIO, required=True,
               choices=CLARIFY_CHOICES, no=75, show_if=_ADVERSE),
            _q('candidate_clarification', "Candidate's Clarification (as recorded)",
               TEXTAREA, required=True, no=76,
               show_if=all_of(_ADVERSE,
                              when('candidate_clarification_opportunity', 'yes'))),
            _q('reviewer_assessment', "Reviewer's Assessment of the Finding", TEXTAREA,
               required=True, no=77, show_if=_ADVERSE),
            _q('discrepancy_summary', 'Overall Discrepancy Summary', TEXTAREA, no=78),
            _q('risk_rating', 'Overall Risk Rating', SELECT, required=True,
               choices=RISK_RATING, no=79),
            _q('verification_recommendation', 'Background Verification Recommendation',
               SELECT, required=True, choices=RECOMMENDATION_CHOICES, no=80),
            _q('hr_verification_summary', 'HR Verification Summary / Justification',
               TEXTAREA, required=True, no=81),
            _q('verification_completion_date', 'Background Verification Completion Date',
               DATE, required=True, no=82),
        ],
    },
    {
        'key': 'clearance',
        'section': 'Offer Acceptance & Position Joining Clearance',
        'title': 'Offer Acceptance & Joining Clearance',
        'description': '',
        'next': None,
        'questions': [
            _q('final_verification_status',
               'Final Background Verification Status at Offer / Joining Stage', SELECT,
               required=True, choices=FINAL_STATUS_CHOICES, no=83,
               help='Not Cleared normally leads to Final HR Clearance: Do Not Proceed.'),
            _q('offer_letter_issued', 'Offer / Appointment Letter Issued?', RADIO,
               required=True, choices=YES_NO, no=84),
            _q('offer_letter_issue_date', 'Offer / Appointment Letter Issue Date', DATE,
               required=True, no=85, show_if=when('offer_letter_issued', 'yes')),
            _q('offer_accepted', 'Offer Accepted by Candidate?', RADIO, required=True,
               choices=OFFER_ACCEPTED_CHOICES, no=86),
            _q('offer_acceptance_date', 'Offer Acceptance Date', DATE, required=True,
               no=87, show_if=when('offer_accepted', 'yes')),
            _q('confirmed_joining_date', 'Confirmed Joining Date', DATE, no=88,
               required_if=when('final_joining_clearance', 'cleared_to_join',
                                'cleared_followup'),
               help='Required when proceeding to join.'),
            _q('actual_joining_date', 'Actual Joining Date', DATE, no=89),
            *_grid_questions(JOINING_GRID, required_suffixes=('status',)),
            _q('pending_items', 'Pending Item(s), Owner & Due Date', TEXTAREA,
               required=True, no=91,
               show_if=any_of(*(when(f'{p}_status', 'pending') for p in JOINING_ROWS)),
               help='Item | Owner | Due date | Follow-up status'),
            _q('exception_required', 'Any Exception / Conditional Approval Required?',
               RADIO, required=True, choices=YES_NO, no=92),
            _q('exception_details', 'Exception / Conditional Approval Details', TEXTAREA,
               required=True, no=93, show_if=when('exception_required', 'yes'),
               help='Condition, approver, follow-up, deadline.'),
            _q('final_joining_clearance', 'Final HR Joining Clearance', SELECT,
               required=True, choices=JOINING_CLEARANCE, no=94),
            _q('final_hr_remarks', 'Final HR Remarks', TEXTAREA, no=95),
            _q('hr_approver_name', 'HR Reviewer / Approver Name', required=True, no=96),
            _q('hr_approver_designation', 'HR Reviewer / Approver Designation',
               required=True, no=97),
            _q('final_signoff_date', 'Final Sign-off Date', DATE, required=True, no=98),
            _q('hr_legal_review_completed', 'HR / Legal Review Completed (if flagged)?',
               RADIO, required=True, choices=YES_NO_NA, no=99, show_if=Q99_TRIGGER,
               help='Asked when the risk is Red / Critical, the recommendation is Further '
                    'Review / Not Cleared, an exception is required, or a material '
                    'concern was raised.'),
        ],
    },
]


# ── Lookups ──────────────────────────────────────────────────────────────
STEPS_BY_KEY = {step['key']: step for step in STEPS}
STEP_KEYS = [step['key'] for step in STEPS]
FIRST_STEP = STEP_KEYS[0]
FINAL_STEP = STEP_KEYS[-1]
TOTAL_STEPS = len(STEP_KEYS)

QUESTIONS_BY_KEY = {q['key']: q for step in STEPS for q in step['questions']}
ALL_QUESTIONS = [q for step in STEPS for q in step['questions']]

FILE_QUESTION_KEYS = frozenset(
    q['key'] for q in QUESTIONS_BY_KEY.values() if q['type'] in FILE_TYPES
)


def get_step(step_key):
    return STEPS_BY_KEY.get(step_key)


def step_number(step_key) -> int:
    return STEP_KEYS.index(step_key) + 1 if step_key in STEP_KEYS else 0


def next_step_key(step_key):
    step = get_step(step_key)
    return step['next'] if step else None


def previous_step_key(step_key):
    index = step_number(step_key) - 1
    return STEP_KEYS[index - 1] if index > 0 else None


def questions(step_key):
    step = get_step(step_key)
    return list(step['questions']) if step else []


def step_of(question_key):
    for step in STEPS:
        if any(q['key'] == question_key for q in step['questions']):
            return step['key']
    return None


# ── Rendering groups ─────────────────────────────────────────────────────
def _group(title, keys, grid=None, row=None):
    return {'title': title, 'keys': keys, 'grid': grid, 'row': row}


def _grid_groups(grid):
    return [_group(f"{grid['title']} — {label}", _grid_keys(grid, prefix), grid, prefix)
            for prefix, label, _ in grid['rows']]


def _employer_group(index):
    return _group(f'Employer {index}', [q['key'] for q in _employer_block(index)])


def _reference_group(index):
    return _group(f'Reference {index}', [q['key'] for q in _reference_block(index)])


STEP_GROUPS = {
    'hr_review': [
        _group('HR review details', [
            'candidate_full_name', 'position_applied_for', 'department',
            'hr_reviewer_name', 'hr_reviewer_designation', 'verification_start_date']),
        _group('Verification route', ['verification_route']),
        _group('Background check agency', [
            'agency_name', 'agency_contact', 'agency_report_reference',
            'agency_report_date', 'agency_report_file']),
    ],
    'identity': [
        _group('Candidate identity & address', [
            'candidate_nid_number', 'candidate_birth_certificate_number',
            'candidate_date_of_birth', 'candidate_present_address',
            'candidate_permanent_address']),
        *_grid_groups(IDENTITY_GRID),
        _group('Identity / address remarks', ['identity_remarks']),
        _group('Police verification', [
            'police_verification_required', 'police_verification_route',
            'police_verification_status', 'police_verification_reference',
            'police_verification_date', 'police_verification_remarks']),
    ],
    'education': [
        _group('Highest / last completed degree', [
            'highest_degree', 'highest_degree_consistent']),
        *_grid_groups(EDUCATION_GRID),
        _group('Education remarks', ['education_remarks']),
        _group('Training & professional certifications', [
            'training_certification_names', 'training_certificates_received',
            'training_verification_status', 'training_verification_method',
            'training_remarks']),
    ],
    'employment': [
        _group('Employment history', ['has_employment']),
        *[_employer_group(i) for i in range(1, EMPLOYER_MAX + 1)],
    ],
    'references': [
        *[_reference_group(i) for i in range(1, REFERENCE_COUNT + 1)],
        _group('Role profile information review', [
            'role_profile_reviewed', 'role_claims_consistent', 'role_further_validation']),
    ],
    'findings': [
        _group('Adverse finding', [
            'adverse_concern_raised', 'finding_categories', 'finding_source',
            'source_reliability', 'finding_details',
            'candidate_clarification_opportunity', 'candidate_clarification',
            'reviewer_assessment']),
        _group('BGV outcome', [
            'discrepancy_summary', 'risk_rating', 'verification_recommendation',
            'hr_verification_summary', 'verification_completion_date']),
    ],
    'clearance': [
        _group('Final background verification status', ['final_verification_status']),
        _group('Offer', [
            'offer_letter_issued', 'offer_letter_issue_date', 'offer_accepted',
            'offer_acceptance_date']),
        _group('Joining', ['confirmed_joining_date', 'actual_joining_date']),
        *_grid_groups(JOINING_GRID),
        _group('Pending items & exceptions', [
            'pending_items', 'exception_required', 'exception_details']),
        _group('Final HR joining clearance & sign-off', [
            'final_joining_clearance', 'final_hr_remarks', 'hr_approver_name',
            'hr_approver_designation', 'final_signoff_date',
            'hr_legal_review_completed']),
    ],
}


def question_groups(step_key):
    """The step's questions in titled blocks; unplaced ones trail untitled."""
    by_key = {q['key']: q for q in questions(step_key)}
    blocks, placed = [], set()
    for group in STEP_GROUPS.get(step_key, []):
        chosen = [by_key[k] for k in group['keys'] if k in by_key]
        if not chosen:
            continue
        placed.update(q['key'] for q in chosen)
        blocks.append({'title': group['title'], 'questions': chosen,
                       'grid': group['grid'], 'row': group['row']})
    leftover = [q for q in by_key.values() if q['key'] not in placed]
    if leftover:
        blocks.append({'title': '', 'questions': leftover, 'grid': None, 'row': None})
    return blocks


_FULL_WIDTH_TYPES = frozenset({TEXTAREA, RADIO, CHECKBOX, FILE})


def is_half_width(question) -> bool:
    if question['type'] in _FULL_WIDTH_TYPES:
        return False
    return len(wizard_label(question)) <= 70


_LABEL_PREFIXES = tuple(
    [f'Employer {i} — ' for i in range(1, EMPLOYER_MAX + 1)]
    + [f'{label} — ' for grid in (IDENTITY_GRID, EDUCATION_GRID, JOINING_GRID)
       for _, label, _ in grid['rows']]
)


def wizard_label(question) -> str:
    """Label without the row / employer prefix its block title already carries."""
    label = question['label']
    for prefix in _LABEL_PREFIXES:
        if label.startswith(prefix):
            return label[len(prefix):]
    return label


# Choice labels of the pre-PDF version, for reading records saved on it.
LEGACY_CHOICE_LABELS = {'agency': 'Background Check Agency',
 'amber': 'Amber – Minor / Explainable Concern',
 'bachelors': "Undergraduate / Bachelor's Degree",
 'banking_financial_services': 'Banking and Financial Services',
 'both': 'Both Internal HR and Background Check Agency',
 'business_development': 'Business Development',
 'certificate_review': 'Certificate Review',
 'clear': 'Clear / Satisfactory',
 'cleared': 'Cleared',
 'cleared_conditions': 'Cleared with Conditions / Clarification',
 'cleared_followup': 'Cleared with Follow-up',
 'cleared_to_join': 'Cleared to Join / Joined',
 'concern': 'Concern / Adverse Finding',
 'conditional': 'Conditional / With Reservations',
 'conditionally_cleared': 'Conditionally Cleared',
 'corroborated': 'Corroborated by 2+ Independent Sources',
 'critical': 'Critical – Serious / Disqualifying Concern',
 'data': 'Data',
 'digital_communications': 'Digital Communications',
 'direct_call': 'Direct Call to Employer HR',
 'direct_internal': 'Direct / Internal',
 'direct_manager': 'Direct Manager',
 'direct_report': 'Direct Report',
 'do_not_proceed': 'Do Not Proceed',
 'document': 'Document Verification',
 'document_review': 'Document Review',
 'documentation_external_audit': 'Documentation & External Audit',
 'ecommerce_operations': 'E-Commerce Operations',
 'ecommerce_services': 'E-Commerce Services',
 'engineering': 'Engineering',
 'enterprise_risk_management': 'Enterprise Risk Management',
 'field_verification': 'Field Verification',
 'finance_accounts': 'Finance and Accounts',
 'former_employer_hr': 'Former Employer HR',
 'former_manager': 'Former Direct Manager',
 'further_review': 'Further Review Required',
 'government_project': 'Government Project',
 'green': 'Green – No Material Concern',
 'hold': 'Hold',
 'hr_other': 'HR / Other',
 'hsc': 'HSC / A Level / Equivalent',
 'human_resources': 'Human Resources',
 'in_progress': 'In Progress',
 'infrastructure_security': 'Infrastructure and Security',
 'innovation_coe': 'Innovation Center of Excellence',
 'institution_confirmation': 'Institution / Board / University Confirmation',
 'internal_control_compliance': 'Internal Control & Compliance',
 'internal_hr': 'Internal HR',
 'issuing_organisation': 'Issuing Organisation Confirmation',
 'legal_affairs': 'Legal Affairs',
 'management': 'Management',
 'masters': "Master's / Postgraduate Degree",
 'na': 'Not Applicable',
 'no': 'No',
 'not_asked': 'Not Asked / Not Disclosed',
 'not_attempted': 'Not Yet Attempted',
 'not_cleared': 'Not Cleared',
 'not_disclosed': 'Employer Would Not Disclose',
 'not_required': 'Not Required',
 'not_started': 'Not Started',
 'official_email': 'Official Email Confirmation',
 'official_source': 'Direct / Official Source Check',
 'online': 'Online Verification',
 'other': 'Other',
 'partially': 'Partially Verified',
 'partially_verified': 'Partially Verified',
 'partnership_management': 'Partnership Management',
 'peer': 'Peer',
 'pending': 'Pending',
 'pending_exception': 'Pending Approved Exception',
 'police': 'Police Verification',
 'procurement': 'Procurement',
 'professional_reference': 'Professional Reference',
 'project_management_office': 'Project Management Office',
 'red': 'Red – Material Concern Requiring Escalation',
 'revenue_assurance': 'Revenue Assurance',
 'risk_compliance': 'Risk & Compliance',
 'service_assurance_call_center': 'Service Assurance-Call Center',
 'service_assurance_quality_assurance': 'Service Assurance-Quality Assurance',
 'service_assurance_technical_operations': 'Service Assurance-Technical Operations',
 'single_source': 'Single Source, Plausible',
 'skip_level_manager': 'Skip-level Manager',
 'ssc': 'SSC / O Level / Equivalent',
 'tbd': 'To Be Decided',
 'unable': 'Unable to Verify',
 'unverified': 'Unverified / Rumour',
 'verified': 'Verified',
 'written_reference': 'Written Reference / Service Letter',
 'yes': 'Yes'}


def choice_label(question_key, value):
    question = QUESTIONS_BY_KEY.get(question_key)
    if not question or 'choices' not in question:
        return LEGACY_CHOICE_LABELS.get(value, value)
    return dict(question['choices']).get(value, LEGACY_CHOICE_LABELS.get(value, value))


def legacy_view(answers):
    """Answers with the employment gate filled in for records saved before it existed."""
    view = dict(answers or {})
    if 'has_employment' in view:
        return view
    named = [i for i in range(1, EMPLOYER_MAX + 1)
             if (view.get(f'employer_{i}_name') or '').strip()]
    if named:
        view['has_employment'] = 'yes'
        for index in named[:-1]:
            view.setdefault(f'employer_{index}_another', 'yes')
    return view
