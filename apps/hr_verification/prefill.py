"""Starting values copied from the candidate's Employee Information Form (EIF).

Only facts the candidate declared are carried across, in the same employer order
and reference numbering. HR's own judgements and the sign-off are never prefilled.
"""
from django.utils import timezone

from apps.core.documents import display_date
from apps.employee_form.schema import declared_employer_indices

from .schema import EMPLOYER_MAX, REFERENCE_COUNT

# HR key <- EIF key, same fact in the same words.
DIRECT_MAP = {
    'requisition_id': 'requisition_id',
    'candidate_full_name': 'candidate_full_name',
    'position_applied_for': 'position_applied_for',
    'department': 'department',
    'candidate_nid_number': 'nid_number',
    'candidate_birth_certificate_number': 'birth_certificate_number',
    'candidate_date_of_birth': 'date_of_birth',
    'candidate_present_address': 'present_address',
    'nid_submitted_value': 'nid_number',
    'birth_certificate_submitted_value': 'birth_certificate_number',
    'present_address_submitted_value': 'present_address',
    'permanent_address_submitted_value': 'permanent_address',
    'training_certification_names': 'training_certification_names',
    'other_details': 'other_qualification_details',
}

DEGREE_MAP = {'masters': 'masters', 'bachelors': 'bachelors', 'other': 'other',
              'hsc': 'hsc', 'ssc': 'ssc'}

RELATIONSHIP_MAP = {'hr_other': 'hr'}


def _candidate_answers(resume) -> dict:
    form = getattr(resume, 'employee_form', None)
    return dict(form.answers or {}) if form else {}


def _text(value) -> str:
    return str(value if value is not None else '').strip()


def _joined(parts, sep=' — '):
    return sep.join(p for p in (_text(x) for x in parts) if p)


def _labelled(answers, pairs):
    out = []
    for key, label in pairs:
        value = _text(answers.get(key))
        if value:
            out.append(f'{label}: {value}' if label else value)
    return ' — '.join(out)


def _education_details(c) -> dict:
    out = {}
    for level in ('masters', 'bachelors'):
        completed = _text(c.get(f'{level}_completion_date'))
        out[f'{level}_details'] = _joined([
            c.get(f'{level}_institution'), c.get(f'{level}_degree_name'),
            c.get(f'{level}_major'),
            f'Completed {display_date(completed)}' if completed else '',
        ])
    for level in ('hsc', 'ssc'):
        out[f'{level}_details'] = _labelled(c, [
            (f'{level}_institution', ''), (f'{level}_board', 'Board'),
            (f'{level}_passing_year', 'Passing year'), (f'{level}_result', 'Result'),
        ])
    return out


def _employers(c) -> dict:
    out = {}
    indices = declared_employer_indices(c)[:EMPLOYER_MAX]
    if indices:
        out['has_employment'] = 'yes'
    elif c.get('has_employment') == 'no':
        out['has_employment'] = 'no'
    for position, index in enumerate(indices, start=1):
        src = f'employer_{index}_'
        dst = f'employer_{position}_'
        current = c.get(f'{src}separation') == 'currently_employed'
        out[f'{dst}name'] = c.get(f'{src}name')
        out[f'{dst}hr_contact'] = _joined([c.get(f'{src}hr_contact'),
                                           c.get(f'{src}hr_email')], sep='\n')
        out[f'{dst}position'] = c.get(f'{src}position')
        out[f'{dst}claimed_start_date'] = c.get(f'{src}start_date')
        if current:
            out[f'{dst}claimed_current'] = 'yes'
        else:
            out[f'{dst}claimed_end_date'] = c.get(f'{src}end_date')
        out[f'{dst}claimed_reason_leaving'] = c.get(f'{src}reason_leaving')
        if position < EMPLOYER_MAX:
            out[f'{dst}another'] = 'yes' if position < len(indices) else 'no'
    return out


def _references(c) -> dict:
    out = {}
    for index in range(1, REFERENCE_COUNT + 1):
        p = f'reference_{index}_'
        relationship = c.get(f'{p}relationship')
        out[f'{p}name'] = c.get(f'{p}name')
        out[f'{p}designation'] = c.get(f'{p}designation')
        out[f'{p}relationship'] = RELATIONSHIP_MAP.get(relationship, relationship)
        out[f'{p}contact'] = _joined([c.get(f'{p}contact'), c.get(f'{p}email')], sep='\n')
    return out


def prefill_answers(resume, user=None) -> dict:
    """Values to start an HR verification with. Blanks are dropped."""
    c = _candidate_answers(resume)
    values = {hr_key: c.get(eif_key) for hr_key, eif_key in DIRECT_MAP.items()}

    present = _text(c.get('present_address'))
    permanent = _text(c.get('permanent_address'))
    same = c.get('address_same')
    if same == 'no' or (same is None and permanent and permanent != present):
        values['candidate_permanent_address'] = permanent

    if c.get('date_of_birth'):
        values['dob_submitted_value'] = display_date(c['date_of_birth'])

    values['highest_degree'] = DEGREE_MAP.get(c.get('highest_degree'))
    values.update(_education_details(c))
    values.update(_employers(c))
    values.update(_references(c))

    if not _text(values.get('candidate_full_name')):
        values['candidate_full_name'] = _text(resume.candidate_name)
    if not _text(values.get('position_applied_for')):
        values['position_applied_for'] = _text(resume.job.title)
    if not _text(values.get('requisition_id')):
        values['requisition_id'] = _text(getattr(resume.job, 'requisition_id', ''))

    values['verification_start_date'] = timezone.localdate().isoformat()
    if user is not None:
        values['hr_reviewer_name'] = (user.get_full_name() or '').strip() or user.get_username()

    return {key: value for key, value in values.items()
            if value is not None and _text(value) != ''}


def pending_prefill(verification, user=None) -> dict:
    """Prefill values for questions HR has not answered yet."""
    answered = verification.answers or {}
    suggested = prefill_answers(verification.resume, user=user)
    return {
        key: value for key, value in suggested.items()
        if answered.get(key) in (None, '', [])
    }
