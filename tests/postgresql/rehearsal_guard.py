from collections.abc import Mapping
from dataclasses import dataclass
import sys

from sqlalchemy.engine import make_url


REHEARSAL_DATABASE_NAME = "spamanager_purge_rehearsal_test"
REHEARSAL_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1"})
REHEARSAL_PORT = 5433
REHEARSAL_OPT_IN_ENV = "SPAMANAGER_RUN_PURGE_POSTGRES_REHEARSAL"


class RehearsalGuardError(RuntimeError):
    """Raised when the dedicated PostgreSQL rehearsal target is unsafe."""


@dataclass(frozen=True, slots=True)
class RehearsalTarget:
    backend: str
    host: str
    port: int
    database: str


def is_rehearsal_requested(environ: Mapping[str, object]) -> bool:
    return environ.get(REHEARSAL_OPT_IN_ENV) == "1"


def _require_exact_marker(environ, name):
    if environ.get(name) != "1":
        raise RehearsalGuardError(f"{name} must be exactly 1.")


def validate_rehearsal_environment(environ: Mapping[str, object]) -> RehearsalTarget:
    if environ.get("APP_ENV") != "testing":
        raise RehearsalGuardError("APP_ENV must be exactly testing.")
    _require_exact_marker(environ, "SPAMANAGER_TEST_PROCESS")
    _require_exact_marker(environ, "SPAMANAGER_ALLOW_POSTGRES_TESTS")
    _require_exact_marker(environ, REHEARSAL_OPT_IN_ENV)

    database_url = environ.get("TEST_DATABASE_URL")
    if not isinstance(database_url, str) or not database_url.strip():
        raise RehearsalGuardError("TEST_DATABASE_URL must be a non-empty string.")
    if database_url != database_url.strip():
        raise RehearsalGuardError("TEST_DATABASE_URL must not have surrounding whitespace.")
    try:
        parsed_url = make_url(database_url)
    except Exception as exc:
        raise RehearsalGuardError("TEST_DATABASE_URL is not a valid database URL.") from None

    if parsed_url.query:
        raise RehearsalGuardError("TEST_DATABASE_URL must not contain query parameters.")

    if parsed_url.get_backend_name() != "postgresql":
        raise RehearsalGuardError("TEST_DATABASE_URL must use the PostgreSQL backend.")
    if parsed_url.host not in REHEARSAL_ALLOWED_HOSTS:
        raise RehearsalGuardError("TEST_DATABASE_URL host is not an approved local rehearsal host.")
    if parsed_url.port != REHEARSAL_PORT:
        raise RehearsalGuardError("TEST_DATABASE_URL port must be 5433.")
    if parsed_url.database != REHEARSAL_DATABASE_NAME:
        raise RehearsalGuardError("TEST_DATABASE_URL database is not the dedicated rehearsal database.")

    return RehearsalTarget(
        backend=parsed_url.get_backend_name(),
        host=parsed_url.host,
        port=parsed_url.port,
        database=parsed_url.database,
    )


def ensure_fresh_process() -> None:
    if "app" in sys.modules or "extensions" in sys.modules:
        raise RehearsalGuardError(
            "Run the dedicated PostgreSQL test path in a fresh pytest process."
        )
