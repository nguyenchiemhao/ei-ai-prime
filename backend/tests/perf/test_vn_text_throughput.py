"""NFR (EA-28): ``ei_ai.vn_text`` processes at least 1 MB of text per second.

Run with ``npm run backend -- bench-vn-text`` (excluded from the unit and integration runs).

The corpus is deterministic text of at least 2 000 000 UTF-8 bytes (``random.Random(2028)``):
70 % Vietnamese lines (the mixed-case inputs and the NFC/NFD sentences, half of them in NFD),
20 % ASCII English/code lines and 10 % lines with emoji and old-style tone marks. ``normalize`` and
``strip_accents`` are each run over the whole corpus (after a warm-up run); the median of the
timed runs gives bytes of input per second, printed for the package README.
"""

import random
import statistics
import time
import unicodedata
from collections.abc import Callable

import pytest
from vn_text.cases import MIXED_CASES, NFC_NFD_SENTENCES

from ei_ai.vn_text import normalize, strip_accents

pytestmark = pytest.mark.benchmark

MIN_BYTES_PER_SECOND = 1_000_000
MIN_CORPUS_BYTES = 2_000_000
WARMUP = 1
RUNS = 5

_ENGLISH_LINES = [
    "def load(path): return open(path, encoding='utf-8').read()",
    "The quarterly report is attached; please review before Friday.",
    "SELECT id, name FROM users WHERE org_id = :org AND active = true;",
    "    for item in items:\n        total += item.price * item.qty",
    "https://example.com/docs/getting-started?lang=en&page=2",
]
_EMOJI_LINES = [
    "Chúc mừng 🎉 hoà bình 👍🏽 thuỷ điện 👨‍👩‍👧",
    "Xong rồi ✅ khoẻ mạnh 🇻🇳 quả đẹp ❤️",
    "Họp lúc 9h 📅 thuỷ lợi, hoà giải 🙂",
]


def _build_corpus() -> str:
    rng = random.Random(2028)
    vietnamese = [text for text, _ in MIXED_CASES] + NFC_NFD_SENTENCES
    lines: list[str] = []
    size = 0
    while size < MIN_CORPUS_BYTES:
        roll = rng.random()
        if roll < 0.7:
            line = rng.choice(vietnamese)
            if rng.random() < 0.5:
                line = unicodedata.normalize("NFD", line)
        elif roll < 0.9:
            line = rng.choice(_ENGLISH_LINES)
        else:
            line = rng.choice(_EMOJI_LINES)
        lines.append(line)
        size += len(line.encode("utf-8")) + 1
    return "\n".join(lines)


def _measure(name: str, function: Callable[[str], str]) -> None:
    corpus = _build_corpus()
    size = len(corpus.encode("utf-8"))
    assert size >= MIN_CORPUS_BYTES
    for _ in range(WARMUP):
        function(corpus)
    timings: list[float] = []
    for _ in range(RUNS):
        started = time.perf_counter()
        function(corpus)
        timings.append(time.perf_counter() - started)
    rate = size / statistics.median(timings)
    print(f"vn_text {name}: {rate / 1_000_000:.2f} MB/s over {size} bytes")
    assert rate >= MIN_BYTES_PER_SECOND


def test_normalize_throughput() -> None:
    _measure("normalize", normalize)


def test_strip_accents_throughput() -> None:
    _measure("strip_accents", strip_accents)
