"""Small shared helpers used from views/services."""


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
