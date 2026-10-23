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
    """The folder still has subfolders or documents (409 ``folder_not_empty``)."""


class InvalidFileName(Exception):
    """The file name is empty, too long or holds a control character (422 ``invalid_file_name``)."""


class UnsupportedFormat(Exception):
    """The extension is not one of the supported formats (415 ``unsupported_format``)."""


class FileTooLarge(Exception):
    """The file is over the size limit (413 ``file_too_large``)."""


class EmptyFile(Exception):
    """The file has no bytes (422 ``empty_file``)."""


class StorageQuotaExceeded(Exception):
    """The Organization's originals would exceed the quota (413 ``storage_quota_exceeded``)."""


class DocumentNotFound(Exception):
    """The document is unknown, or is not in this collection (404)."""


class DocumentNotReady(Exception):
    """The document has no text or chunks yet (409 ``document_not_ready``)."""
