"""Migrate legacy purge retention evidence to immediate eligibility.

This revision is deliberately self-contained.  It does not import application
models, services, or mutable policy constants.
"""

import copy
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import inspect, text


revision = "0009_immediate_purge_eligibility"
down_revision = "0008_durable_purge_reauth_state"
branch_labels = None
depends_on = None
message = "Migrate legacy purge retention evidence to immediate eligibility"

REQUEST_TABLE = "workspace_purge_requests"
WORKSPACE_TABLE = "workspaces"
EVENT_TABLE = "purge_lifecycle_events"
TERMINAL_CLEAR = "purged_at IS NULL AND purge_request_id IS NULL"
OLD_POLICY = "workspace-purge-30d-v1"
NEW_POLICY = "workspace-purge-immediate-v1"
MIGRATION_EVENT = "retention_policy_migrated"
OLD_EVENT_TYPES = (
    "request_created", "retention_pending", "retention_reached",
    "pending_approval", "request_approved", "request_rejected",
    "request_cancelled", "blocked", "unblocked_rereviewed", "expired",
    "manifest_generated", "manifest_invalidated", "hold_clearance_checked",
    "legal_hold_placed", "legal_hold_released", "hold_clearance_invalidated",
    "execution_started", "retry_pending", "manual_reconciliation", "failed",
    "completed", "cancelled", "rejected",
)
EVENT_TYPES = OLD_EVENT_TYPES + (MIGRATION_EVENT,)
LEGACY_STATUSES = ("PENDING_RETENTION",)


def _utc_text(value):
    if not isinstance(value, datetime):
        raise ValueError("timestamp must be datetime")
    normalized = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return normalized.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _canonical_json(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=False)


def _sha256(text_value):
    if not isinstance(text_value, str):
        raise ValueError("canonical text must be string")
    return hashlib.sha256(text_value.encode("utf-8")).hexdigest()


def _parse_manifest(manifest_text, expected_hash):
    if not isinstance(manifest_text, str) or _sha256(manifest_text) != expected_hash:
        raise RuntimeError("0009 stored manifest hash mismatch.")
    try:
        payload = json.loads(manifest_text)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("0009 stored manifest is malformed.") from exc
    if not isinstance(payload, dict) or payload.get("manifest_version") != "purge-manifest-v1":
        raise RuntimeError("0009 stored manifest version mismatch.")
    if "request_id" in payload or not isinstance(payload.get("retention"), dict):
        raise RuntimeError("0009 stored manifest shape mismatch.")
    retention = payload["retention"]
    if not isinstance(retention.get("eligible_at"), str) or not isinstance(retention.get("policy_version"), str):
        raise RuntimeError("0009 stored retention evidence is incomplete.")
    return payload


def _transform_manifest(payload, eligible_at, policy_version):
    transformed = copy.deepcopy(payload)
    transformed["retention"]["eligible_at"] = _utc_text(eligible_at)
    transformed["retention"]["policy_version"] = policy_version
    canonical = _canonical_json(transformed)
    return canonical, _sha256(canonical)


def _migration_details(old_policy_version, new_policy_version, old_eligible_at, new_eligible_at, old_hash, new_hash):
    return _canonical_json({
        "revision": revision,
        "old_policy_version": old_policy_version,
        "new_policy_version": new_policy_version,
        "old_eligible_at": _utc_text(old_eligible_at),
        "new_eligible_at": _utc_text(new_eligible_at),
        "old_manifest_hash": old_hash,
        "new_manifest_hash": new_hash,
    })


def _is_postgresql(connection):
    return connection.dialect.name == "postgresql"


def _columns(connection, table_name):
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def _quoted_values(values):
    return ", ".join("'" + value.replace("'", "''") + "'" for value in values)


def _event_constraint_sql():
    return f"event_type IN ({_quoted_values(EVENT_TYPES)})"


def _old_event_constraint_sql():
    return f"event_type IN ({_quoted_values(OLD_EVENT_TYPES)})"


