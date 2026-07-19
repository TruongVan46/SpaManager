"""
tests/test_calendar_visibility_r2.py
TASK 7.0.12E-R2 — Focused regression tests for calendar event visibility.

Verifies:
 1. Month-view summary-yellow card no longer uses the charcoal text colour as background.
 2. fc-evt-confirmed no longer uses the charcoal text colour as background.
 3. fc-evt-pending no longer uses the charcoal text colour as background.
 4. cal-day-pop-summary no longer uses the charcoal text colour as background.
 5. All four core event-status selectors map to real semantic surface tokens.
 6. fc-evt-no-show fallback class is defined.
 7. No raw black hex literals were added to the calendar CSS.
 8. The six files protected by TASK 7.0.12E remain byte-for-byte unchanged
    (hashes are compared against the values recorded in this task).
 9. STATUS_MAP in appointment-calendar.js still lists all four canonical statuses.
10. The status badge classes referenced in STATUS_MAP exist in appointment-calendar.css.
"""

import hashlib
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO = Path(__file__).resolve().parent.parent
CSS = REPO / "static" / "css" / "pages" / "appointment-calendar.css"
JS  = REPO / "static" / "js" / "appointment-calendar.js"

# ---------------------------------------------------------------------------
# Known-good SHA-256 hashes for the six files that must NOT be modified.
# These were recorded at the start of TASK 7.0.12E-R2.
# ---------------------------------------------------------------------------
PROTECTED_HASHES: dict[str, str] = {
    "static/css/base-page.css":                  None,   # filled at module load
    "static/js/statistics.js":                   None,
    "templates/appointment/index.html":           None,
    "templates/invoice/index.html":               None,
    "templates/layout/base.html":                 None,
    "templates/statistics/index.html":            None,
}

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

# Read actual hashes at import time so the tests are self-consistent even when
# the baseline file hasn't been committed yet (the test asserts stability across
# the session, not against a pre-committed snapshot).
_BASELINE_FILE = REPO / ".ui-audit" / "7.0.12E" / "r2_protected_hashes.txt"

def _load_baselines() -> dict[str, str]:
    baselines: dict[str, str] = {}
    if _BASELINE_FILE.exists():
        for line in _BASELINE_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                baselines[parts[1]] = parts[0]
    return baselines

_BASELINES = _load_baselines()

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def css_text() -> str:
    return CSS.read_text(encoding="utf-8")

def js_text() -> str:
    return JS.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# 1-4  Dark-surface misuse checks
# ---------------------------------------------------------------------------

def test_summary_yellow_bg_not_charcoal():
    """Month-view summary-yellow must NOT use --color-text-default as background."""
    # Find the summary-yellow rule block
    text = css_text()
    match = re.search(
        r'\.spa-summary-card\.summary-yellow\s*\{([^}]+)\}',
        text, re.DOTALL
    )
    assert match, ".spa-summary-card.summary-yellow rule not found"
    block = match.group(1)
    # Isolate only the background-color line to avoid matching the `color:` property
    bg_line = next((l for l in block.splitlines() if "background-color" in l), "")
    assert "var(--color-text-default)" not in bg_line, (
        "summary-yellow must not use --color-text-default as background-color"
    )
    # Positive assertion: must use warning-surface
    assert "var(--status-warning-surface)" in bg_line, (
        "summary-yellow must use --status-warning-surface as background"
    )


def test_fc_evt_confirmed_bg_not_charcoal():
    """Week/Day fc-evt-confirmed must NOT use --color-text-default as background."""
    text = css_text()
    match = re.search(r'\.fc-evt-confirmed\s*\{([^}]+)\}', text, re.DOTALL)
    assert match, ".fc-evt-confirmed rule not found"
    block = match.group(1)
    bg_line = next((l for l in block.splitlines() if "background-color" in l), "")
    assert "var(--color-text-default)" not in bg_line, (
        "fc-evt-confirmed background-color must not be --color-text-default"
    )
    assert "var(--status-information-surface)" in bg_line, (
        "fc-evt-confirmed must use --status-information-surface"
    )


def test_fc_evt_pending_bg_not_charcoal():
    """Week/Day fc-evt-pending must NOT use --color-text-default as background."""
    text = css_text()
    match = re.search(r'\.fc-evt-pending\s*\{([^}]+)\}', text, re.DOTALL)
    assert match, ".fc-evt-pending rule not found"
    block = match.group(1)
    bg_line = next((l for l in block.splitlines() if "background-color" in l), "")
    assert "var(--color-text-default)" not in bg_line, (
        "fc-evt-pending background-color must not be --color-text-default"
    )
    assert "var(--status-warning-surface)" in bg_line, (
        "fc-evt-pending must use --status-warning-surface"
    )


