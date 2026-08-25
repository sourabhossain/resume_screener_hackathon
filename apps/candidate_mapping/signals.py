"""Keep stored documents in step with their rows.

Django never removes the file behind a FileField when the row goes away, so
without this a replaced assessor signature stays on disk forever. Same
reasoning as the two sibling apps.
"""
import logging

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import CandidateMappingFile

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=CandidateMappingFile)
def delete_stored_file(sender, instance, **kwargs):
    if not instance.file:
        return
    try:
        # save=False: the row is already gone, there is nothing to update.
        instance.file.delete(save=False)
    except Exception:
        logger.warning(
            'candidate_mapping.file_cleanup_failed file=%s', instance.file.name,
            exc_info=True,
        )