def _strip_outer_parentheses(value):
    value = value.strip()
    while value.startswith("(") and value.endswith(")"):
        depth = 0
        quoted = False
        closes_at_end = True
        index = 0
        while index < len(value):
            char = value[index]
            if char == "'":
                if quoted and index + 1 < len(value) and value[index + 1] == "'":
                    index += 2
                    continue
                quoted = not quoted
            elif not quoted and char == "(":
                depth += 1
            elif not quoted and char == ")":
                depth -= 1
                if depth == 0 and index != len(value) - 1:
                    closes_at_end = False
                    break
            index += 1
        if closes_at_end and depth == 0:
            value = value[1:-1].strip()
        else:
            break
    return value


def _parse_sql_string_list(value):
    values = []
    index = 0
    while index < len(value):
        while index < len(value) and value[index].isspace():
            index += 1
        parentheses = 0
        while index < len(value) and value[index] == "(":
            parentheses += 1
            index += 1
            while index < len(value) and value[index].isspace():
                index += 1
        if index >= len(value) or value[index] != "'":
            raise ValueError("constraint literal list is malformed")
        index += 1
        chars = []
        while index < len(value):
            if value[index] != "'":
                chars.append(value[index])
                index += 1
                continue
            if index + 1 < len(value) and value[index + 1] == "'":
                chars.append("'")
                index += 2
                continue
            index += 1
            break
        else:
            raise ValueError("constraint string literal is unterminated")
        values.append("".join(chars))
        while index < len(value) and value[index].isspace():
            index += 1
        if value[index:index + 2] == "::":
            index += 2
            while index < len(value) and value[index].isspace():
                index += 1
            cast = re.match(r"(?:text|character\s+varying)\b", value[index:], flags=re.IGNORECASE)
            if cast is None:
                raise ValueError("constraint literal has an unsupported cast")
            index += cast.end()
        while parentheses:
            while index < len(value) and value[index].isspace():
                index += 1
            if index >= len(value) or value[index] != ")":
                raise ValueError("constraint literal parentheses are malformed")
            index += 1
            parentheses -= 1
        if index >= len(value):
            return tuple(values)
        if value[index] != ",":
            raise ValueError("constraint literal list has unexpected content")
        index += 1
    raise ValueError("constraint literal list is empty")


def _event_type_literals(definition):
    if not isinstance(definition, str):
        raise ValueError("constraint definition must be text")
    normalized = " ".join(definition.strip().split())
    match = re.fullmatch(r"CHECK\s*(.*)", normalized, flags=re.IGNORECASE)
    if not match:
        raise ValueError("constraint definition is not a CHECK expression")
    body = _strip_outer_parentheses(match.group(1))
    body = re.sub(r"\(?EVENT_TYPE\)?\s*::\s*[A-Za-z ]+(?:\(\d+\))?", "event_type", body, flags=re.IGNORECASE)
    body = _strip_outer_parentheses(body)

    in_match = re.fullmatch(r"event_type\s+IN\s*\((.*)\)", body, flags=re.IGNORECASE)
    if in_match:
        return _parse_sql_string_list(in_match.group(1))

    any_match = re.fullmatch(
        r"event_type\s*=\s*ANY\s*\(\s*ARRAY\s*\[(.*)\]\s*::[A-Za-z ]+(?:\[\])?\s*\)",
        body,
        flags=re.IGNORECASE,
    )
    if any_match:
        return _parse_sql_string_list(any_match.group(1))
    raise ValueError("constraint definition is unrelated or unsupported")


