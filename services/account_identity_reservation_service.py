"""Runtime guards for identities reserved by terminal account purge workflows."""

import hashlib
from dataclasses import dataclass

from sqlalchemy import func, text

from core.exceptions import ConflictException, NotFoundException, ValidationException
from models.account_purge import AccountIdentityReservation
from models.user import User
from utils.timezone_utils import utc_now


FINGERPRINT_VERSION = 1
USERNAME = "USERNAME"
EMAIL = "EMAIL"


class IdentityReservationConflictError(ConflictException):
    pass


@dataclass(frozen=True)
class IdentityCandidate:
    identity_type: str
    fingerprint: str
    normalized_value: str


class AccountIdentityReservationService:
    """Serialize identity availability checks without persisting raw identity values."""

    @staticmethod
    def normalize_identity(identity_type, value):
        if identity_type not in (USERNAME, EMAIL):
            raise ValidationException("Identity type is invalid.", code="IDENTITY_INVALID")
        if identity_type == USERNAME:
            normalized = (value or "").strip()
        else:
            normalized = (value or "").strip().lower()
        if not normalized:
            raise ValidationException("Identity value is invalid.", code="IDENTITY_INVALID")
        return normalized

    @staticmethod
    def fingerprint_identity(identity_type, value):
        normalized = AccountIdentityReservationService.normalize_identity(identity_type, value)
        canonical = f"v{FINGERPRINT_VERSION}|{identity_type}|{normalized}"
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _candidates(username=None, email=None):
        candidates = []
        if username is not None:
            normalized = AccountIdentityReservationService.normalize_identity(USERNAME, username)
            candidates.append(IdentityCandidate(
                USERNAME,
                AccountIdentityReservationService.fingerprint_identity(USERNAME, normalized),
                normalized,
            ))
        if email:
            normalized = AccountIdentityReservationService.normalize_identity(EMAIL, email)
            candidates.append(IdentityCandidate(
                EMAIL,
                AccountIdentityReservationService.fingerprint_identity(EMAIL, normalized),
                normalized,
            ))
        return sorted(candidates, key=lambda item: (item.identity_type, item.fingerprint))

    @staticmethod
    def acquire_identity_locks(session, *, username=None, email=None):
        candidates = AccountIdentityReservationService._candidates(username=username, email=email)
        bind = session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            for candidate in candidates:
                digest = bytes.fromhex(candidate.fingerprint)[:8]
                high = int.from_bytes(digest[:4], byteorder="big", signed=True)
                low = int.from_bytes(digest[4:], byteorder="big", signed=True)
                session.execute(
                    text("SELECT pg_advisory_xact_lock(:key_high, :key_low)"),
                    {"key_high": high, "key_low": low},
                )
        return candidates

    @staticmethod
    def _active_reservation(session, candidate, lock=False):
        query = session.query(AccountIdentityReservation).filter(
            AccountIdentityReservation.identity_type == candidate.identity_type,
            AccountIdentityReservation.identity_fingerprint == candidate.fingerprint,
            AccountIdentityReservation.released_at.is_(None),
        )
        if lock:
            query = query.populate_existing().with_for_update()
        return query.one_or_none()

    @staticmethod
    def inspect_active_reservation(session, identity_type, raw_value, lock=False):
        normalized = AccountIdentityReservationService.normalize_identity(identity_type, raw_value)
        candidate = IdentityCandidate(
            identity_type,
            AccountIdentityReservationService.fingerprint_identity(identity_type, normalized),
            normalized,
        )
        return AccountIdentityReservationService._active_reservation(session, candidate, lock=lock)

    @staticmethod
    def acquire_identity_creation_locks(session, username=None, email=None):
        return AccountIdentityReservationService.acquire_identity_locks(
            session, username=username, email=email
        )

    @staticmethod
    def assert_identity_available(session, *, username=None, email=None):
        candidates = AccountIdentityReservationService.acquire_identity_locks(
            session, username=username, email=email
        )
        for candidate in candidates:
            if AccountIdentityReservationService._active_reservation(session, candidate, lock=True):
                code = "USERNAME_RESERVED" if candidate.identity_type == USERNAME else "EMAIL_RESERVED"
                raise IdentityReservationConflictError(
                    "The requested identity is reserved.", code=code
                )
        return candidates

    @staticmethod
    def reserve_target_identities_in_transaction(
        session, *, request_id, target_user_id, expected_username=None, expected_email=None
    ):
        snapshot = session.query(User).filter(User.id == target_user_id).one_or_none()
        if snapshot is None:
            raise NotFoundException(
                "The target account was not found.", code="TARGET_USER_NOT_FOUND"
            )

        persisted_username = AccountIdentityReservationService.normalize_identity(
            USERNAME, snapshot.username
        )
        persisted_email = (
            AccountIdentityReservationService.normalize_identity(EMAIL, snapshot.email)
            if snapshot.email
            else None
        )
        if expected_username is not None and AccountIdentityReservationService.normalize_identity(
            USERNAME, expected_username
        ) != persisted_username:
            raise IdentityReservationConflictError(
                "The target account identity snapshot is stale.",
                code="TARGET_USERNAME_MISMATCH",
            )
        if expected_email is not None:
            expected_normalized_email = AccountIdentityReservationService.normalize_identity(
                EMAIL, expected_email
            )
            if expected_normalized_email != persisted_email:
                raise IdentityReservationConflictError(
                    "The target account identity snapshot is stale.",
                    code="TARGET_EMAIL_MISMATCH",
                )

        candidates = AccountIdentityReservationService.acquire_identity_locks(
            session, username=persisted_username, email=persisted_email
        )

        target = (
            session.query(User)
            .populate_existing()
            .filter(User.id == target_user_id)
            .with_for_update()
            .one_or_none()
        )
        if target is None:
            raise NotFoundException(
                "The target account was not found.", code="TARGET_USER_NOT_FOUND"
            )
        fresh_username = AccountIdentityReservationService.normalize_identity(
            USERNAME, target.username
        )
        fresh_email = (
            AccountIdentityReservationService.normalize_identity(EMAIL, target.email)
            if target.email
            else None
        )
        if fresh_username != persisted_username:
            raise IdentityReservationConflictError(
                "The target account identity snapshot is stale.",
                code="TARGET_USERNAME_MISMATCH",
            )
        if fresh_email != persisted_email:
            raise IdentityReservationConflictError(
                "The target account identity snapshot is stale.",
                code="TARGET_EMAIL_MISMATCH",
            )

        other_username_owner = session.query(User).filter(
            func.trim(User.username) == persisted_username, User.id != target.id
        ).first()
        if other_username_owner is not None:
            raise IdentityReservationConflictError(
                "The target account identity is owned by another account.",
                code="USERNAME_OWNED_BY_ANOTHER_USER",
            )
        if persisted_email is not None:
            other_email_owner = session.query(User).filter(
                func.lower(func.trim(User.email)) == persisted_email, User.id != target.id
            ).first()
            if other_email_owner is not None:
                raise IdentityReservationConflictError(
                    "The target account identity is owned by another account.",
                    code="EMAIL_OWNED_BY_ANOTHER_USER",
                )

        existing_rows = []
        for candidate in candidates:
            existing = AccountIdentityReservationService._active_reservation(session, candidate, lock=True)
            if existing is not None:
                if existing.request_id == request_id and existing.target_user_id == target_user_id:
                    existing_rows.append(existing)
                    continue
                code = "USERNAME_RESERVED" if candidate.identity_type == USERNAME else "EMAIL_RESERVED"
                raise IdentityReservationConflictError(
                    "The requested identity is already reserved.", code=code
                )

        summaries = list(existing_rows)
        for candidate in candidates:
            if any(
                row.identity_type == candidate.identity_type
                and row.identity_fingerprint == candidate.fingerprint
                for row in existing_rows
            ):
                continue
            reservation = AccountIdentityReservation(
                target_user_id=target_user_id,
                request_id=request_id,
                identity_type=candidate.identity_type,
                identity_fingerprint=candidate.fingerprint,
                fingerprint_version=FINGERPRINT_VERSION,
                created_at=utc_now(),
            )
            session.add(reservation)
            summaries.append(reservation)
        session.flush()
        return summaries
