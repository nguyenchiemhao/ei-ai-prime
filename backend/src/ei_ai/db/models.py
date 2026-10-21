"""SQLAlchemy 2 models of the tenancy core (0001), provisioning (0002), admin sign-in (0003) and
the model catalog (0005).
The schema itself is created by the migrations, never by ``metadata.create_all``."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, server_default=text("uuid_generate_v7()"))


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=text("now()"))


class Organization(Base):
    """Tenant root. Its RLS key is its own ``id``."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(Text)
    # "Allow cloud models" (D17): off by default.
    allow_cloud_models: Mapped[bool] = mapped_column(server_default=text("false"))
    created_at: Mapped[datetime] = _created_at()


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("org_id", "id"), UniqueConstraint("org_id", "name"))

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class User(Base):
    """A person in one Organization; the same email in another Organization is another user."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("org_id", "id"), UniqueConstraint("org_id", "email"))

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    email: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class Membership(Base):
    """A user in an Organization; ``org_role`` is NULL for a plain member."""

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        UniqueConstraint("org_id", "user_id"),
        ForeignKeyConstraint(["org_id", "user_id"], ["users.org_id", "users.id"]),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    user_id: Mapped[uuid.UUID]
    org_role: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class WorkspaceMembership(Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        UniqueConstraint("org_id", "workspace_id", "user_id"),
        ForeignKeyConstraint(["org_id", "workspace_id"], ["workspaces.org_id", "workspaces.id"]),
        ForeignKeyConstraint(["org_id", "user_id"], ["memberships.org_id", "memberships.user_id"]),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID]
    workspace_id: Mapped[uuid.UUID]
    user_id: Mapped[uuid.UUID]
    role: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class AuditEvent(Base):
    """One platform or admin action (D50). Insert only; no free text and no personal data."""

    __tablename__ = "audit_events"
    __table_args__ = (UniqueConstraint("org_id", "id"),)

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    actor: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str] = mapped_column(Text)
    target_id: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = _created_at()


class SetPasswordToken(Base):
    """A one-time set-password link; only the sha256 of its secret is stored."""

    __tablename__ = "set_password_tokens"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        UniqueConstraint("org_id", "token_hash"),
        ForeignKeyConstraint(["org_id", "user_id"], ["users.org_id", "users.id"]),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    user_id: Mapped[uuid.UUID]
    token_hash: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class UserCredential(Base):
    """The Argon2id hash and lockout counters of one user. No row: no password set yet."""

    __tablename__ = "user_credentials"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        UniqueConstraint("org_id", "user_id"),
        ForeignKeyConstraint(["org_id", "user_id"], ["users.org_id", "users.id"]),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    user_id: Mapped[uuid.UUID]
    password_hash: Mapped[str] = mapped_column(Text)
    password_set_at: Mapped[datetime] = _created_at()
    failed_attempts: Mapped[int] = mapped_column(server_default=text("0"))
    failure_window_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class AdminSession(Base):
    """A server-side admin session; only the sha256 of the cookie secret is stored."""

    __tablename__ = "admin_sessions"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        UniqueConstraint("org_id", "token_hash"),
        ForeignKeyConstraint(["org_id", "user_id"], ["users.org_id", "users.id"]),
        Index("admin_sessions_org_user_idx", "org_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    user_id: Mapped[uuid.UUID]
    token_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    last_seen_at: Mapped[datetime] = _created_at()


class ModelCatalogEntry(Base):
    """One pinned model version an Organization can call (EA-24). The pin columns (kind, model_id,
    version, digest, source_revision, deployment, provider) are immutable (database trigger)."""

    __tablename__ = "model_catalog"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        UniqueConstraint("org_id", "model_id", "version"),
    )

    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    kind: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    model_id: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    digest: Mapped[str | None] = mapped_column(Text)
    source_revision: Mapped[str | None] = mapped_column(Text)
    deployment: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    vietnamese_quality: Mapped[str | None] = mapped_column(Text)
    vietnamese_quality_measured: Mapped[bool] = mapped_column(server_default=text("false"))
    tool_use: Mapped[bool] = mapped_column(server_default=text("false"))
    context_window: Mapped[int | None]
    speed: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'available'"))
    retirement_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = _created_at()