def _postgres_event_constraint(connection):
    if not _is_postgresql(connection):
        raise RuntimeError("0009 requires PostgreSQL for lifecycle constraint replacement.")
    rows = connection.execute(text(
        "SELECT c.contype, pg_get_constraintdef(c.oid, true) "
        "FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
        "JOIN pg_namespace n ON n.oid = t.relnamespace "
        "WHERE n.nspname = CURRENT_SCHEMA() AND t.relname = :table_name "
        "AND c.conname = :constraint_name"
    ), {"table_name": EVENT_TABLE, "constraint_name": "ck_purge_lifecycle_events_event_type"}).fetchall()
    if len(rows) != 1 or rows[0][0] != "c":
        raise RuntimeError("0009 lifecycle event CHECK constraint is missing, duplicated or wrongly typed.")
    try:
        literals = _event_type_literals(rows[0][1])
    except ValueError as exc:
        raise RuntimeError("0009 lifecycle event CHECK constraint definition is malformed.") from exc
    if len(literals) != len(set(literals)):
        raise RuntimeError("0009 lifecycle event CHECK constraint contains duplicate values.")
    return literals


def _assert_postgres_event_constraint(connection, expected, phase):
    actual = _postgres_event_constraint(connection)
    if set(actual) != set(expected) or len(actual) != len(expected):
        raise RuntimeError(f"0009 {phase} lifecycle event CHECK constraint literal set mismatch.")


def _replace_event_constraint(connection, expression):
    connection.execute(text("ALTER TABLE purge_lifecycle_events DROP CONSTRAINT ck_purge_lifecycle_events_event_type"))
    connection.execute(text(
        "ALTER TABLE purge_lifecycle_events ADD CONSTRAINT "
        f"ck_purge_lifecycle_events_event_type CHECK ({expression})"
    ))


def _candidate_rows(connection):
    lock = " FOR UPDATE" if _is_postgresql(connection) else ""
    return connection.execute(text(
        "SELECT r.id, r.lifecycle_id, r.workspace_id, r.status, r.target_deleted_at, "
        "r.target_deleted_by_id, r.eligible_at, r.retention_policy_version, "
        "r.manifest_canonical_text, r.manifest_hash, r.invalidated_at, "
        "r.invalidated_by_restore, r.outcome_unknown, w.deleted_at, w.deleted_by_id, "
        "w.purged_at, w.purge_request_id "
        "FROM workspace_purge_requests r JOIN workspaces w ON w.id = r.workspace_id "
        "WHERE r.status = 'PENDING_RETENTION' ORDER BY r.id" + lock
    )).mappings().all()


def _historical_evidence(connection, row):
    return connection.execute(text(
        "SELECT "
        "(SELECT COUNT(*) FROM purge_lifecycle_events e WHERE e.request_id = :request_id "
        "AND e.event_type = :restore_event) AS restore_event_count, "
        "(SELECT COUNT(*) FROM purge_lifecycle_events e WHERE e.request_id = :request_id "
        "AND e.event_type = :restore_event AND e.lifecycle_id_snapshot = :lifecycle_id "
        "AND e.workspace_id = :workspace_id AND e.status_before = :status "
        "AND e.status_after = :status AND e.actor_id IS NOT NULL AND e.actor_snapshot IS NOT NULL "
        "AND e.reason_code = :reason_code AND e.sanitized_summary = :summary) AS restore_exact_count, "
        "(SELECT COUNT(*) FROM purge_lifecycle_events e JOIN purge_lifecycle_events later "
        "ON later.request_id = e.request_id AND later.event_sequence > e.event_sequence "
        "WHERE e.request_id = :request_id AND e.event_type = :restore_event) AS later_event_count, "
        "(SELECT COUNT(*) FROM purge_lifecycle_events e WHERE e.request_id = :request_id "
        "AND e.event_type = :migration_event) AS migration_event_count"
    ), {
        "request_id": row["id"], "restore_event": "manifest_invalidated",
        "lifecycle_id": row["lifecycle_id"], "workspace_id": row["workspace_id"],
        "status": row["status"], "reason_code": "MANIFEST_INVALIDATED",
        "summary": "Workspace restored; prior deletion lifecycle is invalidated.",
        "migration_event": MIGRATION_EVENT,
    }).mappings().one()


