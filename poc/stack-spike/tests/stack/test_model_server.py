"""AC4-B: a ~4B model on CPU answers through the OpenAI-compatible API (opt-in: CHECK_MODEL=1).

Only metrics are printed, never the prompt or the answer text (D52).
"""

import hashlib
import os
import time
from pathlib import Path

import openai
import pytest

pytestmark = [
    pytest.mark.stack,
    pytest.mark.model,
    pytest.mark.skipif(
        os.environ.get("CHECK_MODEL") != "1", reason="opt-in: model profile not requested"
    ),
]

MODEL_CACHE = Path("/models")  # compose mounts the model-cache volume read-only
PROMPT = "Xin chào, hãy giới thiệu ngắn gọn về bạn."


@pytest.fixture(scope="module")
def client() -> openai.OpenAI:
    return openai.OpenAI(base_url=os.environ["MODEL_BASE_URL"], api_key="not-used", timeout=300)


def test_downloaded_model_file_matches_recorded_sha256():
    # Pinning by content (F8, D18): the file the server loaded is the one recorded in ADR-001.
    files = list(MODEL_CACHE.rglob("*.gguf"))
    assert len(files) == 1, f"expected one GGUF in the cache, found {len(files)} (try down -v)"
    digest = hashlib.sha256()
    with files[0].open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)

    assert digest.hexdigest() == os.environ["MODEL_SHA256"]


def test_model_server_lists_pinned_model(client):
    model_ids = [model.id for model in client.models.list()]

    assert os.environ["MODEL_NAME"] in model_ids


def test_streams_chat_completion_via_openai_sdk_with_usage(client):
    started = time.perf_counter()
    first_token_at = None
    content_deltas = 0
    usage = None

    stream = client.chat.completions.create(
        model=os.environ["MODEL_NAME"],
        messages=[{"role": "user", "content": PROMPT}],
        max_tokens=64,
        stream=True,
        stream_options={"include_usage": True},
    )
    for chunk in stream:
        if chunk.usage is not None:
            usage = chunk.usage
        if chunk.choices and chunk.choices[0].delta.content:
            content_deltas += 1
            if first_token_at is None:
                first_token_at = time.perf_counter()
    finished = time.perf_counter()

    assert content_deltas >= 1
    assert usage is not None
    assert usage.prompt_tokens > 0
    assert usage.completion_tokens > 0

    ttft = first_token_at - started
    generation_seconds = max(finished - first_token_at, 1e-9)
    print(
        f"\nMETRICS ttft_s={ttft:.2f} "
        f"tokens_per_s={usage.completion_tokens / generation_seconds:.2f} "
        f"prompt_tokens={usage.prompt_tokens} completion_tokens={usage.completion_tokens}"
    )
