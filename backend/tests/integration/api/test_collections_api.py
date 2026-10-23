"""The collections and folders API on the real database: shapes, permissions, codes, isolation."""

import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from support.rbac.orgs import RoleOrg, role_client
from support.sign_in import in_tenant

from ..knowledge.conftest import MakeOrg

pytestmark = pytest.mark.integration

ITEM_KEYS = {
    "id",
    "name",
    "subtitle",
    "access_level",
    "groups",
    "local_only",
    "documents",
    "used_by",
    "created_at",
    "updated_at",
}


def _base(org: RoleOrg) -> str:
    return f"/workspaces/{org.workspace('x')}/collections"


async def _create(
    client: httpx.AsyncClient, org: RoleOrg, actor: str = "ke", **overrides: object
) -> dict[str, object]:
    body: dict[str, object] = {"name": "Handbook", "access_level": "authenticated"}
    body.update(overrides)
    response = await client.post(_base(org), headers=org.headers(actor), json=body)
    assert response.status_code == 201, response.text
    created: dict[str, object] = response.json()
    return created


async def _audit(engine: AsyncEngine, org: RoleOrg, target: str) -> list[tuple[str, str | None]]:
    rows = await in_tenant(
        engine,
        org.org_id,
        "SELECT action, new_value FROM audit_events WHERE org_id = :org AND target_id = :t"
        " ORDER BY created_at, id",
        {"t": uuid.UUID(target)},
    )
    return [(row[0], row[1]) for row in rows]


