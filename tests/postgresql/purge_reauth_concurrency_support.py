"""Static-safe support primitives for the PostgreSQL d3e concurrency rehearsal.

This module deliberately has no application, engine, session, Docker, or
database imports at module import time. Database-backed workers are opened
only after the strict rehearsal guard passes.
"""

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field
import os
import re
import secrets
import threading
from types import SimpleNamespace
from typing import Iterable, Mapping

from tests.postgresql.rehearsal_guard import (
    REHEARSAL_DATABASE_NAME,
    REHEARSAL_OPT_IN_ENV,
    RehearsalGuardError,
    RehearsalTarget,
    validate_rehearsal_environment,
)


MIGRATION_METADATA_TABLE = "alembic_version"
EXPECTED_REVISION = "0008_durable_purge_reauth_state"

CLEANUP_KIND_ORDER = (
    "authorization", "throttle", "lifecycle_event", "legal_hold", "activity_log",
    "invoice_detail", "appointment", "invoice", "workspace_member", "customer",
    "service", "setting", "purge_request", "workspace", "user",
)

HARNESS_CLEANUP_REQUIRED = "HARNESS_CLEANUP_REQUIRED"
SERVICE_DELETION_EXPECTED = "SERVICE_DELETION_EXPECTED"
SERVICE_PRESERVATION_REQUIRED = "SERVICE_PRESERVATION_REQUIRED"
NEVER_CREATED_PLANNED_ONLY = "NEVER_CREATED_PLANNED_ONLY"
SERVICE_DELETION_KINDS = frozenset({
    "invoice_detail", "appointment", "invoice", "customer", "service", "setting",
    "workspace_member",
})


@dataclass(frozen=True, slots=True)
class ScenarioPlan:
    name: str
    rounds: int
    workers: int
    synchronization: str
    isolation: str
    acceptable_outcomes: tuple[str, ...]
    forbidden_outcomes: tuple[str, ...]
    execution_mode: str = "AUTHORIZATION_ONLY"

    @property
    def service_deletion_expected(self):
        return self.execution_mode == "PURGE_SERVICE"


@dataclass(frozen=True, slots=True, repr=False)
class SyntheticCase:
    request_id: int
    workspace_id: int
    requester_id: int
    approver_id: int
    executor_ids: tuple[int, ...]
    passwords: tuple[str, ...]
    executor_usernames: tuple[str, ...]
    slug: str

    def __repr__(self):
        return (
            "SyntheticCase(request_id={!r}, workspace_id={!r}, "
            "executor_ids={!r}, slug={!r})"
        ).format(self.request_id, self.workspace_id, self.executor_ids, self.slug)


SCENARIO_PLANS = {
    "A": ScenarioPlan(
        "A", 10, 2, "threading.Barrier", "independent engine/session per worker",
        ("consecutive generations", "latest generation remains claimable"),
        ("lost generation", "duplicate current authorization"),
    ),
    "B": ScenarioPlan(
        "B", 5, 5, "threading.Barrier", "independent engine/session per worker",
        ("five generic failures", "one actor-global lockout"),
        ("lost throttle update", "unaffected actor locked out"),
    ),
    "C": ScenarioPlan(
        "C", 20, 2, "threading.Barrier", "independent engine/session per worker",
        ("one claim winner", "one stable fail-closed loser"),
        ("double claim", "nonce resurrection"),
    ),
    "D": ScenarioPlan(
        "D", 5, 2, "threading.Barrier", "independent app context and service session per worker",
        ("one public purge success", "one claim/replay failure"),
        ("private-core bypass", "double destructive execution"),
        execution_mode="PURGE_SERVICE",
    ),
    "E": ScenarioPlan(
        "E", 5, 2, "threading.Barrier", "two independent Flask clients and sessions",
        ("one copied-cookie winner", "one fail-closed loser"),
        ("shared client object", "double execution", "cookie disclosure"),
        execution_mode="PURGE_SERVICE",
    ),
    "F": ScenarioPlan(
        "F", 10, 2, "threading.Barrier", "independent engine/session per worker",
        ("claim wins", "issuance wins"),
        ("both generations valid", "nonce resurrection", "lost generation"),
    ),
    "G": ScenarioPlan(
        "G", 10, 2, "threading.Barrier", "independent engine/session per worker",
        ("revoke wins", "claim wins while logout succeeds"),
        ("return to ACTIVE", "nonce restoration", "logout blocked"),
    ),
}


POSTGRESQL_SCENARIO_NODE_IDS = {
    code: f"tests/test_postgresql_purge_reauth_concurrency.py::{name}"
    for code, name in {
        "A": "test_postgresql_concurrent_authorization_issuance",
        "B": "test_postgresql_actor_global_throttle_race",
        "C": "test_postgresql_same_nonce_claim_race",
        "D": "test_postgresql_concurrent_public_purge_execution",
        "E": "test_postgresql_copied_session_cookie_race",
        "F": "test_postgresql_issuance_versus_claim_race",
        "G": "test_postgresql_logout_revocation_versus_claim_race",
    }.items()
}

INDEPENDENT_PHASE_NODE_IDS = {
    "A-D": tuple(POSTGRESQL_SCENARIO_NODE_IDS[code] for code in "ABCD"),
    "E": (POSTGRESQL_SCENARIO_NODE_IDS["E"],),
    "F": (POSTGRESQL_SCENARIO_NODE_IDS["F"],),
    "G": (POSTGRESQL_SCENARIO_NODE_IDS["G"],),
}


@dataclass(frozen=True, slots=True)
class ZeroRowGateResult:
    database: str
    revision: str | None
    application_counts: Mapping[str, int]
    unknown_public_tables: tuple[str, ...] = ()

    @property
    def nonzero_tables(self):
        return {
            name: count for name, count in self.application_counts.items() if count
        }

    @property
    def passed(self):
        return (
            self.database == REHEARSAL_DATABASE_NAME
            and self.revision == EXPECTED_REVISION
            and not self.nonzero_tables
            and not self.unknown_public_tables
            and set(self.application_counts) == set(APPLICATION_TABLE_NAMES)
        )


@dataclass(frozen=True, slots=True)
class ScenarioExecutionResult:
    scenario: str
    functional_status: str
    functional_error: str | None = None
    teardown_status: str = "NOT_RUN"
    teardown_error: str | None = None
    postflight_status: str = "NOT_RUN"
    remaining_objects: tuple[str, ...] = ()
    pytest_node_id: str | None = None

    @property
    def overall_status(self):
        if self.functional_status != "PASS":
            return "FAIL"
        if self.teardown_status != "PASS" or self.postflight_status != "PASS":
            return "FAIL"
        return "PASS"


@dataclass(frozen=True, slots=True)
class PhaseEvidence:
    phase: str
    functional_status: str
    teardown_status: str
    postflight_status: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    duration_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class IndependentExecutionPlan:
    phases: tuple[str, ...] = ("A-D", "E", "F", "G")
    stop_on_functional_failure: bool = True
    stop_on_teardown_failure: bool = True
    stop_on_postflight_failure: bool = True
    require_zero_baseline: bool = True

    def selectors(self):
        return {phase: INDEPENDENT_PHASE_NODE_IDS[phase] for phase in self.phases}

    def validate(self):
        selectors = self.selectors()
        all_nodes = tuple(node for nodes in selectors.values() for node in nodes)
        expected = tuple(POSTGRESQL_SCENARIO_NODE_IDS.values())
        if len(all_nodes) != len(set(all_nodes)):
            raise ValueError("independent phase selectors overlap")
        if set(all_nodes) != set(expected):
            raise ValueError("independent phase selectors do not cover A-G exactly")
        if not all(node.startswith("tests/test_postgresql_purge_reauth_concurrency.py::test_postgresql_") for node in all_nodes):
            raise ValueError("destructive selector includes a non-PostgreSQL node")
        return selectors

    def should_start(self, phase, previous: PhaseEvidence | None = None):
        if phase not in self.phases:
            return False
        if previous is None:
            return self.require_zero_baseline
        return (
            previous.functional_status == "PASS"
            and previous.teardown_status == "PASS"
            and previous.postflight_status == "PASS"
        )


