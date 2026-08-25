"""Keep stored documents in step with their rows.

Django never removes the file behind a FileField when the row goes away, so
without this a replaced or deleted upload stays on disk forever -- agency
reports accumulating in the media volume with nothing pointing at them. Same
reasoning as the employee_form receiver.
"""
import logging

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import HRVerificationFile

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=HRVerificationFile)
def delete_stored_file(sender, instance, **kwargs):
    if not instance.file:
        return
    try:
        # save=False: the row is already gone, there is nothing to update.
        instance.file.delete(save=False)
    except Exception:
        logger.warning(
            'hr_verification.file_cleanup_failed file=%s', instance.file.name,
            exc_info=True,
        )
