"""Declarative definition of the HR Background Verification & Joining Clearance Form.

Same approach as the candidate-facing Employee Information Form: the whole form
is data, `forms.py` builds a Django form per section from these dicts, and one
template renders any section.

Source of truth is SSL_Wireless_HR_Verification_Form_Aligned_QuickImport.pdf --
201 questions across Sections A-F, in the order and with the required marks that
document gives.

Unlike the candidate form this one does not branch: HR sees every section, in
order, and may jump between them freely (see `views.step`). It is filled by
staff over days rather than in one sitting, so every section saves on its own.

Two deliberate departures from the PDF, both mirroring the Employee Information
Form:
  * The PDF's Q1 Requisition ID is dropped, so this form has 200 questions and
    our Q1 is the PDF's Q2. `QUESTION_NUMBERS` renumbers from position, so a
    number shown to HR is this form's own -- not the PDF's.
  * The PDF marks Employer 1-4 required, which would make the form
    unsubmittable for a candidate with fewer than four previous jobs -- or any
    at all. Here each employer block is optional until its name is given, at
    which point the rest of that block becomes required. Employer names are
    prefilled from what the candidate declared, so a block the candidate filled
    in *is* required of HR without HR having to be told.
"""
# The question vocabulary is shared with the Employee Information Form rather
# than redeclared: `forms.build_field` there is what turns these dicts into
# Django fields, and it compares against these very constants. Importing them
# means a rename breaks loudly instead of silently building the wrong widget.
from apps.employee_form.schema import (  # noqa: F401
    BOOLEAN,
    CHECKBOX,
    CHOICE_TYPES,
    DATE,
    DECIMAL,
    DEGREE_CHOICES,
    DEPARTMENT_CHOICES,
    EMAIL,
    FILE,
    FILE_TYPES,
    FILES,
    INTEGER,
    MAX_FILES_PER_QUESTION,
    MAX_UPLOAD_MB,
    NUMERIC_TYPES,
    PHONE,
    RADIO,
    RELATIONSHIP_CHOICES,
    SELECT,
    TEXT,
    TEXTAREA,
    YEAR,
)

_UPLOAD_HELP = f'PDF, document or image. Max {MAX_UPLOAD_MB} MB.'

EMPLOYER_COUNT = 4
REFERENCE_COUNT = 2


def _q(key, label, qtype=TEXT, required=False, help='', choices=None, max_files=None,
       min_value=None, max_value=None, decimals=2):
    """One question. Shape matches what `employee_form.forms.build_field` reads."""
    q = {'key': key, 'label': label, 'type': qtype, 'required': required, 'help': help}
    if choices is not None:
        q['choices'] = choices
    if qtype == FILES:
        q['max_files'] = max_files or MAX_FILES_PER_QUESTION
    if qtype in NUMERIC_TYPES:
        q['min_value'] = min_value
        q['max_value'] = max_value
        if qtype == DECIMAL:
            q['decimals'] = decimals
    return q


# ── Choice sets ──────────────────────────────────────────────────────────
YES_NO = [('yes', 'Yes'), ('no', 'No')]
YES_NO_NA = [('yes', 'Yes'), ('no', 'No'), ('na', 'Not Applicable')]

VERIFICATION_ROUTE = [
    ('internal_hr', 'Internal HR'),
    ('agency', 'Background Check Agency'),
    ('both', 'Both Internal HR and Background Check Agency'),
]
AGENCY_REQUIRED = [
    ('yes', 'Yes'),
    ('no', 'No'),
    ('tbd', 'To Be Decided'),
]
IDENTITY_METHOD = [
    ('document_review', 'Document Review'),
    ('official_source', 'Direct / Official Source Check'),
    ('field_verification', 'Field Verification'),
    ('agency', 'Background Check Agency'),
    ('other', 'Other'),
]
POLICE_ROUTE = [
    ('direct_internal', 'Direct / Internal'),
    ('agency', 'Background Check Agency'),
    ('other', 'Other'),
    ('not_required', 'Not Required'),
]
POLICE_STATUS = [
    ('not_started', 'Not Started'),
    ('in_progress', 'In Progress'),
    ('clear', 'Clear / Satisfactory'),
    ('concern', 'Concern / Adverse Finding'),
    ('not_required', 'Not Required'),
]

