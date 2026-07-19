"""Shared helpers for safe first-party return navigation."""

from urllib.parse import urlsplit


def safe_return_url(value):
    """Return a safe internal relative URL, preserving its query string."""
    if not value:
        return None

    candidate = str(value).strip()
    parsed = urlsplit(candidate)
    if candidate.endswith("?") and not parsed.query:
        candidate = candidate[:-1]

    if (
        not candidate.startswith("/")
        or candidate.startswith("//")
        or "\\" in candidate
        or any(ord(char) < 0x20 for char in candidate)
    ):
        return None

    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return None

    return candidate
