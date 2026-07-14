from dataclasses import dataclass
import os
from types import SimpleNamespace

from tests.postgresql.rehearsal_guard import validate_rehearsal_environment


EXPECTED_APPLICATION_TABLES = frozenset({
    "users",
    "customers",
    "services",
    "appointments",
    "invoices",
    "invoice_details",
    "activity_logs",
    "settings",
    "workspaces",
    "workspace_members",
    "workspace_purge_requests",
    "purge_legal_holds",
    "purge_lifecycle_events",
    "workspace_purge_execution_authorizations",
    "workspace_purge_reauth_actor_throttles",
})
EXPECTED_POSTGRES_SERVER_PORT = "5432"
EXPECTED_SCHEMA_TABLES = EXPECTED_APPLICATION_TABLES | {"alembic_version"}
EXPECTED_PURGE_REHEARSAL_REVISION = "0008_durable_purge_reauth_state"
WORKFLOW_TABLES = frozenset({
    "workspace_purge_requests",
    "purge_legal_holds",
    "purge_lifecycle_events",
})


@dataclass
class RehearsalPreflightResult:
    database: str
    role: str
    server_port: str
    revision: str
    table_counts: tuple[tuple[str, int], ...]
    tables_checked: int
    all_tables_zero: bool
    hanging_transactions: int
    connections_closed: bool
    engine_disposed: bool


def apply_transaction_timeouts(executor):
    from sqlalchemy import text
    executor.execute(text("SET LOCAL lock_timeout = '2s'"))
    executor.execute(text("SET LOCAL statement_timeout = '30s'"))


def login_test_client_with_csrf(client, username, password):
    """Log in through the real route and return its post-login CSRF token."""
    login_page = client.get("/login")
    if login_page.status_code != 200:
        return login_page, None
    with client.session_transaction() as session_data:
        login_csrf_token = session_data.get("_csrf_token")
    if not login_csrf_token:
        return login_page, None
    login_response = client.post(
        "/login",
        json={"username": username, "password": password},
        headers={"X-CSRFToken": login_csrf_token},
    )
    if login_response.status_code != 200:
        return login_response, None
    with client.session_transaction() as session_data:
        post_login_csrf_token = session_data.get("_csrf_token")
    return login_response, post_login_csrf_token


def wrap_service_new_session(service_class, monkeypatch):
    import inspect
    static_attr = inspect.getattr_static(service_class, "_new_session")
    is_static = isinstance(static_attr, staticmethod)
    is_class = isinstance(static_attr, classmethod)
    original_func = static_attr.__func__ if (is_static or is_class) else static_attr

    def wrapped(*args, **kwargs):
        session = original_func(*args, **kwargs)
        try:
            apply_transaction_timeouts(session)
            return session
        except Exception:
            try:
                session.rollback()
            except Exception:
                pass
            try:
                session.close()
            except Exception:
                pass
            raise

    if is_static:
        new_descriptor = staticmethod(wrapped)
    elif is_class:
        new_descriptor = classmethod(wrapped)
    else:
        new_descriptor = wrapped

    monkeypatch.setattr(service_class, "_new_session", new_descriptor)


class RehearsalIdentityError(RuntimeError):
    """Raised when the opted-in connection is not the dedicated rehearsal DB."""


class RehearsalDatabaseAuthenticationError(RuntimeError):
    """Raised without exposing the original PostgreSQL authentication error."""


class RehearsalDatabaseConnectionError(RuntimeError):
    """Raised without exposing the original PostgreSQL connection error."""


class RehearsalDatabaseDisposalError(RuntimeError):
    """Raised without exposing an engine disposal error."""


def is_authentication_failure(exc):
    original = getattr(exc, "orig", exc)
    sqlstate = getattr(original, "pgcode", None)
    if sqlstate is None:
        sqlstate = getattr(getattr(original, "diag", None), "sqlstate", None)
    if sqlstate:
        return sqlstate == "28P01"

    diagnostic = str(original).lower()
    return any(
        phrase in diagnostic
        for phrase in ("password authentication failed", "authentication failed")
    )


