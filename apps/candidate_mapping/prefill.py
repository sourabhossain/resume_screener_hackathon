"""Starting values for a mapping, from what the file already holds.

Only the identification block and the assessor's own details. Everything the
mapping actually assesses -- team, customers, performance, risk -- is the
assessor's finding, drawn from the CV, the interview and lawful reference checks.
Suggesting any of it would be putting words in their mouth.
"""
from django.utils import timezone


def _candidate_answers(resume) -> dict:
    form = getattr(resume, 'employee_form', None)
    return dict(form.answers or {}) if form else {}


def prefill_answers(resume, user=None) -> dict:
    candidate = _candidate_answers(resume)

    values = {
        'candidate_full_name': (candidate.get('candidate_full_name')
                                or (resume.candidate_name or '').strip()),
        'position_applied_for': (candidate.get('position_applied_for')
                                 or (resume.job.title or '').strip()),
        'department': candidate.get('department'),
        'date_of_assessment': timezone.localdate().isoformat(),
    }

    if user is not None:
        who = (user.get_full_name() or '').strip() or user.get_username()
        # Both the assessor line and the declaration name default to whoever is
        # filling it in; either can be corrected, since a panel member may be
        # recording an assessment the panel made together.
        values['assessed_by'] = who
        values['assessor_name_designation'] = who

    return {key: value for key, value in values.items()
            if value not in (None, '', [])}


def pending_prefill(mapping, user=None) -> dict:
    """Prefill values for questions the assessor has not answered yet.

    Applied on GET only, so a value cleared on purpose is not put back.
    """
    answered = mapping.answers or {}
    return {
        key: value
        for key, value in prefill_answers(mapping.resume, user=user).items()
        if answered.get(key) in (None, '', [])
    }
