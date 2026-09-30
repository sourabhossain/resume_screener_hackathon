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