async def test_post_collection_201_shape(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()

    async with role_client(app_engine, org) as client:
        created = await _create(client, org, subtitle=" Policies ")

    assert set(created) == ITEM_KEYS
    assert created["name"] == "Handbook"
    assert created["subtitle"] == "Policies"
    assert created["access_level"] == "authenticated"
    assert created["groups"] == []
    assert created["local_only"] is False
    assert created["documents"] == {"total": 0, "ready": 0, "processing": 0, "needs_attention": 0}
    assert created["used_by"] == []


async def test_list_and_detail_shapes(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()

    async with role_client(app_engine, org) as client:
        second = await _create(client, org, name="beta")
        first = await _create(client, org, name="Alpha")
        folder = await client.post(
            f"{_base(org)}/{first['id']}/folders", headers=org.headers("ke"), json={"name": "P"}
        )
        listed = await client.get(_base(org), headers=org.headers("ke"))
        detail = await client.get(f"{_base(org)}/{first['id']}", headers=org.headers("ke"))

    assert [c["id"] for c in listed.json()["collections"]] == [first["id"], second["id"]]
    assert set(listed.json()["collections"][0]) == ITEM_KEYS
    assert set(detail.json()) == ITEM_KEYS | {"folders"}
    assert detail.json()["folders"] == [
        {
            "id": folder.json()["id"],
            "name": "P",
            "parent_id": None,
            "depth": 1,
            "document_count": 0,
        }
    ]


async def test_groups_required_422(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()

    async with role_client(app_engine, org) as client:
        response = await client.post(
            _base(org),
            headers=org.headers("ke"),
            json={"name": "R", "access_level": "restricted", "groups": []},
        )
        invalid = await client.post(
            _base(org),
            headers=org.headers("ke"),
            json={"name": "R", "access_level": "restricted", "groups": ["a,b"]},
        )
        stray = await client.post(
            _base(org),
            headers=org.headers("ke"),
            json={"name": "R", "access_level": "authenticated", "groups": ["a"]},
        )

    assert (response.status_code, response.json()) == (422, {"detail": "groups_required"})
    assert (invalid.status_code, invalid.json()) == (422, {"detail": "invalid_group"})
    assert (stray.status_code, stray.json()) == (422, {"detail": "invalid_request"})


async def test_ke_put_access_is_403_and_unchanged(
    app_engine: AsyncEngine, make_org: MakeOrg
) -> None:
    org = await make_org()

    async with role_client(app_engine, org) as client:
        created = await _create(client, org)
        denied = await client.put(
            f"{_base(org)}/{created['id']}/access",
            headers=org.headers("ke"),
            json={"access_level": "restricted", "groups": ["managers"]},
        )
        after = await client.get(f"{_base(org)}/{created['id']}", headers=org.headers("ke"))
        public = await client.post(
            _base(org),
            headers=org.headers("ke"),
            json={"name": "Pub", "access_level": "public"},
        )

    assert (denied.status_code, denied.json()) == (403, {"detail": "forbidden"})
    assert after.json()["access_level"] == "authenticated"
    assert public.status_code == 403
    assert await _audit(app_engine, org, str(created["id"])) == [
        ("collection.created", "authenticated")
    ]


async def test_admin_put_access_200(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()

    async with role_client(app_engine, org) as client:
        created = await _create(client, org)
        response = await client.put(
            f"{_base(org)}/{created['id']}/access",
            headers=org.headers("ws_admin"),
            json={"access_level": "restricted", "groups": [" Managers "]},
        )

    assert response.status_code == 200
    assert response.json()["access_level"] == "restricted"
    assert response.json()["groups"] == ["managers"]
    assert await _audit(app_engine, org, str(created["id"])) == [
        ("collection.created", "authenticated"),
        ("collection.access_changed", "restricted"),
    ]


async def test_ke_patch_local_only_off_403(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()

    async with role_client(app_engine, org) as client:
        created = await _create(client, org, local_only=True)
        denied = await client.patch(
            f"{_base(org)}/{created['id']}", headers=org.headers("ke"), json={"local_only": False}
        )
        renamed = await client.patch(
            f"{_base(org)}/{created['id']}", headers=org.headers("ke"), json={"name": "New"}
        )
        allowed = await client.patch(
            f"{_base(org)}/{created['id']}",
            headers=org.headers("ws_admin"),
            json={"local_only": False},
        )
        empty = await client.patch(
            f"{_base(org)}/{created['id']}", headers=org.headers("ke"), json={}
        )

    assert (denied.status_code, denied.json()) == (403, {"detail": "forbidden"})
    assert (renamed.status_code, renamed.json()["name"], renamed.json()["local_only"]) == (
        200,
        "New",
        True,
    )
    assert (allowed.status_code, allowed.json()["local_only"]) == (200, False)
    assert (empty.status_code, empty.json()) == (422, {"detail": "invalid_request"})


async def test_extra_fields_are_rejected(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()
    other = uuid.uuid4()

    async with role_client(app_engine, org) as client:
        created = await _create(client, org)
        posts = [
            await client.post(
                _base(org),
                headers=org.headers("ke"),
                json={"name": "X", "access_level": "authenticated", field: str(other)},
            )
            for field in ("org_id", "workspace_id", "id")
        ]
        patch = await client.patch(
            f"{_base(org)}/{created['id']}",
            headers=org.headers("ke"),
            json={"access_level": "public"},
        )

    for response in [*posts, patch]:
        assert (response.status_code, response.json()) == (422, {"detail": "invalid_request"})


async def test_cross_org_ids_are_404(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()
    foreign = await make_org()
    unknown = uuid.uuid4()

    async with role_client(app_engine, org, foreign) as client:
        mine = await _create(client, org)
        theirs = await _create(client, foreign)
        their_folder = (
            await client.post(
                f"{_base(foreign)}/{theirs['id']}/folders",
                headers=foreign.headers("ke"),
                json={"name": "F"},
            )
        ).json()["id"]
        headers = org.headers("ke")

        async def answers(collection: object, folder: object) -> list[tuple[int, str]]:
            calls = [
                client.get(f"{_base(org)}/{collection}", headers=headers),
                client.patch(f"{_base(org)}/{collection}", headers=headers, json={"name": "Z"}),
                client.put(
                    f"{_base(org)}/{collection}/access",
                    headers=org.headers("ws_admin"),
                    json={"access_level": "authenticated", "groups": []},
                ),
                client.delete(f"{_base(org)}/{collection}", headers=headers),
                client.post(
                    f"{_base(org)}/{collection}/folders", headers=headers, json={"name": "Q"}
                ),
                client.patch(
                    f"{_base(org)}/{mine['id']}/folders/{folder}",
                    headers=headers,
                    json={"name": "Q"},
                ),
                client.delete(f"{_base(org)}/{mine['id']}/folders/{folder}", headers=headers),
                client.post(
                    f"{_base(org)}/{mine['id']}/folders",
                    headers=headers,
                    json={"name": "Q", "parent_id": str(folder)},
                ),
            ]
            return [(r.status_code, r.text) for r in [await call for call in calls]]

        foreign_answers = await answers(theirs["id"], their_folder)
        unknown_answers = await answers(unknown, unknown)

    assert foreign_answers == unknown_answers
    assert all(answer == (404, '{"detail":"not_found"}') for answer in foreign_answers)


async def test_delete_then_get_is_404(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()

    async with role_client(app_engine, org) as client:
        created = await _create(client, org)
        await client.post(
            f"{_base(org)}/{created['id']}/folders", headers=org.headers("ke"), json={"name": "F"}
        )
        deleted = await client.delete(f"{_base(org)}/{created['id']}", headers=org.headers("ke"))
        after = await client.get(f"{_base(org)}/{created['id']}", headers=org.headers("ke"))

    assert (deleted.status_code, deleted.content) == (204, b"")
    assert (after.status_code, after.json()) == (404, {"detail": "not_found"})
    left = await in_tenant(
        app_engine,
        org.org_id,
        "SELECT count(*) FROM folders WHERE org_id = :org AND collection_id = :c",
        {"c": uuid.UUID(str(created["id"]))},
    )
    assert left == [(0,)]


async def test_name_taken_and_viewer_forbidden(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()

    async with role_client(app_engine, org) as client:
        await _create(client, org, name="Handbook")
        taken = await client.post(
            _base(org),
            headers=org.headers("ke"),
            json={"name": "HANDBOOK", "access_level": "authenticated"},
        )
        viewer = await client.get(_base(org), headers=org.headers("viewer"))
        anonymous = await client.get(_base(org))

    assert (taken.status_code, taken.json()) == (409, {"detail": "name_taken"})
    assert viewer.status_code == 403
    assert anonymous.status_code == 401


async def test_folder_routes_codes(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()

    async with role_client(app_engine, org) as client:
        collection = await _create(client, org)
        url = f"{_base(org)}/{collection['id']}/folders"
        headers = org.headers("ke")
        first = await client.post(url, headers=headers, json={"name": "Policies"})
        duplicate = await client.post(url, headers=headers, json={"name": "policies"})
        second = await client.post(
            url, headers=headers, json={"name": "2026", "parent_id": first.json()["id"]}
        )
        third = await client.post(
            url, headers=headers, json={"name": "Q1", "parent_id": second.json()["id"]}
        )
        too_deep = await client.post(
            url, headers=headers, json={"name": "Q1a", "parent_id": third.json()["id"]}
        )
        renamed = await client.patch(
            f"{url}/{third.json()['id']}", headers=headers, json={"name": "Q2"}
        )
        not_empty = await client.delete(f"{url}/{first.json()['id']}", headers=headers)
        leaf = await client.delete(f"{url}/{third.json()['id']}", headers=headers)

    assert first.status_code == 201
    assert first.json() == {
        "id": first.json()["id"],
        "name": "Policies",
        "parent_id": None,
        "depth": 1,
        "document_count": 0,
    }
    assert (duplicate.status_code, duplicate.json()) == (409, {"detail": "name_taken"})
    assert (second.status_code, third.json()["depth"]) == (201, 3)
    assert (too_deep.status_code, too_deep.json()) == (422, {"detail": "folder_too_deep"})
    assert (renamed.status_code, renamed.json()["name"]) == (200, "Q2")
    assert (not_empty.status_code, not_empty.json()) == (409, {"detail": "folder_not_empty"})
    assert (leaf.status_code, leaf.content) == (204, b"")


async def test_errors_never_echo_input(app_engine: AsyncEngine, make_org: MakeOrg) -> None:
    org = await make_org()
    secret = "Secret-Name-9"

    async with role_client(app_engine, org) as client:
        await _create(client, org, name=secret)
        responses = [
            await client.post(
                _base(org),
                headers=org.headers("ke"),
                json={"name": secret, "access_level": "authenticated"},
            ),
            await client.post(
                _base(org),
                headers=org.headers("ke"),
                json={"name": secret, "access_level": "restricted", "groups": ["bad,secret-grp"]},
            ),
            await client.post(
                _base(org),
                headers=org.headers("ke"),
                json={"name": secret, "access_level": "authenticated", "x": secret},
            ),
        ]

    for response in responses:
        assert response.status_code in (409, 422)
        assert "secret" not in response.text.lower()


@pytest.mark.parametrize("bad", ["\u0000", "\x07"])
async def test_control_characters_are_422(
    app_engine: AsyncEngine, make_org: MakeOrg, bad: str
) -> None:
    org = await make_org()

    async with role_client(app_engine, org) as client:
        collection = await _create(client, org)
        headers = org.headers("ke")
        url = f"{_base(org)}/{collection['id']}"
        bad_name = await client.post(
            _base(org), headers=headers, json={"name": f"A{bad}B", "access_level": "authenticated"}
        )
        bad_subtitle = await client.post(
            _base(org),
            headers=headers,
            json={"name": "Other", "subtitle": f"S{bad}", "access_level": "authenticated"},
        )
        bad_patch = await client.patch(url, headers=headers, json={"subtitle": f"S{bad}"})
        bad_folder = await client.post(f"{url}/folders", headers=headers, json={"name": f"F{bad}"})

    expected = (422, {"detail": "invalid_request"})
    for response in (bad_name, bad_subtitle, bad_patch, bad_folder):
        assert (response.status_code, response.json()) == expected
