"""Declarative definition of the Candidate Mapping & Assessment Document.

Third form in the same family, built the same way: the whole thing is data,
`forms.py` builds a Django form per section from these dicts, and one template
renders any section.

Source of truth is SSL_Group_Candidate_Mapping_Document.pdf -- 39 items across
Candidate Identification, Sections A-F and the Assessor Declaration. Prepared by
the assessing HR representative or the interview panel, never by the candidate.

Departures from the PDF, each for a reason:
  * Its Q1 Requisition ID is dropped, as in both sibling forms -- nobody filling
    these has that value to hand.
  * Its Q39 Date is dropped. The declaration is dated from `submitted_at`
    instead, so an assessor cannot backdate their own sign-off -- the same
    decision taken for the Employee Information Form's declaration.
  * Q4 asked for "Department / Entity" in one box. Split into two dropdowns, so
    both are pickable and reportable rather than typed prose.
  * Q8 asked for direct *and* indirect supervision in one box. Split into two
    counts, because "12 direct, 40 indirect" is the answer and one field cannot
    hold it as data.
  * Where the PDF says "(describe below)", "(explain below)", "(specify)" or
    "number of months:", that follow-up is a real field here, required only when
    the answer that calls for it is chosen. A recorded risk with no detail is
    not usable by anyone downstream.
"""
# Shared question vocabulary -- `employee_form.forms.build_field` is what turns
# these dicts into Django fields and compares against these constants.
from apps.employee_form.schema import (  # noqa: F401
    CHECKBOX,
    CHOICE_TYPES,
    DATE,
    DECIMAL,
    DEPARTMENT_CHOICES,
    FILE_TYPES,
    INTEGER,
    NUMERIC_TYPES,
    RADIO,
    SELECT,
    SIGNATURE,
    TEXT,
    TEXTAREA,
)


def _q(key, label, qtype=TEXT, required=False, help='', choices=None,
       min_value=None, max_value=None, decimals=2):
    q = {'key': key, 'label': label, 'type': qtype, 'required': required, 'help': help}
    if choices is not None:
        q['choices'] = choices
    if qtype == SIGNATURE:
        q['drawn_key'] = f'{key}_drawn'
    if qtype in NUMERIC_TYPES:
        q['min_value'] = min_value
        q['max_value'] = max_value
        if qtype == DECIMAL:
            q['decimals'] = decimals
    return q


