"""Encrypt and decrypt bytes for one Organization with its own data key.

The Organization comes from the verified context only (D32): a ``TenantContext`` in a route or
a ``JobContext`` in a job; anything else raises ``TypeError``. The session must be the tenant
session of that Organization, so a session of another Organization finds no key row. The key
is read and unwrapped on every call (no cache): destroying it takes effect at once.
Nothing here logs.
"""

from functools import partial

from anyio import to_thread

from ei_ai.crypto.envelope import open_sealed, seal, unwrap_data_key
from ei_ai.crypto.errors import KeyDestroyed, KeyNotFound, MasterKeyMismatch
from ei_ai.crypto.key_rows import read_key_row
from ei_ai.crypto.master_key import MasterKey
from ei_ai.db.tenant import TenantExecutor
from ei_ai.jobs.envelope import JobContext
from ei_ai.tenancy.context import TenantContext


class OrgCipher:
    def __init__(self, master: MasterKey) -> None:
        self._master = master

    async def _data_key(self, session: TenantExecutor, tenant: TenantContext | JobContext) -> bytes:
        if not isinstance(tenant, TenantContext | JobContext):
            raise TypeError(
                "OrgCipher needs the verified TenantContext or JobContext,"
                f" got {type(tenant).__name__}"
            )
        row = await read_key_row(session, tenant.org_id)
        if row is None:
            raise KeyNotFound()
        if row.wrapped_key is None:
            raise KeyDestroyed()
        if row.kek_id != self._master.kek_id:
            raise MasterKeyMismatch()
        return unwrap_data_key(self._master, tenant.org_id, row.wrapped_key)

    async def encrypt(
        self, session: TenantExecutor, tenant: TenantContext | JobContext, data: bytes
    ) -> bytes:
        dek = await self._data_key(session, tenant)
        return await to_thread.run_sync(partial(seal, dek, tenant.org_id, data))

    async def decrypt(
        self, session: TenantExecutor, tenant: TenantContext | JobContext, blob: bytes
    ) -> bytes:
        dek = await self._data_key(session, tenant)
        return await to_thread.run_sync(partial(open_sealed, dek, tenant.org_id, blob))
