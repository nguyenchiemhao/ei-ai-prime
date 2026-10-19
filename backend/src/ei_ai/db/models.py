"""SQLAlchemy 2 models of the tenancy core (revision 0001) and provisioning (revision 0002). The
schema itself is created by the migrations, never by ``metadata.create_all``."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Text, UniqueConstraint, text
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
