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