HIGHEST_DEGREE_CHOICES = list(DEGREE_CHOICES) + [('other', 'Other')]
CONSISTENCY_CHOICES = [
    ('yes', 'Yes'),
    ('no', 'No'),
    ('further_review', 'Further Review Required'),
]
EDUCATION_METHOD = [
    ('document_review', 'Document Review'),
    ('institution_confirmation', 'Institution / Board / University Confirmation'),
    ('online', 'Online Verification'),
    ('agency', 'Background Check Agency'),
    ('other', 'Other'),
]
TRAINING_VERIFIED = [
    ('yes', 'Yes'),
    ('no', 'No'),
    ('partially', 'Partially Verified'),
    ('na', 'Not Applicable'),
]
TRAINING_METHOD = [
    ('certificate_review', 'Certificate Review'),
    ('issuing_organisation', 'Issuing Organisation Confirmation'),
    ('online', 'Online Verification'),
    ('agency', 'Background Check Agency'),
    ('other', 'Other'),
]

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
DISCLOSE_CHOICES = [
    ('yes', 'Yes'),
    ('no', 'No'),
    ('not_disclosed', 'Employer Would Not Disclose'),
]
REHIRE_CHOICES = [
    ('yes', 'Yes'),
    ('no', 'No'),
    ('not_disclosed', 'Not Disclosed'),
    ('na', 'Not Applicable'),
]

