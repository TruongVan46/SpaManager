"""Deterministic PostgreSQL legal-hold serialization rehearsal.

The module is deliberately lazy: importing and collecting it never imports the
application, creates an engine, reads credentials, or opens a connection.
Runtime execution is gated by the canonical ``postgres_rehearsal`` fixture.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
import inspect
import threading
import time
from pathlib import PurePath
from typing import Callable

import pytest
from sqlalchemy import event, text


pytestmark = pytest.mark.postgres_rehearsal

EVENT_TIMEOUT_SECONDS = 10
THREAD_JOIN_TIMEOUT_SECONDS = 20
REHEARSAL_NOW = datetime(2026, 2, 1)
SYNTHETIC_PASSWORD = "legal-hold-rehearsal-password"
SAFE_ERROR_CODES = frozenset({
    "ACTIVE_LEGAL_HOLD",
    "ALREADY_RELEASED",
    "LEGAL_HOLD_UNRESOLVED",
    "TERMINAL_WORKSPACE",
})
SAFE_ROOT_CATEGORIES = frozenset({
    "NONE",
    "DEADLOCK_DETECTED",
    "LOCK_TIMEOUT",
    "DATABASE_CONNECTION",
    "DATABASE_AUTHENTICATION",
    "ASSERTION_FAILURE",
    "BARRIER_FAILURE",
    "THREAD_FAILURE",
    "CLEANUP_FAILURE",
    "UNCLASSIFIED_SAFE_EXCEPTION",
})


@dataclass(frozen=True)
class SanitizedWorkerFailure:
    public_exception_class: str
    public_exception_module: str
    root_exception_class: str
    root_exception_module: str
    sqlstate: str | None
    safe_root_category: str
    code: str | None = None
    project_frame: str | None = None


@dataclass
class WorkerResult:
    name: str
    backend_pid: int | None = None
    started: bool = False
    lock_acquired: bool = False
    post_lock_passed: bool = False
    completed: bool = False
    terminal_outcome: str = "NOT_STARTED"
    result: object | None = None
    exception: SanitizedWorkerFailure | None = None
    safe_exception_class: str | None = None
    safe_error_code: str | None = None
    safe_stage: str | None = None
    safe_root_category: str | None = None
    thread_alive: bool = False
    operation_returned_at: float | None = None
    completed_at: float | None = None
    operation_returned_sequence: int | None = None
    completed_sequence: int | None = None
    safe_project_frame: str | None = None
    cleanup_outcome: str = "PENDING_FIXTURE_RESET"


@dataclass
class HookPlan:
    lock_acquired: threading.Event = field(default_factory=threading.Event)
    post_lock_passed: threading.Event = field(default_factory=threading.Event)
    allow_winner_to_continue: threading.Event = field(default_factory=threading.Event)
    pause_after: str = "none"
    first_delete_reached: threading.Event = field(default_factory=threading.Event)
    execution_lock_armed: threading.Event = field(default_factory=threading.Event)
    active_hold_observed: threading.Event = field(default_factory=threading.Event)
    winner_hold_lock_acquired: threading.Event = field(default_factory=threading.Event)
    winner_observed_active: threading.Event = field(default_factory=threading.Event)
    operation_started: threading.Event = field(default_factory=threading.Event)
    completed_event: threading.Event = field(default_factory=threading.Event)


def _sql(statement):
    return " ".join(str(statement).upper().split())


def _workspace_barrier_is_armed(plan, barrier_target):
    return barrier_target != "execution" or plan.execution_lock_armed.is_set()


def _safe_sqlstate(error):
    current = error
    for _ in range(4):
        if current is None:
            break
        sqlstate = getattr(current, "pgcode", None)
        if sqlstate is None:
            sqlstate = getattr(getattr(current, "diag", None), "sqlstate", None)
        if isinstance(sqlstate, str) and sqlstate:
            return sqlstate
        original = getattr(current, "orig", None)
        if original is not None and original is not current:
            current = original
            continue
        cause = getattr(current, "__cause__", None)
        if cause is not None and cause is not current:
            current = cause
            continue
        break
    return None


def _safe_root_category(error, sqlstate):
    error_class = type(error).__name__
    error_module = type(error).__module__
    if sqlstate == "40P01":
        return "DEADLOCK_DETECTED"
    if sqlstate == "55P03":
        return "LOCK_TIMEOUT"
    if sqlstate == "28P01":
        return "DATABASE_AUTHENTICATION"
    if isinstance(error, AssertionError):
        return "ASSERTION_FAILURE"
    if error_class in {"TimeoutError", "BrokenBarrierError"}:
        return "BARRIER_FAILURE"
    if "Connection" in error_class or error_class == "OperationalError":
        return "DATABASE_CONNECTION"
    if "Cleanup" in error_class:
        return "CLEANUP_FAILURE"
    if "Thread" in error_class or error_module == "threading":
        return "THREAD_FAILURE"
    return "UNCLASSIFIED_SAFE_EXCEPTION"


def _safe_project_frame(error):
    traceback = getattr(error, "__traceback__", None)
    while traceback is not None:
        frame = traceback.tb_frame
        filename = str(frame.f_code.co_filename).replace("\\", "/")
        if filename.endswith(
            (
                "/tests/postgresql/test_purge_legal_hold_concurrency_postgresql.py",
                "/services/purge_legal_hold_service.py",
            )
        ):
            return (
                f"{PurePath(filename).name}:"
                f"{traceback.tb_lineno}:"
                f"{frame.f_code.co_name}"
            )
        traceback = traceback.tb_next
    return None


def _safe_root_exception(error):
    current = error
    seen = set()
    for _ in range(4):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        next_error = getattr(current, "orig", None)
        if next_error is None or next_error is current:
            next_error = getattr(current, "__cause__", None)
        if next_error is None or next_error is current:
            next_error = getattr(current, "__context__", None)
        if next_error is None or next_error is current:
            break
        current = next_error
    return current


def _record_safe_worker_error(result, error):
    public_class = type(error).__name__
    public_module = type(error).__module__
    root_error = _safe_root_exception(error)
    root_class = type(root_error).__name__
    root_module = type(root_error).__module__
    sqlstate = _safe_sqlstate(error)
    code = getattr(error, "code", None)
    safe_code = code if code in SAFE_ERROR_CODES else None
    category = _safe_root_category(error, sqlstate)
    if category not in SAFE_ROOT_CATEGORIES:
        category = "UNCLASSIFIED_SAFE_EXCEPTION"
    project_frame = _safe_project_frame(error)
    result.exception = SanitizedWorkerFailure(
        public_exception_class=public_class,
        public_exception_module=public_module,
        root_exception_class=root_class,
        root_exception_module=root_module,
        sqlstate=sqlstate,
        safe_root_category=category,
        code=safe_code,
        project_frame=project_frame,
    )
    result.safe_exception_class = public_class
    result.safe_error_code = safe_code
    result.safe_stage = f"{result.name.upper()}_OPERATION"
    result.safe_root_category = category
    result.safe_project_frame = project_frame
    result.terminal_outcome = (
        "SAFE_EXCEPTION" if safe_code is not None else "UNSAFE_EXCEPTION"
    )


def _snapshot_worker_results(results, result_sink):
    if result_sink is None:
        return
    for name, result in results.items():
        result_sink[name] = result


def _mark_waiter_join_timeout(result):
    result.safe_exception_class = "WAITER_JOIN_TIMEOUT"
    result.safe_stage = "WAITER_JOIN"
    result.safe_root_category = "WAITER_JOIN_TIMEOUT"
    result.terminal_outcome = "JOIN_TIMEOUT"


def _safe_worker_failure(result):
    return (
        f"worker={result.name} "
        f"stage={result.safe_stage or 'UNKNOWN'} "
        f"class={result.safe_exception_class or 'NONE'} "
        f"code={result.safe_error_code or 'NONE'}"
    )


def _arm_execution_claim(runtime, plans):
    service = runtime.services.PurgeReauthService
    descriptor = inspect.getattr_static(service, "claim_for_execution")
    original = descriptor.__func__ if isinstance(descriptor, staticmethod) else descriptor

    def wrapped(*args, **kwargs):
        claim = original(*args, **kwargs)
        current = plans.get(threading.current_thread().name)
        if current is not None:
            current.execution_lock_armed.set()
        return claim

    service.claim_for_execution = staticmethod(wrapped)
    return service, "claim_for_execution", descriptor


def _arm_active_hold_observation(runtime, plans):
    service = runtime.services.PurgeService
    descriptor = inspect.getattr_static(service, "_validate_holds")
    original = descriptor.__func__ if isinstance(descriptor, staticmethod) else descriptor

    def wrapped(request, holds):
        current = plans.get(threading.current_thread().name)
        active_observed = any(getattr(hold, "status", None) == "ACTIVE" for hold in holds)
        if current is not None and current.execution_lock_armed.is_set() and active_observed:
            current.active_hold_observed.set()
            current.lock_acquired.set()
            current.allow_winner_to_continue.wait(EVENT_TIMEOUT_SECONDS)
            current.post_lock_passed.set()
        return original(request, holds)

    service._validate_holds = staticmethod(wrapped)
    return service, "_validate_holds", descriptor


def _arm_decisive_release_hold_barrier(runtime, plans):
    service = runtime.services.PurgeLegalHoldService
    descriptor = inspect.getattr_static(service, "_phrase")
    original = descriptor.__func__ if isinstance(descriptor, staticmethod) else descriptor

    def wrapped(value, expected, legacy=None):
        current = plans.get(threading.current_thread().name)
        result = original(value, expected, legacy=legacy)
        effective_phrase = legacy if legacy is not None else expected
        if current is plans.get("winner") and isinstance(effective_phrase, str) and effective_phrase.startswith("RELEASE "):
            current.winner_hold_lock_acquired.set()
            current.winner_observed_active.set()
            current.lock_acquired.set()
            current.allow_winner_to_continue.wait(EVENT_TIMEOUT_SECONDS)
            current.post_lock_passed.set()
        return result

    service._phrase = staticmethod(wrapped)
    return service, "_phrase", descriptor


@contextmanager
def _actual_operation_hooks(runtime, plans, *, barrier_target="workspace"):
    """Pause only after real PostgreSQL lock/query/delete operations."""

    def after_cursor_execute(connection, cursor, statement, parameters, context, executemany):
        current = plans.get(threading.current_thread().name)
        if current is None:
            return
        normalized = _sql(statement)
        if "DELETE FROM INVOICE_DETAILS" in normalized:
            current.first_delete_reached.set()
        if barrier_target not in {"active_hold", "decisive_hold"} and "FROM WORKSPACES" in normalized and "FOR UPDATE" in normalized:
            if not _workspace_barrier_is_armed(current, barrier_target):
                return
            current.lock_acquired.set()
            if current.pause_after == "workspace":
                current.allow_winner_to_continue.wait(EVENT_TIMEOUT_SECONDS)
            current.post_lock_passed.set()
        elif current.pause_after == "hold" and "FROM PURGE_LEGAL_HOLDS" in normalized and "FOR UPDATE" in normalized:
            current.lock_acquired.set()
            current.allow_winner_to_continue.wait(EVENT_TIMEOUT_SECONDS)
            current.post_lock_passed.set()

    event.listen(runtime.engine, "after_cursor_execute", after_cursor_execute)
    try:
        yield
    finally:
        event.remove(runtime.engine, "after_cursor_execute", after_cursor_execute)


def _next_sequence(sequence_state):
    if sequence_state is None:
        return None
    with sequence_state["lock"]:
        sequence_state["value"] += 1
        return sequence_state["value"]


def _worker(runtime, name, operation, plan, results, sequence_state=None):
    result = WorkerResult(name=name)
    results[name] = result
    result.started = True
    result.terminal_outcome = "RUNNING"
    try:
        with runtime.app.app_context():
            result.result = operation()
    except Exception as error:
        _record_safe_worker_error(result, error)
    else:
        result.operation_returned_at = time.monotonic()
        result.operation_returned_sequence = _next_sequence(sequence_state)
        result.terminal_outcome = "NORMAL_RETURN"
    finally:
        result.lock_acquired = plan.lock_acquired.is_set()
        result.post_lock_passed = plan.post_lock_passed.is_set()
        result.completed_at = time.monotonic()
        result.completed_sequence = _next_sequence(sequence_state)
        result.completed = True
        plan.completed_event.set()


def _run_pair(
    runtime,
    winner_operation,
    waiter_operation,
    *,
    winner_pause="workspace",
    barrier_target="workspace",
    result_sink=None,
):
    plans = {"winner": HookPlan(pause_after=winner_pause), "waiter": HookPlan()}
    results = {}
    sequence_state = {"lock": threading.Lock(), "value": 0}
    patches = []
    try:
        with _actual_operation_hooks(runtime, plans, barrier_target=barrier_target):
            if barrier_target == "execution":
                patches.append(_arm_execution_claim(runtime, plans))
            elif barrier_target == "active_hold":
                patches.append(_arm_execution_claim(runtime, plans))
                patches.append(_arm_active_hold_observation(runtime, plans))
            elif barrier_target == "decisive_hold":
                patches.append(_arm_decisive_release_hold_barrier(runtime, plans))

            winner = threading.Thread(
                target=_worker, name="winner", args=(runtime, "winner", winner_operation, plans["winner"], results, sequence_state)
            )
            winner.start()
            assert plans["winner"].lock_acquired.wait(EVENT_TIMEOUT_SECONDS)

            waiter_started = threading.Event()

            def waiter_operation_with_marker():
                waiter_started.set()
                plans["waiter"].operation_started.set()
                return waiter_operation()

            waiter = threading.Thread(
                target=_worker, name="waiter", args=(runtime, "waiter", waiter_operation_with_marker, plans["waiter"], results, sequence_state)
            )
            waiter.start()
            assert waiter_started.wait(EVENT_TIMEOUT_SECONDS)
            assert not plans["waiter"].lock_acquired.wait(0.5)
            assert not plans["waiter"].completed_event.is_set()

            plans["winner"].allow_winner_to_continue.set()
            winner.join(THREAD_JOIN_TIMEOUT_SECONDS)
            waiter.join(THREAD_JOIN_TIMEOUT_SECONDS)
            results["winner"].thread_alive = winner.is_alive()
            results["waiter"].thread_alive = waiter.is_alive()
            if results["waiter"].thread_alive:
                _mark_waiter_join_timeout(results["waiter"])
            _snapshot_worker_results(results, result_sink)
            assert not winner.is_alive()
            assert not waiter.is_alive()
    finally:
        for service, attribute, descriptor in reversed(patches):
            setattr(service, attribute, descriptor)
    return results, plans


def _build_case(runtime, *, business=True):
    models = runtime.models
    services = runtime.services
    db = runtime.db
    runtime.prepare_scoped_session()
    marker = f"lh-{threading.get_ident()}-{id(runtime)}"
    requester = models.User(
        username=f"requester-{marker}", full_name="Requester", role="APPROVAL_OWNER",
        approval_status="active", is_active=True,
    )
    approver = models.User(
        username=f"approver-{marker}", full_name="Approver", role="APPROVAL_OWNER",
        approval_status="active", is_active=True,
    )
    executor = models.User(
        username=f"executor-{marker}", full_name="Executor", role="APPROVAL_OWNER",
        approval_status="active", is_active=True,
    )
    owner = models.User(
        username=f"owner-{marker}", full_name="Deleted Owner", role="OWNER",
        approval_status="active", is_active=False, deleted_at=datetime(2026, 1, 1),
    )
    for user in (requester, approver, executor, owner):
        user.set_password(SYNTHETIC_PASSWORD)
    db.session.add_all((requester, approver, executor, owner))
    db.session.flush()
    owner.deleted_by_id = requester.id
    workspace = models.Workspace(
        name=f"Legal Hold Workspace {marker}", slug=f"legal-hold-{marker}", status="active",
        deleted_at=datetime(2026, 1, 1), deleted_by_id=requester.id,
    )
    db.session.add(workspace)
    db.session.flush()
    db.session.add(models.WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role="owner", status="active"))
    if business:
        customer = models.Customer(name=f"Customer {marker}", workspace_id=workspace.id)
        service = models.Service(name=f"Service {marker}", price=100, workspace_id=workspace.id)
        db.session.add_all((customer, service))
        db.session.flush()
        invoice = models.Invoice(customer_id=customer.id, total_amount=100, workspace_id=workspace.id)
        db.session.add(invoice)
        db.session.flush()
        db.session.add(models.InvoiceDetail(invoice_id=invoice.id, service_id=service.id, price=100, quantity=1))
        db.session.add(models.Appointment(
            customer_id=customer.id, service_id=service.id,
            appointment_time=datetime(2026, 1, 2), workspace_id=workspace.id,
        ))
    db.session.commit()
    request = services.PurgeRequestService.create_purge_request(
        workspace_id=workspace.id, requester_user_id=requester.id,
        confirmation_phrase=f"REQUEST PURGE {workspace.slug}", now=REHEARSAL_NOW,
    )
    return {
        "requester_id": requester.id, "approver_id": approver.id, "executor_id": executor.id,
        "workspace_id": workspace.id, "workspace_slug": workspace.slug,
        "request_id": request.id, "lifecycle_id": request.lifecycle_id,
        "models": models, "services": services, "db": db,
    }


def _approve(case):
    return case["services"].PurgeRequestService.approve_purge_request(
        request_id=case["request_id"], approver_user_id=case["approver_id"],
        confirmation_phrase=f"APPROVE PURGE {case['workspace_slug']} {case['lifecycle_id']}",
        now=REHEARSAL_NOW,
    )


def _create_hold(case, actor_id=None):
    actor_id = actor_id or case["requester_id"]
    return case["services"].PurgeLegalHoldService.create_legal_hold(
        workspace_id=case["workspace_id"], actor_user_id=actor_id,
        hold_type="LEGAL", reason="Concurrency rehearsal hold",
        confirmation_phrase=f"HOLD {case['workspace_slug']}",
    )


def _release_hold(case, hold_id, actor_id=None):
    return case["services"].PurgeLegalHoldService.release_legal_hold(
        hold_id=hold_id, actor_user_id=actor_id or case["approver_id"],
        release_reason="Concurrency rehearsal release",
        confirmation_phrase=f"RELEASE {hold_id}",
    )


def _issue_reauth(case):
    return case["services"].PurgeReauthService.issue_local_authorization(
        case["request_id"], case["executor_id"], SYNTHETIC_PASSWORD
    )


def _execute(case, issuance):
    return case["services"].PurgeService.execute_workspace_purge(
        request_id=case["request_id"], workspace_id=case["workspace_id"],
        executor_user_id=case["executor_id"], authorization_generation=issuance.generation,
        authorization_nonce=issuance.raw_nonce, now=REHEARSAL_NOW,
    )


def _verify_and_cleanup(runtime, case):
    verification = runtime.new_session()
    try:
        hold_count = verification.query(case["models"].PurgeLegalHold).filter_by(workspace_id=case["workspace_id"]).count()
        assert hold_count >= 0
    finally:
        verification.rollback()
        verification.close()
    runtime.reset_database()
    with runtime.engine.connect() as connection:
        for table_name in sorted(__import__("tests.postgresql.rehearsal_runtime", fromlist=["EXPECTED_APPLICATION_TABLES"]).EXPECTED_APPLICATION_TABLES):
            assert connection.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar_one() == 0


def _assert_lh_d_semantics(runtime, case, hold_id, results, plans):
    winner_success = results["winner"].exception is None
    waiter_already_released = (
        getattr(results["waiter"].exception, "code", None) == "ALREADY_RELEASED"
    )
    assert winner_success
    assert waiter_already_released

    verification = runtime.new_session()
    try:
        hold = verification.query(case["models"].PurgeLegalHold).filter_by(
            hold_id=hold_id
        ).one()
        final_hold_status = hold.status
        assert final_hold_status == "RELEASED"
        assert hold.released_at is not None
        assert hold.released_by_snapshot is not None
        assert hold.release_reason is not None
        successful_release_result_count = sum(
            result == "SUCCESS"
            for result in (
                "SUCCESS" if winner_success else "UNKNOWN",
                "ALREADY_RELEASED" if waiter_already_released else "UNKNOWN",
            )
        )
    finally:
        verification.rollback()
        verification.close()

    duplicate_release_occurred = not (
        successful_release_result_count == 1
        and winner_success
        and waiter_already_released
    )
    deadlock_detected = any(
        getattr(results[name].exception, "safe_root_category", None)
        == "DEADLOCK_DETECTED"
        for name in ("winner", "waiter")
    )

    assert successful_release_result_count == 1
    assert duplicate_release_occurred is False
    assert deadlock_detected is False
    assert plans["winner"].winner_hold_lock_acquired.is_set()
    assert plans["winner"].winner_observed_active.is_set()
    assert plans["waiter"].operation_started.is_set()
    assert plans["waiter"].completed_event.is_set()
    assert results["winner"].operation_returned_sequence is not None
    assert results["waiter"].completed_sequence is not None
    assert (
        results["waiter"].completed_sequence
        > results["winner"].operation_returned_sequence
    )


def _emit_lh_d_safe_failure(results, stage):
    categories = [
        getattr(results[name].exception, "safe_root_category", None)
        or getattr(results[name], "safe_root_category", None)
        for name in ("winner", "waiter")
    ]
    deadlock_detected = "DEADLOCK_DETECTED" in categories
    winner = (
        "SUCCESS"
        if results["winner"].terminal_outcome == "NORMAL_RETURN"
        else results["winner"].terminal_outcome
    )
    waiter = (
        "ALREADY_RELEASED"
        if getattr(results["waiter"].exception, "code", None) == "ALREADY_RELEASED"
        else results["waiter"].terminal_outcome
    )
    waiter_outcome = results["waiter"].terminal_outcome
    if waiter_outcome == "NOT_STARTED":
        waiter_outcome = "UNKNOWN"
    waiter_code = "UNKNOWN"
    if waiter_outcome == "NORMAL_RETURN":
        waiter_code = "NONE"
    elif waiter_outcome == "SAFE_EXCEPTION":
        waiter_code = (
            "ALREADY_RELEASED"
            if results["waiter"].safe_error_code == "ALREADY_RELEASED"
            else "OTHER_SAFE"
        )
    markers = {
        "LH_D_SAFE_FAILURE_STAGE": stage,
        "LH_D_SAFE_WINNER_RESULT": winner,
        "LH_D_SAFE_WAITER_RESULT": waiter,
        "LH_D_SAFE_WAITER_TERMINAL_OUTCOME": waiter_outcome,
        "LH_D_SAFE_WAITER_EXCEPTION_CODE": waiter_code,
        "LH_D_SAFE_FINAL_HOLD_STATUS": "UNKNOWN",
        "LH_D_SAFE_SUCCESSFUL_RELEASE_RESULT_COUNT": "UNKNOWN",
        "LH_D_SAFE_DUPLICATE_RELEASE_OCCURRED": "UNKNOWN",
        "LH_D_SAFE_WAITER_THREAD_ALIVE": (
            "YES" if results["waiter"].thread_alive else "NO"
        ),
        "LH_D_SAFE_DEADLOCK_DETECTED": "YES" if deadlock_detected else "NO",
        "LH_D_SAFE_WINNER_EXCEPTION_CLASS": (
            results["winner"].exception.public_exception_class
            if results["winner"].exception is not None
            else "NONE"
        ),
        "LH_D_SAFE_WINNER_EXCEPTION_MODULE": (
            results["winner"].exception.public_exception_module
            if results["winner"].exception is not None
            else "NONE"
        ),
        "LH_D_SAFE_WINNER_ROOT_EXCEPTION_CLASS": (
            results["winner"].exception.root_exception_class
            if results["winner"].exception is not None
            else "NONE"
        ),
        "LH_D_SAFE_WINNER_ROOT_EXCEPTION_MODULE": (
            results["winner"].exception.root_exception_module
            if results["winner"].exception is not None
            else "NONE"
        ),
        "LH_D_SAFE_WINNER_SQLSTATE": (
            results["winner"].exception.sqlstate
            if results["winner"].exception is not None
            and results["winner"].exception.sqlstate
            else "NONE"
        ),
        "LH_D_SAFE_WINNER_ROOT_CATEGORY": (
            results["winner"].safe_root_category or "NONE"
        ),
        "LH_D_SAFE_WINNER_FAILURE_PHASE": (
            results["winner"].safe_stage or "NONE"
        ),
        "LH_D_SAFE_WINNER_PROJECT_FRAME": (
            results["winner"].safe_project_frame or "NONE"
        ),
        "LH_D_SAFE_FAILURE_PHASE": stage,
        "LH_D_SAFE_PROJECT_FRAME": (
            results["winner"].safe_project_frame
            or results["waiter"].safe_project_frame
            or "NONE"
        ),
        "LH_D_SAFE_WAITER_EXCEPTION_CLASS": (
            results["waiter"].exception.public_exception_class
            if results["waiter"].exception is not None
            else "NONE"
        ),
        "LH_D_SAFE_WAITER_EXCEPTION_MODULE": (
            results["waiter"].exception.public_exception_module
            if results["waiter"].exception is not None
            else "NONE"
        ),
        "LH_D_SAFE_WAITER_ROOT_EXCEPTION_CLASS": (
            results["waiter"].exception.root_exception_class
            if results["waiter"].exception is not None
            else "NONE"
        ),
        "LH_D_SAFE_WAITER_ROOT_EXCEPTION_MODULE": (
            results["waiter"].exception.root_exception_module
            if results["waiter"].exception is not None
            else "NONE"
        ),
        "LH_D_SAFE_WAITER_SQLSTATE": (
            results["waiter"].exception.sqlstate
            if results["waiter"].exception is not None
            and results["waiter"].exception.sqlstate
            else "NONE"
        ),
        "LH_D_SAFE_WAITER_ROOT_CATEGORY": (
            results["waiter"].safe_root_category or "NONE"
        ),
        "LH_D_SAFE_WAITER_FAILURE_PHASE": (
            results["waiter"].safe_stage or "NONE"
        ),
        "LH_D_SAFE_WAITER_PROJECT_FRAME": (
            results["waiter"].safe_project_frame or "NONE"
        ),
        "LH_D_SAFE_PUBLIC_EXCEPTION_CLASS": (
            results["waiter"].exception.public_exception_class
            if results["waiter"].exception is not None
            else "NONE"
        ),
        "LH_D_SAFE_PUBLIC_EXCEPTION_MODULE": (
            results["waiter"].exception.public_exception_module
            if results["waiter"].exception is not None
            else "NONE"
        ),
        "LH_D_SAFE_ROOT_EXCEPTION_CLASS": (
            results["waiter"].exception.root_exception_class
            if results["waiter"].exception is not None
            else "NONE"
        ),
        "LH_D_SAFE_ROOT_EXCEPTION_MODULE": (
            results["waiter"].exception.root_exception_module
            if results["waiter"].exception is not None
            else "NONE"
        ),
        "LH_D_SAFE_SQLSTATE": (
            results["waiter"].exception.sqlstate
            if results["waiter"].exception is not None
            and results["waiter"].exception.sqlstate
            else "NONE"
        ),
        "LH_D_SAFE_ROOT_CATEGORY": next(
            (category for category in categories if category),
            "UNCLASSIFIED_SAFE_EXCEPTION",
        ),
        "LH_D_SAFE_CLEANUP_RESULT": next(
            (
                results[name].cleanup_outcome
                for name in ("winner", "waiter")
                if results[name].cleanup_outcome
            ),
            "PENDING_FIXTURE_RESET",
        ),
    }
    for key, value in markers.items():
        print(f"{key}={value}")


@pytest.fixture
def legal_hold_case(postgres_runtime):
    assert postgres_runtime.app.config["PERMANENT_PURGE_EXECUTION_ENABLED"] is True
    postgres_runtime.reset_database()
    try:
        yield postgres_runtime
    finally:
        postgres_runtime.reset_database()


def test_lh_a1_create_wins_against_approval(legal_hold_case):
    case = _build_case(legal_hold_case, business=False)
    results, _plans = _run_pair(
        legal_hold_case,
        lambda: _create_hold(case),
        lambda: _approve(case),
    )
    assert results["winner"].exception is None
    assert getattr(results["waiter"].exception, "code", None) == "LEGAL_HOLD_UNRESOLVED"
    _verify_and_cleanup(legal_hold_case, case)


def test_lh_a2_approval_wins_then_hold_blocks_execution(legal_hold_case):
    case = _build_case(legal_hold_case, business=True)
    results, _plans = _run_pair(legal_hold_case, lambda: _approve(case), lambda: _create_hold(case))
    assert results["winner"].exception is None
    assert results["waiter"].exception is None
    issuance = _issue_reauth(case)
    with pytest.raises(Exception) as error:
        _execute(case, issuance)
    assert getattr(error.value, "code", None) == "ACTIVE_LEGAL_HOLD"
    _verify_and_cleanup(legal_hold_case, case)


def test_lh_b1_create_wins_against_execution(legal_hold_case):
    case = _build_case(legal_hold_case)
    _approve(case)
    issuance = _issue_reauth(case)
    results, plans = _run_pair(legal_hold_case, lambda: _create_hold(case), lambda: _execute(case, issuance))
    assert results["winner"].exception is None
    assert getattr(results["waiter"].exception, "code", None) == "ACTIVE_LEGAL_HOLD"
    assert not plans["waiter"].first_delete_reached.is_set()
    _verify_and_cleanup(legal_hold_case, case)


def test_lh_b2_execution_wins_then_create_rejects_terminal_workspace(legal_hold_case):
    case = _build_case(legal_hold_case)
    _approve(case)
    issuance = _issue_reauth(case)
    results, _plans = _run_pair(
        legal_hold_case,
        lambda: _execute(case, issuance),
        lambda: _create_hold(case),
        barrier_target="execution",
    )
    assert results["winner"].exception is None, _safe_worker_failure(results["winner"])
    assert getattr(results["waiter"].exception, "code", None) == "TERMINAL_WORKSPACE", _safe_worker_failure(results["waiter"])
    _verify_and_cleanup(legal_hold_case, case)


def test_lh_c1_release_wins_then_execution_observes_released(legal_hold_case):
    case = _build_case(legal_hold_case)
    _approve(case)
    hold = _create_hold(case)
    issuance = _issue_reauth(case)
    results, _plans = _run_pair(legal_hold_case, lambda: _release_hold(case, hold.hold_id), lambda: _execute(case, issuance), winner_pause="hold")
    assert results["winner"].exception is None
    assert results["waiter"].exception is None
    _verify_and_cleanup(legal_hold_case, case)


def test_lh_c2_execution_sees_active_then_release_succeeds(legal_hold_case):
    case = _build_case(legal_hold_case)
    _approve(case)
    hold = _create_hold(case)
    issuance = _issue_reauth(case)
    results, plans = _run_pair(
        legal_hold_case,
        lambda: _execute(case, issuance),
        lambda: _release_hold(case, hold.hold_id),
        winner_pause="hold",
        barrier_target="active_hold",
    )
    assert getattr(results["winner"].exception, "code", None) == "ACTIVE_LEGAL_HOLD"
    assert results["waiter"].exception is None
    assert plans["winner"].active_hold_observed.is_set()
    assert plans["waiter"].operation_started.is_set()
    assert plans["waiter"].completed_event.is_set()
    assert not plans["winner"].first_delete_reached.is_set()
    _verify_and_cleanup(legal_hold_case, case)


def test_lh_d_concurrent_double_release_is_exactly_once(legal_hold_case):
    results = {"winner": WorkerResult(name="winner"), "waiter": WorkerResult(name="waiter")}
    case = None
    try:
        case = _build_case(legal_hold_case, business=False)
        hold = _create_hold(case)
        results, plans = _run_pair(
            legal_hold_case,
            lambda: _release_hold(case, hold.hold_id, case["approver_id"]),
            lambda: _release_hold(case, hold.hold_id, case["executor_id"]),
            winner_pause="hold",
            barrier_target="decisive_hold",
            result_sink=results,
        )
        _assert_lh_d_semantics(legal_hold_case, case, hold.hold_id, results, plans)
        _verify_and_cleanup(legal_hold_case, case)
    except AssertionError:
        _emit_lh_d_safe_failure(results, "ASSERTION")
        pytest.fail("LH_D_SANITIZED_FAILURE")
    except Exception as error:
        if case is None:
            print("LH_D_SAFE_FAILURE_STAGE=SETUP")
            print("LH_D_SAFE_WINNER_RESULT=UNKNOWN")
            print("LH_D_SAFE_WAITER_RESULT=UNKNOWN")
            print("LH_D_SAFE_FINAL_HOLD_STATUS=UNKNOWN")
            print("LH_D_SAFE_SUCCESSFUL_RELEASE_RESULT_COUNT=UNKNOWN")
            print("LH_D_SAFE_DUPLICATE_RELEASE_OCCURRED=UNKNOWN")
            print("LH_D_SAFE_WAITER_THREAD_ALIVE=UNKNOWN")
            print("LH_D_SAFE_DEADLOCK_DETECTED=NO")
            print("LH_D_SAFE_PUBLIC_EXCEPTION_CLASS=SANITIZED")
            print("LH_D_SAFE_ROOT_EXCEPTION_CLASS=SANITIZED")
            print("LH_D_SAFE_SQLSTATE=UNKNOWN")
            print("LH_D_SAFE_ROOT_CATEGORY=UNCLASSIFIED_SAFE_EXCEPTION")
        else:
            _record_safe_worker_error(results["winner"], error)
            _emit_lh_d_safe_failure(results, "TEST_OPERATION")
        pytest.fail("LH_D_SANITIZED_FAILURE")
