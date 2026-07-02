import logging

from django.db import transaction

from ..models import AuditLog

logger = logging.getLogger(__name__)

# Resolve entities by class NAME so this core-services module needs no
# cross-app import (e.g. of apps.interviews). Maps model name -> the stable
# reference attribute persisted in AuditLog.entity_id.
_ENTITY_KEY_BY_MODEL = {
    'Resume': 'uuid',
    'Job': 'slug',
    'Interview': 'pk',
    'InterviewEvaluation': 'pk',
    'User': 'pk',
}
_ENTITY_TYPE_BY_MODEL = {
    'Resume': 'resume',
    'Job': 'job',
    'Interview': 'interview',
    'InterviewEvaluation': 'interview_evaluation',
    'User': 'user',
}

_DETAILS_MAX = 2000
_REQUEST_ID_MAX = 64


def _coerce_actor(actor):
    """Return a saved, authenticated user, or None for system/anonymous actions."""
    if actor is None:
        return None
    if not getattr(actor, 'is_authenticated', False):
        return None
    if getattr(actor, 'pk', None) is None:
        return None
    return actor


def _resolve_entity(entity):
    """Return (entity_type, entity_id) for a known model instance, else ('', '')."""
    if entity is None:
        return '', ''
    name = type(entity).__name__
    entity_type = _ENTITY_TYPE_BY_MODEL.get(name, '')
    key_attr = _ENTITY_KEY_BY_MODEL.get(name)
    if not entity_type or not key_attr:
        return '', ''
    value = getattr(entity, key_attr, None)
    return entity_type, '' if value is None else str(value)


def audit_log(actor, action, entity, details='', request=None):
    """Append a single AuditLog row. Never raises into the caller.

    The insert runs inside a transaction.atomic() savepoint so that a failure
    is rolled back locally and cannot poison the caller's surrounding
    transaction; any error is logged and swallowed.
    """
    try:
        entity_type, entity_id = _resolve_entity(entity)
        request_id = getattr(request, 'request_id', None)
        if request_id is not None:
            request_id = str(request_id)[:_REQUEST_ID_MAX]
        with transaction.atomic():
            AuditLog.objects.create(
                actor=_coerce_actor(actor),
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                details=(details or '')[:_DETAILS_MAX],
                request_id=request_id,
            )
    except Exception:
        logger.exception('audit_log failed: action=%s', action)
