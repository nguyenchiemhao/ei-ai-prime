"""The one rule for an email address that becomes a user: plain, lower case, bounded."""

import re

_EMAIL = re.compile(r"[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)+")
_EMAIL_MIN, _EMAIL_MAX, _LOCAL_MAX = 3, 320, 64


def parse_email(raw: str) -> str | None:
    """The trimmed, lowercased email, or ``None`` when it is not a plain address."""
    value = raw.strip().lower()
    local = value.partition("@")[0]
    if (
        not _EMAIL_MIN <= len(value) <= _EMAIL_MAX
        or len(local) > _LOCAL_MAX
        or not _EMAIL.fullmatch(value)
    ):
        return None
    return value
