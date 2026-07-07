"""
tests/test_profile_username.py
==============================
Tests for Task 6.5.9d — Allow Google users to edit generated username safely.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

# ── isolated test DB ────────────────────────────────────────────────────────
TEST_DB_FILE = Path(tempfile.gettempdir()) / "spamanager_profile_username.sqlite"
TEST_MEDIA_ROOT = Path(tempfile.gettempdir()) / "spamanager_profile_username_media"

for _p in (TEST_DB_FILE,):
    if _p.exists():
        try:
            _p.unlink()
        except Exception:
            pass
if TEST_MEDIA_ROOT.exists():
    shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

os.environ["APP_ENV"] = "testing"
os.environ["TEST_DATABASE_URL"] = f"sqlite:///{TEST_DB_FILE.as_posix()}"
os.environ["PERSISTENT_ROOT"] = TEST_MEDIA_ROOT.as_posix()
os.environ["UPLOAD_ROOT"] = (TEST_MEDIA_ROOT / "uploads").as_posix()
os.environ["LOGO_UPLOAD_FOLDER"] = (TEST_MEDIA_ROOT / "uploads" / "logos").as_posix()
os.environ["AVATAR_UPLOAD_FOLDER"] = (TEST_MEDIA_ROOT / "uploads" / "avatars").as_posix()

from app import app
from extensions import db
from flask import session
from core.auth.constants import AUTH_SESSION_KEY
from core.auth.enums import UserRole
from models.user import User
from core.auth.google_oauth import create_or_route_google_pending_user


class TestProfileUsername(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        app.config["CSRF_ENABLED"] = False
        cls.app_context = app.app_context()
        cls.app_context.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        app.config["CSRF_ENABLED"] = True
        db.session.remove()
        db.engine.dispose()
        if TEST_DB_FILE.exists():
            try:
                TEST_DB_FILE.unlink()
            except Exception:
                pass
        if TEST_MEDIA_ROOT.exists():
            shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)
        cls.app_context.pop()

    def setUp(self):
        db.session.remove()
        db.session.rollback()
        User.query.delete()
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove()
        db.session.rollback()

    def _login_as(self, user):
        with self.client.session_transaction() as sess:
            sess[AUTH_SESSION_KEY] = user.id

    def test_google_user_can_update_generated_username(self):
        user = User(
            username="google_4903cfaad39536a140aa0d44",
            full_name="Google User",
            role=UserRole.STAFF.value,
            is_active=True,
            approval_status="active",
            email="google@example.com",
            auth_provider="google",
            oauth_id="12345"
        )
        user.set_password("random_password_hash")
        db.session.add(user)
        db.session.commit()

        self._login_as(user)

        # POST profile change
        resp = self.client.post('/profile', data={
            'full_name': 'Google User Edited',
            'username': 'googler_new'
        }, headers={'X-Requested-With': 'XMLHttpRequest'})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])

        # Check DB
        db.session.refresh(user)
        self.assertEqual(user.username, 'googler_new')
        self.assertEqual(user.full_name, 'Google User Edited')

    def test_google_login_still_works_after_username_change(self):
        user = User(
            username="google_4903cfaad39536a140aa0d44",
            full_name="Google User",
            role=UserRole.STAFF.value,
            is_active=True,
            approval_status="active",
            email="google@example.com",
            auth_provider="google",
            oauth_id="12345"
        )
        user.set_password("random_password_hash")
        db.session.add(user)
        db.session.commit()

        # Update username first
        self._login_as(user)
        self.client.post('/profile', data={
            'full_name': 'Google User',
            'username': 'googler_new'
        }, headers={'X-Requested-With': 'XMLHttpRequest'})

        db.session.refresh(user)
        self.assertEqual(user.username, 'googler_new')

        # Now simulate Google login callback routing
        identity = {
            "sub": "12345",
            "email": "google@example.com",
            "name": "Google User"
        }
        with app.test_request_context():
            resp = create_or_route_google_pending_user(identity)
            # Should login and redirect to dashboard index ('/')
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(resp.headers['Location'], '/')

    def test_username_unique_validation(self):
        user_a = User(
            username="usera",
            full_name="User A",
            role=UserRole.STAFF.value,
            is_active=True,
            approval_status="active"
        )
        user_a.set_password("pass_a")

        user_b = User(
            username="userb",
            full_name="User B",
            role=UserRole.STAFF.value,
            is_active=True,
            approval_status="active"
        )
        user_b.set_password("pass_b")

        db.session.add_all([user_a, user_b])
        db.session.commit()

        self._login_as(user_b)

        # Try to change B's username to A's username
        resp = self.client.post('/profile', data={
            'full_name': 'User B',
            'username': 'usera'
        }, headers={'X-Requested-With': 'XMLHttpRequest'})

        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data['success'])
        self.assertIn("đã tồn tại", data['message'])

        # Verify username B is unchanged
        db.session.refresh(user_b)
        self.assertEqual(user_b.username, 'userb')

    def test_username_invalid_validation(self):
        user = User(
            username="userb",
            full_name="User B",
            role=UserRole.STAFF.value,
            is_active=True,
            approval_status="active"
        )
        user.set_password("pass_b")
        db.session.add(user)
        db.session.commit()

        self._login_as(user)

        invalid_usernames = [
            "",  # empty
            "ab",  # too short
            "a" * 51,  # too long
            "user name",  # spaces
            "user@name",  # invalid symbol
            "admin",  # forbidden
            "owner",  # forbidden
            "google",  # forbidden
        ]

        for invalid in invalid_usernames:
            resp = self.client.post('/profile', data={
                'full_name': 'User B',
                'username': invalid
            }, headers={'X-Requested-With': 'XMLHttpRequest'})
            self.assertEqual(resp.status_code, 400)
            db.session.refresh(user)
            self.assertEqual(user.username, 'userb')

    def test_profile_update_does_not_allow_role_or_approval_mutation(self):
        user = User(
            username="userb",
            full_name="User B",
            role=UserRole.STAFF.value,
            is_active=True,
            approval_status="active"
        )
        user.set_password("pass_b")
        db.session.add(user)
        db.session.commit()

        self._login_as(user)

        resp = self.client.post('/profile', data={
            'full_name': 'User B',
            'username': 'userb_new',
            'role': 'OWNER',
            'approval_status': 'pending',
            'is_active': False
        }, headers={'X-Requested-With': 'XMLHttpRequest'})

        self.assertEqual(resp.status_code, 200)
        db.session.refresh(user)
        self.assertEqual(user.username, 'userb_new')
        self.assertEqual(user.role, UserRole.STAFF.value)
        self.assertTrue(user.is_active)
        self.assertEqual(user.approval_status, 'active')

    def test_disabled_input_issue_prevented(self):
        user = User(
            username="google_user",
            full_name="Google User",
            role=UserRole.STAFF.value,
            is_active=True,
            approval_status="active",
            auth_provider="google"
        )
        user.set_password("pass")
        db.session.add(user)
        db.session.commit()

        self._login_as(user)

        resp = self.client.get('/profile')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Check input tags for username
        self.assertIn('name="username"', html)
        self.assertIn('id="username"', html)
        self.assertNotIn('readonly', html.split('id="username"')[1].split('>')[0])
        self.assertNotIn('disabled', html.split('id="username"')[1].split('>')[0])

    def test_approval_owner_cannot_edit_profile(self):
        user = User(
            username="approval_user",
            full_name="Approval Owner",
            role=UserRole.APPROVAL_OWNER.value,
            is_active=True,
            approval_status="active"
        )
        user.set_password("pass")
        db.session.add(user)
        db.session.commit()

        self._login_as(user)

        resp_get = self.client.get('/profile')
        self.assertEqual(resp_get.status_code, 302)
        self.assertIn('/approval/pending', resp_get.headers['Location'])

        resp_post = self.client.post('/profile', data={
            'full_name': 'New Name',
            'username': 'new_approval'
        })
        self.assertEqual(resp_post.status_code, 302)
        self.assertIn('/approval/pending', resp_post.headers['Location'])
