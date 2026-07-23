"""Functional PostgreSQL rehearsal for account-identity reservations."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
from threading import Barrier, Event

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError


pytestmark = pytest.mark.postgres_rehearsal

PASSWORD = "StrongPassword123!"


@pytest.fixture
def reservation_case(postgres_runtime):
    postgres_runtime.reset_database()
    runtime = postgres_runtime
    models = runtime.models
    from models.account_purge import (
        AccountIdentityReservation,
        AccountPurgeAvatarCleanup,
        AccountPurgeExecutionAuthorization,
        AccountPurgeLegalHold,
        AccountPurgeLifecycleEvent,
        AccountPurgeRequest,
        UserCreationProvenance,
    )
    models.AccountIdentityReservation = AccountIdentityReservation
    models.AccountPurgeAvatarCleanup = AccountPurgeAvatarCleanup
    models.AccountPurgeExecutionAuthorization = AccountPurgeExecutionAuthorization
    models.AccountPurgeLegalHold = AccountPurgeLegalHold
    models.AccountPurgeLifecycleEvent = AccountPurgeLifecycleEvent
    models.AccountPurgeRequest = AccountPurgeRequest
    models.UserCreationProvenance = UserCreationProvenance
    session = runtime.prepare_scoped_session()

    workspace = models.Workspace(
        name="Identity Reservation PostgreSQL",
        slug="identity-reservation-rehearsal",
        status="active",
    )
    owner = _user(models, "reservation_owner", "OWNER")
    target = _user(models, "reservation_target", "STAFF")
    session.add_all([workspace, owner, target])
    session.flush()
    workspace.created_by_id = owner.id
    session.add_all([
        models.WorkspaceMember(
            workspace_id=workspace.id,
            user_id=owner.id,
            role="owner",
            status="active",
        ),
        models.WorkspaceMember(
            workspace_id=workspace.id,
            user_id=target.id,
            role="staff",
            status="removed",
            removed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        models.UserCreationProvenance(
            user_id=target.id,
            created_by_user_id=owner.id,
            created_in_workspace_id=workspace.id,
            creation_source="WORKSPACE_OWNER",
            created_role="STAFF",
            provenance_version=1,
        ),
    ])
    request = models.AccountPurgeRequest(
        target_user_id=target.id,
        managing_workspace_id=workspace.id,
        requester_id=owner.id,
        requester_name_snapshot=owner.full_name,
        requester_email_snapshot=owner.email,
        requester_role_snapshot=owner.role,
        target_username_snapshot=target.username,
        target_email_snapshot=target.email,
        target_role_snapshot=target.role,
        target_auth_provider_snapshot=target.auth_provider,
        state="REQUESTED",
        reason="identity reservation rehearsal",
    )
    session.add(request)
    session.commit()
    case = {
        "runtime": runtime,
        "models": models,
        "workspace_id": workspace.id,
        "owner_id": owner.id,
        "target_id": target.id,
        "request_id": request.id,
    }
    try:
        yield case
    finally:
        runtime.reset_database()


def _user(models, username, role):
    user = models.User(
        username=username,
        email=f"{username}@example.test",
        full_name=username.replace("_", " ").title(),
        role=role,
        is_active=True,
        approval_status="active",
    )
    user.set_password(PASSWORD)
    return user


def _service(case):
    return case["runtime"].services.UserService


def _reservation_service():
    from services.account_identity_reservation_service import (
        AccountIdentityReservationService,
    )

    return AccountIdentityReservationService


def _reservation_constants():
    from services.account_identity_reservation_service import FINGERPRINT_VERSION, USERNAME

    return USERNAME, FINGERPRINT_VERSION


def _reservation_model(case):
    return case["models"].AccountIdentityReservation


def _reserve(case, username, *, request_id=None, target_user_id=None, email=None, commit=True):
    runtime = case["runtime"]
    db_session = runtime.new_session()
    try:
        rows = _reservation_service().reserve_target_identities_in_transaction(
            db_session,
            request_id=request_id or case["request_id"],
            target_user_id=target_user_id or case["target_id"],
            expected_username=username,
            expected_email=email,
        )
        if commit:
            db_session.commit()
        return rows
    except Exception:
        db_session.rollback()
        raise
    finally:
        db_session.close()


def _seed_reservation(case, username, *, email=None):
    runtime = case["runtime"]
    session = runtime.new_session()
    try:
        service = _reservation_service()
        values = [("USERNAME", username)]
        if email is not None:
            values.append(("EMAIL", email))
        rows = [
            _reservation_model(case)(
                target_user_id=case["target_id"],
                request_id=case["request_id"],
                identity_type=identity_type,
                identity_fingerprint=service.fingerprint_identity(identity_type, value),
                fingerprint_version=1,
                created_at=datetime.now(timezone.utc),
            )
            for identity_type, value in values
        ]
        session.add_all(rows)
        session.commit()
    finally:
        session.close()


def _create(case, username, *, email=None, actor_id=None, workspace_id=None):
    from flask import session as flask_session

    from tests.session_helpers import set_authenticated_session

    runtime = case["runtime"]
    actor_id = actor_id or case["owner_id"]
    workspace_id = workspace_id or case["workspace_id"]
    with runtime.app.test_request_context():
        actor = runtime.db.session.get(case["models"].User, actor_id)
        set_authenticated_session(
            flask_session,
            actor,
            workspace_id=workspace_id,
            enable_workspace_isolation=True,
        )
        return _service(case).create_user(
            actor=actor,
            username=username,
            full_name="Reserved Test User",
            password=PASSWORD,
            email=email or f"{username}@example.test",
            role="STAFF",
        )


def _counts(case, username):
    models = case["models"]
    session = case["runtime"].new_session()
    try:
        user = session.query(models.User).filter_by(username=username).one_or_none()
        user_id = user.id if user else -1
        return {
            "users": session.query(models.User).filter_by(username=username).count(),
            "memberships": session.query(models.WorkspaceMember).filter_by(user_id=user_id).count(),
            "provenance": session.query(models.UserCreationProvenance).filter_by(user_id=user_id).count(),
            "audit": session.query(models.ActivityLog).filter_by(
                module="Users",
                action="CREATE_USER",
                reference_id=user_id,
            ).count(),
        }
    finally:
        session.rollback()
        session.close()


def _active_reservations(case, identity_type=None):
    session = case["runtime"].new_session()
    try:
        query = session.query(_reservation_model(case)).filter(
            _reservation_model(case).released_at.is_(None)
        )
        if identity_type:
            query = query.filter_by(identity_type=identity_type)
        return query.count()
    finally:
        session.rollback()
        session.close()


def _worker_context(case, callback):
    runtime = case["runtime"]
    with runtime.app.app_context():
        worker_session = runtime.db.session
        try:
            owner = worker_session.get(case["models"].User, case["owner_id"])
            workspace = worker_session.get(case["models"].Workspace, case["workspace_id"])
            if owner is None or workspace is None:
                raise RuntimeError("POSTGRES_REHEARSAL_WORKER_PREREQUISITE_MISSING")
            worker_session.rollback()
            return callback()
        finally:
            worker_session.rollback()
            worker_session.remove()


def _safe_worker_diagnostic(worker_index, *, category, result=None, exc=None):
    diagnostic = {
        "worker_index": worker_index,
        "outcome_category": category,
        "exception_class": None,
        "exception_module": None,
        "public_error_code": None,
        "sqlstate": None,
        "safe_database_category": None,
        "safe_exception_message": None,
    }
    if exc is None:
        return diagnostic
    diagnostic["exception_class"] = type(exc).__name__
    diagnostic["exception_module"] = type(exc).__module__
    diagnostic["public_error_code"] = getattr(exc, "code", None)
    first_line = str(exc).splitlines()[0] if str(exc) else ""
    if first_line == "Working outside of application context.":
        diagnostic["safe_exception_message"] = first_line
    if isinstance(exc, SQLAlchemyError):
        original = getattr(exc, "orig", None)
        diagnostic["sqlstate"] = getattr(original, "sqlstate", None) or getattr(
            original, "pgcode", None
        )
        diagnostic["safe_database_category"] = (
            "integrity" if isinstance(exc, IntegrityError) else "database"
        )
    return diagnostic


def _run_workers(callbacks, *, diagnostics=False):
    outcomes, errors = [], []
    with ThreadPoolExecutor(max_workers=len(callbacks)) as pool:
        futures = [pool.submit(callback) for callback in callbacks]
        for worker_index, future in enumerate(futures):
            try:
                result = future.result(timeout=12)
                outcomes.append(result)
                if diagnostics:
                    errors.append(
                        _safe_worker_diagnostic(
                            worker_index, category="SUCCESS", result=result
                        )
                    )
            except FutureTimeoutError as exc:
                future.cancel()
                if diagnostics:
                    errors.append(
                        _safe_worker_diagnostic(
                            worker_index, category="TIMEOUT", exc=exc
                        )
                    )
                else:
                    errors.append(exc)
            except Exception as exc:
                if diagnostics:
                    from core.exceptions import BusinessException

                    category = (
                        "DOMAIN_ERROR"
                        if isinstance(exc, BusinessException)
                        else "DATABASE_ERROR"
                        if isinstance(exc, SQLAlchemyError)
                        else "HARNESS_ERROR"
                    )
                    errors.append(
                        _safe_worker_diagnostic(worker_index, category=category, exc=exc)
                    )
                else:
                    errors.append(exc)
    return outcomes, errors


def test_node_01_active_username_reservation_blocks_create(reservation_case):
    from services.account_identity_reservation_service import IdentityReservationConflictError

    _seed_reservation(reservation_case, "blocked_username")
    with pytest.raises(IdentityReservationConflictError) as raised:
        _create(reservation_case, "blocked_username")
    assert raised.value.code == "USERNAME_RESERVED"
    assert _counts(reservation_case, "blocked_username") == {
        "users": 0,
        "memberships": 0,
        "provenance": 0,
        "audit": 0,
    }
    assert _active_reservations(reservation_case, "USERNAME") == 1


def test_node_02_active_email_reservation_blocks_create(reservation_case):
    from services.account_identity_reservation_service import IdentityReservationConflictError

    _seed_reservation(reservation_case, "email_target", email="reserved@example.test")
    with pytest.raises(IdentityReservationConflictError) as raised:
        _create(reservation_case, "email_target", email=" RESERVED@EXAMPLE.TEST ")
    assert raised.value.code == "EMAIL_RESERVED"
    assert _counts(reservation_case, "email_target")["users"] == 0
    assert _active_reservations(reservation_case, "EMAIL") == 1


def test_node_03_released_reservation_permits_create(reservation_case):
    runtime = reservation_case["runtime"]
    session = runtime.new_session()
    try:
        service = _reservation_service()
        username_type, fingerprint_version = _reservation_constants()
        rows = [
            _reservation_model(reservation_case)(
                target_user_id=reservation_case["target_id"],
                request_id=reservation_case["request_id"],
                identity_type=username_type,
                identity_fingerprint=service.fingerprint_identity(username_type, "released_identity"),
                fingerprint_version=fingerprint_version,
                created_at=datetime.now(timezone.utc),
                released_at=datetime.now(timezone.utc),
                release_reason="rehearsal",
            )
        ]
        session.add_all(rows)
        session.commit()
    finally:
        session.close()
    created = _create(reservation_case, "released_identity")
    assert created.username == "released_identity"
    assert _counts(reservation_case, "released_identity")["users"] == 1
    assert _active_reservations(reservation_case, "USERNAME") == 0


def test_node_04_target_identity_ownership_is_enforced(reservation_case):
    from services.account_identity_reservation_service import IdentityReservationConflictError

    runtime = reservation_case["runtime"]
    models = reservation_case["models"]
    service = _reservation_service()
    session = runtime.new_session()
    try:
        target = session.get(models.User, reservation_case["target_id"])
        before = (target.username, target.email, target.password_hash)

        with pytest.raises(IdentityReservationConflictError) as raised:
            service.reserve_target_identities_in_transaction(
                session,
                request_id=reservation_case["request_id"],
                target_user_id=target.id,
                expected_username="wrong-target-username",
                expected_email=target.email,
            )
        assert raised.value.code == "TARGET_USERNAME_MISMATCH"
        assert session.query(_reservation_model(reservation_case)).count() == 0

        with pytest.raises(IdentityReservationConflictError) as raised:
            service.reserve_target_identities_in_transaction(
                session,
                request_id=reservation_case["request_id"],
                target_user_id=target.id,
                expected_username=target.username,
                expected_email="wrong-target@example.test",
            )
        assert raised.value.code == "TARGET_EMAIL_MISMATCH"
        assert session.query(_reservation_model(reservation_case)).count() == 0

        other = _user(models, f" {target.username} ", "STAFF")
        other.email = f" {target.email.upper()} "
        session.add(other)
        session.flush()
        with pytest.raises(IdentityReservationConflictError) as raised:
            service.reserve_target_identities_in_transaction(
                session,
                request_id=reservation_case["request_id"],
                target_user_id=target.id,
                expected_username=target.username,
                expected_email=target.email,
            )
        assert raised.value.code == "USERNAME_OWNED_BY_ANOTHER_USER"
        assert session.query(_reservation_model(reservation_case)).count() == 0
        assert (target.username, target.email, target.password_hash) == before
        assert other.username.strip() == target.username
        session.rollback()

        other_email = _user(models, "identity-email-owner", "STAFF")
        other_email.email = f" {target.email.upper()} "
        session.add(other_email)
        session.flush()
        with pytest.raises(IdentityReservationConflictError) as raised:
            service.reserve_target_identities_in_transaction(
                session,
                request_id=reservation_case["request_id"],
                target_user_id=target.id,
                expected_username=target.username,
                expected_email=target.email,
            )
        assert raised.value.code == "EMAIL_OWNED_BY_ANOTHER_USER"
        assert session.query(_reservation_model(reservation_case)).count() == 0
        session.rollback()
    finally:
        session.close()

    rows = _reserve(
        reservation_case,
        "reservation_target",
        email="reservation_target@example.test",
    )
    assert len(rows) == 2
    assert _active_reservations(reservation_case) == 2


def test_node_05_concurrent_create_same_identity_has_one_winner(reservation_case):
    barrier = Barrier(2)
    username = "concurrent_create"

    def worker():
        def call():
            barrier.wait(timeout=5)
            return _create(reservation_case, username)

        return _worker_context(reservation_case, call)

    outcomes, worker_results = _run_workers([worker, worker], diagnostics=True)
    assert len(worker_results) == 2, worker_results
    assert len(outcomes) == 1, worker_results
    assert sorted(item["outcome_category"] for item in worker_results) == [
        "DOMAIN_ERROR",
        "SUCCESS",
    ], worker_results
    loser = next(item for item in worker_results if item["outcome_category"] == "DOMAIN_ERROR")
    assert loser["exception_class"] == "ValidationException", worker_results
    assert loser["public_error_code"] == "VALIDATION_ERROR", worker_results
    assert _counts(reservation_case, username) == {
        "users": 1,
        "memberships": 1,
        "provenance": 1,
        "audit": 1,
    }


def test_node_06_same_request_target_reservation_is_idempotent(reservation_case):
    service = _reservation_service()
    runtime = reservation_case["runtime"]
    session = runtime.new_session()
    try:
        first = service.reserve_target_identities_in_transaction(
            session,
            request_id=reservation_case["request_id"],
            target_user_id=reservation_case["target_id"],
            expected_username="reservation_target",
        )
        second = service.reserve_target_identities_in_transaction(
            session,
            request_id=reservation_case["request_id"],
            target_user_id=reservation_case["target_id"],
            expected_username="reservation_target",
        )
        assert first[0].id is not None
        assert second[0] is first[0]
        session.commit()
    finally:
        session.close()
    assert _active_reservations(reservation_case, "USERNAME") == 1
    assert "same_owner" not in repr(second[0])


def test_node_07_conflicting_reservation_ownership_has_one_winner(reservation_case):
    runtime = reservation_case["runtime"]
    models = reservation_case["models"]
    session = runtime.new_session()
    try:
        original = session.get(models.AccountPurgeRequest, reservation_case["request_id"])
        competing = models.AccountPurgeRequest(
            target_user_id=original.target_user_id,
            managing_workspace_id=original.managing_workspace_id,
            requester_id=original.requester_id,
            requester_name_snapshot=original.requester_name_snapshot,
            requester_email_snapshot=original.requester_email_snapshot,
            requester_role_snapshot=original.requester_role_snapshot,
            target_username_snapshot=original.target_username_snapshot,
            target_email_snapshot=original.target_email_snapshot,
            target_role_snapshot=original.target_role_snapshot,
            target_auth_provider_snapshot=original.target_auth_provider_snapshot,
            state="CANCELLED",
            reason="conflicting ownership historical request",
            cancelled_at=datetime.now(timezone.utc),
            cancellation_reason="superseded before identity reservation rehearsal",
            terminal_at=datetime.now(timezone.utc),
        )
        session.add(competing)
        session.commit()
        request_ids = (original.id, competing.id)
    finally:
        session.close()
    barrier = Barrier(2)

    def worker(request_id):
        def call():
            barrier.wait(timeout=5)
            return _reserve(
                reservation_case,
                "reservation_target",
                email="reservation_target@example.test",
                request_id=request_id,
                target_user_id=reservation_case["target_id"],
            )

        return call()

    outcomes, worker_results = _run_workers([
        lambda: worker(request_ids[0]),
        lambda: worker(request_ids[1]),
    ], diagnostics=True)
    assert len(outcomes) == 1
    assert len(worker_results) == 2, worker_results
    assert sorted(item["outcome_category"] for item in worker_results) == [
        "DOMAIN_ERROR",
        "SUCCESS",
    ], worker_results
    loser = next(item for item in worker_results if item["outcome_category"] == "DOMAIN_ERROR")
    assert loser["exception_class"] == "IdentityReservationConflictError", worker_results
    assert loser["public_error_code"] in {"USERNAME_RESERVED", "EMAIL_RESERVED"}, worker_results
    assert _active_reservations(reservation_case, "USERNAME") == 1


def test_node_08_advisory_lock_releases_after_rollback(reservation_case):
    service = _reservation_service()
    runtime = reservation_case["runtime"]
    holder_started = Event()
    competitor_acquired = Event()
    release_holder = Event()
    username = "rollback_lock"

    def holder():
        session = runtime.new_session()
        try:
            service.acquire_identity_locks(session, username=username)
            holder_started.set()
            assert release_holder.wait(timeout=5)
            session.rollback()
            return "rolled_back"
        finally:
            session.close()

    def competitor():
        assert holder_started.wait(timeout=5)
        session = runtime.new_session()
        try:
            service.acquire_identity_locks(session, username=username)
            competitor_acquired.set()
            session.rollback()
            return "acquired_after_rollback"
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        holder_future = pool.submit(holder)
        assert holder_started.wait(timeout=5)
        competitor_future = pool.submit(competitor)
        assert not competitor_acquired.wait(timeout=0.5)
        release_holder.set()
        assert holder_future.result(timeout=8) == "rolled_back"
        assert competitor_future.result(timeout=8) == "acquired_after_rollback"


def test_node_09_username_email_lock_order_does_not_deadlock(reservation_case):
    service = _reservation_service()
    runtime = reservation_case["runtime"]
    barrier = Barrier(2)

    def worker(username, email):
        def call():
            barrier.wait(timeout=5)
            session = runtime.new_session()
            try:
                candidates = service.acquire_identity_locks(
                    session, username=username, email=email
                )
                session.rollback()
                return [(item.identity_type, item.fingerprint) for item in candidates]
            finally:
                session.close()

        return call()

    outcomes, errors = _run_workers([
        lambda: worker("ordered_user", "ordered@example.test"),
        lambda: worker("ordered_user", "ordered@example.test"),
    ])
    assert errors == []
    assert len(outcomes) == 2
    assert outcomes[0] == outcomes[1]
    assert [item[0] for item in outcomes[0]] == ["EMAIL", "USERNAME"]


def test_node_10_blocked_create_leaves_no_residue(reservation_case):
    from services.account_identity_reservation_service import IdentityReservationConflictError

    username = "blocked_residue"
    _seed_reservation(reservation_case, username)
    with pytest.raises(IdentityReservationConflictError):
        _create(reservation_case, username)
    assert _counts(reservation_case, username) == {
        "users": 0,
        "memberships": 0,
        "provenance": 0,
        "audit": 0,
    }


def test_node_11_helper_has_no_execution_or_anonymization_side_effect(reservation_case):
    models = reservation_case["models"]
    runtime = reservation_case["runtime"]
    session = runtime.new_session()
    try:
        target = session.get(models.User, reservation_case["target_id"])
        request = session.get(models.AccountPurgeRequest, reservation_case["request_id"])
        before = {
            "username": target.username,
            "email": target.email,
            "password_hash": target.password_hash,
            "avatar": target.avatar,
            "is_active": target.is_active,
            "account_purge_state": target.account_purge_state,
            "session_revocation_version": target.session_revocation_version,
            "request_state": request.state,
            "execution_started_at": request.execution_started_at,
            "execution_completed_at": request.execution_completed_at,
        }
        _reservation_service().reserve_target_identities_in_transaction(
            session,
            request_id=request.id,
            target_user_id=target.id,
            expected_username=target.username,
            expected_email=target.email,
        )
        session.rollback()
        session.expire_all()
        target = session.get(models.User, target.id)
        request = session.get(models.AccountPurgeRequest, request.id)
        after = {
            "username": target.username,
            "email": target.email,
            "password_hash": target.password_hash,
            "avatar": target.avatar,
            "is_active": target.is_active,
            "account_purge_state": target.account_purge_state,
            "session_revocation_version": target.session_revocation_version,
            "request_state": request.state,
            "execution_started_at": request.execution_started_at,
            "execution_completed_at": request.execution_completed_at,
        }
        assert after == before
        assert session.query(models.AccountPurgeAvatarCleanup).count() == 0
        assert session.query(models.AccountPurgeLifecycleEvent).count() == 0
    finally:
        session.rollback()
        session.close()


def test_node_12_cleanup_leaves_revision_0010_without_fixture_residue(reservation_case):
    from sqlalchemy import text

    runtime = reservation_case["runtime"]
    models = reservation_case["models"]
    runtime.reset_database()
    session = runtime.new_session()
    try:
        revision = session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        assert revision == "0010_account_purge_foundation"
        for model in (
            models.User,
            models.WorkspaceMember,
            models.UserCreationProvenance,
            models.ActivityLog,
            models.AccountIdentityReservation,
            models.AccountPurgeRequest,
            models.AccountPurgeLifecycleEvent,
            models.AccountPurgeLegalHold,
            models.AccountPurgeExecutionAuthorization,
            models.AccountPurgeAvatarCleanup,
        ):
            assert session.query(model).count() == 0
    finally:
        session.rollback()
        session.close()