def _is_exact_historical_restore_invalidated(row, evidence):
    return (
        row["status"] == "PENDING_RETENTION"
        and row["retention_policy_version"] == OLD_POLICY
        and row["invalidated_at"] is not None
        and row["invalidated_by_restore"] is True
        and row["outcome_unknown"] is False
        and evidence["restore_event_count"] == 1
        and evidence["restore_exact_count"] == 1
        and evidence["later_event_count"] == 0
        and evidence["migration_event_count"] == 0
    )


def _is_currently_restored(row):
    return (
        row["deleted_at"] is None
        and row["deleted_by_id"] is None
        and row["purged_at"] is None
        and row["purge_request_id"] is None
    )


def _request_created_evidence(connection, request_id):
    return connection.execute(text(
        "SELECT COUNT(*) AS event_count, MIN(event_at) AS event_at "
        "FROM purge_lifecycle_events WHERE request_id = :request_id "
        "AND event_type = :event_type"
    ), {"request_id": request_id, "event_type": "request_created"}).mappings().one()


def _is_matching_successor(connection, historical, successor):
    if (
        successor["id"] == historical["id"]
        or successor["workspace_id"] != historical["workspace_id"]
        or successor["lifecycle_id"] == historical["lifecycle_id"]
        or successor["target_deleted_at"] != historical["deleted_at"]
        or successor["target_deleted_by_id"] != historical["deleted_by_id"]
        or historical["deleted_at"] is None
        or historical["deleted_at"] <= historical["invalidated_at"]
    ):
        return False
    created = _request_created_evidence(connection, successor["id"])
    return (
        created["event_count"] == 1
        and created["event_at"] is not None
        and created["event_at"] > historical["invalidated_at"]
    )


def _classify_candidates(connection, rows):
    parsed = []
    historical = []
    for row in rows:
        marker_pair = row["invalidated_at"] is not None or row["invalidated_by_restore"]
        if not marker_pair:
            parsed.append((row, _validate_candidate(row, connection)))
            continue
        evidence = _historical_evidence(connection, row)
        if not _is_exact_historical_restore_invalidated(row, evidence):
            raise RuntimeError("0009 historical request has malformed lifecycle evidence.")
        if _is_currently_restored(row):
            historical.append(row)
            continue
        if row["deleted_at"] is None or row["purged_at"] is not None or row["purge_request_id"] is not None or row["deleted_at"] <= row["invalidated_at"]:
            raise RuntimeError("0009 historical request has unsafe current workspace state.")
        matching = [candidate for candidate in rows if _is_matching_successor(connection, row, candidate)]
        if len(matching) != 1:
            raise RuntimeError("0009 historical re-delete successor is missing or ambiguous.")
        successor = matching[0]
        try:
            _validate_candidate(successor, connection)
        except RuntimeError as error:
            raise RuntimeError("0009 historical re-delete successor is unsafe.") from error
        historical.append(row)
    selected_ids = {row["id"] for row, _payload in parsed}
    if any(row["id"] in selected_ids for row in historical):
        raise RuntimeError("0009 candidate classification is not disjoint.")
    if len(selected_ids) + len(historical) != len(rows):
        raise RuntimeError("0009 candidate classification does not reconcile.")
    return parsed, historical


def _validate_candidate(row, connection):
    if row["deleted_at"] is None or row["purged_at"] is not None or row["purge_request_id"] is not None:
        raise RuntimeError("0009 candidate workspace is not safely soft-deleted.")
    if row["invalidated_at"] is not None or row["invalidated_by_restore"] or row["outcome_unknown"]:
        raise RuntimeError("0009 candidate request has unsafe lifecycle markers.")
    if row["retention_policy_version"] != OLD_POLICY:
        raise RuntimeError("0009 candidate policy version mismatch.")
    expected_legacy = row["deleted_at"] + timedelta(days=30)
    if row["eligible_at"] != expected_legacy:
        raise RuntimeError("0009 candidate eligible_at is not the recognized legacy value.")
    payload = _parse_manifest(row["manifest_canonical_text"], row["manifest_hash"])
    if payload.get("lifecycle_id") != row["lifecycle_id"] or payload.get("workspace_id") != row["workspace_id"]:
        raise RuntimeError("0009 candidate manifest identity mismatch.")
    if payload.get("target_deleted_at") != _utc_text(row["target_deleted_at"]):
        raise RuntimeError("0009 candidate target deletion mismatch.")
    if payload.get("target_deleted_by_id") != row["target_deleted_by_id"]:
        raise RuntimeError("0009 candidate deletion actor mismatch.")
    retention = payload["retention"]
    if retention.get("policy_version") != OLD_POLICY or retention.get("eligible_at") != _utc_text(row["eligible_at"]):
        raise RuntimeError("0009 candidate manifest retention mismatch.")
    event = connection.execute(text(
        "SELECT id FROM purge_lifecycle_events "
        "WHERE request_id = :request_id AND event_type = :event_type"
    ), {"request_id": row["id"], "event_type": MIGRATION_EVENT}).first()
    if event is not None:
        raise RuntimeError("0009 candidate is already migrated.")
    return payload


