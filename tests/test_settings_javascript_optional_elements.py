import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SETTING_JS = REPO_ROOT / "static" / "js" / "setting.js"
SETTING_TEMPLATE = REPO_ROOT / "templates" / "setting" / "index.html"

OPTIONAL_LISTENERS = {
    "wizardBtnContinue1": ("wizard-btn-continue-1", "click"),
    "wizardBtnContinue2": ("wizard-btn-continue-2", "click"),
    "wizardBtnConfirm": ("wizard-btn-confirm", "click"),
    "restoreWizardModalEl": ("restoreWizardModal", "hide.bs.modal"),
}


def _sources():
    return (
        SETTING_JS.read_text(encoding="utf-8"),
        SETTING_TEMPLATE.read_text(encoding="utf-8"),
    )


def _postgresql_excluded_restore_branch(template):
    match = re.search(
        r"\{%\s*if\s+backup_engine\s*!=\s*'postgresql'\s*%\}(.*?)"
        r"\{%\s*endif\s*%\}",
        template,
        flags=re.DOTALL,
    )
    assert match is not None
    return match.group(1)


def test_postgresql_settings_branch_omits_all_optional_restore_elements():
    _, template = _sources()
    branch = _postgresql_excluded_restore_branch(template)

    for element_id, _ in OPTIONAL_LISTENERS.values():
        assert branch.count(f'id="{element_id}"') == 1


def test_supported_restore_branch_preserves_all_optional_restore_elements():
    _, template = _sources()
    branch = _postgresql_excluded_restore_branch(template)

    assert branch.count('id="restoreWizardModal"') == 1
    assert branch.count('id="wizard-btn-continue-1"') == 1
    assert branch.count('id="wizard-btn-continue-2"') == 1
    assert branch.count('id="wizard-btn-confirm"') == 1


def test_each_optional_restore_listener_has_a_direct_existence_guard():
    javascript, _ = _sources()

    for variable, (_, event_name) in OPTIONAL_LISTENERS.items():
        listener = re.escape(f"{variable}.addEventListener('{event_name}'")
        assert re.search(
            rf"if\s*\(\s*{re.escape(variable)}\s*\)\s*\{{\s*{listener}",
            javascript,
            flags=re.DOTALL,
        ), variable


def test_each_optional_restore_listener_event_contract_remains_present_once():
    javascript, _ = _sources()

    for variable, (_, event_name) in OPTIONAL_LISTENERS.items():
        assert javascript.count(
            f"{variable}.addEventListener('{event_name}'"
        ) == 1
