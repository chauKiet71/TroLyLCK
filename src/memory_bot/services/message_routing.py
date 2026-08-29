from __future__ import annotations

import re

SAVE_PREFIX = re.compile(r"^\s*đây\s+là\b", flags=re.IGNORECASE | re.UNICODE)


def explicit_save_content(text: str) -> str | None:
    """Return content after a leading save prefix, or None for ordinary chat."""
    match = SAVE_PREFIX.match(text)
    if not match:
        return None
    return text[match.end() :].strip()