def _insert_event(connection, row, old_hash, new_hash, new_eligible_at, sequence):
    details = _migration_details(
        OLD_POLICY, NEW_POLICY, row["eligible_at"], new_eligible_at, old_hash, new_hash
    )
    connection.execute(text(
        "INSERT INTO purge_lifecycle_events "
        "(request_id, lifecycle_id_snapshot, workspace_id, workspace_name_snapshot, "
        "event_sequence, event_type, actor_id, actor_snapshot, event_at, "
        "status_before, status_after, reason_code, sanitized_summary, "
        "metadata_canonical_text, metadata_hash, created_at) "
        "SELECT :request_id, r.lifecycle_id, r.workspace_id, w.name, :sequence, "
        ":event_type, NULL, 'SYSTEM', CURRENT_TIMESTAMP, 'PENDING_RETENTION', "
        "'PENDING_RETENTION', :reason_code, :summary, :details, :details_hash, "
        "CURRENT_TIMESTAMP FROM workspace_purge_requests r JOIN workspaces w "
        "ON w.id = r.workspace_id WHERE r.id = :request_id"
    ), {
        "request_id": row["id"], "sequence": sequence, "event_type": MIGRATION_EVENT,
        "reason_code": MIGRATION_EVENT.upper(),
        "summary": "Retention policy migrated by revision 0009; request status unchanged.",
        "details": details, "details_hash": _sha256(details),
    })


def _replace_request(connection, row, payload):
    new_eligible_at = row["deleted_at"]
    new_text, new_hash = _transform_manifest(payload, new_eligible_at, NEW_POLICY)
    old_sequence = connection.execute(text(
        "SELECT COALESCE(MAX(event_sequence), 0) FROM purge_lifecycle_events "
        "WHERE request_id = :request_id"
    ), {"request_id": row["id"]}).scalar_one()
    connection.execute(text(
        "UPDATE workspace_purge_requests SET eligible_at = :eligible_at, "
        "retention_policy_version = :policy_version, manifest_canonical_text = :manifest_text, "
        "manifest_hash = :manifest_hash, updated_at = CURRENT_TIMESTAMP WHERE id = :request_id"
    ), {
        "eligible_at": new_eligible_at, "policy_version": NEW_POLICY,
        "manifest_text": new_text, "manifest_hash": new_hash, "request_id": row["id"],
    })
    _insert_event(connection, row, row["manifest_hash"], new_hash, new_eligible_at, old_sequence + 1)


