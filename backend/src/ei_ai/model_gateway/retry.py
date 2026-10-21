"""The retry rule (D18, plan §3 #12): one retry, only for 5xx, timeout or connection error, and in
a stream only before the first text delta was yielded (no duplicated text). 4xx and 429 are never
retried ("busy → report at once", D57). The SDK's own retries are off."""

from ei_ai.model_gateway.transport import UpstreamError

MAX_ATTEMPTS = 2


def should_retry(error: UpstreamError, attempts: int, *, yielded: bool = False) -> bool:
    """True when the failed attempt number ``attempts`` may be repeated."""
    return error.retryable and attempts < MAX_ATTEMPTS and not yielded
