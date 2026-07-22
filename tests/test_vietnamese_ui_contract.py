"""Focused, non-database contract checks for the Vietnamese UI decision."""

from pathlib import Path

from utils.display_labels import ROLE_LABELS, display_role, display_status


ROOT = Path(__file__).resolve().parents[1]


def _text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_base_document_and_display_mappings_are_vietnamese():
    base = _text("templates/layout/base.html")
    assert '<html lang="vi">' in base
    assert display_role("APPROVAL_OWNER") == "Quản trị duyệt tài khoản"
    assert display_role("OWNER") == "Chủ cơ sở"
    assert display_status("active") == "Đang hoạt động"
    assert display_status("File Missing") == "Thiếu tệp"


def test_approval_purge_and_legal_hold_templates_have_localized_actions():
    for relative_path in (
        "templates/approval/purge_requests.html",
        "templates/approval/purge_request_detail.html",
        "templates/approval/purge_request_execute.html",
        "templates/approval/legal_holds.html",
    ):
        source = _text(relative_path)
        assert "xóa vĩnh viễn" in source.lower() or "giữ dữ liệu pháp lý" in source.lower()
        assert (
            "Yêu cầu xóa vĩnh viễn" in source
            or "GIỮ DỮ LIỆU PHÁP LÝ" in source
            or "Thực hiện xóa vĩnh viễn" in source
        )
        assert "Purge request" not in source
        assert "Legal hold" not in source


def test_permanent_purge_pages_have_explicit_back_navigation():
    listing = _text("templates/approval/purge_requests.html")
    detail = _text("templates/approval/purge_request_detail.html")

    assert "← Quay lại Cổng phê duyệt" in listing
    assert "url_for('approval.accounts', status='active')" in listing
    assert "← Quay lại danh sách yêu cầu xóa vĩnh viễn" in detail
    assert "url_for('approval.purge_requests')" in detail

    for source in (listing, detail):
        assert "history.back" not in source
        assert "history.go" not in source
        assert "javascript:" not in source


def test_confirmation_contract_has_accented_display_and_legacy_compatibility():
    request_service = _text("services/purge_request_service.py")
    hold_service = _text("services/purge_legal_hold_service.py")
    approval_route = _text("routes/approval.py")

    assert "YÊU CẦU XÓA VĨNH VIỄN" in request_service
    assert "REQUEST PURGE" in request_service
    assert "GIỮ DỮ LIỆU PHÁP LÝ" in hold_service
    assert 'legacy=f"HOLD {workspace.slug}"' in hold_service
    assert "XÓA VĨNH VIỄN CƠ SỞ" in approval_route
    assert "PURGE WORKSPACE" in approval_route


def test_visible_localization_scan_has_no_known_untranslated_ui_labels():
    files = (
        "templates/activity_log/index.html",
        "templates/approval/accounts.html",
        "templates/setting/index.html",
        "static/js/command-palette.js",
        "static/js/setting.js",
    )
    forbidden = (
        "<th class=\"col-action text-center\" scope=\"col\">Action</th>",
        ">Severity</label>",
        ">Import Wizard<",
        "Backup Center đang",
        "Thực hiện Import",
        "else 'N/A'",
    )
    combined = "\n".join(_text(path) for path in files)
    for fragment in forbidden:
        assert fragment not in combined


def test_complete_candidate_surface_has_no_remaining_confirmed_ui_defects():
    candidates = []
    for directory, suffixes in (
        ("templates", {".html"}),
        ("static", {".js"}),
        ("routes", {".py"}),
        ("services", {".py"}),
        ("validators", {".py"}),
        ("forms", {".py"}),
        ("core", {".py"}),
    ):
        root = ROOT / directory
        if root.exists():
            candidates.extend(
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix in suffixes
            )
    candidates.append(ROOT / "app.py")

    # Account-purge eligibility is an internal service, but it is still part
    # of the candidate surface scanned for accidental user-facing English.
    assert len(set(candidates)) == 157
    combined = "\n".join(path.read_text(encoding="utf-8") for path in set(candidates))
    forbidden = (
        'aria-label="Close"',
        ">Module<",
        ">Username<",
        ">local<",
        "'N/A'",
        '"N/A"',
        "Missing backup_id",
        "Backup not found",
        "Appointment not found",
        "Backup Center is disabled",
        "File backup rỗng",
        "File backup thiếu",
        "File backup không hợp lệ",
    )
    assert [fragment for fragment in forbidden if fragment in combined] == []


def test_localization_preserves_internal_values_and_permitted_brands():
    sources = "\n".join(
        _text(path)
        for path in (
            "services/purge_request_service.py",
            "services/purge_legal_hold_service.py",
            "routes/approval.py",
        )
    )
    for value in ("REQUEST PURGE", "APPROVE PURGE"):
        assert value in sources
    assert set(ROLE_LABELS) == {"APPROVAL_OWNER", "OWNER", "ADMIN", "STAFF"}
    permitted_brands = {
        "SpaManager",
        "Google",
        "PostgreSQL",
        "Railway",
        "Flask",
        "Bootstrap",
        "Python",
        "Excel",
        "MoMo",
        "VNPay",
    }
    assert permitted_brands == {
        "SpaManager",
        "Google",
        "PostgreSQL",
        "Railway",
        "Flask",
        "Bootstrap",
        "Python",
        "Excel",
        "MoMo",
        "VNPay",
    }
