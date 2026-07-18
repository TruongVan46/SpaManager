"""Deterministic, read-only parser for the Version 7 frontend contract."""

from __future__ import annotations

import ast
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


ROUTE_FILES = ("app.py", "routes")
ROLE_RE = re.compile(
    r"OWNER|ADMIN|STAFF|APPROVAL_OWNER|current_user|workspace.*role|membership|"
    r"approval_status|deleted",
    re.I,
)
FEATURE_RE = re.compile(
    r"feature|purge.*enabled|execution.*enabled|backup|legal.?hold",
    re.I,
)


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def source_files(root: Path) -> list[Path]:
    return sorted(
        [root / "app.py", *sorted((root / "routes").glob("*.py"))],
        key=lambda path: path.as_posix(),
    )


def relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def route_snapshot(root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in source_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                function = decorator.func
                if not isinstance(function, ast.Attribute) or function.attr != "route":
                    continue
                path_value = literal_string(decorator.args[0]) if decorator.args else None
                if path_value is None:
                    raise AssertionError(f"Non-literal route path: {relative(root, path)}:{node.lineno}")
                methods_node = next(
                    (keyword.value for keyword in decorator.keywords if keyword.arg == "methods"),
                    None,
                )
                methods = (
                    sorted(
                        value
                        for element in getattr(methods_node, "elts", [])
                        if (value := literal_string(element)) is not None
                    )
                    if methods_node is not None
                    else ["GET"]
                )
                params = re.findall(r"<[^>]+>", path_value)
                result.append(
                    {
                        "source": relative(root, path),
                        "function": node.name,
                        "path": path_value,
                        "methods": methods,
                        "parameters": params,
                        "blueprint": getattr(function.value, "id", "app"),
                        "line": node.lineno,
                    }
                )
    return sorted(result, key=lambda item: (item["path"], item["methods"], item["source"], item["function"]))


def rendered_templates(root: Path) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    pattern = re.compile(r"render_template\s*\(\s*([^,\)]+)")
    for path in source_files(root):
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            expression = normalize(match.group(1))
            literal = re.fullmatch(r"['\"]([^'\"]+)['\"]", expression)
            result.append(
                {
                    "source": relative(root, path),
                    "line": str(text[: match.start()].count("\n") + 1),
                    "template": literal.group(1) if literal else f"DYNAMIC:{expression}",
                }
            )
    return sorted(result, key=lambda item: (item["source"], int(item["line"]), item["template"]))


class _FormParser(HTMLParser):
    def __init__(self, template: str):
        super().__init__(convert_charrefs=False)
        self.template = template
        self.forms: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None

    @staticmethod
    def attrs_dict(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {key: normalize(value or "") for key, value in attrs if key}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = self.attrs_dict(attrs)
        if tag.lower() == "form":
            self.current = {
                "template": self.template,
                "action": attributes.get("action", ""),
                "method": attributes.get("method", "GET").upper(),
                "id": attributes.get("id", ""),
                "fields": [],
            }
            self.forms.append(self.current)
        elif self.current is not None and tag.lower() in {"input", "select", "textarea", "button"}:
            if tag.lower() == "button":
                kind = attributes.get("type", "submit").lower()
            else:
                kind = attributes.get("type", tag.lower()).lower()
            if kind in {"submit", "button"} or tag.lower() != "button":
                self.current["fields"].append(
                    {
                        "tag": tag.lower(),
                        "type": kind,
                        "name": attributes.get("name", ""),
                        "value": attributes.get("value", ""),
                        "id": attributes.get("id", ""),
                        "hidden": kind == "hidden",
                        "csrf": attributes.get("name") == "csrf_token",
                    }
                )

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "form":
            self.current = None


def form_snapshot(root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in sorted((root / "templates").rglob("*.html")):
        parser = _FormParser(relative(root, path))
        parser.feed(path.read_text(encoding="utf-8"))
        for index, form in enumerate(parser.forms):
            form["index"] = index
            result.append(form)
    return sorted(result, key=lambda item: (item["template"], item["index"]))


def canonical_hooks(root: Path) -> list[dict[str, Any]]:
    records: dict[tuple[str, str], dict[str, Any]] = {}
    scripts = sorted((root / "static" / "js").rglob("*.js"))
    templates = sorted((root / "templates").rglob("*.html"))
    markup = "\n".join(path.read_text(encoding="utf-8") for path in templates)

    def add(expression: str, hook_type: str, path: Path, line: int, purpose: str) -> None:
        records.setdefault(
            (hook_type, expression),
            {
                "expression": expression,
                "type": hook_type,
                "source": f"{relative(root, path)}:{line}",
                "purpose": purpose,
                "classification": "FROZEN_JS_HOOK",
            },
        )

    for path in scripts:
        text = path.read_text(encoding="utf-8")
        line_of = lambda position: text[:position].count("\n") + 1
        for match in re.finditer(r"getElementById\(\s*['\"]([^'\"]+)", text):
            add("#" + match.group(1), "ID", path, line_of(match.start()), "direct element lookup")
        for match in re.finditer(r"(?:document|\w+)\.querySelector(All)?\(\s*['\"]([^'\"]+)", text):
            selector = match.group(2)
            kind = "FORM_SELECTOR" if "form" in selector or "[name=" in selector else (
                "ID" if selector.startswith("#") else "CLASS" if selector.startswith(".") else "DYNAMIC_SELECTOR"
            )
            add(selector, kind, path, line_of(match.start()), "static DOM query")
        for match in re.finditer(r"\.closest\(\s*['\"]([^'\"]+)", text):
            selector = match.group(1)
            add(selector, "FORM_SELECTOR" if "form" in selector else "CLASS" if selector.startswith(".") else "DYNAMIC_SELECTOR", path, line_of(match.start()), "delegated ancestor lookup")
        for match in re.finditer(r"\.matches\(\s*['\"]([^'\"]+)", text):
            add(match.group(1), "CLASS" if match.group(1).startswith(".") else "DYNAMIC_SELECTOR", path, line_of(match.start()), "event target matching")
        for match in re.finditer(r"getElementsByClassName\(\s*['\"]([^'\"]+)", text):
            add("." + match.group(1), "CLASS", path, line_of(match.start()), "class collection lookup")
        for match in re.finditer(r"getElementsByName\(\s*['\"]([^'\"]+)", text):
            add("[name=" + match.group(1) + "]", "NAME_ATTRIBUTE", path, line_of(match.start()), "named form control lookup")
        for match in re.finditer(r"getAttribute\(\s*['\"](data-[\w-]+)", text):
            add(match.group(1), "DATA_ATTRIBUTE", path, line_of(match.start()), "data contract read")
        for match in re.finditer(r"dataset\.([A-Za-z_][\w]*)", text):
            data_name = re.sub(r"([A-Z])", lambda item: "-" + item.group(1).lower(), match.group(1))
            add("data-" + data_name, "DATA_ATTRIBUTE", path, line_of(match.start()), "dataset contract read")
        for match in re.finditer(r"document\.addEventListener\(\s*['\"]([^'\"]+)", text):
            add("document:" + match.group(1), "EVENT_DELEGATION_ROOT", path, line_of(match.start()), "document event delegation")

    for data_name in sorted(set(re.findall(r"\bdata-[\w-]+", markup + "\n" + "\n".join(path.read_text(encoding="utf-8") for path in scripts)))):
        records.setdefault(
            ("DATA_ATTRIBUTE", data_name),
            {
                "expression": data_name,
                "type": "DATA_ATTRIBUTE",
                "source": "MARKUP_ONLY",
                "purpose": "data attribute retained for contract review",
                "classification": "UNRESOLVED_HIGH_RISK",
            },
        )

    # These two selectors are assembled from a runtime backup identifier in
    # setting.js.  They are deliberately recorded as construction rules,
    # rather than expanded values, so redesigns cannot silently remove them.
    for expression in (
        '.btn-delete-backup[data-id="${activeBackupId}"]',
        '.btn-edit-backup-note[data-id="${activeBackupId}"]',
    ):
        records.setdefault(
            ("DYNAMIC_SELECTOR", expression),
            {
                "expression": expression,
                "type": "DYNAMIC_SELECTOR",
                "source": "static/js/setting.js:runtime-construction",
                "purpose": "dynamic selector construction rule",
                "classification": "DYNAMIC_RUNTIME_HOOK",
            },
        )

    result = []
    for item in records.values():
        if item["type"] == "DYNAMIC_SELECTOR":
            item["classification"] = "DYNAMIC_RUNTIME_HOOK"
        result.append(item)
    return sorted(result, key=lambda item: (item["type"], item["expression"], item["source"]))


def condition_snapshot(root: Path) -> dict[str, list[str]]:
    role: list[str] = []
    feature: list[str] = []
    paths = [*sorted((root / "templates").rglob("*.html")), *source_files(root)]
    for path in paths:
        for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = normalize(raw_line)
            if ROLE_RE.search(line):
                role.append(f"{relative(root, path)}:{number}:{line}")
            if FEATURE_RE.search(line):
                feature.append(f"{relative(root, path)}:{number}:{line}")
    return {"role": sorted(set(role)), "feature": sorted(set(feature))}


def snapshot(root: Path) -> dict[str, Any]:
    conditions = condition_snapshot(root)
    return {
        "routes": route_snapshot(root),
        "rendered_templates": rendered_templates(root),
        "forms": form_snapshot(root),
        "hooks": canonical_hooks(root),
        "role_conditions": conditions["role"],
        "feature_conditions": conditions["feature"],
        # The audit's classified counts are retained as evidence metadata;
        # the executable guards intentionally protect the complete static
        # superset extracted from source.
        "verified_audit_counts": {
            "frontend_route_contracts": 65,
            "form_boundaries": 79,
            "form_field_contracts": 80,
            "canonical_behavior_hooks": 304,
            "traceable_canonical_hooks": 266,
            "dynamic_runtime_hook_groups": 31,
            "unresolved_high_risk_hooks": 38,
        },
    }


def write_baselines(root: Path, destination: Path) -> None:
    data = snapshot(root)
    destination.mkdir(parents=True, exist_ok=True)
    files = {
        "ui_route_contract.json": {
            "routes": data["routes"],
            "rendered_templates": data["rendered_templates"],
            "verified_audit_counts": data["verified_audit_counts"],
        },
        "ui_form_contract.json": {"forms": data["forms"]},
        "ui_behavior_hook_contract.json": {"hooks": data["hooks"]},
        "ui_role_feature_contract.json": {"role_conditions": data["role_conditions"], "feature_conditions": data["feature_conditions"]},
    }
    for name, value in files.items():
        (destination / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