# ── Choice sets ──────────────────────────────────────────────────────────
ENTITY_CHOICES = [
    ('ssl_wireless', 'SSL Wireless'),
    ('sslcommerz', 'SSLCOMMERZ'),
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

REPORTING_TYPE_CHOICES = [
    ('sales', 'Sales'),
    ('business', 'Business'),
    ('operational', 'Operational'),
    ('financial', 'Financial'),
    ('performance', 'Performance'),
    ('management', 'Management'),
]

# "None known / Yes / Unable to verify" -- the PDF's own wording. "Unable to
# verify" is a real answer here, not a blank: it says the check was attempted.
FINDING_CHOICES = [
    ('none_known', 'None known'),
    ('yes', 'Yes'),
    ('unable', 'Unable to verify'),
]

SEPARATION_CHOICES = [
    ('resigned', 'Resigned voluntarily'),
    ('terminated', 'Asked to leave / terminated'),
    ('mixed', 'Mixed / varies by employer'),
    ('unable', 'Unable to verify'),
]

NO_YES_CHOICES = [
    ('no', 'No'),
    ('yes', 'Yes'),
]

DEPARTURE_REASON_CHOICES = [
    ('voluntary', 'Voluntary'),
    ('organizational', 'Organizational reasons'),
    ('individual_performance', 'Individual performance issues'),
    ('unable', 'Unable to verify'),
]

OUTCOME_CHOICES = [
    ('strongly_recommended', 'Strongly recommended'),
    ('recommended', 'Recommended'),
    ('with_reservations', 'Recommended with reservations'),
    ('not_recommended', 'Not recommended'),
]

_NA_HELP = ('Where information is not available, record "N/A" or "Not verifiable" '
            'rather than leaving this blank.')

DECLARATION_TEXT = (
    'I confirm that this Candidate Mapping has been prepared objectively, based '
    'on the information available at the time of assessment, and that any '
    'negative findings are supported by verifiable records, references or '
    'credible sources.'
)

SAFEGUARD_TEXT = (
    'Any negative information must be based on verifiable records, references or '
    'credible sources. It must not be treated as fact merely on the basis of '
    'unverified market rumours. All background checks must be conducted lawfully '
    'and in line with SSL policy.'
)


# ── Sections ─────────────────────────────────────────────────────────────
STEPS = [
    {
        'key': 'candidate',
        'section': 'Candidate Identification',
        'title': 'Candidate & Assessor',
        'description': 'Who is being mapped, against which position, and by whom.',
        'next': 'team',
        'questions': [
            _q('candidate_full_name', 'Candidate Full Name', required=True),
            _q('position_applied_for', 'Position Applied For / Mapped Against',
               required=True),
            _q('entity', 'Entity', SELECT, required=True, choices=ENTITY_CHOICES),
            _q('department', 'Department', SELECT, required=True,
               choices=DEPARTMENT_CHOICES),
            _q('assessed_by', 'Assessed By (Name & Designation)', required=True),
            _q('date_of_assessment', 'Date of Assessment', DATE, required=True),
        ],
    },
    {
        'key': 'team',
        'section': 'Previous Team & People Management',
        'title': 'Team & People Management',
        'description': 'Drawn from the CV, the interview and lawful reference checks '
                       '— not from what the candidate would like recorded.',
        'next': 'customers',
        'questions': [
            _q('team_structure',
               'What type of team / team structure did the candidate manage or '
               'work with?', TEXTAREA, required=True, help=_NA_HELP),
            _q('direct_reports_count', 'People under direct supervision', INTEGER,
               required=True, min_value=0, max_value=100000),
            _q('indirect_reports_count', 'People under indirect supervision', INTEGER,
               required=True, min_value=0, max_value=100000),
            _q('team_functions',
               'What were the key functions and responsibilities of the team?',
               TEXTAREA, required=True),
            _q('authority_level',
               "What was the candidate's level of authority and decision-making "
               'responsibility?', TEXTAREA, required=True),
        ],
    },
    {
        'key': 'customers',
        'section': 'Customer Profile & Exposure',
        'title': 'Customer Profile & Exposure',
        'description': '',
        'next': 'reporting',
        'questions': [
            _q('customer_types', 'What type of customers did the candidate deal with?',
               TEXTAREA, required=True, help=_NA_HELP),
            _q('customer_segments', 'Primary customer segment', CHECKBOX,
               required=True, choices=CUSTOMER_SEGMENT_CHOICES,
               help='Select all that apply.'),
            _q('customer_segment_other', 'If other, specify'),
            _q('portfolio_scale',
               'What was the scale and nature of the customer portfolio?',
               TEXTAREA, required=True),
            _q('products_services',
               'What type of products / services did the candidate sell or manage?',
               TEXTAREA, required=True),
        ],
    },
    {
        'key': 'reporting',
        'section': 'Reporting Structure',
        'title': 'Reporting Structure',
        'description': 'Establish a clear reporting-line map.',
        'next': 'performance',
        'questions': [
            _q('reporting_head',
               "Candidate's immediate reporting head (name & designation)",
               required=True),
            _q('reporting_head_manager', 'To whom did that reporting head report?',
               required=True),
            _q('direct_reportees', 'Who reported directly to the candidate?',
               TEXTAREA, required=True, help=_NA_HELP),
            _q('org_structure',
               'What was the overall organizational / reporting structure?',
               TEXTAREA, required=True),
            _q('reporting_types', 'What type of reporting was maintained?', CHECKBOX,
               required=True, choices=REPORTING_TYPE_CHOICES,
               help='Select all that apply.'),
        ],
    },
    {
        'key': 'performance',
        'section': 'Sales / Business Performance & Measurable Success',
        'title': 'Business Performance',
        'description': "Assess the candidate's actual business contribution — do not "
                       'rely on CV descriptions alone.',
        'next': 'risk',
        'questions': [
            _q('business_type',
               'What type of sales / business did the candidate generate?',
               TEXTAREA, required=True, help=_NA_HELP),
            _q('revenue_volume',
               'Revenue or business volume handled / generated (where verifiable)',
               TEXTAREA, required=True,
               help='State the currency and period, and say whether the figure is '
                    'candidate-stated or independently verified.'),
            _q('key_achievements',
               'Key achievements and major accounts / projects acquired',
               TEXTAREA, required=True),
            _q('target_vs_achievement', 'Target versus achievement', TEXTAREA,
               help='Where applicable.'),
            _q('success_indicators',
               'Specific measurable and verifiable success indicators',
               TEXTAREA, required=True),
        ],
    },
    {
        'key': 'risk',
        'section': 'Negative / Risk Profile Assessment',
        'title': 'Risk Profile',
        'description': 'Every candidate goes through this, not only those where '
                       'something is suspected.',
        'next': 'summary',
        'questions': [
            _q('adverse_record',
               'Any adverse professional record in previous organizations?',
               SELECT, choices=FINDING_CHOICES),
            _q('adverse_record_details', 'Describe the adverse record', TEXTAREA),
            _q('performance_concerns', 'Any performance-related concerns?', SELECT,
               choices=FINDING_CHOICES),
            _q('performance_concerns_details', 'Describe the performance concerns',
               TEXTAREA),
            _q('integrity_issues', 'Any disciplinary or integrity-related issues?',
               SELECT, choices=FINDING_CHOICES),
            _q('integrity_issues_details',
               'Describe the disciplinary / integrity issues', TEXTAREA),
            _q('reasons_for_leaving',
               'Reason(s) for leaving previous organization(s)', TEXTAREA,
               required=True),
            _q('separation_type',
               'Did the candidate resign voluntarily, or was asked to leave / '
               'terminated?', SELECT, choices=SEPARATION_CHOICES),
            _q('short_tenure_pattern',
               'Is there a pattern of repeated short tenures or frequent job '
               'changes?', SELECT, choices=NO_YES_CHOICES),
            _q('short_tenure_details', 'Explain the pattern', TEXTAREA),
            _q('serving_notice', 'Is the candidate currently serving a notice period?',
               SELECT, choices=NO_YES_CHOICES),
            _q('notice_period_months', 'Notice period (months)', INTEGER,
               min_value=0, max_value=24),
            _q('current_departure_reason',
               'Is the candidate leaving their current organization voluntarily, or '
               'due to organizational / individual performance issues?',
               SELECT, choices=DEPARTURE_REASON_CHOICES),
            _q('market_reference_feedback', 'Relevant market / reference feedback',
               TEXTAREA,
               help='Only where lawfully and appropriately obtainable.'),
        ],
    },
    {
        'key': 'summary',
        'section': 'Assessor Summary, Recommendation & Declaration',
        'title': 'Summary & Recommendation',
        'description': '',
        'next': None,
        'questions': [
            _q('suitability_summary',
               'Overall suitability summary (fit against role, strengths, gaps)',
               TEXTAREA, required=True),
            _q('mapping_outcome', 'Overall mapping outcome', SELECT, required=True,
               choices=OUTCOME_CHOICES),
            _q('key_risks_flagged',
               'Key risks flagged (if any) and mitigation / further checks required',
               TEXTAREA),
            _q('assessor_name_designation', 'Assessor Name & Designation',
               required=True),
            _q('assessor_signature', 'Signature', SIGNATURE, required=True,
               help='Sign in the box, or upload a photo or scan of your signature. '
                    'The declaration is dated automatically when you sign off.'),
        ],
    },
]


# ── Follow-ups that only apply to one answer ─────────────────────────────
# The PDF's "(describe below)", "(explain below)", "(specify)" and "number of
# months:" as data. Enforced in forms.py and mirrored in the browser so the
# asterisk appears the moment the triggering answer is picked.
CONDITIONAL_RULES = [
    {'trigger': 'adverse_record', 'when': ['yes'],
     'keys': ['adverse_record_details']},
    {'trigger': 'performance_concerns', 'when': ['yes'],
     'keys': ['performance_concerns_details']},
    {'trigger': 'integrity_issues', 'when': ['yes'],
     'keys': ['integrity_issues_details']},
    {'trigger': 'short_tenure_pattern', 'when': ['yes'],
     'keys': ['short_tenure_details']},
    {'trigger': 'serving_notice', 'when': ['yes'],
     'keys': ['notice_period_months']},
    {'trigger': 'customer_segments', 'when': ['other'],
     'keys': ['customer_segment_other']},
]


# ── Rendering hints ──────────────────────────────────────────────────────
HALF_WIDTH_KEYS = frozenset({
    'position_applied_for', 'entity', 'department',
    'assessed_by', 'date_of_assessment',
    'direct_reports_count', 'indirect_reports_count',
    'customer_segment_other',
    'reporting_head', 'reporting_head_manager',
    'notice_period_months',
    'assessor_name_designation',
})

STEP_GROUPS = {
    'candidate': [
        ('Candidate', ['candidate_full_name', 'position_applied_for',
                       'entity', 'department']),
        ('Assessor', ['assessed_by', 'date_of_assessment']),
    ],
    'team': [
        ('Team structure', ['team_structure', 'direct_reports_count',
                            'indirect_reports_count']),
        ('Responsibility', ['team_functions', 'authority_level']),
    ],
    'customers': [
        ('Customers', ['customer_types', 'customer_segments',
                       'customer_segment_other']),
        ('Portfolio', ['portfolio_scale', 'products_services']),
    ],
    'reporting': [
        ('Reporting line', ['reporting_head', 'reporting_head_manager',
                            'direct_reportees']),
        ('Structure', ['org_structure', 'reporting_types']),
    ],
    'performance': [
        ('Business generated', ['business_type', 'revenue_volume']),
        ('Measurable success', ['key_achievements', 'target_vs_achievement',
                                'success_indicators']),
    ],
    'risk': [
        ('Adverse findings', ['adverse_record', 'adverse_record_details',
                              'performance_concerns',
                              'performance_concerns_details',
                              'integrity_issues', 'integrity_issues_details']),
        ('Employment history', ['reasons_for_leaving', 'separation_type',
                                'short_tenure_pattern', 'short_tenure_details']),
        ('Current position', ['serving_notice', 'notice_period_months',
                              'current_departure_reason']),
        ('Market feedback', ['market_reference_feedback']),
    ],
    'summary': [
        ('Assessment', ['suitability_summary', 'mapping_outcome',
                        'key_risks_flagged']),
        ('Assessor declaration', ['assessor_name_designation',
                                  'assessor_signature']),
    ],
}


# ── Single-choice questions are dropdowns ────────────────────────────────
# Declared as RADIO above for readability, flipped here in one place. Same
# reasoning as the HR verification form: the source Google Form used dropdowns,
# and a pick-one reads better as one line than as a list of unread options.
for _step in STEPS:
    for _question in _step['questions']:
        if _question['type'] == RADIO:
            _question['type'] = SELECT
del _step, _question


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
    """This form's own item number per key, generated from position."""
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
    """The section's questions arranged into its titled blocks.

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


_SHORT_LABEL_CHARS = 58


def is_half_width(question) -> bool:
    if question['key'] in HALF_WIDTH_KEYS:
        return True
    return (question['type'] == SELECT
            and len(question['label']) <= _SHORT_LABEL_CHARS)


def conditional_rules(step_key):
    """The follow-up rules whose trigger and targets are both on this section."""
    keys = {q['key'] for q in questions(step_key)}
    return [
        {**rule, 'keys': [k for k in rule['keys'] if k in keys]}
        for rule in CONDITIONAL_RULES
        if rule['trigger'] in keys and any(k in keys for k in rule['keys'])
    ]


def conditional_keys():
    """Every key that is required only under some answer."""
    return {key for rule in CONDITIONAL_RULES for key in rule['keys']}


def choice_label(question_key, value):
    question = QUESTIONS_BY_KEY.get(question_key)
    if not question or 'choices' not in question:
        return value
    for choice_value, label in question['choices']:
        if choice_value == value:
            return label
    return value


def wizard_label(question) -> str:
    """No section prefixes to strip on this form; kept for template symmetry."""
    return question['label']
