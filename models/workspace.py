from extensions import db
from utils.timezone_utils import utc_now
from sqlalchemy import Index, UniqueConstraint


class Workspace(db.Model):
    __tablename__ = "workspaces"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    slug = db.Column(db.String(150), nullable=False, unique=True, index=True)
    status = db.Column(db.String(20), nullable=False, default="active", index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    members = db.relationship(
        "WorkspaceMember",
        back_populates="workspace",
        cascade="all, delete-orphan",
        lazy=True,
    )
    created_by = db.relationship("User", foreign_keys=[created_by_id], lazy=True)

    WORKSPACE_STATUSES = ("active", "pending", "suspended", "archived")

    def is_active(self):
        return self.status == "active"

    def __repr__(self):
        return f"<Workspace {self.slug} ({self.status})>"


class WorkspaceMember(db.Model):
    __tablename__ = "workspace_members"

    id = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False, default="staff", index=True)
    status = db.Column(db.String(20), nullable=False, default="active", index=True)
    invited_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    joined_at = db.Column(db.DateTime, nullable=True)
    removed_at = db.Column(db.DateTime, nullable=True)
    removed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    removal_reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    workspace = db.relationship("Workspace", back_populates="members", lazy=True)
    user = db.relationship("User", foreign_keys=[user_id], lazy=True)
    invited_by = db.relationship("User", foreign_keys=[invited_by_id], lazy=True)
    removed_by = db.relationship("User", foreign_keys=[removed_by_id], lazy=True)

    WORKSPACE_MEMBER_ROLES = ("owner", "admin", "staff")
    WORKSPACE_MEMBER_STATUSES = ("active", "invited", "disabled", "removed")

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_user"),
        Index("ix_workspace_members_workspace_role", "workspace_id", "role"),
        Index("ix_workspace_members_workspace_status", "workspace_id", "status"),
    )

    def is_owner(self):
        return self.role == "owner"

    def is_admin(self):
        return self.role == "admin"

    def is_staff(self):
        return self.role == "staff"

    def __repr__(self):
        return f"<WorkspaceMember workspace_id={self.workspace_id} user_id={self.user_id} role={self.role}>"
