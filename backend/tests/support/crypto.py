"""Test-only master key for the crypto tests and the fixtures that create Organization keys.

Never imported by ``src``. The value is public on purpose: it protects nothing.
"""

from ei_ai.crypto.master_key import MasterKey

TEST_MASTER_KEY = MasterKey(bytes(range(32)))
