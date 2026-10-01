"""Small shared helpers used from views/services."""
import hashlib


def candidate_initial(name) -> str:
    """First letter of the first word (Unicode-aware), uppercase; empty → '?'."""
    if not name:
        return "?"
    first_word = str(name).strip().split(maxsplit=1)[0]
    if not first_word:
        return "?"
    for ch in first_word:
        if ch.isalpha():
            return ch.upper()
    return first_word[0].upper()


def compute_file_hash(file) -> str:
    """Return the SHA-256 hex digest of an uploaded file without loading it all into memory."""
    file.seek(0)
    sha256 = hashlib.sha256()
    for chunk in iter(lambda: file.read(8192), b''):
        sha256.update(chunk)
    file.seek(0)
    return sha256.hexdigest()


def claim_send(kind: str, pk, seconds: int = 15) -> bool:
    """True for the first send of one invitation within a few seconds, else False.

    A double click on Resend queues two tasks, and the second code invalidates
    the first before the candidate can use it.
    """
    from django.core.cache import cache
    try:
        return cache.add(f'send-claim:{kind}:{pk}', 1, seconds)
    except Exception:
        return True


def queue_task(task, *args) -> bool:
    """Queue a Celery task; False instead of an exception when the broker is down."""
    import logging
    try:
        task.delay(*args)
        return True
    except Exception:
        logging.getLogger(__name__).exception('queue.failed task=%s args=%s', task.name, args)
        return False


def check_counted_otp(obj, raw: str) -> bool:
    """Check a one-time code against `obj`, spending one attempt atomically.

    The attempt is taken in the database before the slow hash comparison, so
    guesses sent in parallel cannot all read the same count and all get through
    the lock; each one costs an attempt, and the fifth closes the door.
    """
    from django.contrib.auth.hashers import check_password
    from django.db.models import F
    from django.utils import timezone

    if not obj.otp_hash or obj.otp_is_expired or obj.otp_is_locked:
        return False
    rows = type(obj)._base_manager.filter(
        pk=obj.pk, otp_hash=obj.otp_hash, otp_attempts__lt=obj.OTP_MAX_ATTEMPTS)
    if not rows.update(otp_attempts=F('otp_attempts') + 1, updated_at=timezone.now()):
        obj.refresh_from_db(fields=['otp_attempts', 'otp_hash'])
        return False
    if check_password(raw, obj.otp_hash):
        obj.otp_verified_at = timezone.now()
        obj.otp_attempts = 0
        obj.save(update_fields=['otp_verified_at', 'otp_attempts', 'updated_at'])
        return True
    obj.refresh_from_db(fields=['otp_attempts'])
    return False


def revoke_candidate_links(resume) -> int:
    """Close the candidate's unfinished form and assessment links.

    Called when the candidate's email changes: whoever received the old one,
    if it was mistyped, must not keep a verified session that will later show
    what the real candidate enters. The links are reissued on the next send.
    Returns how many links were closed.
    """
    import uuid as _uuid
    from apps.employee_form.models import EmployeeForm
    from apps.sei_assessment.models import AssessmentInvitation

    closed = 0
    for model, rows in ((EmployeeForm, EmployeeForm.objects.filter(resume=resume, is_submitted=False)),
                        (AssessmentInvitation, AssessmentInvitation.objects.filter(resume=resume))):
        for row in rows:
            closed += model.objects.filter(pk=row.pk).update(
                token=_uuid.uuid4(), otp_hash='', otp_verified_at=None)
    return closed

