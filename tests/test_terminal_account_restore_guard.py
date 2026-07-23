import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault(
    "TEST_DATABASE_URL",
    f"sqlite:///{(Path(__file__).resolve().parent / 'terminal_restore_test.db').as_posix()}",
)

import pytest

from app import app
from core.auth.enums import UserRole
from services.user_service import UserService


def _terminal_user():
    return SimpleNamespace(
        account_purge_state="PURGED_TOMBSTONE",
        deleted_at="terminal",
        is_active=False,
        role="STAFF",
        username="terminal",
    )


def test_workspace_restore_rejects_terminal_before_membership_mutation():
    actor = SimpleNamespace(id=1, role=UserRole.OWNER.value)
    membership = SimpleNamespace(status="removed", removed_at="kept", removed_by_id=9)
    with pytest.raises(Exception) as error:
        with patch.object(UserService, "_authorize_workspace_user_action", return_value=(_terminal_user(), membership)):
            UserService.restore_user(actor, 2)
    assert error.value.code == "TERMINAL_ACCOUNT_NOT_RESTORABLE"
    assert membership.status == "removed"
    assert membership.removed_at == "kept"


def test_approval_restore_rejects_terminal_before_user_mutation():
    actor = SimpleNamespace(role=UserRole.APPROVAL_OWNER.value)
    user = _terminal_user()
    with app.app_context():
        with pytest.raises(Exception) as error:
            with patch("services.user_service.User.query", create=True) as query:
                query.get.return_value = user
                UserService.restore_account(actor, 2)
    assert error.value.code == "TERMINAL_ACCOUNT_NOT_RESTORABLE"
    assert user.deleted_at == "terminal"
    assert user.is_active is False