def build_independent_execution_plan():
    plan = IndependentExecutionPlan()
    plan.validate()
    return plan


APPLICATION_TABLE_NAMES = frozenset(
    {
        "users",
        "workspaces",
        "workspace_members",
        "settings",
        "customers",
        "services",
        "appointments",
        "invoices",
        "invoice_details",
        "activity_logs",
        "workspace_purge_requests",
        "purge_legal_holds",
        "purge_lifecycle_events",
        "workspace_purge_execution_authorizations",
        "workspace_purge_reauth_actor_throttles",
    }
)


def classify_public_tables(catalog_tables: Iterable[str], metadata_tables: Iterable[str]):
    """Reconcile catalog tables against the revision-0008 table contract.

    The purge workflow models use a separate SQLAlchemy registry, so relying
    only on ``extensions.db.metadata`` is import-order dependent.  The
    explicit allowlist is the authoritative application contract; reflected
    metadata may be a partial view but may not introduce unclassified names.
    """

    catalog = frozenset(catalog_tables)
    metadata = frozenset(metadata_tables)
    if MIGRATION_METADATA_TABLE not in catalog:
        raise RehearsalGuardError("alembic_version metadata table is missing.")
    metadata_application = metadata - {MIGRATION_METADATA_TABLE}
    metadata_unknown = metadata_application - APPLICATION_TABLE_NAMES
    if metadata_unknown:
        raise RehearsalGuardError(
            "Unknown application metadata table classification: "
            + ", ".join(sorted(metadata_unknown))
        )
    application = APPLICATION_TABLE_NAMES
    unknown = catalog - application - {MIGRATION_METADATA_TABLE}
    missing = application - catalog
    if unknown:
        raise RehearsalGuardError(
            "Unknown public non-system table classification: "
            + ", ".join(sorted(unknown))
        )
    if missing:
        raise RehearsalGuardError(
            "Application table missing from PostgreSQL catalog: "
            + ", ".join(sorted(missing))
        )
    return {
        "metadata": frozenset({MIGRATION_METADATA_TABLE}),
        "application": application,
        "system": frozenset(),
    }


def assert_revision_metadata(revision_rows: Iterable[str]):
    """Require exactly one Alembic row at the rehearsal revision."""

    revisions = tuple(revision_rows)
    if revisions != (EXPECTED_REVISION,):
        raise RehearsalGuardError("PostgreSQL rehearsal revision mismatch.")


def source_application_table_names(metadata) -> frozenset[str]:
    """Return the stable application contract independent of model imports."""

    metadata_application = frozenset(metadata.tables) - {MIGRATION_METADATA_TABLE}
    unknown = metadata_application - APPLICATION_TABLE_NAMES
    if unknown:
        raise RehearsalGuardError(
            "Unknown application metadata table classification: "
            + ", ".join(sorted(unknown))
        )
    return APPLICATION_TABLE_NAMES


def require_rehearsal_environment(environ: Mapping[str, object]) -> RehearsalTarget:
    """Require explicit d3e opt-in; never silently fall back to SQLite."""

    if environ.get(REHEARSAL_OPT_IN_ENV) != "1":
        raise RehearsalGuardError("PostgreSQL rehearsal requires explicit opt-in.")
    return validate_rehearsal_environment(environ)


@dataclass(frozen=True, slots=True, repr=False)
class WorkerResult:
    scenario: str
    round_number: int
    worker: str
    outcome: str
    backend_pid: int | None = None
    generation: int | None = None
    state: str | None = None

    def __repr__(self):
        return (
            "WorkerResult("
            f"scenario={self.scenario!r}, round_number={self.round_number!r}, "
            f"worker={self.worker!r}, outcome={self.outcome!r}, "
            f"backend_pid={self.backend_pid!r}, generation={self.generation!r}, "
            f"state={self.state!r})"
        )


@dataclass(frozen=True, slots=True)
class CapturedPytestResult:
    """Secret-free subprocess evidence retained before postflight verification."""

    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    completed: bool = True
    timed_out: bool = False

    @property
    def has_output(self):
        return bool(self.stdout or self.stderr)


@dataclass(frozen=True, slots=True)
class PostflightResult:
    """Independent final-state verifier evidence."""

    passed: bool
    summary: str = ""
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CombinedRehearsalResult:
    """Combined result whose success requires complete pytest and postflight evidence."""

    pytest: CapturedPytestResult
    postflight: PostflightResult
    evidence_error: str | None = None

    @property
    def overall_pass(self):
        return (
            self.pytest.completed
            and not self.pytest.timed_out
            and self.pytest.exit_code == 0
            and self.pytest.has_output
            and self.postflight.passed
            and self.evidence_error is None
        )


class CleanupFailure(RehearsalGuardError):
    """Typed cleanup failure retaining the registered remaining namespace."""

    def __init__(self, message, remaining_by_kind=None):
        self.remaining_by_kind = {
            kind: tuple(sorted(ids))
            for kind, ids in (remaining_by_kind or {}).items()
            if ids
        }
        suffix = ""
        if self.remaining_by_kind:
            suffix = f" remaining={self.remaining_by_kind!r}"
        super().__init__(f"{message}{suffix}")


def _remaining_manifest_objects(manifest):
    return {
        kind: {
            object_id
            for object_id in ids
            if manifest.lifecycle_by_key.get((kind, object_id)) == "created"
        }
        for kind, ids in manifest.ids_by_kind.items()
    }


def sanitize_rehearsal_output(value, secret_values=()):
    """Remove supplied secrets and credential-bearing values without hiding test totals."""

    rendered = str(value or "")
    for secret in secret_values:
        if secret:
            rendered = rendered.replace(str(secret), "[REDACTED]")
    rendered = re.sub(
        r"(?i)(postgres(?:ql)?(?:\+\w+)?://[^:/\s]+:)[^@\s]+(@)",
        r"\1[REDACTED]\2",
        rendered,
    )
    rendered = re.sub(
        r"(?i)(\b(?:password|passwd|nonce|nonce_hash|signed_cookie|cookie|hash)\b\s*[:=]\s*)[^\s,;]+",
        r"\1[REDACTED]",
        rendered,
    )
    return rendered


def run_postflight_with_evidence(pytest_result, verifier, *, secret_values=()):
    """Run postflight after subprocess completion while preserving both outcomes."""

    if not isinstance(pytest_result, CapturedPytestResult):
        raise TypeError("pytest_result must be CapturedPytestResult")
    if not pytest_result.completed:
        postflight = PostflightResult(False, error="pytest subprocess did not complete")
    else:
        try:
            summary = verifier()
        except BaseException as error:
            postflight = PostflightResult(False, error=f"{type(error).__name__}: {error}")
        else:
            postflight = PostflightResult(True, summary=str(summary or "PASS"))
    evidence_error = None
    if not pytest_result.has_output:
        evidence_error = "captured pytest stdout/stderr is empty"
    sanitized = CapturedPytestResult(
        pytest_result.exit_code,
        sanitize_rehearsal_output(pytest_result.stdout, secret_values),
        sanitize_rehearsal_output(pytest_result.stderr, secret_values),
        pytest_result.completed,
        pytest_result.timed_out,
    )
    sanitized_postflight = PostflightResult(
        postflight.passed,
        sanitize_rehearsal_output(postflight.summary, secret_values),
        sanitize_rehearsal_output(postflight.error, secret_values) if postflight.error else None,
    )
    return CombinedRehearsalResult(sanitized, sanitized_postflight, evidence_error)


