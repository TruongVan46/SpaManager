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

        # 1. Idempotency Check: check if user already has an active 'owner' membership
        existing_membership = WorkspaceMember.query.filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.role == "owner",
            WorkspaceMember.status == "active",
        ).first()

        if existing_membership:
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
