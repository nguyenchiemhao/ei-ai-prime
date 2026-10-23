"""Store original files encrypted, one directory per Organization.

Layout: ``<root>/<org_id>/<file_id>.bin`` (directory 0700, file 0600). Paths are built only from
``uuid.UUID`` objects, so a client string can never traverse. The Organization comes from the
verified context only (D32). A file id of another Organization is not under this directory, so it
is "not found" exactly like an unknown id. Nothing here logs.
"""

import os
import uuid
from pathlib import Path

from anyio import to_thread

from ei_ai.crypto.cipher import OrgCipher
from ei_ai.db.tenant import TenantExecutor
from ei_ai.jobs.envelope import JobContext
from ei_ai.tenancy.context import TenantContext

DIRECTORY_MODE = 0o700
FILE_MODE = 0o600


class FileNotFound(Exception):
    def __init__(self) -> None:
        super().__init__("file not found")


def _check_tenant(tenant: object) -> TenantContext | JobContext:
    if not isinstance(tenant, TenantContext | JobContext):
        raise TypeError("OrgFileStore needs the verified TenantContext or JobContext")
    return tenant


def _check_file_id(file_id: object) -> uuid.UUID:
    if not isinstance(file_id, uuid.UUID):
        raise TypeError("file_id must be a uuid.UUID")
    return file_id


def _write_atomically(directory: Path, final: Path, blob: bytes) -> None:
    directory.mkdir(mode=DIRECTORY_MODE, parents=True, exist_ok=True)
    directory.chmod(DIRECTORY_MODE)  # the process umask may have narrowed the mkdir mode only
    temp = directory / f".{uuid.uuid4().hex}.tmp"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(blob)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, final)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        raise FileNotFound from None


def _remove(path: Path) -> bool:
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


class OrgFileStore:
    def __init__(self, root: Path, cipher: OrgCipher) -> None:
        self._root = root
        self._cipher = cipher

    def _directory(self, tenant: TenantContext | JobContext) -> Path:
        return self._root / str(tenant.org_id)

    async def put(
        self, session: TenantExecutor, tenant: TenantContext | JobContext, data: bytes | bytearray
    ) -> uuid.UUID:
        _check_tenant(tenant)
        file_id = uuid.uuid4()
        blob = await self._cipher.encrypt(session, tenant, data)
        directory = self._directory(tenant)
        final = directory / f"{file_id}.bin"
        await to_thread.run_sync(_write_atomically, directory, final, blob)
        return file_id

    async def get(
        self, session: TenantExecutor, tenant: TenantContext | JobContext, file_id: uuid.UUID
    ) -> bytes:
        _check_tenant(tenant)
        _check_file_id(file_id)
        blob = await to_thread.run_sync(_read, self._directory(tenant) / f"{file_id}.bin")
        return await self._cipher.decrypt(session, tenant, blob)

    async def delete(self, tenant: TenantContext | JobContext, file_id: uuid.UUID) -> bool:
        _check_tenant(tenant)
        _check_file_id(file_id)
        return await to_thread.run_sync(_remove, self._directory(tenant) / f"{file_id}.bin")