def format_rehearsal_evidence(result: CombinedRehearsalResult):
    """Format primary pytest evidence before independent postflight evidence."""

    if not isinstance(result, CombinedRehearsalResult):
        raise TypeError("result must be CombinedRehearsalResult")
    lines = [
        f"PYTEST_EXIT_CODE={result.pytest.exit_code}",
        f"PYTEST_COMPLETED={result.pytest.completed}",
        f"PYTEST_TIMED_OUT={result.pytest.timed_out}",
        "PYTEST_STDOUT_BEGIN",
        result.pytest.stdout,
        "PYTEST_STDOUT_END",
        "PYTEST_STDERR_BEGIN",
        result.pytest.stderr,
        "PYTEST_STDERR_END",
    ]
    if result.evidence_error:
        lines.append(f"EVIDENCE_ERROR={result.evidence_error}")
    lines.append(f"POSTFLIGHT_PASS={result.postflight.passed}")
    if result.postflight.summary:
        lines.append(f"POSTFLIGHT_SUMMARY={result.postflight.summary}")
    if result.postflight.error:
        lines.append(f"POSTFLIGHT_ERROR={result.postflight.error}")
    lines.append(f"OVERALL_PASS={result.overall_pass}")
    return "\n".join(lines)


@dataclass(slots=True)
class CleanupManifest:
    namespace: str
    ids_by_kind: dict[str, set[int]] = field(default_factory=dict)
    namespaces: dict[tuple[str, int], str] = field(default_factory=dict, repr=False)
    lifecycle_by_key: dict[tuple[str, int], str] = field(default_factory=dict, repr=False)
    classification_by_key: dict[tuple[str, int], str] = field(default_factory=dict, repr=False)

    VALID_KINDS = frozenset({
        "user", "workspace", "workspace_member", "setting", "customer", "service",
        "appointment", "invoice", "invoice_detail", "purge_request", "legal_hold",
        "lifecycle_event", "activity_log", "authorization", "throttle",
    })

    def _validate(self, kind: str, object_id: int):
        if kind == MIGRATION_METADATA_TABLE or kind not in self.VALID_KINDS:
            raise ValueError("manifest kind is outside the synthetic namespace")
        if not isinstance(object_id, int) or isinstance(object_id, bool) or object_id <= 0:
            raise ValueError("manifest IDs must be positive integers")
        key = (kind, object_id)
        previous = self.namespaces.get(key)
        if previous is not None and previous != self.namespace:
            raise ValueError("synthetic ID is already registered in another namespace")
        self.namespaces[key] = self.namespace
        self.ids_by_kind.setdefault(kind, set()).add(object_id)

    def register(self, kind: str, object_id: int, *, state="created"):
        if state not in {"planned", "created"}:
            raise ValueError("invalid cleanup lifecycle state")
        self._validate(kind, object_id)
        self.lifecycle_by_key[(kind, object_id)] = state
        self.classification_by_key.setdefault((kind, object_id), HARNESS_CLEANUP_REQUIRED)

    def plan(self, kind: str, object_id: int):
        self.register(kind, object_id, state="planned")

    def mark_persisted(self, kind: str, object_id: int):
        key = (kind, object_id)
        if key not in self.lifecycle_by_key:
            raise ValueError("cannot mark an unregistered cleanup object persisted")
        self.lifecycle_by_key[key] = "created"

    def mark_all_persisted(self):
        for key, state in tuple(self.lifecycle_by_key.items()):
            if state == "planned":
                self.lifecycle_by_key[key] = "created"

    def mark_cleanup_completed(self, kind: str, object_id: int):
        key = (kind, object_id)
        if self.lifecycle_by_key.get(key) != "created":
            raise ValueError("cleanup completed for an object that was not persisted")
        self.lifecycle_by_key[key] = "cleanup-completed"

    def register_typed(self, kind: str, object_id: int, namespace: str | None = None):
        if namespace is not None and namespace != self.namespace:
            raise ValueError("synthetic object namespace mismatch")
        self.register(kind, object_id)

    def register_service_deletion_expected(self, kind: str, object_id: int):
        if kind not in SERVICE_DELETION_KINDS:
            raise ValueError("kind is not covered by the purge deletion contract")
        self.register(kind, object_id)
        self.classification_by_key[(kind, object_id)] = SERVICE_DELETION_EXPECTED

    def mark_service_deletion_verified(self, kind: str, object_id: int):
        key = (kind, object_id)
        if self.classification_by_key.get(key) != SERVICE_DELETION_EXPECTED:
            raise ValueError("object is not service-deletion-expected")
        if self.lifecycle_by_key.get(key) != "created":
            raise ValueError("service deletion verified for an object that was not persisted")
        self.lifecycle_by_key[key] = "service-deleted-verified"

    def _typed(self, kind, object_id):
        self.register_typed(kind, object_id)

    register_user = lambda self, object_id: self._typed("user", object_id)
    register_workspace = lambda self, object_id: self._typed("workspace", object_id)
    register_workspace_member = lambda self, object_id: self._typed("workspace_member", object_id)
    register_setting = lambda self, object_id: self._typed("setting", object_id)
    register_customer = lambda self, object_id: self._typed("customer", object_id)
    register_service = lambda self, object_id: self._typed("service", object_id)
    register_appointment = lambda self, object_id: self._typed("appointment", object_id)
    register_invoice = lambda self, object_id: self._typed("invoice", object_id)
    register_invoice_detail = lambda self, object_id: self._typed("invoice_detail", object_id)
    register_purge_request = lambda self, object_id: self._typed("purge_request", object_id)
    register_legal_hold = lambda self, object_id: self._typed("legal_hold", object_id)
    register_lifecycle_event = lambda self, object_id: self._typed("lifecycle_event", object_id)
    register_activity_log = lambda self, object_id: self._typed("activity_log", object_id)
    register_authorization = lambda self, object_id: self._typed("authorization", object_id)
    register_throttle = lambda self, object_id: self._typed("throttle", object_id)

    def require_registered(self, kind: str, object_id: int):
        if object_id not in self.ids_by_kind.get(kind, set()):
            raise ValueError("cleanup attempted for an unregistered synthetic ID")

    def deletion_order(self):
        return tuple(
            (kind, object_id)
            for kind in CLEANUP_KIND_ORDER
            if kind in self.ids_by_kind
            for object_id in sorted(self.ids_by_kind[kind], reverse=True)
            if self.lifecycle_by_key.get((kind, object_id)) == "created"
            and self.classification_by_key.get((kind, object_id), HARNESS_CLEANUP_REQUIRED)
            != SERVICE_DELETION_EXPECTED
        )


@dataclass(slots=True, repr=False)
class RehearsalContext:
    """Enabled-only context; credentials and URL are intentionally omitted."""

    application: object
    db: object
    database: str
    engine_url: str
    models: object
    services: object
    manifest: CleanupManifest
    classification: Mapping[str, frozenset[str]]
    app_context: object | None = None
    fixture_builder: object | None = None
    scenario_callbacks: Mapping[str, object] = field(default_factory=dict)
    lock_timeout: str = "2s"
    statement_timeout: str = "30s"

    def __repr__(self):
        return (
            "RehearsalContext(database={!r}, manifest_namespace={!r}, "
            "lock_timeout={!r}, statement_timeout={!r})"
        ).format(self.database, self.manifest.namespace, self.lock_timeout, self.statement_timeout)

    def close(self):
        if self.app_context is not None:
            self.app_context.pop()
            self.app_context = None


@dataclass(slots=True, repr=False)
class RoundContext:
    scenario: str
    round_number: int
    namespace: str
    manifest: CleanupManifest
    execution_mode: str = "AUTHORIZATION_ONLY"

    def __repr__(self):
        return f"RoundContext(scenario={self.scenario!r}, round_number={self.round_number!r})"


def create_round_context(scenario: str, round_number: int, run_namespace: str):
    if scenario not in SCENARIO_PLANS or round_number <= 0 or not run_namespace:
        raise ValueError("invalid rehearsal round context")
    namespace = f"{run_namespace}-{scenario.lower()}-{round_number}"
    return RoundContext(
        scenario,
        round_number,
        namespace,
        CleanupManifest(namespace),
        SCENARIO_PLANS[scenario].execution_mode,
    )


