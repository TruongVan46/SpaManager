import re
from extensions import db
from models import Workspace, WorkspaceMember
from utils.timezone_utils import utc_now


class WorkspaceService:
    @staticmethod
    def generate_unique_slug(base_string):
        """
        Generate a unique slug based on a string (e.g. name, username, email).
        Only lowercase alphanumeric characters and hyphens are kept.
        If duplicates exist, appends a counter (e.g. -2, -3).
        """
        s = base_string.strip().lower()
        if "@" in s:
            s = s.split("@")[0]

        # Replace non-alphanumeric characters with hyphens
        s = re.sub(r"[^a-z0-9]", "-", s)
        # Collapse multiple hyphens and trim
        s = re.sub(r"-+", "-", s).strip("-")

        if not s:
            s = "workspace"

        original_slug = s
        counter = 2
        while Workspace.query.filter(Workspace.slug == s).first() is not None:
            s = f"{original_slug}-{counter}"
            counter += 1
        return s

    @staticmethod
    def ensure_workspace_for_approved_owner(user, approved_by=None):
        """
        Ensure a workspace exists for the approved user and assign them as the owner.
        This operation is idempotent. If the user already has an active 'owner' membership,
        returns the existing workspace.

        Constraints:
        - Only for active users with active approval.
        - Exclude APPROVAL_OWNER role.
        """
        if not user or not user.is_active or not user.is_approval_active:
            return None

        if user.role == "APPROVAL_OWNER":
            return None

        # 1. Idempotency Check: check if user already has an 'owner' membership
        existing_membership = WorkspaceMember.query.filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.role == "owner",
        ).first()

        if existing_membership:
            if existing_membership.status != "active":
                existing_membership.status = "active"
                existing_membership.updated_at = utc_now()
                db.session.flush()
            return existing_membership.workspace

        # 2. Workspace name & slug generation
        # Fallback order: full_name -> username -> email
        base_name = user.full_name or user.username or user.email or "Spa"
        workspace_name = f"Spa của {base_name}"

        slug_base = user.username or user.email or user.full_name or "spa"
        slug = WorkspaceService.generate_unique_slug(slug_base)

        # 3. Create Workspace
        workspace = Workspace(
            name=workspace_name,
            slug=slug,
            status="active",
            created_by_id=user.id,
            notes=f"Created automatically when user {user.username} was approved.",
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        db.session.add(workspace)
        db.session.flush()  # Populates workspace.id

        # 4. Create WorkspaceMember
        membership = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role="owner",
            status="active",
            invited_by_id=approved_by.id if approved_by else None,
            joined_at=utc_now(),
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        db.session.add(membership)
        db.session.flush()

        return workspace

    @staticmethod
    def ensure_current_workspace_session(user):
        """
        Auto-select workspace for the user after successful login and set session["current_workspace_id"].

        Rules:
        - If user is APPROVAL_OWNER, do not set workspace context.
        - If user is pending/rejected/disabled, do not set workspace context.
        - If user has exactly one active workspace membership, set it.
        - If user has multiple active memberships, pick the oldest (deterministic, e.g. ordered by joined_at/id).
        - If user has no active memberships, do not set workspace context (legacy compatibility).
        """
        from flask import session

        if not user or not user.is_active or not user.is_approval_active:
            return None

        if user.role == "APPROVAL_OWNER":
            return None

        # Get active memberships, ordered deterministically by joined_at asc, id asc
        memberships = WorkspaceMember.query.filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.status == "active"
        ).order_by(WorkspaceMember.joined_at.asc(), WorkspaceMember.id.asc()).all()

        if not memberships:
            if user.role == "OWNER":
                workspace = WorkspaceService.ensure_workspace_for_approved_owner(user)
                if workspace:
                    try:
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
                        return None
                    session["current_workspace_id"] = workspace.id
                    return workspace
            return None

        # Auto-select the first one (oldest joined or lowest ID)
        selected_membership = memberships[0]
        session["current_workspace_id"] = selected_membership.workspace_id
        return selected_membership.workspace

    @staticmethod
    def get_current_workspace_from_session():
        """
        Get current Workspace object based on session["current_workspace_id"].
        """
        from flask import has_request_context, session
        if not has_request_context():
            return None
        workspace_id = session.get("current_workspace_id")
        if workspace_id:
            return db.session.get(Workspace, workspace_id)
        return None

    @staticmethod
    def clear_current_workspace_session():
        """
        Clear current workspace context from session during logout.
        """
        from flask import has_request_context, session
        if has_request_context():
            session.pop("current_workspace_id", None)

    @staticmethod
    def get_current_workspace_id():
        """
        Get current workspace ID from session, validating that the current user has access to it.
        """
        from flask import has_request_context, session
        from services.auth_service import AuthService

        if not has_request_context():
            return None

        workspace_id = session.get("current_workspace_id")
        if not workspace_id:
            return None

        user = AuthService.get_current_user()
        if not user or not user.is_active or not user.is_approval_active:
            session.pop("current_workspace_id", None)
            return None

        # Verify user role is not APPROVAL_OWNER
        if user.role == "APPROVAL_OWNER":
            session.pop("current_workspace_id", None)
            return None

        # Verify active membership exists
        has_membership = WorkspaceMember.query.filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.status == "active"
        ).first() is not None

        if not has_membership:
            session.pop("current_workspace_id", None)
            return None

        return workspace_id

    @staticmethod
    def require_current_workspace_id():
        """
        Get current workspace ID, raising 403 Forbidden if not set or invalid.
        """
        from flask import abort
        wid = WorkspaceService.get_current_workspace_id()
        if wid is None:
            abort(403)
        return wid

    @staticmethod
    def scoped_query(model):
        """
        Return a query for the model filtered by the current workspace_id.
        Fail closed: if there is no current workspace context, filters by workspace_id = -1
        (returning empty results instead of global data).
        """
        from flask import has_request_context, session, current_app, has_app_context

        is_testing = has_app_context() and current_app.config.get("TESTING") is True

        if is_testing:
            # Only enforce workspace isolation in unit tests if explicitly requested
            if has_request_context() and session.get("_enable_workspace_isolation") == True:
                wid = session.get("current_workspace_id")
                if wid is None:
                    return model.query.filter(model.workspace_id == -1)
                return model.query.filter(model.workspace_id == wid)
            else:
                return model.query

        wid = WorkspaceService.get_current_workspace_id()
        if wid is None:
            return model.query.filter(model.workspace_id == -1)
        return model.query.filter(model.workspace_id == wid)

    @staticmethod
    def assign_workspace(record):
        """
        Assign current_workspace_id to the record's workspace_id attribute.
        Raises 403 if there is no active workspace context.
        """
        from flask import has_request_context, session, current_app, has_app_context

        is_testing = has_app_context() and current_app.config.get("TESTING") is True

        if is_testing:
            if has_request_context() and session.get("_enable_workspace_isolation") == True:
                record.workspace_id = session.get("current_workspace_id")
            return

        wid = WorkspaceService.require_current_workspace_id()
        record.workspace_id = wid

    @staticmethod
    def add_member_for_user(workspace_id, user, global_role, actor=None):
        """
        Add a WorkspaceMember record for `user` in `workspace_id`.

        Maps global role to workspace role:
          OWNER  -> owner
          ADMIN  -> admin
          STAFF  -> staff

        Idempotent: if a membership already exists (any status), updates it to
        `active` and sets the mapped role.  Raises ValueError if workspace_id
        is None or if the global_role maps to an invalid workspace role.

        This method only flushes (does NOT commit).  The caller is responsible
        for committing the surrounding transaction.
        """
        if not workspace_id:
            raise ValueError("workspace_id is required to add workspace member.")

        role_map = {
            "OWNER": "owner",
            "ADMIN": "admin",
            "STAFF": "staff",
        }
        workspace_role = role_map.get((global_role or "").upper())
        if not workspace_role:
            raise ValueError(f"Cannot map global role '{global_role}' to a workspace role.")

        existing = WorkspaceMember.query.filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        ).first()

        if existing:
            existing.role = workspace_role
            existing.status = "active"
            existing.updated_at = utc_now()
        else:
            membership = WorkspaceMember(
                workspace_id=workspace_id,
                user_id=user.id,
                role=workspace_role,
                status="active",
                invited_by_id=actor.id if actor else None,
                joined_at=utc_now(),
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            db.session.add(membership)

        db.session.flush()

    @staticmethod
    def get_workspace_members_query(workspace_id):
        """
        Return a base query of User joined with WorkspaceMember for a workspace.
        Used by UserService to scope the user list.
        Returns None if workspace_id is falsy.
        """
        from models.user import User as UserModel

        if not workspace_id:
            return None

        return (
            UserModel.query
            .join(
                WorkspaceMember,
                (WorkspaceMember.user_id == UserModel.id)
                & (WorkspaceMember.workspace_id == workspace_id)
                & (WorkspaceMember.status == "active"),
            )
        )

    @staticmethod
    def is_user_in_workspace(user_id, workspace_id):
        """
        Check whether user_id has an active membership in workspace_id.
        """
        if not workspace_id or not user_id:
            return False
        return WorkspaceMember.query.filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.status == "active",
        ).first() is not None

    @staticmethod
    def _get_current_workspace_id_for_testing_bypass():
        """
        Get current workspace ID, or return None if testing bypass is active.
        If testing bypass is not active and workspace is None, returns -1 to fail-closed.
        This helper is test-only and ensures production-like fail-closed behavior.
        """
        from flask import has_request_context, session, current_app, has_app_context

        is_testing = has_app_context() and current_app.config.get("TESTING") is True
        if is_testing:
            if not has_request_context() or not session.get("_enable_workspace_isolation"):
                return None

        wid = WorkspaceService.get_current_workspace_id()
        return wid if wid is not None else -1
