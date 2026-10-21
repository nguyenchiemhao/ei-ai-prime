"""The output of ``ei-ai seed demo``: one block per Organization (EA-94 contract §3).

It holds names, ids, roles and counts only: never a password, a hash, a token or a link. A run
that creates nothing prints the same text every time.
"""

import uuid
from dataclasses import dataclass

from ei_ai.seed.manifest import DemoManifest, Member, folder_names


@dataclass(frozen=True)
class SeedResult:
    """What one run found or created for one Organization.

    ``workspaces`` holds ``(name, id, created)`` and ``members_created`` one flag per member,
    both in manifest order; ``audit_events`` counts the events actually written this run.
    """

    organization_created: bool
    workspaces: tuple[tuple[str, uuid.UUID, bool], ...]
    members_created: tuple[bool, ...]
    collections_created: int
    folders_created: int
    passwords_applied: int
    audit_events: int


def _status(created: bool) -> str:
    """The status word of one summary line."""
    return "created" if created else "already present"


def _roles(manifest: DemoManifest, member: Member) -> str:
    """The member's Organization role, then ``Workspace=role`` in manifest Workspace order."""
    roles: list[str] = [member.org_role] if member.org_role else []
    roles += [
        f"{workspace.name}={member.workspaces[workspace.name]}"
        for workspace in manifest.workspaces
        if workspace.name in member.workspaces
    ]
    return ", ".join(roles)


def format_summary(manifest: DemoManifest, result: SeedResult) -> str:
    """The lines of one Organization, joined by newlines."""
    collections = [c for workspace in manifest.workspaces for c in workspace.collections]
    folders = sum(len(folder_names(collection.folders)) for collection in collections)
    shared = sum(member.shared_password for member in manifest.members)
    lines = [
        f"Demo seed: {manifest.organization}",
        f"  Organization: {manifest.organization} ({manifest.organization_id}):"
        f" {_status(result.organization_created)}",
        *(
            f"  Workspace: {name} ({ws_id}): {_status(created)}"
            for name, ws_id, created in result.workspaces
        ),
        f"  Members: {len(manifest.members)}",
        *(
            f"    - {member.name}: {_roles(manifest, member)}: {_status(created)}"
            for member, created in zip(manifest.members, result.members_created, strict=True)
        ),
        f"  Collections: {len(collections)} (created: {result.collections_created})",
        f"  Folders: {folders} (created: {result.folders_created})",
        f"  Shared test password applied to {result.passwords_applied} of {shared} accounts",
        f"  Audit events written: {result.audit_events}",
    ]
    return "\n".join(lines)