def _verify_upgrade(connection, selected_ids):
    for request_id in selected_ids:
        row = connection.execute(text(
            "SELECT r.status, r.eligible_at, r.retention_policy_version, "
            "r.manifest_canonical_text, r.manifest_hash, w.deleted_at "
            "FROM workspace_purge_requests r JOIN workspaces w ON w.id = r.workspace_id "
            "WHERE r.id = :request_id"
        ), {"request_id": request_id}).mappings().one()
        if row["status"] != "PENDING_RETENTION" or row["eligible_at"] != row["deleted_at"] or row["retention_policy_version"] != NEW_POLICY:
            raise RuntimeError("0009 post-upgrade request verification failed.")
        payload = _parse_manifest(row["manifest_canonical_text"], row["manifest_hash"])
        if payload["retention"] != {"eligible_at": _utc_text(row["deleted_at"]), "policy_version": NEW_POLICY}:
            raise RuntimeError("0009 post-upgrade manifest verification failed.")
        count = connection.execute(text(
            "SELECT COUNT(*) FROM purge_lifecycle_events WHERE request_id = :request_id "
            "AND event_type = :event_type AND actor_id IS NULL AND actor_snapshot = 'SYSTEM'"
        ), {"request_id": request_id, "event_type": MIGRATION_EVENT}).scalar_one()
        if count != 1:
            raise RuntimeError("0009 provenance event verification failed.")


def _verify_historical_unchanged(connection, snapshots):
    for request_id, snapshot in snapshots.items():
        row = connection.execute(text(
            "SELECT eligible_at, retention_policy_version, manifest_canonical_text, manifest_hash, "
            "invalidated_at, invalidated_by_restore, outcome_unknown "
            "FROM workspace_purge_requests WHERE id = :request_id"
        ), {"request_id": request_id}).mappings().one()
        if tuple(row[key] for key in snapshot) != tuple(snapshot.values()):
            raise RuntimeError("0009 historical request changed during migration.")
        event_count = connection.execute(text(
            "SELECT COUNT(*) FROM purge_lifecycle_events WHERE request_id = :request_id "
            "AND event_type = :event_type"
        ), {"request_id": request_id, "event_type": MIGRATION_EVENT}).scalar_one()
        if event_count != 0:
            raise RuntimeError("0009 historical request received migration provenance.")


def _reversible_events(connection):
    return connection.execute(text(
        "SELECT e.id AS event_id, e.request_id, e.event_sequence, "
        "r.status, r.eligible_at, r.retention_policy_version, r.manifest_canonical_text, "
        "r.manifest_hash, r.invalidated_at, r.invalidated_by_restore, r.outcome_unknown, "
        "w.deleted_at, w.purged_at, w.purge_request_id, e.metadata_canonical_text, "
        "e.metadata_hash, e.actor_id, e.actor_snapshot "
        "FROM purge_lifecycle_events e JOIN workspace_purge_requests r ON r.id = e.request_id "
        "JOIN workspaces w ON w.id = r.workspace_id WHERE e.event_type = :event_type "
        "ORDER BY e.request_id"
    ), {"event_type": MIGRATION_EVENT}).mappings().all()


def _validate_reversible_event(connection, row):
    if row["status"] != "PENDING_RETENTION" or row["eligible_at"] != row["deleted_at"]:
        raise RuntimeError("0009 downgrade found progressed request.")
    if row["retention_policy_version"] != NEW_POLICY or row["deleted_at"] is None or row["purged_at"] is not None or row["purge_request_id"] is not None:
        raise RuntimeError("0009 downgrade found unsafe workspace/request state.")
    if row["invalidated_at"] is not None or row["invalidated_by_restore"] or row["outcome_unknown"]:
        raise RuntimeError("0009 downgrade found invalidated request.")
    if row["actor_id"] is not None or row["actor_snapshot"] != "SYSTEM":
        raise RuntimeError("0009 downgrade provenance actor mismatch.")
    payload = _parse_manifest(row["manifest_canonical_text"], row["manifest_hash"])
    if payload["retention"] != {"eligible_at": _utc_text(row["eligible_at"]), "policy_version": NEW_POLICY}:
        raise RuntimeError("0009 downgrade manifest mismatch.")
    details = json.loads(row["metadata_canonical_text"])
    if set(details) != {"revision", "old_policy_version", "new_policy_version", "old_eligible_at", "new_eligible_at", "old_manifest_hash", "new_manifest_hash"} or _sha256(row["metadata_canonical_text"]) != row["metadata_hash"]:
        raise RuntimeError("0009 downgrade event details mismatch.")


