"""Demo seed manifests (version 3): one packaged JSON file per Organization.

A manifest lists the Organization, its Workspaces (with collections and nested folders) and its
members. ``load_manifests`` reads the packaged files in ``MANIFEST_FILES`` order and applies the
rules that span several manifests; nothing here touches the database.
"""

import json
import re
import uuid
from collections.abc import Sequence
from importlib import resources
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ei_ai.knowledge.errors import InvalidKnowledgeInput
from ei_ai.knowledge.names import clean_name
from ei_ai.provisioning.validation import ProvisioningError, normalise_email
from ei_ai.rbac.roles import ASSIGNABLE_WORKSPACE_ROLES

MANIFEST_FILES: tuple[str, ...] = ("mekong-devworks.json", "song-han-retail.json")
SYSADMIN_EMAIL = "sysadmin@mekongdevworks.example"
PLACEHOLDER_WORDS: tuple[str, ...] = (
    "test",
    "tests",
    "testing",
    "foo",
    "bar",
    "baz",
    "lorem",
    "ipsum",
    "dummy",
    "placeholder",
    "sample",
    "todo",
    "xxx",
    "asdf",
)
MAX_FOLDER_DEPTH = 3

_ASSIGNABLE = frozenset(role.value for role in ASSIGNABLE_WORKSPACE_ROLES)
_PLACEHOLDER = re.compile(r"\b(?:" + "|".join(PLACEHOLDER_WORDS) + r")\b", re.IGNORECASE)


def _clean_text(value: str) -> str:
    """The trimmed name; raises ValueError unless it has 1-200 characters and no control one."""
    try:
        return clean_name(value)
    except InvalidKnowledgeInput:
        raise ValueError("must have 1-200 characters and no control character") from None


def _has_duplicate(names: Sequence[str]) -> bool:
    """True when two names are equal ignoring case."""
    lowered = [name.casefold() for name in names]
    return len(set(lowered)) != len(lowered)


