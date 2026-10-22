"""Platform plane: create and destroy the data key of an Organization.

These functions take a raw ``org_id`` (the provisioning command line, the demo seed, a test),
so only the crypto package, provisioning and the seed may import this module (a test checks it).
The tenant plane uses ``OrgCipher``, which takes the verified context.
"""

import uuid

from ei_ai.crypto.envelope import new_data_key, wrap_data_key
from ei_ai.crypto.key_rows import insert_key_row, mark_key_destroyed, read_key_row
from ei_ai.crypto.master_key import MasterKey
from ei_ai.db.tenant import TenantExecutor


async def create_org_key(conn: TenantExecutor, org_id: uuid.UUID, master: MasterKey) -> uuid.UUID:
    """Insert a new wrapped data key for the Organization of the caller's tenant transaction."""
    wrapped = wrap_data_key(master, org_id, new_data_key())
    return await insert_key_row(conn, org_id, wrapped, master.kek_id)


async def ensure_org_key(conn: TenantExecutor, org_id: uuid.UUID, master: MasterKey) -> bool:
    """Create the key when the Organization has no key row; True when it did. A destroyed key
    is never recreated."""
    if await read_key_row(conn, org_id) is not None:
        return False
    await create_org_key(conn, org_id, master)
    return True


async def destroy_org_key(conn: TenantExecutor, org_id: uuid.UUID) -> bool:
    """Erase the wrapped key; everything encrypted for the Organization becomes unreadable.
    False when it was already destroyed or never existed."""
    return await mark_key_destroyed(conn, org_id)