def _cleanup_runtime_creation(db, app_context):
    if db is not None:
        try:
            db.session.remove()
        except Exception:
            pass
        try:
            db.engine.dispose()
        except Exception:
            pass
    if app_context is not None:
        try:
            app_context.pop()
        except Exception:
            pass


def raise_sanitized_database_error(exc):
    if is_authentication_failure(exc):
        raise RehearsalDatabaseAuthenticationError(
            "LOCAL_REHEARSAL_DATABASE_AUTHENTICATION_FAILED"
        ) from None
    raise RehearsalDatabaseConnectionError(
        "LOCAL_REHEARSAL_DATABASE_CONNECTION_FAILED"
    ) from None


def _create_preflight_engine(database_url):
    from sqlalchemy import create_engine

    return create_engine(
        database_url,
        hide_parameters=True,
        pool_pre_ping=True,
    )


def _preflight_identity(connection, target):
    from sqlalchemy import text

    current_database, current_user, server_port = connection.execute(
        text("SELECT current_database(), current_user, current_setting('port')")
    ).one()
    if current_database != target.database or current_user != "spamanager":
        raise RehearsalIdentityError("PostgreSQL rehearsal database identity mismatch.")
    if target.port != 5433 or str(server_port) != EXPECTED_POSTGRES_SERVER_PORT:
        raise RehearsalIdentityError("PostgreSQL rehearsal server port mismatch.")
    revision_rows = connection.execute(
        text("SELECT version_num FROM alembic_version")
    ).all()
    table_rows = connection.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    ).scalars().all()
    if revision_rows != [(EXPECTED_PURGE_REHEARSAL_REVISION,)]:
        raise RehearsalIdentityError("PostgreSQL rehearsal migration revision mismatch.")
    if set(table_rows) != EXPECTED_SCHEMA_TABLES:
        raise RehearsalIdentityError("PostgreSQL rehearsal table inventory mismatch.")
    return current_database, current_user, str(server_port), revision_rows[0][0]


def run_rehearsal_preflight(environ=None):
    from sqlalchemy import text

    environ = os.environ if environ is None else environ
    target = validate_rehearsal_environment(environ)
    engine = None
    connection = None
    result_data = None
    connection_closed = False
    engine_disposed = False
    try:
        engine = _create_preflight_engine(environ["TEST_DATABASE_URL"])
        connection = engine.connect()
        with connection.begin():
            apply_transaction_timeouts(connection)
            database, role, server_port, revision = _preflight_identity(connection, target)
            counts = {}
            for table_name in sorted(EXPECTED_APPLICATION_TABLES):
                identifier = '"' + table_name.replace('"', '""') + '"'
                counts[table_name] = connection.execute(
                    text(f"SELECT count(*) FROM {identifier}")
                ).scalar_one()
            hanging_transactions = connection.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "AND pid <> pg_backend_pid() "
                    "AND state <> 'idle'"
                )
            ).scalar_one()
        result_data = dict(
            database=database,
            role=role,
            server_port=server_port,
            revision=revision,
            table_counts=tuple(sorted(counts.items())),
            tables_checked=len(counts),
            all_tables_zero=all(value == 0 for value in counts.values()),
            hanging_transactions=hanging_transactions,
        )
    except (RehearsalIdentityError, RehearsalDatabaseAuthenticationError, RehearsalDatabaseConnectionError):
        raise
    except Exception as exc:
        raise_sanitized_database_error(exc)
    finally:
        if connection is not None:
            try:
                connection.close()
                connection_closed = True
            except Exception:
                pass
        if engine is not None:
            try:
                engine.dispose()
                engine_disposed = True
            except Exception:
                raise RehearsalDatabaseDisposalError(
                    "LOCAL_REHEARSAL_DATABASE_DISPOSAL_FAILED"
                ) from None
    if result_data is None:
        return None
    if not connection_closed:
        raise RehearsalDatabaseConnectionError(
            "LOCAL_REHEARSAL_DATABASE_CONNECTION_CLOSE_FAILED"
        ) from None
    if not engine_disposed:
        raise RehearsalDatabaseDisposalError(
            "LOCAL_REHEARSAL_DATABASE_DISPOSAL_FAILED"
        ) from None
    return RehearsalPreflightResult(
        **result_data,
        connections_closed=connection_closed,
        engine_disposed=engine_disposed,
    )


