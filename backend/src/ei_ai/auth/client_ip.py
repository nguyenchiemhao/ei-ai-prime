"""The client address used as a rate-limit key."""

from fastapi import Request


def client_ip(request: Request, trust_proxy_headers: bool) -> str:
    """Rightmost ``X-Forwarded-For`` entry when the proxy is trusted, else the socket peer.

    The rightmost entry is the one our own proxy appended; entries to its left are client-made.
    """
    if trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        last = forwarded.rsplit(",", 1)[-1].strip()
        if last:
            return last
    return request.client.host if request.client else "unknown"