REFERENCE_METHOD = [
    ('direct_call', 'Direct Call'),
    ('official_email', 'Official Email'),
    ('agency', 'Background Check Agency'),
    ('other', 'Other'),
]
REFERENCE_RECOMMEND = [
    ('yes', 'Yes'),
    ('no', 'No'),
    ('conditional', 'Conditional / With Reservations'),
    ('not_asked', 'Not Asked / Not Disclosed'),
]
ROLE_CONSISTENCY = [
    ('yes', 'Yes'),
    ('no', 'No'),
    ('partially', 'Partially'),
    ('na', 'Not Applicable'),
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
CLARIFY_CHOICES = [
    ('yes', 'Yes'),
    ('no', 'No'),
    ('not_required', 'Not Required'),
]
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
OFFER_ACCEPTED_CHOICES = [
    ('yes', 'Yes'),
    ('no', 'No'),
    ('pending', 'Pending'),
]
CHECKED_CHOICES = [
    ('yes', 'Yes'),
    ('no', 'No'),
    ('not_required', 'Not Required'),
]
RECEIVED_CHOICES = [
    ('yes', 'Yes'),
    ('no', 'No'),
    ('na', 'Not Applicable'),
    ('pending', 'Pending'),
]
JOINING_CLEARANCE = [
    ('cleared_to_join', 'Cleared to Join / Joined'),
    ('cleared_followup', 'Cleared with Follow-up'),
    ('hold', 'Hold'),
    ('do_not_proceed', 'Do Not Proceed'),
]


# ── Repeated blocks ──────────────────────────────────────────────────────
def _degree_block(prefix, title, *, passing_year=False):
    """One education level's verification questions.

    HSC and SSC record a passing year where the university-level degrees record
    a degree/major and a completion date -- the PDF asks for exactly that, and
    it matches what the candidate was asked for.
    """
    if passing_year:
        identity = [
            _q(f'{prefix}_institution', f'{title} — Institution / Board / University'),
            _q(f'{prefix}_passing_year', f'{title} — Passing Year', YEAR),
        ]
    else:
        identity = [
            _q(f'{prefix}_institution', f'{title} — Institution / Board / University'),
            _q(f'{prefix}_degree_major', f'{title} — Degree / Major (as applicable)'),
            _q(f'{prefix}_completion_date',
               f'{title} — Graduation / Completion Date', DATE),
        ]
    return identity + [
        _q(f'{prefix}_certificate_received', f'{title} — Certificate Received?',
           RADIO, choices=YES_NO_NA),
        _q(f'{prefix}_verified', f'{title} — Verified?', RADIO, choices=YES_NO_NA),
        _q(f'{prefix}_verification_method', f'{title} — Verification Method',
           RADIO, choices=EDUCATION_METHOD),
        _q(f'{prefix}_discrepancy', f'{title} — Discrepancy Found?',
           RADIO, choices=YES_NO_NA),
        _q(f'{prefix}_remarks', f'{title} — Verification Remarks / Discrepancy Details',
           TEXTAREA),
    ]


# Everything in an employer block that becomes required once the employer is
# named. The PDF marks these *Required; naming is what switches them on.
#
# The employer's *confirmed* dates are deliberately not here, even though the PDF
# requires them. They are the employer's answer, not HR's: this same section
# offers "Unable to Verify" and "Employer Would Not Disclose", and requiring the
# confirmed dates would make both of those unrecordable -- Section D could never
# be saved, and because sign-off needs every section, the whole verification
# would deadlock with no way out but erasing the employer's name.
EMPLOYER_REQUIRED_ONCE_NAMED = (
    'hr_contact', 'hr_email', 'position',
    'claimed_start_date', 'claimed_end_date',
    'reference_check_verified', 'verification_status', 'verification_method',
    'tenure_discrepancy',
)


def _employer_block(index):
    """Employer `index`'s verification questions (19 of them, per the PDF)."""
    p = f'employer_{index}'
    n = index
    return [
        _q(f'{p}_name', f'Employer {n} Name',
           help='Prefilled from what the candidate declared. Leave blank to skip '
                'this employer; fill it in and the rest of the block is required.'),
        _q(f'{p}_hr_contact', f'Employer {n} HR / Official Contact Number', PHONE),
        _q(f'{p}_hr_email', f'Employer {n} HR / Official Email Address', EMAIL),
        _q(f'{p}_position', f'Candidate Position / Designation at Employer {n}'),
        _q(f'{p}_claimed_start_date',
           f"Candidate's Claimed Start Date at Employer {n}", DATE),
        _q(f'{p}_claimed_end_date',
           f"Candidate's Claimed End Date at Employer {n}", DATE),
        _q(f'{p}_confirmed_start_date',
           f"Employer's Confirmed Start Date at Employer {n}", DATE),
        _q(f'{p}_confirmed_end_date',
           f"Employer's Confirmed End Date at Employer {n}", DATE),
        _q(f'{p}_reference_check_verified',
           f'Employment / HR Reference Check Verified for Employer {n}?',
           RADIO, choices=YES_NO),
        _q(f'{p}_verification_status', f'Employer {n} Verification Status',
           RADIO, choices=EMPLOYER_STATUS),
        _q(f'{p}_verification_method', f'Employer {n} Verification Method',
           RADIO, choices=EMPLOYER_METHOD),
        _q(f'{p}_verifier_name', f'Employer {n} Verifier Name & Designation'),
        _q(f'{p}_position_verified',
           f'Candidate Position / Designation Verified for Employer {n}?',
           RADIO, choices=DISCLOSE_CHOICES),
        _q(f'{p}_claimed_reason_leaving',
           f"Candidate's Stated Reason for Leaving Employer {n}", TEXTAREA),
        _q(f'{p}_confirmed_reason_leaving',
           f"Employer {n}'s Confirmed Reason for Leaving", TEXTAREA),
        _q(f'{p}_reason_consistent',
           f'Reason for Leaving Consistent with Candidate Statement for Employer {n}?',
           RADIO, choices=DISCLOSE_CHOICES),
        _q(f'{p}_rehire_eligible', f'Eligible for Rehire at Employer {n}?',
           RADIO, choices=REHIRE_CHOICES),
        _q(f'{p}_tenure_discrepancy',
           f'Tenure / Employment Discrepancy Found for Employer {n}?',
           RADIO, choices=YES_NO),
        _q(f'{p}_remarks', f'Employer {n} Verification Remarks / Discrepancy Details',
           TEXTAREA),
    ]


def _reference_block(index):
    """Professional reference `index`'s verification questions."""
    p = f'reference_{index}'
    n = index
    return [
        _q(f'{p}_name', f'Reference {n} Name', required=True),
        _q(f'{p}_designation', f'Reference {n} Designation & Company', required=True),
        _q(f'{p}_relationship', f'Reference {n} Relationship to Candidate',
           SELECT, choices=RELATIONSHIP_CHOICES),
        _q(f'{p}_contact', f'Reference {n} Contact Number', PHONE),
        _q(f'{p}_email', f'Reference {n} Official / Work Email Address', EMAIL),
        _q(f'{p}_check_verified', f'HR Reference Check Verified for Reference {n}?',
           RADIO, required=True, choices=YES_NO),
        _q(f'{p}_verification_method', f'Reference {n} Verification Method',
           RADIO, choices=REFERENCE_METHOD),
        _q(f'{p}_feedback', f'Reference {n} Feedback Summary', TEXTAREA),
        _q(f'{p}_recommend',
           f'Would Reference {n} Rehire / Recommend the Candidate?',
           RADIO, choices=REFERENCE_RECOMMEND),
    ]


# ── Sections A-F ─────────────────────────────────────────────────────────
STEPS = [
    {
        'key': 'section_a',
        'section': 'Section A — Candidate Link & HR Review Details',
        'title': 'Candidate Link & HR Review',
        'description': 'Who is being verified, by whom, and through which route.',
        'next': 'section_b',
        'questions': [
            _q('candidate_full_name', 'Candidate Full Name', required=True),
            _q('position_applied_for', 'Position Applied For', required=True),
            _q('department', 'Department', SELECT, required=True,
               choices=DEPARTMENT_CHOICES),
            _q('hr_reviewer_name', 'HR Reviewer Name', required=True),
            _q('hr_reviewer_designation', 'HR Reviewer Designation', required=True),
            _q('verification_start_date', 'Verification Start Date', DATE,
               required=True),
            _q('verification_route', 'Overall Verification Route', RADIO,
               required=True, choices=VERIFICATION_ROUTE),
            _q('agency_required', 'Background Check Agency Required?', RADIO,
               required=True, choices=AGENCY_REQUIRED),
            _q('agency_name', 'Background Check Agency Name (if used)'),
            _q('agency_contact', 'Agency Contact Person / Contact Details'),
            _q('agency_report_reference', 'Agency Report Reference Number'),
            _q('agency_report_date', 'Agency Report Date', DATE),
            _q('agency_report_file', 'Agency Report / Supporting Evidence', FILE,
               help=_UPLOAD_HELP),
        ],
    },
    {
        'key': 'section_b',
        'section': 'Section B — Identity, Address & Police Verification',
        'title': 'Identity, Address & Police',
        'description': 'These mirror Section A of the candidate\'s Employee '
                       'Information Form, prefilled from what they submitted.',
        'next': 'section_c',
        'questions': [
            _q('candidate_nid_number', 'Candidate NID Number', required=True),
            _q('candidate_birth_certificate_number',
               'Candidate Birth Certificate Number (if applicable)'),
            _q('candidate_date_of_birth', 'Candidate Date of Birth', DATE,
               required=True),
            _q('candidate_present_address', 'Candidate Present Address', TEXTAREA,
               required=True),
            _q('candidate_permanent_address', 'Candidate Permanent Address', TEXTAREA,
               required=True),
            _q('nid_verified', 'NID Verified?', RADIO, required=True,
               choices=YES_NO_NA),
            _q('birth_certificate_verified', 'Birth Certificate Verified?', RADIO,
               choices=YES_NO_NA),
            _q('dob_verified', 'Date of Birth Verified?', RADIO, required=True,
               choices=YES_NO_NA),
            _q('present_address_verified', 'Present Address Verified?', RADIO,
               required=True, choices=YES_NO_NA),
            _q('permanent_address_verified', 'Permanent Address Verified?', RADIO,
               required=True, choices=YES_NO_NA),
            _q('identity_verification_method',
               'Identity / Address Verification Method', RADIO,
               choices=IDENTITY_METHOD),
            _q('police_verification_required', 'Police Verification Required?', RADIO,
               required=True, choices=YES_NO),
            _q('police_verification_route', 'Police Verification Route', RADIO,
               choices=POLICE_ROUTE),
            _q('police_verification_status', 'Police Verification Status', RADIO,
               choices=POLICE_STATUS),
            _q('police_verification_reference',
               'Police Verification Reference / Report Number'),
            _q('police_verification_date', 'Police Verification Date', DATE),
            _q('identity_police_remarks',
               'Identity / Address / Police Verification Remarks', TEXTAREA),
        ],
    },
    {
        'key': 'section_c',
        'section': 'Section C — Educational Qualification & Training Verification',
        'title': 'Education & Training',
        'description': 'Highest to secondary, the same order the candidate filled in.',
        'next': 'section_d',
        'questions': [
            _q('highest_degree', 'Candidate Highest / Last Completed Degree', RADIO,
               required=True, choices=HIGHEST_DEGREE_CHOICES),
            _q('highest_degree_consistent',
               'Highest / Last Completed Degree Consistent with Submitted Documents?',
               RADIO, required=True, choices=CONSISTENCY_CHOICES),
            *_degree_block('masters', "Master's / Postgraduate Degree"),
            *_degree_block('bachelors', "Undergraduate / Bachelor's Degree"),
            *_degree_block('hsc', 'HSC / A Level / Equivalent', passing_year=True),
            *_degree_block('ssc', 'SSC / O Level / Equivalent', passing_year=True),
            _q('training_certification_names',
               'Relevant Training / Professional Certification Name(s) — as provided '
               'by candidate', TEXTAREA),
            _q('training_certificates_received',
               'Training / Professional Certification Certificates Received?', RADIO,
               choices=YES_NO_NA),
            _q('training_verified', 'Training / Professional Certifications Verified?',
               RADIO, choices=TRAINING_VERIFIED),
            _q('training_verification_method',
               'Training / Certification Verification Method', RADIO,
               choices=TRAINING_METHOD),
            _q('training_discrepancy',
               'Training / Certification Discrepancy Found?', RADIO,
               choices=YES_NO_NA),
            _q('training_remarks', 'Training / Certification Verification Remarks',
               TEXTAREA),
        ],
    },
    {
        'key': 'section_d',
        'section': 'Section D — Employment Verification',
        'title': 'Employment Verification',
        'description': 'Employer numbers match the candidate\'s form. Compare the '
                       'dates they claimed with the ones the employer confirmed.',
        'next': 'section_e',
        'questions': [
            *[q for i in range(1, EMPLOYER_COUNT + 1) for q in _employer_block(i)],
            _q('additional_employer_notes',
               'Additional Employer Verification Notes (for employment history '
               'beyond Employer 4)', TEXTAREA),
        ],
    },
    {
        'key': 'section_e',
        'section': 'Section E — Professional Reference, Role Profile & Adverse '
                   'Finding Review',
        'title': 'References & Findings',
        'description': '',
        'next': 'section_f',
        'questions': [
            *[q for i in range(1, REFERENCE_COUNT + 1) for q in _reference_block(i)],
            _q('role_profile_reviewed',
               'Candidate Department / Role Profile Information Reviewed?', RADIO,
               required=True, choices=YES_NO_NA),
            _q('role_claims_consistent',
               'Role-Specific Claims Reasonably Consistent with CV / Interview / '
               'Available Evidence?', RADIO, choices=ROLE_CONSISTENCY),
            _q('role_further_validation',
               'Role-Specific Information Requiring Further Validation (if any)',
               TEXTAREA),
            _q('adverse_concern_raised',
               'Any performance, disciplinary, integrity, legal or other adverse '
               'concern raised?', RADIO, required=True, choices=YES_NO),
            _q('finding_source', 'Source of Finding', RADIO, choices=FINDING_SOURCE),
            _q('source_reliability', 'Reliability of Source', RADIO,
               choices=SOURCE_RELIABILITY),
            _q('finding_details', 'Evidence / Finding Details', TEXTAREA),
            _q('candidate_clarification_opportunity',
               'Was the Candidate Given an Opportunity to Clarify?', RADIO,
               choices=CLARIFY_CHOICES),
            _q('candidate_clarification', "Candidate's Clarification (as recorded)",
               TEXTAREA),
            _q('reviewer_assessment', "Reviewer's Assessment of the Finding", TEXTAREA),
            _q('discrepancy_summary', 'Overall Discrepancy Summary', TEXTAREA),
            _q('risk_rating', 'Overall Risk Rating', RADIO, required=True,
               choices=RISK_RATING),
            _q('verification_recommendation', 'Background Verification Recommendation',
               RADIO, required=True, choices=RECOMMENDATION_CHOICES),
            _q('involuntary_separation_wording',
               'Does the Case Involve Involuntary Separation Wording (termination / '
               'dismissal / forced resignation)?', RADIO, choices=YES_NO),
            _q('hr_verification_summary', 'HR Verification Summary / Justification',
               TEXTAREA, required=True),
            _q('section_e_completion_date', 'Section E Completion Date', DATE,
               required=True),
        ],
    },
    {
        'key': 'section_f',
        'section': 'Section F — Offer Acceptance & Position Joining Clearance',
        'title': 'Offer & Joining Clearance',
        'description': 'Completed during offer acceptance and joining, after the '
                       'verification outcome above.',
        'next': None,
        'questions': [
            _q('final_verification_status',
               'Final Background Verification Status at Offer / Joining Stage', RADIO,
               required=True, choices=FINAL_STATUS_CHOICES),
            _q('offer_letter_issued', 'Offer / Appointment Letter Issued?', RADIO,
               required=True, choices=YES_NO),
            _q('offer_letter_issue_date', 'Offer / Appointment Letter Issue Date', DATE),
            _q('offer_accepted', 'Offer Accepted by Candidate?', RADIO, required=True,
               choices=OFFER_ACCEPTED_CHOICES),
            _q('offer_acceptance_date', 'Offer Acceptance Date', DATE),
            _q('confirmed_joining_date', 'Confirmed Joining Date', DATE, required=True),
            _q('actual_joining_date', 'Actual Joining Date', DATE),
            _q('original_certificates_checked',
               'Original / Required Educational Certificates Checked at Joining?',
               RADIO, choices=CHECKED_CHOICES),
            _q('original_nid_checked',
               'Original NID / Identity Document Checked at Joining?', RADIO,
               choices=YES_NO),
            _q('employment_documents_received',
               'Required Employment / Release / Experience Documents Received?', RADIO,
               choices=RECEIVED_CHOICES),
            _q('police_report_received',
               'Police / Background Check Report Received (if required)?', RADIO,
               choices=RECEIVED_CHOICES),
            _q('pending_document_at_joining',
               'Any Pending Document / Verification at Joining?', RADIO,
               choices=YES_NO),
            _q('pending_items', 'Pending Item(s), Owner & Due Date', TEXTAREA),
            _q('exception_required', 'Any Exception / Conditional Approval Required?',
               RADIO, choices=YES_NO),
            _q('exception_details', 'Exception / Conditional Approval Details',
               TEXTAREA),
            _q('final_joining_clearance', 'Final HR Joining Clearance', RADIO,
               required=True, choices=JOINING_CLEARANCE),
            _q('final_hr_remarks', 'Final HR Remarks', TEXTAREA),
            _q('hr_approver_name', 'HR Reviewer / Approver Name', required=True),
            _q('hr_approver_designation', 'HR Reviewer / Approver Designation',
               required=True),
            _q('final_signoff_date', 'Final Sign-off Date', DATE, required=True),
            _q('hr_legal_review_completed', 'HR / Legal Review Completed (if flagged)?',
               RADIO, required=True, choices=YES_NO_NA),
        ],
    },
]


# ── Rendering hints ──────────────────────────────────────────────────────
# Fields short enough to share a row. Anything unlisted spans the form.
HALF_WIDTH_KEYS = frozenset({
    'position_applied_for', 'department',
    'hr_reviewer_name', 'hr_reviewer_designation', 'verification_start_date',
    'agency_name', 'agency_contact', 'agency_report_reference', 'agency_report_date',
    'candidate_nid_number', 'candidate_birth_certificate_number',
    'candidate_date_of_birth',
    'police_verification_reference', 'police_verification_date',
    'masters_institution', 'masters_degree_major', 'masters_completion_date',
    'bachelors_institution', 'bachelors_degree_major', 'bachelors_completion_date',
    'hsc_institution', 'hsc_passing_year',
    'ssc_institution', 'ssc_passing_year',
    'section_e_completion_date',
    'offer_letter_issue_date', 'offer_acceptance_date',
    'confirmed_joining_date', 'actual_joining_date',
    'hr_approver_name', 'hr_approver_designation', 'final_signoff_date',
    *(f'employer_{i}_hr_contact' for i in range(1, EMPLOYER_COUNT + 1)),
    *(f'employer_{i}_hr_email' for i in range(1, EMPLOYER_COUNT + 1)),
    *(f'employer_{i}_position' for i in range(1, EMPLOYER_COUNT + 1)),
    *(f'employer_{i}_claimed_start_date' for i in range(1, EMPLOYER_COUNT + 1)),
    *(f'employer_{i}_claimed_end_date' for i in range(1, EMPLOYER_COUNT + 1)),
    *(f'employer_{i}_confirmed_start_date' for i in range(1, EMPLOYER_COUNT + 1)),
    *(f'employer_{i}_confirmed_end_date' for i in range(1, EMPLOYER_COUNT + 1)),
    *(f'employer_{i}_verifier_name' for i in range(1, EMPLOYER_COUNT + 1)),
    *(f'reference_{i}_name' for i in range(1, REFERENCE_COUNT + 1)),
    *(f'reference_{i}_designation' for i in range(1, REFERENCE_COUNT + 1)),
    *(f'reference_{i}_contact' for i in range(1, REFERENCE_COUNT + 1)),
    *(f'reference_{i}_email' for i in range(1, REFERENCE_COUNT + 1)),
    *(f'reference_{i}_relationship' for i in range(1, REFERENCE_COUNT + 1)),
})


def _degree_group(prefix, title, *, passing_year=False):
    keys = [f'{prefix}_institution']
    keys += ([f'{prefix}_passing_year'] if passing_year
             else [f'{prefix}_degree_major', f'{prefix}_completion_date'])
    keys += [f'{prefix}_certificate_received', f'{prefix}_verified',
             f'{prefix}_verification_method', f'{prefix}_discrepancy',
             f'{prefix}_remarks']
    return (title, keys)


def _employer_group(index):
    p = f'employer_{index}'
    return (f'Employer {index}', [f'{p}_{suffix}' for suffix in (
        'name', 'hr_contact', 'hr_email', 'position',
        'claimed_start_date', 'claimed_end_date',
        'confirmed_start_date', 'confirmed_end_date',
        'reference_check_verified', 'verification_status', 'verification_method',
        'verifier_name', 'position_verified',
        'claimed_reason_leaving', 'confirmed_reason_leaving', 'reason_consistent',
        'rehire_eligible', 'tenure_discrepancy', 'remarks',
    )])


def _reference_group(index):
    p = f'reference_{index}'
    return (f'Professional Reference {index}', [f'{p}_{suffix}' for suffix in (
        'name', 'designation', 'relationship', 'contact', 'email',
        'check_verified', 'verification_method', 'feedback', 'recommend',
    )])


# Long sections render as a few short titled blocks instead of one wall.
STEP_GROUPS = {
    'section_a': [
        ('Candidate', ['candidate_full_name', 'position_applied_for',
                       'department']),
        ('HR reviewer', ['hr_reviewer_name', 'hr_reviewer_designation',
                         'verification_start_date']),
        ('Verification route', ['verification_route', 'agency_required']),
        ('Background check agency', ['agency_name', 'agency_contact',
                                     'agency_report_reference', 'agency_report_date',
                                     'agency_report_file']),
    ],
    'section_b': [
        ('Candidate details on record', [
            'candidate_nid_number', 'candidate_birth_certificate_number',
            'candidate_date_of_birth', 'candidate_present_address',
            'candidate_permanent_address']),
        ('Identity & address checks', [
            'nid_verified', 'birth_certificate_verified', 'dob_verified',
            'present_address_verified', 'permanent_address_verified',
            'identity_verification_method']),
        ('Police verification', [
            'police_verification_required', 'police_verification_route',
            'police_verification_status', 'police_verification_reference',
            'police_verification_date']),
        ('Remarks', ['identity_police_remarks']),
    ],
    'section_c': [
        ('Highest qualification', ['highest_degree', 'highest_degree_consistent']),
        _degree_group('masters', "Master's / Postgraduate Degree"),
        _degree_group('bachelors', "Undergraduate / Bachelor's Degree"),
        _degree_group('hsc', 'HSC / A Level / Equivalent', passing_year=True),
        _degree_group('ssc', 'SSC / O Level / Equivalent', passing_year=True),
        ('Training & professional certifications', [
            'training_certification_names', 'training_certificates_received',
            'training_verified', 'training_verification_method',
            'training_discrepancy', 'training_remarks']),
    ],
    'section_d': [
        *[_employer_group(i) for i in range(1, EMPLOYER_COUNT + 1)],
        ('Beyond Employer 4', ['additional_employer_notes']),
    ],
    'section_e': [
        *[_reference_group(i) for i in range(1, REFERENCE_COUNT + 1)],
        ('Role profile review', ['role_profile_reviewed', 'role_claims_consistent',
                                 'role_further_validation']),
        ('Adverse finding', ['adverse_concern_raised', 'finding_source',
                             'source_reliability', 'finding_details',
                             'candidate_clarification_opportunity',
                             'candidate_clarification', 'reviewer_assessment']),
        ('Outcome', ['discrepancy_summary', 'risk_rating',
                     'verification_recommendation',
                     'involuntary_separation_wording', 'hr_verification_summary',
                     'section_e_completion_date']),
    ],
    'section_f': [
        ('Verification outcome at offer', ['final_verification_status']),
        ('Offer', ['offer_letter_issued', 'offer_letter_issue_date',
                   'offer_accepted', 'offer_acceptance_date']),
        ('Joining', ['confirmed_joining_date', 'actual_joining_date',
                     'original_certificates_checked', 'original_nid_checked',
                     'employment_documents_received', 'police_report_received']),
        ('Pending items & exceptions', ['pending_document_at_joining',
                                        'pending_items', 'exception_required',
                                        'exception_details']),
        ('Sign-off', ['final_joining_clearance', 'final_hr_remarks',
                      'hr_approver_name', 'hr_approver_designation',
                      'final_signoff_date', 'hr_legal_review_completed']),
    ],
}


# ── Lookups ──────────────────────────────────────────────────────────────
STEPS_BY_KEY = {step['key']: step for step in STEPS}
STEP_KEYS = [step['key'] for step in STEPS]
FIRST_STEP = STEP_KEYS[0]
FINAL_STEP = STEP_KEYS[-1]
TOTAL_STEPS = len(STEP_KEYS)

QUESTIONS_BY_KEY = {q['key']: q for step in STEPS for q in step['questions']}

FILE_QUESTION_KEYS = frozenset(
    q['key'] for q in QUESTIONS_BY_KEY.values() if q['type'] in FILE_TYPES
)


def get_step(step_key):
    return STEPS_BY_KEY.get(step_key)


def step_number(step_key) -> int:
    """1-based position, for "Section 3 of 6"."""
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


def _numbers():
    """This form's own question number per key, generated from position.

    Not the PDF's numbers: dropping its Q1 Requisition ID shifts everything up
    one, so our Q1 is its Q2. Generated rather than written down so adding or
    removing a question cannot leave the numbering stale.
    """
    out, n = {}, 0
    for step in STEPS:
        for question in step['questions']:
            n += 1
            out[question['key']] = n
    return out


QUESTION_NUMBERS = _numbers()


def numbered_questions(step_key):
    return [
        {**question, 'number': QUESTION_NUMBERS[question['key']]}
        for question in questions(step_key)
    ]


def question_groups(step_key):
    """The step's questions arranged into its titled blocks.

    Anything not named in STEP_GROUPS still renders, in a trailing untitled
    block, so adding a question cannot make it silently disappear.
    """
    numbered = {q['key']: q for q in numbered_questions(step_key)}
    blocks, placed = [], set()
    for title, keys in STEP_GROUPS.get(step_key, []):
        chosen = [numbered[k] for k in keys if k in numbered]
        if not chosen:
            continue
        placed.update(q['key'] for q in chosen)
        blocks.append({'title': title, 'questions': chosen})
    leftover = [q for q in numbered.values() if q['key'] not in placed]
    if leftover:
        blocks.append({'title': '', 'questions': leftover})
    return blocks


def is_half_width(question) -> bool:
    return question['key'] in HALF_WIDTH_KEYS


def choice_label(question_key, value):
    question = QUESTIONS_BY_KEY.get(question_key)
    if not question or 'choices' not in question:
        return value
    for choice_value, label in question['choices']:
        if choice_value == value:
            return label
    return value


def wizard_label(question) -> str:
    """Label with a repeated education-level prefix stripped.

    The four degree blocks put "HSC / A Level / Equivalent — " in front of every
    question, which the block title already says. Employer and reference labels
    are left alone: they carry the number inside the sentence ("Claimed Start
    Date at Employer 2"), where cutting it out reads worse than repeating it.
    """
    label = question['label']
    for separator in (' — ', ' - '):
        head, _, tail = label.partition(separator)
        if tail and head in _BLOCK_PREFIXES:
            return tail
    return label


_BLOCK_PREFIXES = frozenset({
    "Master's / Postgraduate Degree",
    "Undergraduate / Bachelor's Degree",
    'HSC / A Level / Equivalent',
    'SSC / O Level / Equivalent',
})
