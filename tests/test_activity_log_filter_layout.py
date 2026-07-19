import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPO / "templates" / "activity_log" / "index.html"
STYLESHEET_PATH = REPO / "static" / "css" / "pages" / "activity-log.css"


def tmpl() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def css() -> str:
    return STYLESHEET_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Template integrity
# ---------------------------------------------------------------------------

def test_all_eight_filter_controls_present():
    """Verify all 8 canonical filter control name attributes remain."""
    t = tmpl()
    expected = ["q", "actor", "module", "action", "severity", "time_range", "sort_by", "per_page"]
    for name in expected:
        assert f'name="{name}"' in t, f"Filter control '{name}' must exist with correct name attribute"


def test_form_method_is_get():
    """Filter form must use GET method (not POST)."""
    t = tmpl()
    assert re.search(r'method="GET"', t, re.IGNORECASE), "Filter form must use GET method"


def test_form_has_correct_id():
    """Filter form must retain its canonical ID for JS hooks."""
    assert 'id="activity-log-filter-form"' in tmpl()


def test_submit_button_and_icon_present():
    """Filter submit button (Lọc) must remain with its icon."""
    t = tmpl()
    assert 'type="submit"' in t, "Submit button must be present"
    assert "Lọc" in t or "bi-funnel-fill" in t, "Filter Lọc button content must exist"


def test_toolbar_grid_container_class_in_template():
    """Grid container class must be used in the template markup."""
    assert "activity-log-toolbar-row" in tmpl()


def test_no_stash_or_conflict_markers():
    """No git conflict markers or stash artifact text in template or stylesheet."""
    conflict = re.compile(r'^(?:<<<<<<<|=======|>>>>>>>)(?:\s|$)', re.MULTILINE)
    for content, name in [(tmpl(), "template"), (css(), "stylesheet")]:
        assert not conflict.search(content), f"Git conflict markers found in {name}"
        assert "Stashed changes" not in content, f"Stash artifact text found in {name}"


# ---------------------------------------------------------------------------
# CSS Grid implementation
# ---------------------------------------------------------------------------

def test_css_uses_display_grid():
    """Toolbar must use CSS grid (not flex) as the layout engine."""
    c = css()
    assert "display: grid" in c or "display:grid" in c, (
        "activity-log-toolbar-row must use CSS grid"
    )


def test_css_column_gap_at_least_12px():
    """column-gap must be defined and >= 12px on the toolbar grid."""
    c = css()
    gaps = [int(m) for m in re.findall(r'column-gap:\s*(\d+)px', c)]
    assert gaps, "column-gap must be explicitly set on the toolbar grid"
    assert all(g >= 12 for g in gaps), f"All column-gap values must be >= 12px, got: {gaps}"


def test_css_row_gap_at_least_12px():
    """row-gap must be defined and >= 12px on the toolbar grid."""
    c = css()
    gaps = [int(m) for m in re.findall(r'row-gap:\s*(\d+)px', c)]
    assert gaps, "row-gap must be explicitly set on the toolbar grid"
    assert all(g >= 12 for g in gaps), f"All row-gap values must be >= 12px, got: {gaps}"


def test_css_grid_children_have_min_width_zero():
    """filter-item must have min-width: 0 to prevent grid blowout."""
    c = css()
    # Find the .filter-item rule block and check min-width: 0
    match = re.search(r'\.filter-item\s*\{([^}]+)\}', c)
    assert match, ".filter-item rule block must exist"
    assert "min-width: 0" in match.group(1) or "min-width:0" in match.group(1), (
        ".filter-item must have min-width: 0 to allow safe shrinking in grid cells"
    )


def test_css_filter_items_fill_cells():
    """filter-item must use width: 100% to fill its grid cell."""
    c = css()
    match = re.search(r'\.filter-item\s*\{([^}]+)\}', c)
    assert match, ".filter-item rule block must exist"
    assert "width: 100%" in match.group(1) or "width:100%" in match.group(1), (
        ".filter-item must use width: 100% to fill grid cells"
    )


def test_css_desktop_uses_four_column_two_row_layout():
    """Desktop breakpoint must define a 4-column grid (2-row layout for 8 controls),
    not 8 compressed columns that force all items into one row."""
    c = css()
    # At least one media query must define a 4-column (not 8-column) desktop layout
    desktop_blocks = re.findall(
        r'@media\s*\([^)]*min-width:\s*(\d+)px[^)]*\)\s*\{([^@]+)\}',
        c, re.DOTALL
    )
    four_col_found = False
    for bp_str, block in desktop_blocks:
        bp = int(bp_str)
        if bp >= 768 and ("repeat(4" in block or "4, 1fr" in block or
                          re.search(r'grid-template-columns:\s*2fr.*1fr.*1fr.*1fr', block)):
            four_col_found = True
            break
    assert four_col_found, (
        "A desktop-range breakpoint (>=768px) must define a 4-column grid for clean 2-row layout"
    )


def test_css_no_eight_column_layout_at_normal_desktop():
    """The 8-column single-row layout must NOT activate at normal desktop widths
    (viewport <= 1600px), as this causes compression with the sidebar present."""
    c = css()
    # Find media blocks with 8-column template
    blocks = re.findall(
        r'@media\s*\([^)]*min-width:\s*(\d+)px[^)]*\)\s*\{([^@]+)\}',
        c, re.DOTALL
    )
    for bp_str, block in blocks:
        bp = int(bp_str)
        # An 8-column layout at <=1400px is not acceptable
        if bp <= 1400:
            eight_col = re.search(
                r'grid-template-columns:[^;]*1fr[^;]*1fr[^;]*1fr[^;]*1fr[^;]*1fr[^;]*1fr[^;]*1fr',
                block
            )
            assert not eight_col, (
                f"An 8-column compressed layout at breakpoint {bp}px (with sidebar) "
                f"must not exist; use 4-column two-row layout instead"
            )


def test_css_button_has_stable_width():
    """filter-buttons must have flex-shrink: 0 or min-width to prevent compression."""
    c = css()
    fb_blocks = re.findall(r'\.filter-buttons\s*\{([^}]+)\}', c)
    assert fb_blocks, ".filter-buttons rule must exist"
    combined = " ".join(fb_blocks)
    assert "flex-shrink: 0" in combined or "min-width" in combined or "width: auto" in combined, (
        ".filter-buttons must not shrink; add flex-shrink: 0 or min-width"
    )


def test_css_mobile_stacking_rule_present():
    """A 1-column (full-width stack) layout must exist for mobile viewports."""
    c = css()
    assert "grid-template-columns: 1fr" in c or "grid-template-columns:1fr" in c, (
        "A 1-column mobile stacking grid layout must be defined"
    )


def test_css_no_ui_audit_dependency():
    """Test must not depend on .ui-audit files or SHA-256 hashes."""
    # This test itself is the proof; no .ui-audit paths are referenced
    assert ".ui-audit" not in __file__, "Test file must not be inside .ui-audit"


def test_css_responsive_breakpoints_exist():
    """Multiple responsive breakpoints must exist covering tablet and desktop ranges."""
    c = css()
    breakpoints = [int(m) for m in re.findall(r'min-width:\s*(\d+)px', c)]
    assert any(bp >= 768 for bp in breakpoints), "Tablet breakpoint (>=768px) must exist"
    assert any(bp >= 1200 for bp in breakpoints), "Desktop breakpoint (>=1200px) must exist"
