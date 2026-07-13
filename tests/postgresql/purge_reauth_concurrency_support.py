"""Static-safe support primitives for the PostgreSQL d3e concurrency rehearsal.

This module deliberately has no application, engine, session, Docker, or
database imports at module import time. Database-backed workers are opened
only after the strict rehearsal guard passes.
"""

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field
import os
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


@dataclass(frozen=True, slots=True)
class ScenarioPlan:
    name: str
    rounds: int
    workers: int
    synchronization: str
    isolation: str
    acceptable_outcomes: tuple[str, ...]
    forbidden_outcomes: tuple[str, ...]


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
    ),
    "E": ScenarioPlan(
        "E", 5, 2, "threading.Barrier", "two independent Flask clients and sessions",
        ("one copied-cookie winner", "one fail-closed loser"),
        ("shared client object", "double execution", "cookie disclosure"),
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


@dataclass(slots=True)
class CleanupManifest:
    namespace: str
    ids_by_kind: dict[str, set[int]] = field(default_factory=dict)
    namespaces: dict[tuple[str, int], str] = field(default_factory=dict, repr=False)
    lifecycle_by_key: dict[tuple[str, int], str] = field(default_factory=dict, repr=False)

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
            for kind in reversed(tuple(self.ids_by_kind))
            for object_id in sorted(self.ids_by_kind[kind], reverse=True)
            if self.lifecycle_by_key.get((kind, object_id)) == "created"
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

    def __repr__(self):
        return f"RoundContext(scenario={self.scenario!r}, round_number={self.round_number!r})"


def create_round_context(scenario: str, round_number: int, run_namespace: str):
    if scenario not in SCENARIO_PLANS or round_number <= 0 or not run_namespace:
        raise ValueError("invalid rehearsal round context")
    namespace = f"{run_namespace}-{scenario.lower()}-{round_number}"
    return RoundContext(scenario, round_number, namespace, CleanupManifest(namespace))


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


def run_barrier_workers(context, plan: ScenarioPlan, operation):
    """Run real worker callbacks with independent sessions and bounded joins."""

    barrier = threading.Barrier(plan.workers)

    def worker(label):
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
                cleanup_error = error
        if primary_error is not None:
            if cleanup_error is not None:
                raise primary_error from cleanup_error
            raise primary_error
        if cleanup_error is not None:
            raise cleanup_error
    return results


def resolve_scenario_callback(context, code):
    if code not in SCENARIO_CALLBACKS or context.scenario_callbacks.get(code) is not SCENARIO_CALLBACKS[code]:
        raise RehearsalGuardError(f"Scenario {code} is not registered by the harness.")
    callback = context.scenario_callbacks[code]
    if not callable(callback):
        raise RehearsalGuardError(f"Scenario {code} callback is not callable.")
    return callback


def discover_and_register_indirect_rows(context, round_context, request_id, workspace_id, actor_ids=()):
    """Register dependent rows by exact synthetic request/workspace/actor bindings."""
    from sqlalchemy import select

    models = context.models
    db = context.db
    indirect = (
        ("authorization", getattr(models, "WorkspacePurgeExecutionAuthorization", None),
         lambda model: model.purge_request_id == request_id),
        ("throttle", getattr(models, "WorkspacePurgeReauthActorThrottle", None),
         lambda model: model.actor_user_id.in_(tuple(actor_ids))),
        ("lifecycle_event", getattr(models, "PurgeLifecycleEvent", None),
         lambda model: model.request_id == request_id),
        ("activity_log", getattr(models, "ActivityLog", None),
         lambda model: model.workspace_id == workspace_id),
    )
    for kind, model, predicate in indirect:
        if model is None:
            continue
        for row in db.session.execute(select(model).where(predicate(model))).scalars():
            round_context.manifest.register_typed(kind, row.id)


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
    discover_and_register_indirect_rows(
        context, round_context, _manifest_request_id(round_context),
        _manifest_workspace_id(round_context), _manifest_actor_ids(round_context),
    )
    _cleanup_manifest(context, round_context.manifest)
    verify_final_zero_row_state(context, round_context)


def _manifest_request_id(round_context):
    return next(iter(round_context.manifest.ids_by_kind.get("purge_request", {0})))


def _manifest_workspace_id(round_context):
    return next(iter(round_context.manifest.ids_by_kind.get("workspace", {0})))


def _manifest_actor_ids(round_context):
    return round_context.manifest.ids_by_kind.get("user", set())


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
        with engine.begin() as connection:
            database = connection.execute(text("SELECT current_database()")).scalar_one()
            if database != REHEARSAL_DATABASE_NAME:
                raise RehearsalGuardError("Cleanup database identity mismatch.")
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
    client.get("/login")
    with client.session_transaction() as state:
        token = state.get("_csrf_token")
    if not token:
        raise RehearsalGuardError("application did not issue a CSRF token")
    return token


def authenticate_executor(client, case, index=0):
    csrf_token_for_client(client)
    response = client.post(
        "/login",
        json={"username": case.executor_usernames[index], "password": case.passwords[index]},
    )
    if response.status_code not in (200, 302):
        raise AssertionError("real local login failed during rehearsal")


def issue_route_transport(client, case):
    csrf = csrf_token_for_client(client)
    confirmation = client.get(
        f"/approval/purge-requests/{case.request_id}/execute/confirm"
    )
    if confirmation.status_code != 200:
        raise AssertionError("confirmation page was not available")
    response = client.post(
        f"/approval/purge-requests/{case.request_id}/reauth",
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
        f"/approval/purge-requests/{case.request_id}/execute",
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
            response = client.post("/logout", data={"csrf_token": csrf})
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