def configure_rehearsal_app(application, target, environ):
    required_gates = (
        "APP_ENV",
        "SPAMANAGER_TEST_PROCESS",
        "SPAMANAGER_ALLOW_POSTGRES_TESTS",
        "SPAMANAGER_RUN_PURGE_POSTGRES_REHEARSAL",
    )
    if any(environ.get(name) != "1" for name in required_gates[1:]):
        raise RehearsalIdentityError("PostgreSQL rehearsal environment gate mismatch.")
    if environ.get("APP_ENV") != "testing" or not environ.get("TEST_DATABASE_URL"):
        raise RehearsalIdentityError("PostgreSQL rehearsal environment gate mismatch.")
    if (
        target.backend != "postgresql"
        or target.host not in {"localhost", "127.0.0.1"}
        or target.port != 5433
        or target.database != "spamanager_purge_rehearsal_test"
    ):
        raise RehearsalIdentityError("PostgreSQL rehearsal target mismatch.")

    application.config["PERMANENT_PURGE_EXECUTION_ENABLED"] = True
    if application.config["PERMANENT_PURGE_EXECUTION_ENABLED"] is not True:
        raise RehearsalIdentityError("PostgreSQL rehearsal execution flag was not enabled safely.")


@dataclass
class PostgresRehearsalRuntime:
    app: object
    db: object
    app_context: object
    engine: object
    target: object
    models: SimpleNamespace
    services: SimpleNamespace

    def _perform_identity_checks(self, active_connection):
        from sqlalchemy import text
        current_database, current_user, server_port = active_connection.execute(
            text("SELECT current_database(), current_user, current_setting('port')")
        ).one()
        if current_database != self.target.database or not current_user:
            raise RehearsalIdentityError("PostgreSQL rehearsal database identity mismatch.")
        if self.target.port != 5433:
            raise RehearsalIdentityError("PostgreSQL rehearsal client port mismatch.")
        if str(server_port) != EXPECTED_POSTGRES_SERVER_PORT:
            raise RehearsalIdentityError("PostgreSQL rehearsal server port mismatch.")
        revision_rows = active_connection.execute(text("SELECT version_num FROM alembic_version")).all()
        if revision_rows != [(EXPECTED_PURGE_REHEARSAL_REVISION,)]:
            raise RehearsalIdentityError("PostgreSQL rehearsal migration revision mismatch.")
        table_rows = active_connection.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        ).scalars().all()
        if set(table_rows) != EXPECTED_SCHEMA_TABLES:
            raise RehearsalIdentityError("PostgreSQL rehearsal table inventory mismatch.")
        column_rows = active_connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'workspaces' "
                "AND column_name IN ('purged_at', 'purge_request_id') "
                "ORDER BY column_name"
            )
        ).scalars().all()
        if column_rows != ["purge_request_id", "purged_at"]:
            raise RehearsalIdentityError("PostgreSQL rehearsal terminal columns mismatch.")
        return {
            "database": current_database,
            "user": current_user,
            "server_port": server_port,
            "revision": revision_rows[0][0],
            "workflow_tables": tuple(sorted(WORKFLOW_TABLES)),
            "terminal_columns": tuple(column_rows),
        }

    def identity(self, connection=None):
        if connection is not None:
            apply_transaction_timeouts(connection)
            return self._perform_identity_checks(connection)
        else:
            with self.engine.begin() as connection:
                apply_transaction_timeouts(connection)
                return self._perform_identity_checks(connection)

    def reset_database(self):
        from sqlalchemy import text

        self.db.session.remove()
        with self.engine.begin() as connection:
            self.identity(connection)
            table_rows = connection.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            ).scalars().all()
            if set(table_rows) != EXPECTED_SCHEMA_TABLES:
                raise RehearsalIdentityError("Refusing reset with an unexpected table inventory.")
            ordered_tables = ", ".join(f'"{name}"' for name in sorted(EXPECTED_APPLICATION_TABLES))
            connection.execute(text(f"TRUNCATE {ordered_tables} RESTART IDENTITY CASCADE"))

    def prepare_scoped_session(self):
        session = self.db.session
        try:
            apply_transaction_timeouts(session)
            return session
        except Exception:
            try:
                session.rollback()
            except Exception:
                pass
            try:
                self.db.session.remove()
            except Exception:
                pass
            raise

    def new_session(self):
        from sqlalchemy.orm import sessionmaker

        session = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)()
        try:
            apply_transaction_timeouts(session)
            return session
        except Exception:
            try:
                session.rollback()
            except Exception:
                pass
            try:
                session.close()
            except Exception:
                pass
            raise

    def close(self):
        self.db.session.remove()
        self.engine.dispose()
        self.app_context.pop()