@contextmanager
def isolated_purge_execution_flags(application):
    config = application.config
    keys = ("PERMANENT_PURGE_UI_ENABLED", "PERMANENT_PURGE_EXECUTION_ENABLED")
    missing = object()
    original = {key: config.get(key, missing) for key in keys}
    try:
        config[keys[0]] = True
        config[keys[1]] = True
        yield
    finally:
        for key, value in original.items():
            if value is missing:
                config.pop(key, None)
            else:
                config[key] = value


def _catalog_and_metadata(connection, metadata):
    from sqlalchemy import text

    catalog = frozenset(
        connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"
            )
        ).scalars()
    )
    return classify_public_tables(catalog, metadata.tables)


def _count_tables(connection, table_names):
    from sqlalchemy import text

    counts = {}
    for table_name in sorted(table_names):
        identifier = '"' + table_name.replace('"', '""') + '"'
        counts[table_name] = connection.execute(text(f"SELECT count(*) FROM {identifier}")).scalar_one()
    return counts


def assert_application_tables_empty(counts):
    """Fail closed on any application-row delta; never delete the delta here."""

    if any(count != 0 for count in counts.values()):
        raise RehearsalGuardError("PostgreSQL rehearsal application data is not empty.")


def _assert_readiness(connection, metadata):
    from sqlalchemy import text

    database, user, port = connection.execute(
        text("SELECT current_database(), current_user, current_setting('port')")
    ).one()
    if database != REHEARSAL_DATABASE_NAME or not user or str(port) != "5432":
        raise RehearsalGuardError("PostgreSQL rehearsal identity mismatch.")
    revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    assert_revision_metadata(revision)
    classification = _catalog_and_metadata(connection, metadata)
    counts = _count_tables(connection, classification["application"])
    assert_application_tables_empty(counts)
    return classification


def create_enabled_rehearsal_context(environ: Mapping[str, object]) -> RehearsalContext:
    """Create the guarded application/engine context only after opt-in."""

    target = require_rehearsal_environment(environ)
    # This explicit setting must precede importing app.py, whose module-level
    # bootstrap hook otherwise seeds accounts during application creation.
    os.environ["SPAMANAGER_BOOTSTRAP_ACCOUNTS_ENABLED"] = "0"
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    from app import app
    from extensions import db
    from models import appointment, customer, invoice, invoice_detail, purge, service, setting, user, workspace
    from services import purge_reauth_service, purge_service, purge_request_service

    app_context = app.app_context()
    app_context.push()
    try:
        classification = None
        engine_url = os.environ["TEST_DATABASE_URL"]
        engine = create_engine(engine_url, poolclass=NullPool, future=True)
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL lock_timeout = '2s'"))
                connection.execute(text("SET LOCAL statement_timeout = '30s'"))
                classification = _assert_readiness(connection, db.metadata)
            with engine.connect() as connection:
                assert_application_tables_empty(
                    _count_tables(connection, classification["application"])
                )
        finally:
            engine.dispose()
        context = RehearsalContext(
            application=app,
            db=db,
            database=target.database,
            engine_url=engine_url,
            models=SimpleNamespace(
                Appointment=appointment.Appointment,
                Customer=customer.Customer,
                Invoice=invoice.Invoice,
                InvoiceDetail=invoice_detail.InvoiceDetail,
                Purge=purge,
                Service=service.Service,
                Setting=setting.Setting,
                User=user.User,
                Workspace=workspace.Workspace,
                WorkspaceMember=workspace.WorkspaceMember,
                ActivityLog=__import__("models.activity_log", fromlist=["ActivityLog"]).ActivityLog,
                WorkspacePurgeRequest=purge.WorkspacePurgeRequest,
                workspace_terminal_state_table=purge.workspace_terminal_state_table,
                PurgeLegalHold=purge.PurgeLegalHold,
                PurgeLifecycleEvent=purge.PurgeLifecycleEvent,
                WorkspacePurgeExecutionAuthorization=purge.WorkspacePurgeExecutionAuthorization,
                WorkspacePurgeReauthActorThrottle=purge.WorkspacePurgeReauthActorThrottle,
            ),
            services=SimpleNamespace(
                PurgeReauthService=purge_reauth_service.PurgeReauthService,
                PurgeService=purge_service.PurgeService,
                PurgeRequestService=purge_request_service.PurgeRequestService,
            ),
            manifest=CleanupManifest(f"d3e-{os.getpid()}"),
            classification=classification,
            app_context=app_context,
            fixture_builder=None,
            scenario_callbacks=SCENARIO_CALLBACKS,
        )
        context.fixture_builder = SyntheticFixtureBuilder()
        if set(context.scenario_callbacks) != set("ABCDEFG") or not all(callable(value) for value in context.scenario_callbacks.values()):
            context.close()
            raise RehearsalGuardError("Incomplete PostgreSQL scenario callback registry.")
        return context
    except Exception:
        app_context.pop()
        raise


@contextmanager
def independent_worker_session(context: RehearsalContext):
    """Yield one independent SQLAlchemy session and PostgreSQL backend PID."""

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool

    engine = create_engine(context.engine_url, poolclass=NullPool, future=True)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        session.execute(text("SET lock_timeout = '2s'"))
        session.execute(text("SET statement_timeout = '30s'"))
        pid = session.execute(text("SELECT pg_backend_pid()")).scalar_one()
        yield session, pid
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


def assert_fixture_actor_contract(context: RehearsalContext, case: SyntheticCase):
    """Verify committed actors are independently visible before any race starts."""

    from core.auth.permissions import is_approval_owner

    actor_ids = (case.requester_id, case.approver_id, *case.executor_ids)
    if case.requester_id == case.approver_id or len(set(actor_ids)) != len(actor_ids):
        raise RehearsalGuardError("synthetic actor separation contract failed")
    with independent_worker_session(context) as (session, _pid):
        users = [session.get(context.models.User, actor_id) for actor_id in actor_ids]
        if any(user is None for user in users):
            raise RehearsalGuardError("synthetic actors are not visible in a fresh session")
        if any(
            not is_approval_owner(user)
            or not user.is_active
            or user.deleted_at is not None
            or user.approval_status != user.APPROVAL_ACTIVE
            for user in users[:2]
        ):
            raise RehearsalGuardError("requester/approver approval-owner contract failed")
        if any(
            not is_approval_owner(user)
            or user.auth_provider != "local" or not user.password_hash
            or not user.is_active
            or user.deleted_at is not None
            or user.approval_status != user.APPROVAL_ACTIVE
            for user in users[2:]
        ):
            raise RehearsalGuardError("executor local-password eligibility contract failed")
        if any(
            not user.check_password(password)
            for user, password in zip(users[2:], case.passwords)
        ):
            raise RehearsalGuardError("executor password fixture self-check failed")


def run_barrier_workers(context, plan: ScenarioPlan, operation):
    """Run real worker callbacks with independent sessions and bounded joins."""

    barrier = threading.Barrier(plan.workers)

    def worker(label):
        with context.application.app_context():
            with independent_worker_session(context) as resource:
                barrier.wait(timeout=30)
                return operation(label, resource)

    with ThreadPoolExecutor(max_workers=plan.workers, thread_name_prefix=f"d3e-{plan.name}") as pool:
        futures = [pool.submit(worker, f"worker-{index + 1}") for index in range(plan.workers)]
        results = []
        try:
            for future in futures:
                results.append(future.result(timeout=45))
        except TimeoutError:
            for future in futures:
                future.cancel()
            raise AssertionError(f"scenario {plan.name} exceeded bounded worker timeout")
    assert_distinct_backend_pids(
        [result for result in results if isinstance(result, WorkerResult)]
    )
    return results


