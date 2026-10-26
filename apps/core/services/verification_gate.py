"""When a CV's links get checked.

Verification drives a headless browser per CV, and running it for every
application kept the server busy for hours on a large job. It now waits until
a recruiter shortlists the candidate (VERIFY_LINKS_AFTER_SHORTLIST); a CV still
waiting is stored as skipped with ``{'deferred': True}`` in its results.
"""
from django.conf import settings
from django.db import transaction

DEFERRED_RESULTS = {'deferred': True}


def verification_wanted(recruiter_status) -> bool:
    if not getattr(settings, 'VERIFY_LINKS_AFTER_SHORTLIST', True):
        return True
    from apps.core.status import rank
    status = recruiter_status or 'new'
    return status not in ('rejected', 'withdrawn') and rank(status) >= rank('shortlisted')


def _queue(resume_id) -> None:
    from apps.core.models import Resume
    from apps.core.tasks import verify_resume_links_task
    from apps.core.utils import queue_task
    Resume.objects.filter(pk=resume_id).update(verification_status='pending', verification_results={},
                                               verification_score=None, verified_at=None)
    transaction.on_commit(lambda: queue_task(verify_resume_links_task, resume_id))


def after_screening(resume) -> None:
    """Check the links now, or park the CV until it is shortlisted."""
    from apps.core.models import Resume
    if verification_wanted(resume.recruiter_status):
        _queue(resume.pk)
    else:
        Resume.objects.filter(pk=resume.pk).update(verification_status='skipped',
                                                   verification_results=DEFERRED_RESULTS,
                                                   verification_score=None, verified_at=None)


def after_status_change(resume) -> None:
    """A parked CV whose candidate has just been shortlisted gets checked."""
    from apps.core.models import Resume
    results = Resume.objects.filter(pk=resume.pk).values_list('verification_results', flat=True).first()
    if (results or {}).get('deferred') and verification_wanted(resume.recruiter_status):
        _queue(resume.pk)