def create_runtime(target, environ=None):
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import OperationalError

    environ = os.environ if environ is None else environ
    app = None
    db = None
    app_context = None
    try:
        from app import app as flask_app
        from extensions import db as extension_db

        app = flask_app
        db = extension_db
        configure_rehearsal_app(app, target, environ)
        configured_url = make_url(app.config["SQLALCHEMY_DATABASE_URI"])
        if (
            configured_url.get_backend_name() != target.backend
            or configured_url.host != target.host
            or configured_url.port != target.port
            or configured_url.database != target.database
            or configured_url.query
        ):
            raise RehearsalIdentityError("Application database target does not match the validated rehearsal target.")

        app_context = app.app_context()
        app_context.push()
        from models.activity_log import ActivityLog
        from models.appointment import Appointment
        from models.customer import Customer
        from models.invoice import Invoice
        from models.invoice_detail import InvoiceDetail
        from models.purge import (
            PurgeLegalHold,
            PurgeLifecycleEvent,
            WorkspacePurgeExecutionAuthorization,
            WorkspacePurgeReauthActorThrottle,
            WorkspacePurgeRequest,
        )
        from models.service import Service
        from models.setting import Setting
        from models.user import User
        from models.workspace import Workspace, WorkspaceMember
        from services.purge_legal_hold_service import PurgeLegalHoldService
        from services.purge_request_service import PurgeRequestConflictError, PurgeRequestService
        from services.purge_reauth_service import PurgeReauthService
        from services.purge_service import PurgeExecutionError, PurgeService
        from services.user_service import UserService

        runtime = PostgresRehearsalRuntime(
            app=app,
            db=db,
            app_context=app_context,
            engine=db.engine,
            target=target,
            models=SimpleNamespace(
                ActivityLog=ActivityLog,
                Appointment=Appointment,
                Customer=Customer,
                Invoice=Invoice,
                InvoiceDetail=InvoiceDetail,
                PurgeLegalHold=PurgeLegalHold,
                PurgeLifecycleEvent=PurgeLifecycleEvent,
                WorkspacePurgeExecutionAuthorization=WorkspacePurgeExecutionAuthorization,
                WorkspacePurgeReauthActorThrottle=WorkspacePurgeReauthActorThrottle,
                Setting=Setting,
                Service=Service,
                User=User,
                Workspace=Workspace,
                WorkspaceMember=WorkspaceMember,
                WorkspacePurgeRequest=WorkspacePurgeRequest,
            ),
            services=SimpleNamespace(
                PurgeExecutionError=PurgeExecutionError,
                PurgeRequestConflictError=PurgeRequestConflictError,
                PurgeRequestService=PurgeRequestService,
                PurgeLegalHoldService=PurgeLegalHoldService,
                PurgeReauthService=PurgeReauthService,
                PurgeService=PurgeService,
                UserService=UserService,
            ),
        )
        runtime.identity()
        return runtime
    except OperationalError as exc:
        _cleanup_runtime_creation(db, app_context)
        raise_sanitized_database_error(exc)
    except Exception:
        _cleanup_runtime_creation(db, app_context)
        raise
