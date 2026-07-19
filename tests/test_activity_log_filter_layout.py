import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPO / "templates" / "activity_log" / "index.html"
STYLESHEET_PATH = REPO / "static" / "css" / "pages" / "activity-log.css"

def tmpl_content() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")

def css_content() -> str:
    return STYLESHEET_PATH.read_text(encoding="utf-8")

def test_activity_log_filter_names_remain():
    """Verify that all canonical filter controls remain in the template with correct name attributes."""
    content = tmpl_content()
    expected_names = ["q", "actor", "module", "action", "severity", "time_range", "sort_by"]
    for name in expected_names:
        assert f'name="{name}"' in content, f"Filter control for '{name}' must exist with correct name attribute"

def test_activity_log_form_properties():
    """Verify that the filter form uses the GET method and submits to the index route."""
    content = tmpl_content()
    assert re.search(r'<form\s+method="GET"[^>]*id="activity-log-filter-form"[^>]*>', content) or \
           re.search(r'<form\s+id="activity-log-filter-form"[^>]*method="GET"[^>]*>', content), (
        "Filter form must exist with method GET and ID activity-log-filter-form"
    )

def test_activity_log_submit_button_exists():
    """Verify that the filter submission button remains present inside the toolbar."""
    content = tmpl_content()
    assert 'type="submit"' in content, "Submit button must be present in the filter form"
    assert "Lọc" in content or "bi-funnel-fill" in content, "Filter/Lọc button styling or text must exist"

def test_activity_log_grid_class_referenced():
    """Verify that the grid row container is used in the template markup."""
    content = tmpl_content()
    assert "activity-log-toolbar-row" in content, (
        "Toolbar container must use the activity-log-toolbar-row class"
    )

def test_activity_log_no_stash_markers():
    """Verify that no git conflict markers or stash text exist in the template or stylesheet."""
    # Check for git conflict marker lines: <<<<<<<, =======, >>>>>>>
    conflict_pattern = re.compile(r'^(?:<<<<<<<|=======|>>>>>>>)(?:\s|$)', re.MULTILINE)
    
    assert not conflict_pattern.search(tmpl_content()), "Git conflict markers found in template"
    assert "Stashed changes" not in tmpl_content(), "Stash changes text found in template"

    assert not conflict_pattern.search(css_content()), "Git conflict markers found in stylesheet"
    assert "Stashed changes" not in css_content(), "Stash changes text found in stylesheet"

def test_activity_log_css_grid_implemented():
    """Verify that the toolbar utilizes display: grid and defines breakpoints."""
    css = css_content()
    assert "display: grid" in css or "display:grid" in css, (
        "activity-log-toolbar-row must utilize CSS grid instead of display: flex"
    )
    # Verify breakpoints exist for responsive wrapping
    assert "@media" in css, "Responsive media queries must exist in activity-log.css"
    assert "min-width: 768px" in css, "768px medium breakpoint must exist for multi-row wrap"
    assert "min-width: 1200px" in css, "1200px large breakpoint must exist for single-row desktop"

def test_activity_log_css_items_occupy_full_width():
    """Verify that filter items and buttons take full width of their grid cells on mobile."""
    css = css_content()
    # Check width configurations
    assert "width: 100%" in css or "width:100%" in css, (
        "filter-item and buttons must occupy full cell width to prevent shrinking overlap"
    )
