"""Keep stored documents in step with their rows.

Django never removes the file behind a FileField when the row goes away, so
without this a replaced or deleted upload stays on disk forever — candidate NID
scans and certificates accumulating in the media volume with nothing pointing at
them. A post_delete receiver covers every route: instance.delete(),
queryset.delete(), and the cascade when an EmployeeForm or Resume is removed
(the presence of a receiver disables Django's fast-delete path, so the signal is
guaranteed to fire per row).
"""
import logging

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import EmployeeFormFile

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=EmployeeFormFile)
def delete_stored_file(sender, instance, **kwargs):
    if not instance.file:
        return
    try:
        # save=False: the row is already gone, there is nothing to update.
        instance.file.delete(save=False)
    except Exception:
        # A missing or unreadable file must not abort the delete that triggered
        # this, so log and move on.
        logger.warning(
            'employee_form.file_cleanup_failed file=%s', instance.file.name,
            exc_info=True,
        )
