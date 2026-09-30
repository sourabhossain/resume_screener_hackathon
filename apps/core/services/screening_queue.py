"""Handing a résumé to the screening worker, and rescuing ones that never came back."""
import logging
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

# Well past the task's own hard limit (210 s) plus its retries, so a row still
# 'processing' after this has lost its task: the broker was down, the message
# was dropped, or the worker died mid-run.
STALE_AFTER = timedelta(minutes=30)

STALE_REASON = ('Screening did not finish: the background worker never picked it up '
                'or stopped part-way. Re-run screening to try again.')
QUEUE_REASON = ('Screening could not be started because the background queue was '
                'unavailable. Re-run screening to try again.')


def stale_filter(now=None) -> Q:
    """Rows left 'processing' long after their task should have ended."""
    cutoff = (now or timezone.now()) - STALE_AFTER
    return Q(screening_status='processing', updated_at__lt=cutoff)


def queue_screening(resume_id) -> bool:
    """Queue one résumé. On a broker failure mark it failed instead of raising.

    Raising here would give a candidate a server error after their application
    was already saved, and leave the row 'processing' with no task behind it.
    """
    from apps.core.models import Resume
    from apps.core.tasks import screen_resume_task

    try:
        screen_resume_task.delay(resume_id)
        return True
    except Exception:
        logger.exception('screening.queue_failed resume=%s', resume_id)
        Resume.all_objects.filter(pk=resume_id).update(
            screening_status='failed', reasoning=QUEUE_REASON, updated_at=timezone.now())
        return False
