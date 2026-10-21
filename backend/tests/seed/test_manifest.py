import json
import os
import re
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ei_ai.rbac.roles import ASSIGNABLE_WORKSPACE_ROLES
from ei_ai.seed.manifest import (
    MANIFEST_FILES,
    PLACEHOLDER_WORDS,
    SYSADMIN_EMAIL,
    DemoManifest,
    SeedFolder,
    load_manifests,
    validate_manifest_set,
)

REPO_ROOT = Path(os.environ.get("EI_AI_REPO_ROOT", Path(__file__).resolve().parents[3]))
FAKE_DATA = REPO_ROOT / "eval" / "datasets" / "mekong-devworks" / "fake_personal_data.json"
MEKONG_ID = "0192a000-0000-7000-8000-00000000ea21"
SONG_HAN_ID = "0192a000-0000-7000-8000-00000000ea94"


def _raw(file_name: str = "mekong-devworks.json") -> dict[str, Any]:
    text = resources.files("ei_ai.seed").joinpath(f"data/{file_name}").read_text("utf-8")
    raw: dict[str, Any] = json.loads(text)
    return raw


def _mekong() -> DemoManifest:
    return load_manifests()[0]


def _song_han() -> DemoManifest:
    return load_manifests()[1]


def _workspace(manifest: DemoManifest, name: str) -> Any:
    return next(w for w in manifest.workspaces if w.name == name)


def _collection(manifest: DemoManifest, workspace: str, name: str) -> Any:
    return next(c for c in _workspace(manifest, workspace).collections if c.name == name)


def _member(manifest: DemoManifest, name: str) -> Any:
    return next(m for m in manifest.members if m.name == name)