def _restore_request(connection, row):
    old_eligible_at = row["deleted_at"] + timedelta(days=30)
    payload = _parse_manifest(row["manifest_canonical_text"], row["manifest_hash"])
    new_text, new_hash = _transform_manifest(payload, old_eligible_at, OLD_POLICY)
    connection.execute(text(
        "UPDATE workspace_purge_requests SET eligible_at = :eligible_at, "
        "retention_policy_version = :policy_version, manifest_canonical_text = :manifest_text, "
        "manifest_hash = :manifest_hash, updated_at = CURRENT_TIMESTAMP WHERE id = :request_id"
    ), {
        "eligible_at": old_eligible_at, "policy_version": OLD_POLICY,
        "manifest_text": new_text, "manifest_hash": new_hash, "request_id": row["request_id"],
    })
    connection.execute(text(
        "DELETE FROM purge_lifecycle_events WHERE id = :event_id AND request_id = :request_id "
        "AND event_type = :event_type"
    ), {"event_id": row["event_id"], "request_id": row["request_id"], "event_type": MIGRATION_EVENT})


def upgrade():
    from extensions import db

    if db.engine.dialect.name != "postgresql":
        raise RuntimeError("0009 requires PostgreSQL; refusing non-PostgreSQL migration execution.")
    with db.engine.begin() as connection:
        required = {
            REQUEST_TABLE: {"id", "lifecycle_id", "workspace_id", "status", "target_deleted_at", "target_deleted_by_id", "eligible_at", "retention_policy_version", "manifest_canonical_text", "manifest_hash", "invalidated_at", "invalidated_by_restore", "outcome_unknown"},
            WORKSPACE_TABLE: {"id", "name", "deleted_at", "deleted_by_id", "purged_at", "purge_request_id"},
            EVENT_TABLE: {"id", "request_id", "lifecycle_id_snapshot", "workspace_id", "event_sequence", "event_type", "event_at", "actor_id", "actor_snapshot", "status_before", "status_after", "reason_code", "sanitized_summary", "metadata_canonical_text", "metadata_hash"},
        }
        for table_name, columns in required.items():
            if not inspect(connection).has_table(table_name) or not columns.issubset(_columns(connection, table_name)):
                raise RuntimeError(f"0009 required schema missing: {table_name}.")
        rows = _candidate_rows(connection)
        parsed, historical = _classify_candidates(connection, rows)
        historical_snapshots = {
            row["id"]: {
                "eligible_at": row["eligible_at"],
                "retention_policy_version": row["retention_policy_version"],
                "manifest_canonical_text": row["manifest_canonical_text"],
                "manifest_hash": row["manifest_hash"],
                "invalidated_at": row["invalidated_at"],
                "invalidated_by_restore": row["invalidated_by_restore"],
                "outcome_unknown": row["outcome_unknown"],
            }
            for row in historical
        }
        _assert_postgres_event_constraint(connection, OLD_EVENT_TYPES, "pre-drop")
        _replace_event_constraint(connection, _event_constraint_sql())
        _assert_postgres_event_constraint(connection, EVENT_TYPES, "post-create")
        selected_ids = []
        for row, payload in parsed:
            _replace_request(connection, row, payload)
            selected_ids.append(row["id"])
        _verify_upgrade(connection, selected_ids)
        _verify_historical_unchanged(connection, historical_snapshots)


def downgrade():
    from extensions import db

    if db.engine.dialect.name != "postgresql":
        raise RuntimeError("0009 requires PostgreSQL; refusing non-PostgreSQL migration execution.")
    with db.engine.begin() as connection:
        rows = _reversible_events(connection)
        for row in rows:
            _validate_reversible_event(connection, row)
        for row in rows:
            _restore_request(connection, row)
        _assert_postgres_event_constraint(connection, EVENT_TYPES, "downgrade pre-drop")
        _replace_event_constraint(connection, _old_event_constraint_sql())
        _assert_postgres_event_constraint(connection, OLD_EVENT_TYPES, "downgrade post-create")
