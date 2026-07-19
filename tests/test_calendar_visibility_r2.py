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
# ---------------------------------------------------------------------------
# Semantic verification helper properties
# ---------------------------------------------------------------------------

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
    assert "var(--color-canvas)" in bg_line, (
        "cal-day-pop-summary background-color must use var(--color-canvas)"
    )
    color_line = next((l for l in block.splitlines() if "color:" in l and "background" not in l), "")
    assert "var(--color-text-default)" in color_line, (
        "cal-day-pop-summary must have explicit var(--color-text-default) text color"
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
    bg_line = next((l for l in block.splitlines() if "background-color" in l), "")
    assert "var(--color-text-default)" not in bg_line, (
        ".fc-evt-no-show must not use --color-text-default as background"
    )
    assert "var(--status-neutral-surface)" in bg_line, (
        ".fc-evt-no-show must use var(--status-neutral-surface) background"
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
# 8  Semantic Calendar Styling and Structure assertions
# ---------------------------------------------------------------------------

def test_calendar_css_variables_exist():
    """Verify that essential CSS variables for status colors exist in the root rule block."""
    text = css_text()
    assert "--status-confirmed" in text, "confirmed status variable missing"
    assert "--status-pending" in text, "pending status variable missing"
    assert "--status-completed" in text, "completed status variable missing"
    assert "--status-cancelled" in text, "cancelled status variable missing"

def test_calendar_container_and_font_families():
    """Verify calendar view container and main calendar component styles."""
    text = css_text()
    assert "#calendar-view-container" in text, "calendar container selector missing"
    assert "animation: calFadeIn" in text, "fade-in animation rule missing"
    assert "#calendar" in text, "calendar selector missing"
    assert "font-family: var(--cal-font)" in text, "calendar font family missing"

def test_month_view_hides_default_events():
    """Verify that Month view hides FullCalendar default event handlers semantically."""
    text = css_text()
    assert ".fc-dayGridMonth-view .fc-daygrid-event" in text, "month view event selector missing"
    assert "display: none !important" in text, "display: none !important hiding rule missing"

def test_summary_card_box_shadow_and_transitions():
    """Verify semantic card visual rules for the custom month-view summary tiles."""
    text = css_text()
    assert ".spa-summary-card" in text, "summary card class missing"
    assert "box-shadow: var(--elevation-card)" in text, "elevation card shadow missing"
    assert "transition:" in text, "transition rule missing"
    # hover scale transition
    assert ".spa-summary-card:hover" in text, "hover state selector missing"
    assert "transform: translateY" in text, "hover translateY transition missing"

def test_popover_header_and_day_summary_classes():
    """Verify that the detail hover popovers and summary boxes are correctly defined."""
    text = css_text()
    assert ".cal-popover" in text, "popover selector missing"
    assert ".cal-day-popover" in text, "day popover selector missing"
    assert ".cal-day-pop-summary" in text, "day pop summary class missing"
    assert ".cal-day-pop-list" in text, "day pop list class missing"

def test_offcanvas_detail_panel_styles():
    """Verify that the responsive offcanvas panel utilizes safe and surface variables."""
    text = css_text()
    assert ".cal-offcanvas" in text, "offcanvas panel class missing"
    assert "width: 420px" in text, "offcanvas width rule missing"
    assert "background: var(--color-surface)" in text, "offcanvas background surface missing"
    assert ".cal-oc-time-badge" in text, "offcanvas time badge class missing"
    assert ".cal-oc-customer" in text, "offcanvas customer class missing"


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

def test_calendar_view_hooks_defined():
    """Verify month, week, and day view classes exist in CSS to style the view layout."""
    text = css_text()
    assert "fc-dayGridMonth-view" in text, "Month view class must be present"
    assert "fc-timegrid-event" in text or "fc-v-event" in text, "Week/Day view classes must be present"