class SeedFolder(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    folders: list["SeedFolder"] = []

    @field_validator("name")
    @classmethod
    def name_is_clean(cls, value: str) -> str:
        """The folder name follows the knowledge naming rules."""
        return _clean_text(value)

    @model_validator(mode="after")
    def sibling_names_are_unique(self) -> "SeedFolder":
        """No two child folders share a name, ignoring case."""
        if _has_duplicate([folder.name for folder in self.folders]):
            raise ValueError("sibling folder names must be unique")
        return self


class SeedCollection(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    subtitle: str | None = None
    access_level: Literal["public", "authenticated", "restricted"]
    groups: list[str] = []
    local_only: bool
    folders: list[SeedFolder] = []

    @field_validator("name")
    @classmethod
    def name_is_clean(cls, value: str) -> str:
        """The collection name follows the knowledge naming rules."""
        return _clean_text(value)

    @field_validator("subtitle")
    @classmethod
    def subtitle_is_clean(cls, value: str | None) -> str | None:
        """A subtitle, when given, follows the same text rules."""
        return None if value is None else _clean_text(value)

    @model_validator(mode="after")
    def groups_match_the_level(self) -> "SeedCollection":
        """Only a restricted collection has groups, and it has at least one."""
        if bool(self.groups) != (self.access_level == "restricted"):
            raise ValueError("groups are required for, and only for, a restricted collection")
        return self

    @model_validator(mode="after")
    def folders_are_valid(self) -> "SeedCollection":
        """Top-level folder names are unique and no folder is deeper than three levels."""
        if _has_duplicate([folder.name for folder in self.folders]):
            raise ValueError("sibling folder names must be unique")
        if _depth(self.folders) > MAX_FOLDER_DEPTH:
            raise ValueError(f"folders may be nested at most {MAX_FOLDER_DEPTH} levels deep")
        return self


def _depth(folders: Sequence[SeedFolder]) -> int:
    """The deepest nesting level of ``folders`` (0 for none)."""
    return max((1 + _depth(folder.folders) for folder in folders), default=0)


class SeedWorkspace(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    collections: list[SeedCollection] = []

    @field_validator("name")
    @classmethod
    def name_is_clean(cls, value: str) -> str:
        """The Workspace name has 1-200 characters and no control character."""
        return _clean_text(value)

    @model_validator(mode="after")
    def collection_names_are_unique(self) -> "SeedWorkspace":
        """No two collections of a Workspace share a name, ignoring case."""
        if _has_duplicate([collection.name for collection in self.collections]):
            raise ValueError("collection names must be unique within a Workspace")
        return self


class Member(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    email: str
    org_role: Literal["org_owner", "org_admin"] | None = None
    workspaces: dict[str, str] = {}
    shared_password: bool = True

    @field_validator("name")
    @classmethod
    def name_is_clean(cls, value: str) -> str:
        """The display name has 1-200 characters and no control character."""
        return _clean_text(value)

    @field_validator("email")
    @classmethod
    def email_is_normalised(cls, value: str) -> str:
        """The email must be valid and already trimmed and lowercase."""
        try:
            valid = normalise_email(value) == value
        except ProvisioningError as error:
            raise ValueError(str(error)) from None
        if not valid:
            raise ValueError("email must be trimmed and lowercase")
        return value

    @field_validator("workspaces")
    @classmethod
    def workspace_roles_are_assignable(cls, value: dict[str, str]) -> dict[str, str]:
        """Every Workspace role is one the Members screen can assign."""
        for role in value.values():
            if role not in _ASSIGNABLE:
                raise ValueError(f'"{role}" is not an assignable Workspace role')
        return value

    @model_validator(mode="after")
    def has_a_role(self) -> "Member":
        """A member holds an Organization role or at least one Workspace role."""
        if self.org_role is None and not self.workspaces:
            raise ValueError("a member needs at least one role")
        return self


class DemoManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: Literal[3]
    organization_id: uuid.UUID
    organization: str
    workspaces: list[SeedWorkspace] = Field(min_length=1)
    members: list[Member] = Field(min_length=1)

    @field_validator("organization")
    @classmethod
    def organization_is_clean(cls, value: str) -> str:
        """The Organization name has 1-200 characters and no control character."""
        return _clean_text(value)

    @model_validator(mode="after")
    def names_are_unique(self) -> "DemoManifest":
        """Member emails and Workspace names are unique (names ignoring case)."""
        if len({member.email for member in self.members}) != len(self.members):
            raise ValueError("member emails must be unique")
        if _has_duplicate([workspace.name for workspace in self.workspaces]):
            raise ValueError("Workspace names must be unique")
        return self

    @model_validator(mode="after")
    def member_workspaces_exist(self) -> "DemoManifest":
        """Every Workspace a member is assigned to is listed in the manifest."""
        known = {workspace.name for workspace in self.workspaces}
        for member in self.members:
            unknown = set(member.workspaces) - known
            if unknown:
                raise ValueError(f"{member.email} names unknown Workspaces: {sorted(unknown)}")
        return self

    @model_validator(mode="after")
    def has_no_placeholder_text(self) -> "DemoManifest":
        """No name, subtitle, folder, group or email local part holds a filler word."""
        for text in _manifest_texts(self):
            if _PLACEHOLDER.search(text):
                raise ValueError(f'placeholder text is not allowed: "{text}"')
        return self


def folder_names(folders: Sequence[SeedFolder]) -> list[str]:
    """The names of ``folders`` and of every folder nested below them."""
    names: list[str] = []
    for folder in folders:
        names.append(folder.name)
        names.extend(folder_names(folder.folders))
    return names


def _manifest_texts(manifest: DemoManifest) -> list[str]:
    """Every text of the manifest that a person reads (the email domain is excluded)."""
    texts = [manifest.organization]
    for workspace in manifest.workspaces:
        texts.append(workspace.name)
        for collection in workspace.collections:
            texts.extend([collection.name, *collection.groups, *folder_names(collection.folders)])
            if collection.subtitle:
                texts.append(collection.subtitle)
    for member in manifest.members:
        texts.extend([member.name, member.email.split("@", 1)[0]])
    return texts


def _check_sysadmin(manifest: DemoManifest) -> Member:
    """The sysadmin member, who must be Org Owner and Workspace Admin of every Workspace."""
    sysadmin = next((m for m in manifest.members if m.email == SYSADMIN_EMAIL), None)
    expected = {workspace.name: "workspace_admin" for workspace in manifest.workspaces}
    if sysadmin is None or sysadmin.org_role != "org_owner" or sysadmin.workspaces != expected:
        raise ValueError(
            f"{manifest.organization} needs the sysadmin as org_owner and workspace_admin "
            "in every Workspace"
        )
    return sysadmin


def validate_manifest_set(manifests: Sequence[DemoManifest]) -> None:
    """Check the rules that span manifests; raises ``ValueError`` on the first violation."""
    ids = [manifest.organization_id for manifest in manifests]
    names = [manifest.organization.casefold() for manifest in manifests]
    sysadmin_names = {
        member.name
        for manifest in manifests
        for member in manifest.members
        if member.email == SYSADMIN_EMAIL
    }
    seen_emails: set[str] = set()

    if len(set(ids)) != len(ids) or len(set(names)) != len(names):
        raise ValueError("Organization ids and names must be unique")
    if ids != sorted(ids):
        raise ValueError("Organization ids must ascend in manifest file order")
    if len(sysadmin_names) > 1:
        raise ValueError("the sysadmin must have the same name in every manifest")
    for index, manifest in enumerate(manifests):
        sysadmin = _check_sysadmin(manifest)
        # The first Organization is where sign-in lands for the sysadmin (R7, R25).
        if index == 0 and not sysadmin.shared_password:
            raise ValueError("the sysadmin needs shared_password in the first manifest")
        for member in manifest.members:
            if member.email in seen_emails and member.shared_password:
                raise ValueError(
                    f"{member.email} has shared_password only in the first manifest that lists it"
                )
            seen_emails.add(member.email)


def load_manifests() -> tuple[DemoManifest, ...]:
    """The packaged manifests in ``MANIFEST_FILES`` order, validated as a set."""
    data = resources.files("ei_ai.seed").joinpath("data")
    manifests = tuple(
        DemoManifest.model_validate(json.loads(data.joinpath(name).read_text("utf-8")))
        for name in MANIFEST_FILES
    )
    validate_manifest_set(manifests)
    return manifests