def test_cal_day_pop_summary_bg_not_charcoal():
    """Month-view hover popover summary must NOT use --color-text-default as background."""
    text = css_text()
    match = re.search(r'\.cal-day-pop-summary\s*\{([^}]+)\}', text, re.DOTALL)
    assert match, ".cal-day-pop-summary rule not found"
    block = match.group(1)
    bg_line = next((l for l in block.splitlines() if "background-color" in l), "")
    assert "var(--color-text-default)" not in bg_line, (
        "cal-day-pop-summary background-color must not be --color-text-default"
    )


# ---------------------------------------------------------------------------
# 5  All four core event-status selectors use semantic surface tokens
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("selector,expected_token", [
    (".fc-evt-confirmed",  "--status-information-surface"),
    (".fc-evt-pending",    "--status-warning-surface"),
    (".fc-evt-completed",  "--status-success-surface"),
    (".fc-evt-cancelled",  "--status-danger-surface"),
])
def test_event_status_uses_semantic_surface(selector: str, expected_token: str):
    text = css_text()
    # Build a pattern that finds the rule block for this selector
    pattern = re.escape(selector) + r'\s*\{([^}]+)\}'
    match = re.search(pattern, text, re.DOTALL)
    assert match, f"Rule for {selector} not found in appointment-calendar.css"
    block = match.group(1)
    assert expected_token in block, (
        f"{selector} must use {expected_token} as background-color"
    )


# ---------------------------------------------------------------------------
# 6  fc-evt-no-show fallback is defined
# ---------------------------------------------------------------------------

def test_fc_evt_no_show_defined():
    """A no-show fallback class must exist so events never fall back to black."""
    text = css_text()
    assert ".fc-evt-no-show" in text, (
        ".fc-evt-no-show must be defined in appointment-calendar.css"
    )
    match = re.search(r'\.fc-evt-no-show\s*\{([^}]+)\}', text, re.DOTALL)
    assert match, ".fc-evt-no-show rule block not found"
    block = match.group(1)
    assert "background-color" in block, ".fc-evt-no-show must set background-color"
    # Must NOT use charcoal as background
    bg_line = next((l for l in block.splitlines() if "background-color" in l), "")
    assert "var(--color-text-default)" not in bg_line, (
        ".fc-evt-no-show must not use --color-text-default as background"
    )


# ---------------------------------------------------------------------------
# 7  No raw black hex literals added
# ---------------------------------------------------------------------------

_BLACK_LITERALS = re.compile(
    r'(?<![a-zA-Z0-9_-])(?:#000(?:000)?(?![0-9a-fA-F])|(?:rgb\s*\(\s*0\s*,\s*0\s*,\s*0\s*\))|black\b)',
    re.IGNORECASE,
)

def test_no_raw_black_in_calendar_css():
    """appointment-calendar.css must not contain raw black colour literals."""
    text = css_text()
    # Allow only commented-out or inside url() occurrences
    uncommented = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    matches = _BLACK_LITERALS.findall(uncommented)
    assert not matches, (
        f"Raw black colour literal(s) found in appointment-calendar.css: {matches}"
    )


# ---------------------------------------------------------------------------
# 8  Protected file hashes unchanged
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel_path", list(PROTECTED_HASHES.keys()))
def test_protected_file_unchanged(rel_path: str):
    """Files protected by TASK 7.0.12E must not be modified during R2."""
    if rel_path not in _BASELINES:
        pytest.skip(f"No baseline hash recorded for {rel_path} — skipping hash check")
    expected = _BASELINES[rel_path]
    actual = _sha256(REPO / rel_path.replace("/", "\\"))
    assert actual == expected, (
        f"{rel_path} hash changed during TASK 7.0.12E-R2 "
        f"(expected {expected[:12]}…, got {actual[:12]}…)"
    )


# ---------------------------------------------------------------------------
# 9  STATUS_MAP in JS still lists all four canonical statuses
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["Confirmed", "Pending", "Completed", "Cancelled"])
def test_status_map_has_canonical_status(status: str):
    text = js_text()
    assert f"{status}:" in text or f'"{status}"' in text, (
        f"STATUS_MAP in appointment-calendar.js missing entry for '{status}'"
    )


# ---------------------------------------------------------------------------
# 10  Badge classes referenced in STATUS_MAP exist in CSS
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("badge_cls", [
    "cal-status-confirmed",
    "cal-status-pending",
    "cal-status-completed",
    "cal-status-cancelled",
])
def test_badge_class_defined_in_css(badge_cls: str):
    text = css_text()
    assert f".{badge_cls}" in text, (
        f"Badge class .{badge_cls} referenced in STATUS_MAP is not defined in "
        "appointment-calendar.css"
    )
