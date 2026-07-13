"""Short-lived browser transport for a durable purge re-auth authorization."""

from datetime import datetime, timezone

from flask import session


PURGE_REAUTH_TRANSPORT_KEY = "purge_reauth_transport_v1"
PURGE_REAUTH_TRANSPORT_VERSION = 1
_REQUIRED_FIELDS = {
    "version", "authorization_id", "purge_request_id", "workspace_id",
    "actor_user_id", "generation", "raw_nonce", "authenticated_at", "expires_at",
}


def _is_positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_iso_datetime(value):
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return True


def _validate(envelope):
    if not isinstance(envelope, dict) or not _REQUIRED_FIELDS.issubset(envelope):
        return None
    if envelope.get("version") != PURGE_REAUTH_TRANSPORT_VERSION:
        return None
    for field in ("authorization_id", "purge_request_id", "workspace_id", "actor_user_id", "generation"):
        if not _is_positive_int(envelope.get(field)):
            return None
    if not isinstance(envelope.get("raw_nonce"), str) or not envelope["raw_nonce"]:
        return None
    if not _is_iso_datetime(envelope.get("authenticated_at")) or not _is_iso_datetime(envelope.get("expires_at")):
        return None
    try:
        expires_at = datetime.fromisoformat(envelope["expires_at"])
    except ValueError:
        return None
    if expires_at.tzinfo is not None:
        return None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if expires_at.replace(tzinfo=None) <= now:
        return None
    return envelope


def store_transport(issuance, workspace_id):
    envelope = {
        "version": PURGE_REAUTH_TRANSPORT_VERSION,
        "authorization_id": issuance.authorization_id,
        "purge_request_id": issuance.purge_request_id,
        "workspace_id": workspace_id,
        "actor_user_id": issuance.actor_user_id,
        "generation": issuance.generation,
        "raw_nonce": issuance.raw_nonce,
        "authenticated_at": issuance.authenticated_at.isoformat(),
        "expires_at": issuance.expires_at.isoformat(),
    }
    if _validate(envelope) is None:
        raise ValueError("Invalid purge re-auth issuance.")
    session[PURGE_REAUTH_TRANSPORT_KEY] = envelope
    session.modified = True


def peek_transport():
    return _validate(session.get(PURGE_REAUTH_TRANSPORT_KEY))


def clear_transport():
    session.pop(PURGE_REAUTH_TRANSPORT_KEY, None)
    session.modified = True


def consume_transport(*, request_id, workspace_id, actor_user_id):
    envelope = peek_transport()
    if envelope is None:
        clear_transport()
        return None
    if (
        envelope["purge_request_id"] != request_id
        or envelope["workspace_id"] != workspace_id
        or envelope["actor_user_id"] != actor_user_id
    ):
        clear_transport()
        return None
    clear_transport()
    return envelope


def transport_matches(envelope, *, request_id, workspace_id, actor_user_id):
    return bool(
        envelope
        and envelope["purge_request_id"] == request_id
        and envelope["workspace_id"] == workspace_id
        and envelope["actor_user_id"] == actor_user_id
    )
