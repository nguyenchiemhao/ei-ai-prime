from starlette.requests import Request

from ei_ai.auth.client_ip import client_ip


def _request(headers: dict[str, str], client: tuple[str, int] | None) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": client,
        }
    )


def test_client_ip_rightmost_forwarded_when_trusted() -> None:
    request = _request({"X-Forwarded-For": "1.1.1.1, 2.2.2.2 , 3.3.3.3"}, ("9.9.9.9", 1))

    assert client_ip(request, trust_proxy_headers=True) == "3.3.3.3"


def test_client_ip_header_ignored_when_not_trusted() -> None:
    request = _request({"X-Forwarded-For": "1.1.1.1"}, ("9.9.9.9", 1))

    assert client_ip(request, trust_proxy_headers=False) == "9.9.9.9"


def test_client_ip_falls_back_to_peer_then_unknown() -> None:
    assert client_ip(_request({}, ("9.9.9.9", 1)), trust_proxy_headers=True) == "9.9.9.9"
    assert client_ip(_request({}, None), trust_proxy_headers=True) == "unknown"
