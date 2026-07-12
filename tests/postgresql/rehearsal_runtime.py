from dataclasses import dataclass
from types import SimpleNamespace


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
})
EXPECTED_POSTGRES_SERVER_PORT = "5432"
EXPECTED_SCHEMA_TABLES = EXPECTED_APPLICATION_TABLES | {"alembic_version"}
WORKFLOW_TABLES = frozenset({
    "workspace_purge_requests",
    "purge_legal_holds",
    "purge_lifecycle_events",
})


def apply_transaction_timeouts(executor):
    from sqlalchemy import text
    executor.execute(text("SET LOCAL lock_timeout = '2s'"))
    executor.execute(text("SET LOCAL statement_timeout = '30s'"))


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
        if revision_rows != [("0007_permanent_purge_workflow",)]:
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


def create_runtime(target):
    from sqlalchemy.engine import make_url

    from app import app
    from extensions import db

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
    try:
        from models.activity_log import ActivityLog
        from models.appointment import Appointment
        from models.customer import Customer
        from models.invoice import Invoice
        from models.invoice_detail import InvoiceDetail
        from models.purge import PurgeLegalHold, PurgeLifecycleEvent, WorkspacePurgeRequest
        from models.service import Service
        from models.setting import Setting
        from models.user import User
        from models.workspace import Workspace, WorkspaceMember
        from services.purge_request_service import PurgeRequestConflictError, PurgeRequestService
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
                PurgeService=PurgeService,
                UserService=UserService,
            ),
        )
        runtime.identity()
        return runtime
    except Exception:
        try:
            db.session.remove()
        except Exception:
            pass
        try:
            db.engine.dispose()
        except Exception:
            pass
        try:
            app_context.pop()
        except Exception:
            pass
        raise
