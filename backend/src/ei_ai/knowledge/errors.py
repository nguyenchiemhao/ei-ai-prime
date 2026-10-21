"""Errors of the knowledge service. The API maps each one to a status and a code; none carries
the input that caused it (D52)."""


class CollectionNotFound(Exception):
    """The collection is unknown, or belongs to another Workspace or Organization (404)."""


class FolderNotFound(Exception):
    """The folder is unknown, or is not in this collection (404)."""


class NameTaken(Exception):
    """The name is already used here, ignoring case (409 ``name_taken``)."""


class GroupsRequired(Exception):
    """A restricted collection needs at least one group (422 ``groups_required``)."""


class InvalidGroup(Exception):
    """A group name or the group list is not acceptable (422 ``invalid_group``)."""


class InvalidKnowledgeInput(Exception):
    """A name, subtitle, access level or change is not acceptable (422 ``invalid_request``)."""


class FolderTooDeep(Exception):
    """Folders nest up to three levels (422 ``folder_too_deep``)."""


class FolderNotEmpty(Exception):
    """The folder still has subfolders (409 ``folder_not_empty``)."""
