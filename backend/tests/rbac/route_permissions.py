"""The reviewed route table (D48): the permission every API route declares.

Adding a route means adding a line here, in the same change as the route; changing a permission
means changing its line, so a reviewer sees the change. ``test_route_declarations.py`` compares
this table with the declarations of the real app. Values are permission codes, ``signed_in`` or
``public``.
"""

from ei_ai.rbac.declarations import PUBLIC, SIGNED_IN
from ei_ai.rbac.permissions import Permission

ROUTE_PERMISSIONS: dict[tuple[str, str], str] = {
    ("GET", "/healthz"): PUBLIC,
    ("GET", "/readyz"): PUBLIC,
    ("GET", "/auth/csrf"): PUBLIC,
    ("POST", "/auth/sign-in"): PUBLIC,
    ("POST", "/auth/sign-out"): PUBLIC,
    ("POST", "/auth/forgot-password"): PUBLIC,
    ("POST", "/auth/set-password"): PUBLIC,
    ("GET", "/auth/session"): SIGNED_IN,
    ("GET", "/organization"): SIGNED_IN,
    ("GET", "/workspaces/{workspace_id}"): Permission.WORKSPACE_ACCESS.value,
    ("GET", "/workspaces/{workspace_id}/members"): Permission.MEMBERS_VIEW.value,
    ("POST", "/workspaces/{workspace_id}/members"): Permission.MEMBERS_MANAGE.value,
    ("PUT", "/workspaces/{workspace_id}/members/{user_id}"): Permission.MEMBERS_MANAGE.value,
    ("DELETE", "/workspaces/{workspace_id}/members/{user_id}"): Permission.MEMBERS_MANAGE.value,
    ("GET", "/workspaces/{workspace_id}/collections"): Permission.KNOWLEDGE_MANAGE.value,
    ("POST", "/workspaces/{workspace_id}/collections"): Permission.KNOWLEDGE_MANAGE.value,
    (
        "GET",
        "/workspaces/{workspace_id}/collections/{collection_id}",
    ): Permission.KNOWLEDGE_MANAGE.value,
    (
        "PATCH",
        "/workspaces/{workspace_id}/collections/{collection_id}",
    ): Permission.KNOWLEDGE_MANAGE.value,
    (
        "PUT",
        "/workspaces/{workspace_id}/collections/{collection_id}/access",
    ): Permission.COLLECTIONS_ACCESS_MANAGE.value,
    (
        "DELETE",
        "/workspaces/{workspace_id}/collections/{collection_id}",
    ): Permission.KNOWLEDGE_MANAGE.value,
    (
        "POST",
        "/workspaces/{workspace_id}/collections/{collection_id}/folders",
    ): Permission.KNOWLEDGE_MANAGE.value,
    (
        "PATCH",
        "/workspaces/{workspace_id}/collections/{collection_id}/folders/{folder_id}",
    ): Permission.KNOWLEDGE_MANAGE.value,
    (
        "DELETE",
        "/workspaces/{workspace_id}/collections/{collection_id}/folders/{folder_id}",
    ): Permission.KNOWLEDGE_MANAGE.value,
    (
        "POST",
        "/workspaces/{workspace_id}/collections/{collection_id}/folders/{folder_id}/documents",
    ): Permission.KNOWLEDGE_MANAGE.value,
    (
        "GET",
        "/workspaces/{workspace_id}/collections/{collection_id}/documents",
    ): Permission.KNOWLEDGE_MANAGE.value,
    (
        "GET",
        "/workspaces/{workspace_id}/collections/{collection_id}/documents/{document_id}/text",
    ): Permission.KNOWLEDGE_MANAGE.value,
    (
        "GET",
        "/workspaces/{workspace_id}/collections/{collection_id}/documents/{document_id}/chunks",
    ): Permission.KNOWLEDGE_MANAGE.value,
    (
        "DELETE",
        "/workspaces/{workspace_id}/collections/{collection_id}/documents/{document_id}",
    ): Permission.KNOWLEDGE_MANAGE.value,
    (
        "POST",
        "/workspaces/{workspace_id}/collections/{collection_id}/ask",
    ): Permission.KNOWLEDGE_MANAGE.value,
    ("PUT", "/organization/members/{user_id}/org-role"): Permission.ORG_ROLES_MANAGE.value,
}
