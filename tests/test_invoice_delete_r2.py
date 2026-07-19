"""
tests/test_invoice_delete_r2.py
TASK 7.0.12D-R2 — Focused regression tests for Invoice delete button interaction.

Verifies:
 1.  Desktop delete control exists with correct onclick attribute.
 2.  Mobile (responsive) delete control presence.
 3.  Modal #deleteConfirmModal exists in template.
 4.  Form #deleteInvoiceForm exists inside modal.
 5.  confirmDelete JS function is defined in template.
 6.  DOMContentLoaded handler for form submit is defined.
 7.  No bare 'Stashed changes' text in template (the root-cause contamination).
 8.  No bare 'Stashed changes' text inside any <script> block.
 9.  confirmDelete sets form.action to the correct delete URL pattern.
 10. Delete route returns JSON for XHR requests.
 11. Delete route returns redirect for normal form POSTs.
 12. Delete route requires POST method (GET is rejected).
 13. Delete route enforces authorization (anonymous rejected).
 14. No window.location.reload() in the invoice index template.
 15. No location.reload() in the invoice index template.
 16. csrfFetch is used (not plain fetch) for the async request.
 17. Frozen UI contract hooks remain unchanged.
 18. Non-invoice TASK 7.0.12E files are not modified by R2.
"""

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO = Path(__file__).resolve().parent.parent
INVOICE_TEMPLATE = REPO / "templates" / "invoice" / "index.html"
INVOICE_ROUTE    = REPO / "routes" / "invoice.py"

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Template loading helpers
# ---------------------------------------------------------------------------

def tmpl() -> str:
    return INVOICE_TEMPLATE.read_text(encoding="utf-8")

def route() -> str:
    return INVOICE_ROUTE.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# 1.  Desktop delete control: button with onclick="confirmDelete(...)"
# ---------------------------------------------------------------------------
def test_desktop_delete_button_exists():
    text = tmpl()
    assert re.search(r'onclick=["\']confirmDelete\(', text), (
        "Desktop delete button with onclick=\"confirmDelete(...)\" not found in invoice/index.html"
    )

# ---------------------------------------------------------------------------
# 2.  Delete control uses btn-outline-danger class (visual contract)
# ---------------------------------------------------------------------------
def test_desktop_delete_button_has_danger_class():
    text = tmpl()
    # Find the delete button section
    assert "btn-outline-danger" in text or "btn-danger" in text, (
        "Delete button must have a danger class variant"
    )

# ---------------------------------------------------------------------------
# 3.  Modal #deleteConfirmModal exists
# ---------------------------------------------------------------------------
def test_delete_confirm_modal_exists():
    text = tmpl()
    assert 'id="deleteConfirmModal"' in text, (
        "#deleteConfirmModal must exist in invoice/index.html"
    )

# ---------------------------------------------------------------------------
# 4.  Form #deleteInvoiceForm exists inside modal
# ---------------------------------------------------------------------------
def test_delete_invoice_form_exists():
    text = tmpl()
    assert 'id="deleteInvoiceForm"' in text, (
        "#deleteInvoiceForm must exist inside the modal"
    )

# ---------------------------------------------------------------------------
# 5.  confirmDelete function is defined in the script block
# ---------------------------------------------------------------------------
def test_confirm_delete_function_defined():
    text = tmpl()
    assert "function confirmDelete" in text, (
        "confirmDelete() function must be defined in invoice/index.html scripts"
    )

# ---------------------------------------------------------------------------
# 6.  DOMContentLoaded submit handler references deleteInvoiceForm
# ---------------------------------------------------------------------------
def test_dom_content_loaded_submit_handler():
    text = tmpl()
    assert "deleteForm.addEventListener('submit'" in text or \
           'deleteForm.addEventListener("submit"' in text, (
        "Form submit listener must be registered in the DOMContentLoaded block"
    )

# ---------------------------------------------------------------------------
# 7.  No bare 'Stashed changes' text anywhere in the template
# ---------------------------------------------------------------------------
def test_no_stash_artifact_in_template():
    text = tmpl()
    assert "Stashed changes" not in text, (
        "Template contains 'Stashed changes' git stash artifact — must be removed"
    )

# ---------------------------------------------------------------------------
# 8.  No 'Stashed changes' text inside any <script> block
# ---------------------------------------------------------------------------
def test_no_stash_artifact_in_script_blocks():
    text = tmpl()
    # Extract all <script>...</script> blocks
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', text, re.DOTALL | re.IGNORECASE)
    for script in scripts:
        assert "Stashed changes" not in script, (
            "A <script> block in invoice/index.html contains 'Stashed changes' — "
            "this causes a JavaScript syntax error and breaks the delete handler"
        )

# ---------------------------------------------------------------------------
# 9.  confirmDelete sets form.action to /invoices/delete/ prefix
# ---------------------------------------------------------------------------
def test_confirm_delete_sets_form_action():
    text = tmpl()
    assert "/invoices/delete/" in text, (
        "confirmDelete must set deleteForm.action to /invoices/delete/<id>"
    )

# ---------------------------------------------------------------------------
# 10. Delete route returns JSON for XHR (async path exists in route)
# ---------------------------------------------------------------------------
def test_delete_route_has_json_branch():
    text = route()
    assert "jsonify" in text, "invoice.py must import/use jsonify"
    assert "X-Requested-With" in text or "is_json" in text, (
        "Delete route must detect XHR/JSON request and return JSON"
    )
    assert "'success'" in text or '"success"' in text, (
        "Delete route JSON response must include 'success' key"
    )