def execute_scenario(context: RehearsalContext, code: str):
    """Dispatch an enabled scenario to its real service operation callback."""

    plan = SCENARIO_PLANS[code]
    callback = resolve_scenario_callback(context, code)
    results = []
    for round_number in range(1, plan.rounds + 1):
        round_context = create_round_context(code, round_number, context.manifest.namespace)
        primary_error = None
        cleanup_error = None
        try:
            results.append(callback(context, plan, round_context))
        except BaseException as error:
            primary_error = error
        finally:
            try:
                cleanup_round_exactly(context, round_context)
            except BaseException as error:
                cleanup_error = error if isinstance(error, CleanupFailure) else CleanupFailure(
                    str(error), _remaining_manifest_objects(round_context.manifest)
                )
        if primary_error is not None:
            if cleanup_error is not None:
                raise primary_error from cleanup_error
            raise primary_error
        if cleanup_error is not None:
            raise cleanup_error
    return results


def execute_scenario_with_outcomes(context: RehearsalContext, code: str):
    """Run one scenario while preserving functional, teardown, and postflight outcomes."""

    plan = SCENARIO_PLANS[code]
    callback = resolve_scenario_callback(context, code)
    functional_error = None
    teardown_error = None
    remaining = ()
    for round_number in range(1, plan.rounds + 1):
        round_context = create_round_context(code, round_number, context.manifest.namespace)
        try:
            callback(context, plan, round_context)
        except BaseException as error:
            functional_error = error
        finally:
            try:
                cleanup_round_exactly(context, round_context)
            except BaseException as error:
                teardown_error = error
                remaining = tuple(
                    f"{kind}:{object_id}"
                    for kind, object_id in _remaining_manifest_objects(round_context.manifest)
                )
        if functional_error is not None or teardown_error is not None:
            break
    functional_status = "FAIL" if functional_error is not None else "PASS"
    teardown_status = "FAIL" if teardown_error is not None else "PASS"
    postflight_status = "FAIL" if teardown_error is not None else "PASS"
    return ScenarioExecutionResult(
        scenario=code,
        functional_status=functional_status,
        functional_error=(str(functional_error) if functional_error else None),
        teardown_status=teardown_status,
        teardown_error=(str(teardown_error) if teardown_error else None),
        postflight_status=postflight_status,
        remaining_objects=remaining,
        pytest_node_id=POSTGRESQL_SCENARIO_NODE_IDS.get(code),
    )


def resolve_scenario_callback(context, code):
    if code not in SCENARIO_CALLBACKS or context.scenario_callbacks.get(code) is not SCENARIO_CALLBACKS[code]:
        raise RehearsalGuardError(f"Scenario {code} is not registered by the harness.")
    callback = context.scenario_callbacks[code]
    if not callable(callback):
        raise RehearsalGuardError(f"Scenario {code} callback is not callable.")
    return callback


def discover_and_register_indirect_rows(context, round_context, request_ids, workspace_ids, actor_ids=()):
    """Register all dependent rows by exact synthetic round bindings."""
    from sqlalchemy import or_, select

    models = context.models
    request_ids = tuple(sorted(set(request_ids)))
    workspace_ids = tuple(sorted(set(workspace_ids)))
    actor_ids = tuple(sorted(set(actor_ids)))
    with independent_worker_session(context) as (session, _pid):
        request_model = models.WorkspacePurgeRequest
        if not request_ids and workspace_ids:
            discovered_requests = session.execute(
                select(request_model.id).where(request_model.workspace_id.in_(workspace_ids))
            ).scalars().all()
            if not discovered_requests:
                raise RehearsalGuardError("round has no discoverable purge request")
            if len(discovered_requests) != len(set(discovered_requests)):
                raise RehearsalGuardError("round request discovery returned duplicate IDs")
            if len(discovered_requests) > len(workspace_ids):
                raise RehearsalGuardError("round has multiple purge requests for a workspace")
            request_ids = tuple(sorted(set(discovered_requests)))
            for request_id in request_ids:
                round_context.manifest.register_purge_request(request_id)
        if not request_ids:
            raise RehearsalGuardError("round has no registered purge request")
        visible_request_ids = set(
            session.execute(
                select(request_model.id).where(request_model.id.in_(request_ids))
            ).scalars()
        )
        if visible_request_ids != set(request_ids):
            raise RehearsalGuardError("registered round purge request is missing")

        indirect = (
            ("authorization", getattr(models, "WorkspacePurgeExecutionAuthorization", None),
             lambda model: model.purge_request_id.in_(request_ids)),
            ("lifecycle_event", getattr(models, "PurgeLifecycleEvent", None),
             lambda model: model.request_id.in_(request_ids)),
            ("legal_hold", getattr(models, "PurgeLegalHold", None),
             lambda model: model.workspace_id.in_(workspace_ids)),
            ("throttle", getattr(models, "WorkspacePurgeReauthActorThrottle", None),
             lambda model: model.actor_user_id.in_(actor_ids)),
            ("activity_log", getattr(models, "ActivityLog", None),
             lambda model: or_(
                 model.workspace_id.in_(workspace_ids),
                 model.user_id.in_(actor_ids),
                 model.reference_id.in_(request_ids),
             )),
        )
        for kind, model, predicate in indirect:
            if model is None:
                continue
            if kind in {"legal_hold", "activity_log"} and not workspace_ids:
                continue
            if kind == "throttle" and not actor_ids:
                continue
            for row in session.execute(select(model).where(predicate(model))).scalars():
                object_id = row.actor_user_id if kind == "throttle" else row.id
                round_context.manifest.register_typed(kind, object_id)