def _folder_paths(folders: list[SeedFolder], prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    paths: list[tuple[str, ...]] = []
    for folder in folders:
        path = (*prefix, folder.name)
        paths.append(path)
        paths.extend(_folder_paths(folder.folders, path))
    return paths


def _all_folder_paths(manifest: DemoManifest) -> list[tuple[str, ...]]:
    return [
        path
        for workspace in manifest.workspaces
        for collection in workspace.collections
        for path in _folder_paths(collection.folders)
    ]


def _all_texts(manifest: DemoManifest) -> list[str]:
    texts = [manifest.organization]
    for workspace in manifest.workspaces:
        texts.append(workspace.name)
        for collection in workspace.collections:
            texts.extend([collection.name, collection.subtitle or "", *collection.groups])
    texts.extend(name for path in _all_folder_paths(manifest) for name in path)
    for member in manifest.members:
        texts.extend([member.name, member.email.split("@")[0]])
    return texts


def test_manifest_files_match_the_data_directory() -> None:
    data = resources.files("ei_ai.seed").joinpath("data")
    listed = sorted(item.name for item in data.iterdir() if item.name.endswith(".json"))

    assert sorted(MANIFEST_FILES) == listed
    assert MANIFEST_FILES == ("mekong-devworks.json", "song-han-retail.json")


def test_existing_people_ops_members_and_collections_are_unchanged() -> None:
    mekong = _mekong()
    expected_members = [
        ("Linh Tran", "linh.tran@mekongdevworks.example", "org_admin", "workspace_admin"),
        ("Minh Pham", "minh.pham@mekongdevworks.example", None, "builder"),
        ("Thao Nguyen", "thao.nguyen@mekongdevworks.example", None, "knowledge_editor"),
        ("Quang Le", "quang.le@mekongdevworks.example", None, "developer"),
        ("Hà Vũ", "ha.vu@mekongdevworks.example", None, "reviewer"),
        ("Son Hoang", "son.hoang@mekongdevworks.example", None, "viewer"),
    ]

    assert str(mekong.organization_id) == MEKONG_ID
    assert mekong.organization == "Mekong Devworks"
    assert [w.name for w in mekong.workspaces] == ["People Ops", "Engineering"]
    assert [
        (m.name, m.email, m.org_role, m.workspaces.get("People Ops")) for m in mekong.members[:6]
    ] == expected_members
    assert [
        (c.name, c.subtitle, c.access_level, c.groups, c.local_only)
        for c in _workspace(mekong, "People Ops").collections
    ] == [
        ("Company & Careers", None, "public", [], False),
        ("Employee Handbook", None, "authenticated", [], False),
        ("Engineering Standards", None, "authenticated", [], False),
        ("IT & Security", None, "authenticated", [], False),
        ("Manager Handbook", None, "restricted", ["managers"], True),
        ("Project Falcon", "Client: Japan · under NDA", "restricted", ["project-falcon"], True),
    ]


def test_mekong_engineering_workspace_content() -> None:
    mekong = _mekong()

    assert [
        (c.name, c.access_level, c.groups, c.local_only)
        for c in _workspace(mekong, "Engineering").collections
    ] == [
        ("Architecture Decisions", "authenticated", [], False),
        ("Runbooks", "restricted", ["on-call"], True),
    ]
    assert _member(mekong, "Duy Lâm").org_role == "org_owner"
    assert _member(mekong, "Duy Lâm").workspaces == {}
    assert _member(mekong, "Vy Huỳnh").workspaces == {"Engineering": "developer"}
    assert _member(mekong, "Phúc Lương").workspaces == {"Engineering": "knowledge_editor"}


def test_every_assignable_role_and_org_role_is_seeded() -> None:
    seeded = {
        role
        for manifest in load_manifests()
        for member in manifest.members
        for role in (member.org_role, *member.workspaces.values())
    }
    required = {"org_owner", "org_admin"} | {role.value for role in ASSIGNABLE_WORKSPACE_ROLES}

    assert required <= seeded


def test_sysadmin_is_owner_and_admin_everywhere() -> None:
    for manifest in load_manifests():
        sysadmin = next(m for m in manifest.members if m.email == SYSADMIN_EMAIL)

        assert sysadmin.name == "Trung Võ"
        assert sysadmin.org_role == "org_owner"
        assert sysadmin.workspaces == {w.name: "workspace_admin" for w in manifest.workspaces}


def test_one_person_has_different_roles_in_two_workspaces() -> None:
    quang = _member(_mekong(), "Quang Le")

    assert quang.workspaces == {"People Ops": "developer", "Engineering": "workspace_admin"}


def test_employee_handbook_folders_match_the_artboard() -> None:
    handbook = _collection(_mekong(), "People Ops", "Employee Handbook")
    paths = _folder_paths(handbook.folders)

    assert [f.name for f in handbook.folders] == [
        "Policies",
        "Benefits",
        "Onboarding & offboarding",
        "Templates",
    ]
    assert ("Templates", "Contracts", "Labor contracts") in paths
    assert len(paths) == 14


def test_folder_counts() -> None:
    assert len(_all_folder_paths(_mekong())) == 33
    assert len(_all_folder_paths(_song_han())) == 3


def test_second_org_has_workspace_member_and_collection() -> None:
    song_han = _song_han()
    ngan = _member(song_han, "Ngân Trịnh")

    assert str(song_han.organization_id) == SONG_HAN_ID
    assert song_han.organization == "Sông Hàn Retail"
    assert [w.name for w in song_han.workspaces] == ["Customer Care"]
    assert (ngan.email, ngan.org_role, ngan.workspaces) == (
        "ngan.trinh@songhanretail.example",
        "org_admin",
        {"Customer Care": "workspace_admin"},
    )
    assert [c.name for c in song_han.workspaces[0].collections] == ["Store Policies"]
    assert _member(song_han, "Trung Võ").shared_password is False


def test_no_placeholder_text() -> None:
    pattern = re.compile(r"\b(?:" + "|".join(PLACEHOLDER_WORDS) + r")\b", re.IGNORECASE)

    for manifest in load_manifests():
        assert [text for text in _all_texts(manifest) if pattern.search(text)] == []


def test_placeholder_text_is_rejected_by_the_model() -> None:
    raw = _raw()
    raw["workspaces"][0]["collections"][0]["folders"][0]["name"] = "Lorem ipsum"

    with pytest.raises(ValidationError):
        DemoManifest.model_validate(raw)


@pytest.mark.skipif(not FAKE_DATA.exists(), reason="the eval datasets are not mounted")
def test_names_avoid_the_fake_personal_data_registry() -> None:
    registry = {name.lower() for name in json.loads(FAKE_DATA.read_text("utf-8"))["names"]}

    for manifest in load_manifests():
        assert registry.isdisjoint(member.name.lower() for member in manifest.members)


def _too_deep(raw: dict[str, Any]) -> None:
    level_four = {"name": "D"}
    level_three = {"name": "C", "folders": [level_four]}
    level_two = {"name": "B", "folders": [level_three]}
    raw["workspaces"][0]["collections"][0]["folders"] = [{"name": "A", "folders": [level_two]}]


def _duplicate_sibling(raw: dict[str, Any]) -> None:
    raw["workspaces"][0]["collections"][0]["folders"] = [{"name": "Policies"}, {"name": "POLICIES"}]


def _control_character(raw: dict[str, Any]) -> None:
    raw["workspaces"][0]["collections"][0]["folders"] = [{"name": "Bad\nname"}]


@pytest.mark.parametrize("mutate", [_too_deep, _duplicate_sibling, _control_character])
def test_folder_depth_and_sibling_names(mutate: Any) -> None:
    raw = _raw()
    mutate(raw)

    with pytest.raises(ValidationError):
        DemoManifest.model_validate(raw)


def test_same_folder_name_under_different_parents_is_allowed() -> None:
    raw = _raw()
    raw["workspaces"][0]["collections"][0]["folders"] = [
        {"name": "One", "folders": [{"name": "Archive"}]},
        {"name": "Two", "folders": [{"name": "Archive"}]},
    ]

    DemoManifest.model_validate(raw)


def test_member_workspace_must_exist() -> None:
    raw = _raw()
    raw["members"][1]["workspaces"] = {"Nowhere": "builder"}

    with pytest.raises(ValidationError):
        DemoManifest.model_validate(raw)


def test_member_role_member_is_rejected() -> None:
    raw = _raw()
    raw["members"][1]["workspaces"] = {"People Ops": "member"}

    with pytest.raises(ValidationError):
        DemoManifest.model_validate(raw)


def test_member_needs_a_role() -> None:
    raw = _raw()
    raw["members"][1]["workspaces"] = {}
    raw["members"][1]["org_role"] = None

    with pytest.raises(ValidationError):
        DemoManifest.model_validate(raw)


@pytest.mark.parametrize("email", ["not-an-email", "Minh.Pham@mekongdevworks.example", " a@b.c"])
def test_member_emails_must_be_valid_and_normalised(email: str) -> None:
    raw = _raw()
    raw["members"][1]["email"] = email

    with pytest.raises(ValidationError):
        DemoManifest.model_validate(raw)


def test_member_emails_are_unique() -> None:
    raw = _raw()
    raw["members"][1]["email"] = raw["members"][0]["email"]

    with pytest.raises(ValidationError):
        DemoManifest.model_validate(raw)


def test_workspace_names_are_unique_ignoring_case() -> None:
    raw = _raw()
    raw["workspaces"][1]["name"] = "PEOPLE OPS"

    with pytest.raises(ValidationError):
        DemoManifest.model_validate(raw)


def test_collection_names_are_unique_per_workspace_ignoring_case() -> None:
    raw = _raw()
    collections = raw["workspaces"][0]["collections"]
    collections[1]["name"] = collections[0]["name"].upper()

    with pytest.raises(ValidationError):
        DemoManifest.model_validate(raw)


def test_restricted_collections_need_groups_and_others_have_none() -> None:
    restricted = _raw()
    restricted["workspaces"][0]["collections"][4]["groups"] = []
    open_one = _raw()
    open_one["workspaces"][0]["collections"][0]["groups"] = ["managers"]

    for raw in (restricted, open_one):
        with pytest.raises(ValidationError):
            DemoManifest.model_validate(raw)


def test_shared_password_defaults_to_true() -> None:
    assert _member(_mekong(), "Linh Tran").shared_password is True


def test_shared_password_only_in_first_manifest_for_shared_emails() -> None:
    mekong, song_han = load_manifests()
    raw = _raw("song-han-retail.json")
    for member in raw["members"]:
        member["shared_password"] = True
    both_shared = DemoManifest.model_validate(raw)

    validate_manifest_set([mekong, song_han])
    with pytest.raises(ValueError, match="shared_password"):
        validate_manifest_set([mekong, both_shared])


def test_sysadmin_has_the_shared_password_in_the_first_manifest() -> None:
    song_han = _song_han()
    raw = _raw()
    for member in raw["members"]:
        if member["email"] == SYSADMIN_EMAIL:
            member["shared_password"] = False
    without_credential = DemoManifest.model_validate(raw)

    with pytest.raises(ValueError, match="sysadmin"):
        validate_manifest_set([without_credential, song_han])


def test_org_ids_ascend_in_file_order() -> None:
    mekong, song_han = load_manifests()

    assert mekong.organization_id < song_han.organization_id
    with pytest.raises(ValueError, match="ascend"):
        validate_manifest_set([song_han, mekong])


def test_sysadmin_missing_from_a_manifest_is_rejected() -> None:
    mekong = _mekong()
    raw = _raw("song-han-retail.json")
    raw["members"] = [m for m in raw["members"] if m["email"] != SYSADMIN_EMAIL]
    without_sysadmin = DemoManifest.model_validate(raw)

    with pytest.raises(ValueError, match="sysadmin"):
        validate_manifest_set([mekong, without_sysadmin])


def test_version_2_is_rejected() -> None:
    raw = _raw()
    raw["version"] = 2

    with pytest.raises(ValidationError):
        DemoManifest.model_validate(raw)
