"""``create_valkey_client``: the one sanctioned way for app code to get a client for TenantCache."""

from ei_ai.cache import create_valkey_client


def test_the_client_returns_bytes_and_has_timeouts() -> None:
    client = create_valkey_client("redis://valkey:6379/0")
    options = client.connection_pool.connection_kwargs

    assert options["host"] == "valkey"
    assert options.get("decode_responses", False) is False
    assert options["socket_connect_timeout"] == 2.0
    assert options["socket_timeout"] == 2.0
