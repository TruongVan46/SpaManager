import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

TEST_DB_FILE = Path(tempfile.gettempdir()) / "spamanager_owner_seed_test.sqlite"
TEST_MEDIA_ROOT = Path(tempfile.gettempdir()) / "spamanager_media_seed_test"
if TEST_DB_FILE.exists():
    TEST_DB_FILE.unlink()
if TEST_MEDIA_ROOT.exists():
    shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)
os.environ["APP_ENV"] = "testing"
os.environ["TEST_DATABASE_URL"] = f"sqlite:///{TEST_DB_FILE.as_posix()}"
os.environ["PERSISTENT_ROOT"] = TEST_MEDIA_ROOT.as_posix()
os.environ["UPLOAD_ROOT"] = (TEST_MEDIA_ROOT / "uploads").as_posix()
os.environ["LOGO_UPLOAD_FOLDER"] = (TEST_MEDIA_ROOT / "uploads" / "logos").as_posix()
os.environ["AVATAR_UPLOAD_FOLDER"] = (TEST_MEDIA_ROOT / "uploads" / "avatars").as_posix()

from app import app
from config import DevelopmentConfig, ProductionConfig
from extensions import db
from models.user import User
from services.auth_service import AuthService


class BasicTestCase(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        try:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        finally:
            if TEST_DB_FILE.exists():
                TEST_DB_FILE.unlink()
            if TEST_MEDIA_ROOT.exists():
                shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.app_context = app.app_context()
        self.app_context.push()
        self.client = app.test_client()
        db.session.rollback()
        User.query.delete(synchronize_session=False)
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        User.query.delete(synchronize_session=False)
        db.session.commit()
        self.app_context.pop()

    def create_user(self, username, password="secret123", full_name="Test User", role="STAFF"):
        user = User(
            username=username,
            full_name=full_name,
            role=role,
            is_active=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user

    def create_media_file(self, relative_path, content=b"media-bytes"):
        absolute_path = TEST_MEDIA_ROOT / relative_path
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        absolute_path.write_bytes(content)
        return absolute_path

    def insert_owner_row(self):
        now = datetime.utcnow()
        with db.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO users
                        (username, password_hash, full_name, avatar, role, is_active,
                         last_login, email, email_verified, auth_provider, oauth_id,
                         created_at, updated_at)
                    VALUES
                        (:username, :password_hash, :full_name, NULL, :role, :is_active,
                         NULL, NULL, 0, 'local', NULL, :created_at, :updated_at)
                    """
                ),
                {
                    "username": "owner",
                    "password_hash": "existing-owner-hash",
                    "full_name": "Chủ Spa",
                    "role": "OWNER",
                    "is_active": 1,
                    "created_at": now,
                    "updated_at": now,
                },
            )

    def test_app_initialization(self):
        self.assertIsNotNone(app)

    def test_login_page_loads(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)

    def test_health_check_returns_json_without_login(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertTrue(response.is_json)
        self.assertEqual(response.get_json(), {
            "status": "ok",
            "app": "SpaManager",
            "database": "connected",
        })

    def test_health_check_executes_database_probe(self):
        with patch("app.db.session.execute") as mocked_execute:
            response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        mocked_execute.assert_called_once()
        self.assertEqual(str(mocked_execute.call_args.args[0]), "SELECT 1")

    def test_health_check_returns_503_on_database_error_and_rolls_back(self):
        self.create_user("health-check-user", password="health-pass", full_name="Health Check", role="STAFF")
        original_rollback = db.session.rollback

        with patch("app.db.session.execute", side_effect=SQLAlchemyError("database unavailable")) as mocked_execute:
            with patch("app.db.session.rollback", wraps=original_rollback) as mocked_rollback:
                response = self.client.get("/health")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertTrue(response.is_json)
        payload = response.get_json()
        self.assertEqual(payload["status"], "unhealthy")
        self.assertEqual(payload["database"], "unavailable")
        self.assertNotIn("password", response.get_data(as_text=True).lower())
        self.assertNotIn("database unavailable", response.get_data(as_text=True).lower())
        mocked_execute.assert_called_once()
        mocked_rollback.assert_called_once()
        self.assertEqual(User.query.filter_by(username="health-check-user").count(), 1)

    def test_health_check_post_method_is_not_allowed(self):
        response = self.client.post("/health")

        self.assertEqual(response.status_code, 405)

    def test_health_check_session_remains_usable_after_rollback(self):
        self.create_user("session-safe", password="session-pass", full_name="Session Safe", role="STAFF")

        with patch("app.db.session.execute", side_effect=SQLAlchemyError("database unavailable")):
            response = self.client.get("/health")

        self.assertEqual(response.status_code, 503)
        query_result = User.query.filter_by(username="session-safe").first()
        self.assertIsNotNone(query_result)
        self.assertEqual(query_result.username, "session-safe")

    def test_production_requires_secret_key(self):
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "sqlite:///prod.sqlite",
                "DEFAULT_OWNER_PASSWORD": "prod-owner-pass",
                "SECRET_KEY": "",
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                ProductionConfig()

    def test_production_requires_database_url(self):
        with patch.dict(
            os.environ,
            {
                "SECRET_KEY": "prod-secret",
                "DEFAULT_OWNER_PASSWORD": "prod-owner-pass",
                "DATABASE_URL": "",
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                ProductionConfig()

    def test_media_route_serves_logo_from_persistent_folder(self):
        self.create_media_file(Path("uploads") / "logos" / "sample-logo.png", b"\x89PNG\r\n\x1a\n")

        response = self.client.get("/media/logos/sample-logo.png")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/png")
        response.close()

    def test_missing_media_returns_404_without_redirect(self):
        response = self.client.get("/media/logos/missing.png", follow_redirects=False)

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("Location", response.headers)

    def test_seed_owner_creates_owner_when_database_is_empty(self):
        owner = AuthService.seed_owner_if_empty()

        self.assertIsNotNone(owner)
        self.assertEqual(owner.username, "owner")
        self.assertEqual(User.query.filter_by(username="owner").count(), 1)
        self.assertTrue(User.query.filter_by(username="owner").first().check_password("owner123"))

    def test_seed_owner_does_not_change_existing_owner(self):
        existing_owner = self.create_user("owner", password="old-password", full_name="Chủ Spa", role="OWNER")
        existing_hash = existing_owner.password_hash

        result = AuthService.seed_owner_if_empty()

        refreshed_owner = User.query.filter_by(username="owner").first()
        self.assertEqual(result.id, existing_owner.id)
        self.assertEqual(User.query.filter_by(username="owner").count(), 1)
        self.assertEqual(refreshed_owner.password_hash, existing_hash)
        self.assertTrue(refreshed_owner.check_password("old-password"))

    def test_seed_owner_creates_owner_when_other_user_exists(self):
        self.create_user("customer-1", password="customer-pass", full_name="Customer 1", role="STAFF")

        owner = AuthService.seed_owner_if_empty()

        self.assertIsNotNone(owner)
        self.assertEqual(owner.username, "owner")
        self.assertEqual(User.query.filter_by(username="owner").count(), 1)
        self.assertEqual(User.query.count(), 2)

    def test_seed_owner_recovers_from_integrity_error_when_owner_appears(self):
        self.create_user("observer", password="observer-pass", full_name="Observer", role="STAFF")

        def inject_owner_before_commit(session):
            self.insert_owner_row()

        event.listen(db.session, "before_commit", inject_owner_before_commit)
        try:
            result = AuthService.seed_owner_if_empty()
        finally:
            event.remove(db.session, "before_commit", inject_owner_before_commit)

        self.assertEqual(result.username, "owner")
        self.assertEqual(User.query.filter_by(username="owner").count(), 1)
        self.assertEqual(User.query.filter_by(username="observer").first().username, "observer")
        self.assertEqual(User.query.count(), 2)

    def test_seed_owner_raises_when_integrity_error_and_owner_still_missing(self):
        self.create_user("observer-2", password="observer-pass", full_name="Observer 2", role="STAFF")
        original_add = db.session.add
        duplicate_added = False

        def add_duplicate_owner(obj):
            nonlocal duplicate_added
            original_add(obj)
            if isinstance(obj, User) and obj.username == "owner" and not duplicate_added:
                duplicate_added = True
                duplicate_owner = User(
                    username="owner",
                    full_name="Chủ Spa",
                    role="OWNER",
                    is_active=True,
                )
                duplicate_owner.set_password("duplicate-pass")
                original_add(duplicate_owner)

        with patch("services.auth_service.db.session.add", side_effect=add_duplicate_owner):
            with self.assertRaises(IntegrityError):
                AuthService.seed_owner_if_empty()

        self.assertIsNone(User.query.filter_by(username="owner").first())
        self.assertEqual(User.query.filter_by(username="observer-2").first().username, "observer-2")
        self.assertEqual(User.query.count(), 1)

    def test_seed_owner_session_still_queryable_after_rollback(self):
        self.create_user("session-check", password="session-pass", full_name="Session Check", role="STAFF")
        original_add = db.session.add
        duplicate_added = False

        def add_duplicate_owner(obj):
            nonlocal duplicate_added
            original_add(obj)
            if isinstance(obj, User) and obj.username == "owner" and not duplicate_added:
                duplicate_added = True
                duplicate_owner = User(
                    username="owner",
                    full_name="Chủ Spa",
                    role="OWNER",
                    is_active=True,
                )
                duplicate_owner.set_password("duplicate-pass")
                original_add(duplicate_owner)

        with patch("services.auth_service.db.session.add", side_effect=add_duplicate_owner):
            with self.assertRaises(IntegrityError):
                AuthService.seed_owner_if_empty()

        query_result = User.query.filter_by(username="session-check").first()
        self.assertIsNotNone(query_result)
        self.assertEqual(query_result.username, "session-check")

    def test_seed_owner_multiple_calls_keep_single_owner(self):
        AuthService.seed_owner_if_empty()
        AuthService.seed_owner_if_empty()
        AuthService.seed_owner_if_empty()

        self.assertEqual(User.query.filter_by(username="owner").count(), 1)
        self.assertEqual(User.query.count(), 1)

    def test_production_requires_owner_password(self):
        with patch.dict(
            os.environ,
            {
                "SECRET_KEY": "prod-secret",
                "DATABASE_URL": "sqlite:///prod.sqlite",
                "DEFAULT_OWNER_PASSWORD": "",
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                ProductionConfig()

    def test_production_reads_database_url_and_persistent_paths(self):
        with patch.dict(
            os.environ,
            {
                "SECRET_KEY": "prod-secret",
                "DATABASE_URL": "sqlite:////app/database/spa.db",
                "DEFAULT_OWNER_PASSWORD": "prod-owner-pass",
                "PERSISTENT_ROOT": "/app/database",
            },
            clear=True,
        ):
            config = ProductionConfig()

        self.assertEqual(config.SQLALCHEMY_DATABASE_URI, "sqlite:////app/database/spa.db")
        self.assertEqual(config.PERSISTENT_ROOT, "/app/database")
        self.assertEqual(config.UPLOAD_ROOT.replace("\\", "/"), "/app/database/uploads")
        self.assertEqual(config.LOGO_UPLOAD_FOLDER.replace("\\", "/"), "/app/database/uploads/logos")
        self.assertEqual(config.AVATAR_UPLOAD_FOLDER.replace("\\", "/"), "/app/database/uploads/avatars")
        self.assertFalse(config.DEBUG)

    def test_local_config_can_still_initialize(self):
        config = DevelopmentConfig()

        self.assertTrue(config.DEBUG)
        self.assertTrue(config.SQLALCHEMY_DATABASE_URI.startswith("sqlite:///"))
        self.assertEqual(config.DEFAULT_OWNER_USERNAME, "owner")
        self.assertEqual(config.DEFAULT_OWNER_PASSWORD, "owner123")

    def test_google_oauth_variables_remain_optional(self):
        with patch.dict(
            os.environ,
            {
                "SECRET_KEY": "prod-secret",
                "DATABASE_URL": "sqlite:///prod.sqlite",
                "DEFAULT_OWNER_PASSWORD": "prod-owner-pass",
            },
            clear=True,
        ):
            config = ProductionConfig()

        self.assertEqual(config.GOOGLE_CLIENT_ID, "")
        self.assertEqual(config.GOOGLE_CLIENT_SECRET, "")
        self.assertEqual(config.GOOGLE_REDIRECT_URI, "")


if __name__ == "__main__":
    unittest.main()
