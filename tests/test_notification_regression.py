import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_single_shared_notification_container_exists_and_location():
    # 1. Verify single shared notification container exists in layout templates
    base_html = (ROOT / "templates" / "layout" / "base.html").read_text(encoding="utf-8")
    approval_base_html = (ROOT / "templates" / "layout" / "approval_base.html").read_text(encoding="utf-8")
    
    # Check that toast-container ID is present
    assert 'id="toast-container"' in base_html
    assert 'id="toast-container"' in approval_base_html
    
    # Check that there is only one occurrence per file
    assert base_html.count('id="toast-container"') == 1
    assert approval_base_html.count('id="toast-container"') == 1
    
    # 2. Verify container is outside main-content clipping region
    # main-content starts at <main id="main-content" ...>
    # toast-container should be defined before it.
    toast_idx = base_html.find('id="toast-container"')
    main_idx = base_html.find('id="main-content"')
    assert toast_idx < main_idx, "toast-container must be outside/before the main-content clipping container to prevent layout hidden clips"

def test_notification_positioning_and_z_index():
    css_content = (ROOT / "static" / "css" / "components" / "notification.css").read_text(encoding="utf-8")
    theme_content = (ROOT / "static" / "css" / "theme.css").read_text(encoding="utf-8")
    
    # 3. Verify expected fixed positioning
    assert "position: fixed;" in css_content
    
    # 4. Verify notification z-index is configured above the top header token (z-index maps to z-layer-toast)
    assert "z-index: var(--z-index-toast);" in css_content
    assert "--z-layer-toast: 1040;" in theme_content
    assert "--z-index-toast: var(--z-layer-toast);" in theme_content
    
    # 5. Verify top offset accounts for header height (desktop uses top: 170px)
    assert "top: 170px;" in css_content
    
    # 6. Verify mobile width and inset rules exist (tablet/mobile uses top: 108px)
    assert "top: 108px;" in css_content
    assert "right: 16px;" in css_content
    assert "right: 12px;" in css_content
    assert "left: 12px;" in css_content

def test_no_generic_alert_or_toast_overrides():
    css_content = (ROOT / "static" / "css" / "components" / "notification.css").read_text(encoding="utf-8")
    
    # 7. Check that we style using specific class prefixes, avoiding naked global element overrides like `.alert { ... }` or `.toast { ... }`
    # We should use `.spa-toast` or `.toast-container`
    assert ".spa-toast" in css_content
    # Ensure there is no naked `.alert` selector override
    assert re.search(r'(?<!\w)\.alert\s*\{', css_content) is None
    # Ensure there is no naked `.toast` selector override
    assert re.search(r'(?<!\w)\.toast\s*\{', css_content) is None

def test_flash_categories_mapping_and_aria_attributes():
    base_html = (ROOT / "templates" / "layout" / "base.html").read_text(encoding="utf-8")
    
    # 8. Check that flash categories still map correctly
    assert "type === 'danger' || type === 'error'" in base_html
    assert "Notification.error(msg)" in base_html
    assert "type === 'warning'" in base_html
    assert "Notification.warning(msg)" in base_html
    assert "type === 'info'" in base_html
    assert "Notification.info(msg)" in base_html
    
    # 9. Verify required ARIA attributes and role are present in notification creation
    js_content = (ROOT / "static" / "js" / "notification.js").read_text(encoding="utf-8")
    assert 'role' in js_content
    assert 'alert' in js_content
    assert 'aria-live' in js_content
    assert 'aria-atomic' in js_content
    assert 'aria-label="Đóng"' in js_content or "aria-label" in js_content

def test_ids_and_js_hooks_unchanged():
    js_content = (ROOT / "static" / "js" / "notification.js").read_text(encoding="utf-8")
    
    # 10. Existing IDs and hooks must remain unchanged
    assert "toast-container" in js_content
    assert "spa-toast" in js_content
    assert "spa-toast-close" in js_content
    assert "NotificationService" in js_content
    assert "window.Notification" in js_content
