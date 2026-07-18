from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from contracts.ui_contract_parser import (
    canonical_hooks,
    condition_snapshot,
    form_snapshot,
    rendered_templates,
    route_snapshot,
    snapshot,
    write_baselines,
)


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests" / "contracts"
REVIEW_MESSAGE = "Frontend contract baseline changes require explicit review. Do not regenerate merely to make the test pass."


def load(name: str) -> dict:
    return json.loads((BASELINE / name).read_text(encoding="utf-8"))


def test_contract_baselines_are_explicit_and_complete() -> None:
    routes = load("ui_route_contract.json")
    forms = load("ui_form_contract.json")
    hooks = load("ui_behavior_hook_contract.json")
    role_feature = load("ui_role_feature_contract.json")
    route_meta = routes["verified_audit_counts"]

    # The source parser protects every Flask decorator (including API and
    # operational endpoints); the audit's 65 frontend-facing route nodes are
    # a reporting subset, not a safe replacement for the complete guard set.
    assert len(routes["routes"]) == 103
    assert len(routes["rendered_templates"]) == 48
    assert len(forms["forms"]) == 79
    assert len(hooks["hooks"]) == 304
    assert len(role_feature["role_conditions"]) == 242
    assert len(role_feature["feature_conditions"]) == 289
    assert route_meta == {
        "canonical_behavior_hooks": 304,
        "dynamic_runtime_hook_groups": 31,
        "form_boundaries": 79,
        "form_field_contracts": 80,
        "frontend_route_contracts": 65,
        "traceable_canonical_hooks": 266,
        "unresolved_high_risk_hooks": 38,
    }
    assert REVIEW_MESSAGE in (BASELINE / "README.txt").read_text(encoding="utf-8")


def test_current_routes_and_template_relationships_match_baseline() -> None:
    baseline = load("ui_route_contract.json")
    current = snapshot(ROOT)
    assert current["routes"] == baseline["routes"], REVIEW_MESSAGE
    assert current["rendered_templates"] == baseline["rendered_templates"], REVIEW_MESSAGE


def test_current_forms_match_baseline() -> None:
    assert form_snapshot(ROOT) == load("ui_form_contract.json")["forms"], REVIEW_MESSAGE


def test_current_behavior_hooks_match_baseline() -> None:
    assert canonical_hooks(ROOT) == load("ui_behavior_hook_contract.json")["hooks"], REVIEW_MESSAGE


def test_current_role_and_feature_conditions_match_baseline() -> None:
    expected = load("ui_role_feature_contract.json")
    current = condition_snapshot(ROOT)
    assert current["role"] == expected["role_conditions"], REVIEW_MESSAGE
    assert current["feature"] == expected["feature_conditions"], REVIEW_MESSAGE


def test_route_guard_detects_get_to_post_mutation_without_source_edit() -> None:
    path = ROOT / "routes" / "dashboard.py"
    original = path.read_text(encoding="utf-8")
    mutated = original.replace('@dashboard_bp.route("/")', '@dashboard_bp.route("/", methods=["POST"])', 1)
    with tempfile.TemporaryDirectory() as directory:
        temp_root = Path(directory)
        (temp_root / "routes").mkdir()
        (temp_root / "app.py").write_text("", encoding="utf-8")
        (temp_root / "routes" / "dashboard.py").write_text(mutated, encoding="utf-8")
        assert route_snapshot(temp_root) != load("ui_route_contract.json")["routes"]


def test_form_guard_detects_field_and_csrf_mutation_without_source_edit() -> None:
    from contracts.ui_contract_parser import _FormParser

    parser = _FormParser("synthetic.html")
    parser.feed('<form action="{{ url_for(\'auth.login\') }}" method="post"><input type="hidden" name="csrf_token"><input name="username"></form>')
    mutated = _FormParser("synthetic.html")
    mutated.feed('<form action="/changed" method="post"><input name="user_name"></form>')
    assert parser.forms != mutated.forms
    assert parser.forms[0]["fields"][0]["csrf"] is True


def test_hook_guard_detects_removed_data_hook_and_dynamic_prefix_mutation() -> None:
    source = "const row = document.querySelector('[data-stf-search]'); row.closest('.stf-toolbar');"
    mutated = source.replace("data-stf-search", "data-renamed-search").replace(".stf-toolbar", ".renamed-toolbar")
    with tempfile.TemporaryDirectory() as directory:
        temp_root = Path(directory)
        (temp_root / "static" / "js").mkdir(parents=True)
        (temp_root / "templates").mkdir()
        (temp_root / "static" / "js" / "app.js").write_text(source, encoding="utf-8")
        (temp_root / "templates" / "index.html").write_text(
            '<div data-stf-search class="stf-toolbar"></div>', encoding="utf-8"
        )
        original = canonical_hooks(temp_root)
        (temp_root / "static" / "js" / "app.js").write_text(mutated, encoding="utf-8")
        (temp_root / "templates" / "index.html").write_text(
            '<div data-renamed-search class="renamed-toolbar"></div>', encoding="utf-8"
        )
        changed = canonical_hooks(temp_root)
        assert original != changed
        assert any(item["expression"] == "data-stf-search" for item in original)
        assert not any(item["expression"] == "data-stf-search" for item in changed)
        assert any(item["expression"] == ".stf-toolbar" for item in original)
        assert not any(item["expression"] == ".stf-toolbar" for item in changed)


def test_role_and_feature_guards_detect_condition_mutation_without_source_edit() -> None:
    role = "{% if current_user.role == 'OWNER' %}owner{% endif %}"
    feature = "{% if config.PERMANENT_PURGE_UI_ENABLED %}purge{% endif %}"
    with tempfile.TemporaryDirectory() as directory:
        temp_root = Path(directory)
        (temp_root / "routes").mkdir()
        (temp_root / "templates").mkdir()
        (temp_root / "app.py").write_text("", encoding="utf-8")
        (temp_root / "templates" / "index.html").write_text(
            f"{role}{feature}", encoding="utf-8"
        )
        original = condition_snapshot(temp_root)
        (temp_root / "templates" / "index.html").write_text(
            f"{role.replace('OWNER', 'ADMIN')}{feature.replace('PERMANENT_PURGE_UI_ENABLED', 'OTHER_FLAG')}",
            encoding="utf-8",
        )
        changed = condition_snapshot(temp_root)
        assert original != changed
        assert any("OWNER" in item for item in original["role"])
        assert not any("OWNER" in item for item in changed["role"])
        assert any("PERMANENT_PURGE_UI_ENABLED" in item for item in original["feature"])
        assert not any("PERMANENT_PURGE_UI_ENABLED" in item for item in changed["feature"])


def test_baseline_generation_is_explicit_not_automatic() -> None:
    assert not (BASELINE / "regenerate.py").exists()
    assert REVIEW_MESSAGE in (BASELINE / "README.txt").read_text(encoding="utf-8")