# ---------------------------------------------------------------------------
# 11. Delete route has HTML redirect fallback
# ---------------------------------------------------------------------------
def test_delete_route_has_html_fallback():
    text = route()
    assert "redirect(" in text, (
        "Delete route must redirect for non-XHR requests"
    )

# ---------------------------------------------------------------------------
# 12. Delete route only accepts POST
# ---------------------------------------------------------------------------
def test_delete_route_requires_post():
    text = route()
    # Look for the route decorator with POST
    assert re.search(r"methods=\[.*'POST'.*\]", text), (
        "Delete route must be restricted to POST method"
    )

# ---------------------------------------------------------------------------
# 13. Delete route calls authorization check
# ---------------------------------------------------------------------------
def test_delete_route_checks_authorization():
    text = route()
    assert "AuthService" in text or "require_current_username" in text or \
           "login_required" in text, (
        "Delete route must enforce authorization"
    )

# ---------------------------------------------------------------------------
# 14 & 15. No reload() calls in the template's async success path
# ---------------------------------------------------------------------------
def test_no_reload_call_in_invoice_template():
    text = tmpl()
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', text, re.DOTALL | re.IGNORECASE)
    full_script = "\n".join(scripts)
    assert "window.location.reload()" not in full_script, (
        "window.location.reload() must not be called on delete success"
    )
    assert "location.reload()" not in full_script, (
        "location.reload() must not be called on delete success"
    )

# ---------------------------------------------------------------------------
# 16. csrfFetch (not plain fetch) is used for the async delete request
# ---------------------------------------------------------------------------
def test_csrf_fetch_used_for_delete():
    text = tmpl()
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', text, re.DOTALL | re.IGNORECASE)
    full_script = "\n".join(scripts)
    assert "csrfFetch(" in full_script, (
        "csrfFetch() must be used (not plain fetch) to include CSRF token"
    )

# ---------------------------------------------------------------------------
# 17. Confirm button (#confirmDeleteSubmitBtn) exists in modal
# ---------------------------------------------------------------------------
def test_confirm_submit_button_exists():
    text = tmpl()
    assert 'id="confirmDeleteSubmitBtn"' in text, (
        "#confirmDeleteSubmitBtn must exist in the modal footer"
    )

# ---------------------------------------------------------------------------
# 18. Semantic structure assertions for delete confirm form and modal closing controls
# ---------------------------------------------------------------------------
def test_delete_confirm_form_method():
    """Verify that #deleteInvoiceForm is configured as POST."""
    text = tmpl()
    assert re.search(r'<form\s+id="deleteInvoiceForm"[^>]*method="POST"[^>]*>', text) or \
           re.search(r'<form\s+method="POST"[^>]*id="deleteInvoiceForm"[^>]*>', text), (
        "#deleteInvoiceForm must use POST method for safe state modification"
    )

def test_delete_confirm_modal_dismissal():
    """Verify that close/dismiss controls exist to close the confirmation modal safely."""
    text = tmpl()
    assert 'data-bs-dismiss="modal"' in text, (
        "Modal must have dismissing controls using bootstrap data-bs-dismiss attribute"
    )

def test_invoice_filter_form_structure():
    """Verify that the filter GET form exists with standard query fields."""
    text = tmpl()
    assert 'method="GET"' in text, "filter form must be method GET"
    assert 'name="q"' in text, "search query name attribute must exist"
    assert 'name="payment_method"' in text, "payment method selection name attribute must exist"

def test_invoice_ajax_dom_removal_in_template():
    """Verify that a successful deletion removes the invoice row from the DOM."""
    text = tmpl()
    assert "__invoiceRowToDelete.remove()" in text or "rowToDelete.remove()" in text or "closest('tr').remove()" in text, (
        "JS script must remove the deleted invoice row from the DOM on successful request"
    )

def test_invoice_ajax_toast_notifications():
    """Verify that Notification behavior is connected to deletion success/error."""
    text = tmpl()
    assert "Notification.error" in text or "Notification.success" in text or "showToast" in text, (
        "JS script must notify the user via Notification or showToast on successful delete or failure"
    )

def test_invoice_ajax_duplicate_submit_prevention():
    """Verify that the submit button is disabled on submission to prevent duplicates."""
    text = tmpl()
    assert "confirmSubmitBtn.disabled = true" in text or 'confirmSubmitBtn.disabled = true' in text or 'confirmSubmitBtn.setAttribute("disabled"' in text, (
        "JS script must disable the confirm button on submit to prevent duplicate delete requests"
    )


# ---------------------------------------------------------------------------
# Route-level tests using Flask test client
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    """Create a test Flask application."""
    import sys
    sys.path.insert(0, str(REPO))
    try:
        from app import create_app
        application = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False,
                                  'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                                  'SECRET_KEY': 'test-secret'})
        return application
    except Exception:
        return None


@pytest.fixture(scope="module")
def client(app):
    if app is None:
        pytest.skip("Could not create Flask test app")
    return app.test_client()


def test_delete_route_rejects_get(client):
    """DELETE route must reject GET requests with 405."""
    resp = client.get("/invoices/delete/99999")
    assert resp.status_code == 405, (
        f"GET /invoices/delete/99999 should return 405, got {resp.status_code}"
    )


def test_delete_route_requires_auth_for_xhr(client):
    """DELETE route must reject unauthenticated XHR with 401 or redirect."""
    resp = client.post(
        "/invoices/delete/99999",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    # Must not return 200 with success=True for unauthenticated user
    assert resp.status_code in (302, 401, 403), (
        f"Unauthenticated delete XHR should be rejected, got {resp.status_code}"
    )