def verify_final_zero_row_state(context, round_context):
    """Verify metadata and every authoritative application table from a fresh connection."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(context.engine_url, poolclass=NullPool, future=True)
    try:
        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
            if revision != [EXPECTED_REVISION]:
                raise RehearsalGuardError("final rehearsal revision mismatch")
            classification = _catalog_and_metadata(connection, context.db.metadata)
            if classification["application"] != APPLICATION_TABLE_NAMES:
                raise RehearsalGuardError("authoritative application table set changed")
            counts = _count_tables(connection, classification["application"])
            if any(count != 0 for count in counts.values()):
                raise RehearsalGuardError("final rehearsal application state is not empty")
    finally:
        engine.dispose()


def cleanup_round_exactly(context: RehearsalContext, round_context: RoundContext):
    errors = []
    try:
        discover_and_register_indirect_rows(
            context, round_context, _manifest_request_ids(round_context),
            _manifest_workspace_ids(round_context), _manifest_actor_ids(round_context),
        )
    except BaseException as error:
        errors.append(error)
    if not errors:
        try:
            reconcile_service_deletion_expected(context, round_context)
        except BaseException as error:
            errors.append(error)
    try:
        _cleanup_manifest(context, round_context.manifest)
    except BaseException as error:
        errors.append(error)
    try:
        verify_final_zero_row_state(context, round_context)
    except BaseException as error:
        errors.append(error)
    if errors:
        error = errors[0]
        if isinstance(error, CleanupFailure):
            raise error
        raise CleanupFailure(
            str(error), _remaining_manifest_objects(round_context.manifest)
        ) from error


def _manifest_request_ids(round_context):
    return tuple(sorted(round_context.manifest.ids_by_kind.get("purge_request", set())))


def _manifest_workspace_ids(round_context):
    return tuple(sorted(round_context.manifest.ids_by_kind.get("workspace", set())))


def _manifest_actor_ids(round_context):
    return round_context.manifest.ids_by_kind.get("user", set())


def reconcile_service_deletion_expected(context: RehearsalContext, round_context: RoundContext):
    """Reconcile purge-owned deletions from a fresh independent database session."""

    expected = tuple(
        (kind, object_id)
        for kind, object_ids in round_context.manifest.ids_by_kind.items()
        for object_id in sorted(object_ids)
        if round_context.manifest.classification_by_key.get((kind, object_id))
        == SERVICE_DELETION_EXPECTED
        and round_context.manifest.lifecycle_by_key.get((kind, object_id)) == "created"
    )
    if not expected:
        return
    request_ids = _manifest_request_ids(round_context)
    if len(request_ids) != 1:
        raise RehearsalGuardError("service-deletion reconciliation requires one purge request")

    from sqlalchemy import select
    workspace_terminal_state_table = getattr(
        context.models, "workspace_terminal_state_table", None
    )
    if workspace_terminal_state_table is None:
        raise RehearsalGuardError("terminal workspace state contract is unavailable")

    model_name_by_kind = {
        "invoice_detail": "InvoiceDetail",
        "appointment": "Appointment",
        "invoice": "Invoice",
        "customer": "Customer",
        "service": "Service",
        "setting": "Setting",
        "workspace_member": "WorkspaceMember",
    }
    with independent_worker_session(context) as (session, _pid):
        request = session.get(context.models.WorkspacePurgeRequest, request_ids[0])
        terminal = session.execute(
            select(workspace_terminal_state_table).where(
                workspace_terminal_state_table.c.id == request.workspace_id
            )
        ).mappings().one_or_none() if request is not None else None
        committed = bool(
            request is not None
            and request.status == "COMPLETED"
            and not request.outcome_unknown
            and terminal is not None
            and terminal["purged_at"] is not None
            and terminal["purge_request_id"] == request.id
        )
        for kind, object_id in expected:
            model = getattr(context.models, model_name_by_kind[kind], None)
            if model is None:
                raise RehearsalGuardError(f"service-deletion model contract is unavailable for {kind}")
            present = session.query(model).filter_by(id=object_id).one_or_none()
            if committed and present is None:
                round_context.manifest.mark_service_deletion_verified(kind, object_id)
            elif committed:
                raise RehearsalGuardError(f"Verified purge retained approved {kind} row.")
            elif present is None:
                raise RehearsalGuardError(
                    f"Service-deletion-expected {kind} row is missing before verified purge."
                )


def validate_terminal_backlink_bindings(workspace_rows, request_rows, workspace_ids, request_ids):
    """Validate the exact nullable workspace/request relationship before reconciliation."""

    workspace_ids = set(workspace_ids)
    request_ids = set(request_ids)
    workspace_map = dict(workspace_rows)
    request_map = dict(request_rows)
    if set(workspace_map) != workspace_ids or set(request_map) != request_ids:
        raise RehearsalGuardError("workspace/request discovery set mismatch")
    for request_id, workspace_id in request_map.items():
        if workspace_id not in workspace_ids:
            raise RehearsalGuardError("purge request points outside cleanup namespace")
    to_clear = []
    for workspace_id, request_id in workspace_map.items():
        if request_id is None:
            continue
        if request_id not in request_ids or request_map[request_id] != workspace_id:
            raise RehearsalGuardError("workspace terminal backlink crosses cleanup namespace")
        to_clear.append((workspace_id, request_id))
    return tuple(sorted(to_clear))


def _reconcile_workspace_terminal_backlinks(connection, manifest, metadata):
    """Clear only discovered run-owned terminal backlinks before request deletion."""

    from sqlalchemy import Table, select, update

    request_ids = tuple(sorted(
        object_id for kind, object_id in manifest.deletion_order()
        if kind == "purge_request"
    ))
    workspace_ids = tuple(sorted(
        object_id for kind, object_id in manifest.deletion_order()
        if kind == "workspace"
    ))
    if not workspace_ids and request_ids:
        raise RehearsalGuardError("purge request has no discovered workspace")
    if not workspace_ids:
        return

    workspaces = metadata.tables.get("workspaces")
    if workspaces is None:
        workspaces = Table("workspaces", metadata, autoload_with=connection)
    requests = metadata.tables.get("workspace_purge_requests")
    if requests is None:
        requests = Table("workspace_purge_requests", metadata, autoload_with=connection)
    workspace_rows = connection.execute(
        select(workspaces.c.id, workspaces.c.purge_request_id)
        .where(workspaces.c.id.in_(workspace_ids))
        .with_for_update()
    ).all()
    request_rows = connection.execute(
        select(requests.c.id, requests.c.workspace_id)
        .where(requests.c.id.in_(request_ids))
        .with_for_update()
    ).all() if request_ids else []
    clear_rows = validate_terminal_backlink_bindings(
        workspace_rows, request_rows, workspace_ids, request_ids
    )
    if not clear_rows:
        return
    clear_ids = tuple(workspace_id for workspace_id, _request_id in clear_rows)
    clear_request_ids = tuple(request_id for _workspace_id, request_id in clear_rows)
    affected = connection.execute(
        update(workspaces)
        .where(
            workspaces.c.id.in_(clear_ids),
            workspaces.c.purge_request_id.in_(clear_request_ids),
        )
        .values(purge_request_id=None, purged_at=None)
    ).rowcount
    if affected != len(clear_rows):
        raise RehearsalGuardError("terminal backlink reconciliation affected an unexpected row count")


def cleanup_manifest(context: RehearsalContext, round_context: RoundContext | None = None):
    """Compatibility wrapper; enabled callbacks must pass their fresh round."""
    if round_context is None:
        round_context = RoundContext("legacy", 1, context.manifest.namespace, context.manifest)
    _cleanup_manifest(context, round_context.manifest)


def _cleanup_manifest(context: RehearsalContext, manifest: CleanupManifest):
    """Delete only registered IDs, in dependency order, using fresh resources."""

    from sqlalchemy import MetaData, create_engine, delete, select, text
    from sqlalchemy.pool import NullPool

    table_by_kind = {
        "authorization": ("workspace_purge_execution_authorizations", "id"),
        "throttle": ("workspace_purge_reauth_actor_throttles", "actor_user_id"),
        "lifecycle_event": ("purge_lifecycle_events", "id"),
        "purge_request": ("workspace_purge_requests", "id"),
        "legal_hold": ("purge_legal_holds", "id"),
        "activity_log": ("activity_logs", "id"),
        "invoice_detail": ("invoice_details", "id"),
        "appointment": ("appointments", "id"),
        "invoice": ("invoices", "id"),
        "customer": ("customers", "id"),
        "service": ("services", "id"),
        "setting": ("settings", "id"),
        "workspace_member": ("workspace_members", "id"),
        "workspace": ("workspaces", "id"),
        "user": ("users", "id"),
    }
    if any(kind not in table_by_kind for kind in manifest.ids_by_kind):
        raise RehearsalGuardError("Cleanup manifest contains an unknown object kind.")

    engine = create_engine(context.engine_url, poolclass=NullPool, future=True)
    metadata = MetaData()
    try:
        try:
            with engine.begin() as connection:
                database = connection.execute(text("SELECT current_database()")).scalar_one()
                if database != REHEARSAL_DATABASE_NAME:
                    raise RehearsalGuardError("Cleanup database identity mismatch.")
                _reconcile_workspace_terminal_backlinks(connection, manifest, metadata)
                for kind, object_id in manifest.deletion_order():
                    table_name, column_name = table_by_kind[kind]
                    table = metadata.tables.get(table_name)
                    if table is None:
                        from sqlalchemy import Table
                        table = Table(table_name, metadata, autoload_with=connection)
                    column = table.c[column_name]
                    present = connection.execute(select(column).where(column == object_id)).first()
                    if present is None:
                        raise RehearsalGuardError("Registered cleanup object is missing.")
                    affected = connection.execute(delete(table).where(column == object_id)).rowcount
                    if affected != 1:
                        raise RehearsalGuardError("Cleanup affected an unexpected row count.")
                    manifest.mark_cleanup_completed(kind, object_id)
            with engine.connect() as connection:
                remaining = _count_tables(connection, context.classification["application"])
                if any(value != 0 for value in remaining.values()):
                    raise RehearsalGuardError("Cleanup did not restore application zero-row state.")
        except BaseException as error:
            if isinstance(error, CleanupFailure):
                raise
            raise CleanupFailure(str(error), _remaining_manifest_objects(manifest)) from error
    finally:
        engine.dispose()


def assert_distinct_backend_pids(results: Iterable[WorkerResult]):
    pids = [result.backend_pid for result in results]
    if any(pid is None for pid in pids) or len(set(pids)) != len(pids):
        raise AssertionError("concurrent workers must use distinct PostgreSQL backend PIDs")


class SyntheticFixtureBuilder:
    """Builds only namespaced, manifest-registered rehearsal objects."""

    def approved_request(self, context: RehearsalContext, round_context: RoundContext, *, executors=2):
        from datetime import datetime
        import uuid

        models = context.models
        services = context.services
        db = context.db
        manifest = round_context.manifest
        marker = f"{round_context.namespace}-{uuid.uuid4().hex[:8]}"
        users = []
        for role_name in ("requester", "approver", *(f"executor{n}" for n in range(executors))):
            user = models.User(
                username=f"d3e_{role_name}_{marker}",
                email=f"d3e_{role_name}_{marker}@invalid.test",
                full_name=f"D3E {role_name}",
                role="APPROVAL_OWNER",
                approval_status="active",
                is_active=True,
                auth_provider="local",
            )
            password = secrets.token_urlsafe(24)
            user.set_password(password)
            users.append((user, password))
            db.session.add(user)
            db.session.flush()
            manifest.plan("user", user.id)
        requester, approver = users[0][0], users[1][0]
        target_owner = models.User(
            username=f"d3e_target_{marker}",
            email=f"d3e_target_{marker}@invalid.test",
            full_name="D3E target owner",
            role="OWNER",
            approval_status="active",
            is_active=False,
            deleted_at=datetime(2026, 1, 1),
            deleted_by_id=requester.id,
        )
        target_owner.set_password(secrets.token_urlsafe(24))
        db.session.add(target_owner)
        db.session.flush()
        manifest.plan("user", target_owner.id)
        workspace = models.Workspace(
            name=f"D3E {marker}", slug=f"d3e-{marker}", status="active",
            deleted_at=datetime(2026, 1, 1), deleted_by_id=requester.id,
        )
        db.session.add(workspace)
        db.session.flush()
        manifest.plan("workspace", workspace.id)
        member = models.WorkspaceMember(workspace_id=workspace.id, user_id=target_owner.id, role="owner", status="active")
        db.session.add(member)
        db.session.flush()
        manifest.plan("workspace_member", member.id)
        setting = models.Setting(key=f"d3e_{marker}", value="safe", workspace_id=workspace.id)
        customer = models.Customer(name=f"D3E customer {marker}", workspace_id=workspace.id)
        service = models.Service(name=f"D3E service {marker}", price=10.0, duration=30, workspace_id=workspace.id)
        db.session.add_all([setting, customer, service])
        db.session.flush()
        manifest.plan("setting", setting.id)
        manifest.plan("customer", customer.id)
        manifest.plan("service", service.id)
        appointment = models.Appointment(
            customer_id=customer.id, service_id=service.id,
            appointment_time=datetime(2026, 2, 2), status="Confirmed",
            workspace_id=workspace.id,
        )
        invoice = models.Invoice(
            customer_id=customer.id, invoice_date=datetime(2026, 2, 2).date(),
            subtotal=10.0, total_amount=10.0, workspace_id=workspace.id,
        )
        db.session.add_all([appointment, invoice])
        db.session.flush()
        detail = models.InvoiceDetail(invoice_id=invoice.id, service_id=service.id, price=10.0, quantity=1)
        db.session.add(detail)
        activity = models.ActivityLog(
            module="d3e", action="CREATE", description="synthetic rehearsal row",
            reference_id=customer.id, user_id=requester.id, workspace_id=workspace.id,
        )
        db.session.add(activity)
        db.session.flush()
        manifest.plan("appointment", appointment.id)
        manifest.plan("invoice", invoice.id)
        manifest.plan("invoice_detail", detail.id)
        manifest.plan("activity_log", activity.id)
        db.session.commit()
        manifest.mark_all_persisted()
        if round_context.execution_mode == "PURGE_SERVICE":
            for kind, object_id in (
                ("invoice_detail", detail.id),
                ("appointment", appointment.id),
                ("invoice", invoice.id),
                ("customer", customer.id),
                ("service", service.id),
                ("setting", setting.id),
                ("workspace_member", member.id),
            ):
                manifest.classification_by_key[(kind, object_id)] = SERVICE_DELETION_EXPECTED
        request = services.PurgeRequestService.create_purge_request(
            workspace_id=workspace.id,
            requester_user_id=requester.id,
            confirmation_phrase=f"REQUEST PURGE {workspace.slug}",
            now=datetime(2026, 2, 1),
        )
        services.PurgeRequestService.approve_purge_request(
            request_id=request.id,
            approver_user_id=approver.id,
            confirmation_phrase=f"APPROVE PURGE {workspace.slug} {request.lifecycle_id}",
            now=datetime(2026, 2, 1),
        )
        manifest.register_purge_request(request.id)
        assert_fixture_actor_contract(
            context,
            SyntheticCase(
                request.id, workspace.id, requester.id, approver.id,
                tuple(item[0].id for item in users[2:]),
                tuple(item[1] for item in users[2:]),
                tuple(item[0].username for item in users[2:]), workspace.slug,
            ),
        )
        return SyntheticCase(
            request.id, workspace.id, requester.id, approver.id,
            tuple(item[0].id for item in users[2:]),
            tuple(item[1] for item in users[2:]),
            tuple(item[0].username for item in users[2:]), workspace.slug,
        )


def _service_worker_results(context, plan, operation):
    return run_barrier_workers(context, plan, operation)


def csrf_token_for_client(client):
    client.get(canonical_route_url(client, "auth.login", "GET"))
    with client.session_transaction() as state:
        token = state.get("_csrf_token")
    if not token:
        raise RehearsalGuardError("application did not issue a CSRF token")
    return token


def canonical_route_url(client, endpoint, method, **values):
    """Resolve a browser step only through the registered Flask endpoint contract."""

    rules = tuple(
        rule for rule in client.application.url_map.iter_rules()
        if rule.endpoint == endpoint
    )
    if len(rules) != 1:
        raise RehearsalGuardError(
            f"route contract unavailable: endpoint={endpoint!r} rule_count={len(rules)}"
        )
    rule = rules[0]
    if method.upper() not in rule.methods:
        raise RehearsalGuardError(
            f"route contract method mismatch: endpoint={endpoint!r} method={method.upper()!r}"
        )
    missing = sorted(set(rule.arguments) - set(values))
    if missing:
        raise RehearsalGuardError(
            f"route contract parameters missing: endpoint={endpoint!r} missing={missing!r}"
        )
    from flask import url_for
    with client.application.test_request_context():
        return url_for(endpoint, **values)


def authenticate_executor(client, case, index=0):
    from core.auth.constants import AUTH_SESSION_KEY

    csrf = csrf_token_for_client(client)
    response = client.post(
        canonical_route_url(client, "auth.login", "POST"),
        json={"username": case.executor_usernames[index], "password": case.passwords[index]},
        headers={"X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest"},
    )
    with client.session_transaction() as state:
        authenticated_user_id = state.get(AUTH_SESSION_KEY)
    payload = response.get_json(silent=True) or {}
    if response.status_code not in (200, 302) or authenticated_user_id != case.executor_ids[index]:
        code = payload.get("code") or payload.get("error") or "LOGIN_REJECTED"
        raise AssertionError(
            "real local login failed during rehearsal: "
            f"status={response.status_code} csrf_present={bool(csrf)} "
            f"authenticated_user_match={authenticated_user_id == case.executor_ids[index]} "
            f"code={code}"
        )


def issue_route_transport(client, case):
    csrf = csrf_token_for_client(client)
    confirmation = client.get(canonical_route_url(
        client, "approval.confirm_purge_request", "GET", request_id=case.request_id
    ))
    if confirmation.status_code != 200:
        raise AssertionError("confirmation page was not available")
    response = client.post(
        canonical_route_url(
            client, "approval.reauth_purge_request", "POST", request_id=case.request_id
        ),
        data={"current_password": case.passwords[0], "csrf_token": csrf},
        follow_redirects=False,
    )
    if response.status_code not in (302, 303):
        raise AssertionError("real re-auth issuance failed during rehearsal")


def copy_actual_session_cookie(source, target):
    cookie = source.get_cookie("session")
    if cookie is None:
        raise AssertionError("real session cookie was not issued")
    target.set_cookie(cookie.key, cookie.value, domain=cookie.domain, path=cookie.path)


def execute_route_with_copied_cookie(client, case):
    csrf = csrf_token_for_client(client)
    return client.post(
        canonical_route_url(
            client, "approval.execute_purge_request", "POST", request_id=case.request_id
        ),
        data={
            "confirmation_phrase": f"PURGE WORKSPACE {case.workspace_id} REQUEST {case.request_id}",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )


def run_scenario_a_concurrent_issuance(context, plan, round_context):
    round_number = round_context.round_number
    case = context.fixture_builder.approved_request(context, round_context, executors=2)
    try:
        def issue(label, resource):
            index = 0 if label.endswith("1") else 1
            issuance = context.services.PurgeReauthService.issue_local_authorization(
                case.request_id, case.executor_ids[index], case.passwords[index]
            )
            return WorkerResult("A", round_number, label, "ISSUED", resource[1], issuance.generation, "ACTIVE")
        return _service_worker_results(context, plan, issue)
    finally:
        pass


def run_scenario_b_global_throttle(context, plan, round_context):
    round_number = round_context.round_number
    case = context.fixture_builder.approved_request(context, round_context, executors=1)
    try:
        requests = [context.fixture_builder.approved_request(context, round_context, executors=1) for _ in range(5)]
        def wrong_password(label, resource):
            index = int(label.rsplit("-", 1)[-1]) - 1
            try:
                context.services.PurgeReauthService.issue_local_authorization(
                    requests[index].request_id, case.executor_ids[0], "incorrect-d3e-password"
                )
            except Exception as error:
                return WorkerResult("B", round_number, label, getattr(error, "code", "REAUTH_FAILURE"), resource[1])
            raise AssertionError("wrong password unexpectedly succeeded")
        return _service_worker_results(context, plan, wrong_password)
    finally:
        pass


def run_scenario_c_same_nonce_claim(context, plan, round_context):
    round_number = round_context.round_number
    case = context.fixture_builder.approved_request(context, round_context, executors=1)
    issuance = context.services.PurgeReauthService.issue_local_authorization(
        case.request_id, case.executor_ids[0], case.passwords[0]
    )
    try:
        def claim(label, resource):
            try:
                result = context.services.PurgeReauthService.claim_for_execution(
                    case.request_id, case.workspace_id, case.executor_ids[0], issuance.generation, issuance.raw_nonce
                )
                return WorkerResult("C", round_number, label, "CLAIMED", resource[1], result.generation, "CLAIMED")
            except Exception as error:
                return WorkerResult("C", round_number, label, getattr(error, "code", "REPLAY_FAILURE"), resource[1])
        return _service_worker_results(context, plan, claim)
    finally:
        issuance = None
        pass


def run_scenario_d_concurrent_public_execution(context, plan, round_context):
    round_number = round_context.round_number
    case = context.fixture_builder.approved_request(context, round_context, executors=1)
    issuance = context.services.PurgeReauthService.issue_local_authorization(case.request_id, case.executor_ids[0], case.passwords[0])
    try:
        def execute(label, resource):
            try:
                result = context.services.PurgeService.execute_workspace_purge(
                    request_id=case.request_id, workspace_id=case.workspace_id,
                    executor_user_id=case.executor_ids[0], authorization_generation=issuance.generation,
                    authorization_nonce=issuance.raw_nonce,
                )
                return WorkerResult("D", round_number, label, "COMPLETED", resource[1], result.request_id, "CONSUMED_SUCCESS")
            except Exception as error:
                return WorkerResult("D", round_number, label, getattr(error, "code", "EXECUTION_FAILURE"), resource[1])
        with isolated_purge_execution_flags(context.application):
            return _service_worker_results(context, plan, execute)
    finally:
        issuance = None
        pass


def run_scenario_e_copied_cookie(context, plan, round_context):
    round_number = round_context.round_number
    case = context.fixture_builder.approved_request(context, round_context, executors=1)
    try:
        source = context.application.test_client()
        authenticate_executor(source, case)
        issue_route_transport(source, case)
        clients = [context.application.test_client(), context.application.test_client()]
        copy_actual_session_cookie(source, clients[0])
        copy_actual_session_cookie(source, clients[1])
        def execute(label, resource):
            client = clients[0 if label.endswith("1") else 1]
            response = execute_route_with_copied_cookie(client, case)
            return WorkerResult("E", round_number, label, f"HTTP_{response.status_code}", resource[1])
        with isolated_purge_execution_flags(context.application):
            return _service_worker_results(context, plan, execute)
    finally:
        pass


def run_scenario_f_issuance_vs_claim(context, plan, round_context):
    round_number = round_context.round_number
    case = context.fixture_builder.approved_request(context, round_context, executors=1)
    issuance = context.services.PurgeReauthService.issue_local_authorization(case.request_id, case.executor_ids[0], case.passwords[0])
    try:
        def transition(label, resource):
            if label.endswith("1"):
                try:
                    result = context.services.PurgeReauthService.claim_for_execution(case.request_id, case.workspace_id, case.executor_ids[0], issuance.generation, issuance.raw_nonce)
                    return WorkerResult("F", round_number, label, "CLAIMED", resource[1], result.generation, "CLAIMED")
                except Exception as error:
                    return WorkerResult("F", round_number, label, getattr(error, "code", "CLAIM_FAILURE"), resource[1])
            try:
                result = context.services.PurgeReauthService.issue_local_authorization(case.request_id, case.executor_ids[0], case.passwords[0])
                return WorkerResult("F", round_number, label, "ISSUED", resource[1], result.generation, "ACTIVE")
            except Exception as error:
                return WorkerResult("F", round_number, label, getattr(error, "code", "ISSUANCE_FAILURE"), resource[1])
        return _service_worker_results(context, plan, transition)
    finally:
        issuance = None
        pass


def run_scenario_g_logout_vs_claim(context, plan, round_context):
    round_number = round_context.round_number
    case = context.fixture_builder.approved_request(context, round_context, executors=1)
    issuance = context.services.PurgeReauthService.issue_local_authorization(case.request_id, case.executor_ids[0], case.passwords[0])
    try:
        def revoke_or_claim(label, resource):
            if label.endswith("1"):
                try:
                    result = context.services.PurgeReauthService.claim_for_execution(case.request_id, case.workspace_id, case.executor_ids[0], issuance.generation, issuance.raw_nonce)
                    return WorkerResult("G", round_number, label, "CLAIMED", resource[1], result.generation, "CLAIMED")
                except Exception as error:
                    return WorkerResult("G", round_number, label, getattr(error, "code", "CLAIM_FAILURE"), resource[1])
            client = context.application.test_client()
            csrf = csrf_token_for_client(client)
            response = client.post(
                canonical_route_url(client, "auth.logout", "POST"),
                data={"csrf_token": csrf},
            )
            return WorkerResult("G", round_number, label, f"HTTP_{response.status_code}", resource[1], issuance.generation, "REVOKED")
        return _service_worker_results(context, plan, revoke_or_claim)
    finally:
        issuance = None
        pass


SCENARIO_CALLBACKS = {
    "A": run_scenario_a_concurrent_issuance,
    "B": run_scenario_b_global_throttle,
    "C": run_scenario_c_same_nonce_claim,
    "D": run_scenario_d_concurrent_public_execution,
    "E": run_scenario_e_copied_cookie,
    "F": run_scenario_f_issuance_vs_claim,
    "G": run_scenario_g_logout_vs_claim,
}
