"""The leak markers of a fixture Organization match its own data and nothing else."""

import uuid

from support.isolation.markers import count_markers
from support.tenants import OrgRows


def _rows(label: str) -> OrgRows:
    return OrgRows(
        org_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        workspace_membership_id=uuid.uuid4(),
        audit_event_id=uuid.uuid4(),
        set_password_token_id=uuid.uuid4(),
        user_credential_id=uuid.uuid4(),
        admin_session_id=uuid.uuid4(),
        model_catalog_entry_id=uuid.uuid4(),
        collection_id=uuid.uuid4(),
        folder_id=uuid.uuid4(),
        organization_key_id=uuid.uuid4(),
        chunk_embedding_id=uuid.uuid4(),
        empty_folder_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        model_digest=f"sha256:{'0' * 64}",
        label=label,
        suffix=uuid.uuid4().hex[:8],
    )


def test_ordinary_text_is_not_a_marker() -> None:
    text = "Set your user agent or ask an org admin for workspace access to Org A and User B"

    assert count_markers(text, _rows("A")) == 0
    assert count_markers(text, _rows("B")) == 0


def test_names_ids_and_email_are_markers_in_any_case() -> None:
    rows = _rows("A")

    assert count_markers(rows.names.organization.upper(), rows) == 1
    assert count_markers(f"{rows.workspace_id} {rows.email}", rows) >= 2


def test_two_organizations_never_share_a_name() -> None:
    first, second = _rows("A"), _rows("A")

    assert first.names != second.names
    assert count_markers(first.names.organization, second) == 0
