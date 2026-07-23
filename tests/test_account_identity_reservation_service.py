from types import SimpleNamespace
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault(
    "TEST_DATABASE_URL",
    f"sqlite:///{(Path(__file__).resolve().parent / 'account_identity_test.db').as_posix()}",
)

from app import app  # noqa: F401
from core.exceptions import NotFoundException, ValidationException
from models.account_purge import AccountIdentityReservation
from models.user import User
from extensions import db
from services.account_identity_reservation_service import (
    AccountIdentityReservationService,
    EMAIL,
    IdentityReservationConflictError,
    USERNAME,
)


@pytest.fixture
def reservation_session():
    engine = create_engine("sqlite:///:memory:")
    db.Model.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    target = User(
        username="target_user",
        email="target@example.test",
        full_name="Target User",
        role="STAFF",
        approval_status="active",
    )
    target.set_password("StrongPassword123!")
    session.add(target)
    session.flush()
    try:
        yield session, target
    finally:
        session.rollback()
        session.close()
        engine.dispose()


def test_identity_normalization_matches_user_creation_contract():
    assert AccountIdentityReservationService.normalize_identity(USERNAME, "  Staff_A  ") == "Staff_A"
    assert AccountIdentityReservationService.normalize_identity(EMAIL, "  STAFF@Example.TEST ") == "staff@example.test"
    with pytest.raises(ValidationException):
        AccountIdentityReservationService.normalize_identity(USERNAME, "  ")


def test_fingerprint_is_deterministic_and_domain_separated():
    username = AccountIdentityReservationService.fingerprint_identity(USERNAME, "same")
    email = AccountIdentityReservationService.fingerprint_identity(EMAIL, "same")
    assert username == AccountIdentityReservationService.fingerprint_identity(USERNAME, " same ")
    assert len(username) == 64
    assert username != email


def test_sqlite_lock_fallback_is_sorted_and_does_not_issue_postgres_sql():
    executed = []

    class Bind:
        dialect = SimpleNamespace(name="sqlite")

    class Session:
        def get_bind(self):
            return Bind()

        def execute(self, *args, **kwargs):
            executed.append((args, kwargs))

    candidates = AccountIdentityReservationService.acquire_identity_creation_locks(
        Session(), username="user", email="USER@example.test"
    )
    assert [(candidate.identity_type, candidate.fingerprint) for candidate in candidates] == sorted(
        (candidate.identity_type, candidate.fingerprint) for candidate in candidates
    )
    assert executed == []


def test_fingerprint_does_not_contain_raw_identity():
    raw = "private-user@example.test"
    fingerprint = AccountIdentityReservationService.fingerprint_identity(EMAIL, raw)
    assert raw not in fingerprint


def test_postgresql_lock_uses_two_signed_advisory_key_parts():
    executed = []

    class Bind:
        dialect = SimpleNamespace(name="postgresql")

    class Session:
        def get_bind(self):
            return Bind()

        def execute(self, statement, params):
            executed.append((str(statement), params))

    AccountIdentityReservationService.acquire_identity_creation_locks(
        Session(), username="user", email="user@example.test"
    )
    assert len(executed) == 2
    assert all("pg_advisory_xact_lock" in statement for statement, _ in executed)
    assert all(set(params) == {"key_high", "key_low"} for _, params in executed)


def test_missing_target_is_typed_and_creates_no_reservation(reservation_session):
    session, _ = reservation_session
    with pytest.raises(NotFoundException) as raised:
        AccountIdentityReservationService.reserve_target_identities_in_transaction(
            session,
            request_id=1,
            target_user_id=9999,
            expected_username="target_user",
        )
    assert raised.value.code == "TARGET_USER_NOT_FOUND"
    assert session.query(AccountIdentityReservation).count() == 0


@pytest.mark.parametrize(
    ("expected_username", "expected_email", "code"),
    [
        ("wrong-user", "target@example.test", "TARGET_USERNAME_MISMATCH"),
        ("target_user", "wrong@example.test", "TARGET_EMAIL_MISMATCH"),
    ],
)
def test_expected_target_identity_mismatch_is_fail_closed(
    reservation_session, expected_username, expected_email, code
):
    session, target = reservation_session
    with pytest.raises(IdentityReservationConflictError) as raised:
        AccountIdentityReservationService.reserve_target_identities_in_transaction(
            session,
            request_id=1,
            target_user_id=target.id,
            expected_username=expected_username,
            expected_email=expected_email,
        )
    assert raised.value.code == code
    assert session.query(AccountIdentityReservation).count() == 0


def test_different_normalized_user_ownership_is_blocked(reservation_session):
    session, target = reservation_session
    other = User(
        username=" target_user ",
        email="other@example.test",
        full_name="Other User",
        role="STAFF",
        approval_status="active",
    )
    other.set_password("StrongPassword123!")
    session.add(other)
    session.flush()
    with pytest.raises(IdentityReservationConflictError) as raised:
        AccountIdentityReservationService.reserve_target_identities_in_transaction(
            session,
            request_id=1,
            target_user_id=target.id,
            expected_username=target.username,
            expected_email=target.email,
        )
    assert raised.value.code == "USERNAME_OWNED_BY_ANOTHER_USER"
    assert session.query(AccountIdentityReservation).count() == 0


def test_different_normalized_email_ownership_is_blocked(reservation_session):
    session, target = reservation_session
    other = User(
        username="other_user",
        email=" TARGET@EXAMPLE.TEST ",
        full_name="Other User",
        role="STAFF",
        approval_status="active",
    )
    other.set_password("StrongPassword123!")
    session.add(other)
    session.flush()
    with pytest.raises(IdentityReservationConflictError) as raised:
        AccountIdentityReservationService.reserve_target_identities_in_transaction(
            session,
            request_id=1,
            target_user_id=target.id,
            expected_username=target.username,
            expected_email=target.email,
        )
    assert raised.value.code == "EMAIL_OWNED_BY_ANOTHER_USER"
    assert session.query(AccountIdentityReservation).count() == 0


def test_target_owned_identities_are_idempotent_and_caller_owns_commit(reservation_session):
    session, target = reservation_session
    before = (target.username, target.email, target.password_hash, target.session_revocation_version)
    first = AccountIdentityReservationService.reserve_target_identities_in_transaction(
        session,
        request_id=1,
        target_user_id=target.id,
        expected_username=target.username,
        expected_email=target.email,
    )
    second = AccountIdentityReservationService.reserve_target_identities_in_transaction(
        session,
        request_id=1,
        target_user_id=target.id,
        expected_username=target.username,
        expected_email=target.email,
    )
    assert second == first
    assert session.query(AccountIdentityReservation).count() == 2
    assert (target.username, target.email, target.password_hash, target.session_revocation_version) == before
    session.rollback()
    assert session.query(AccountIdentityReservation).count() == 0


def test_conflicting_request_is_blocked_and_raw_identity_is_not_persisted(reservation_session):
    session, target = reservation_session
    AccountIdentityReservationService.reserve_target_identities_in_transaction(
        session,
        request_id=1,
        target_user_id=target.id,
        expected_username=target.username,
    )
    with pytest.raises(IdentityReservationConflictError) as raised:
        AccountIdentityReservationService.reserve_target_identities_in_transaction(
            session,
            request_id=2,
            target_user_id=target.id,
            expected_username=target.username,
        )
    assert raised.value.code in {"USERNAME_RESERVED", "EMAIL_RESERVED"}
    assert all(target.username not in repr(row) for row in session.query(AccountIdentityReservation).all())
