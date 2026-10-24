"""Citation marker filter (EA-37, AC2, R21).

A marker is ``[``, optional spaces, a number, ``, number`` repeated, optional spaces, ``]``, at most
12 characters. Each valid number (1..k, no leading zero) is written as ``[n]``; invalid numbers are
dropped. Anything that is not a marker is ordinary text, passed on at the first character that
cannot continue a marker. Pure and streaming: a marker split across deltas is held back.
"""

import re

_MAX_MARKER_LENGTH = 12
_FULL = re.compile(r"\[ *(\d+(?:, *\d+)*) *\]")
_PREFIX = re.compile(r"\[ *(?:\d+(?:, *\d+)*,? *)?")


def _valid(number: str, passage_count: int) -> bool:
    return not number.startswith("0") and 1 <= int(number) <= passage_count


class CitationFilter:
    def __init__(self, passage_count: int) -> None:
        self._count = passage_count
        self._held = ""
        self.removed = 0

    def feed(self, text: str) -> str:
        out: list[str] = []
        for ch in text:
            self._step(ch, out)
        return "".join(out)

    def flush(self) -> str:
        held, self._held = self._held, ""
        return held

    def _step(self, ch: str, out: list[str]) -> None:
        if not self._held:
            if ch == "[":
                self._held = ch
            else:
                out.append(ch)
            return
        candidate = self._held + ch
        if len(candidate) <= _MAX_MARKER_LENGTH:
            full = _FULL.fullmatch(candidate)
            if full:
                self._held = ""
                out.append(self._rewrite(full.group(1)))
                return
            if _PREFIX.fullmatch(candidate):
                self._held = candidate
                return
        out.append(self._held)
        self._held = ""
        self._step(ch, out)

    def _rewrite(self, numbers: str) -> str:
        kept: list[str] = []
        for number in (part.strip() for part in numbers.split(",")):
            if _valid(number, self._count):
                kept.append(f"[{int(number)}]")
            else:
                self.removed += 1
        return "".join(kept)


def cited_numbers(text: str, passage_count: int) -> tuple[int, ...]:
    """Sorted unique valid citation numbers of an already filtered text."""
    found: set[int] = set()
    for match in _FULL.finditer(text):
        for number in (part.strip() for part in match.group(1).split(",")):
            if _valid(number, passage_count):
                found.add(int(number))
    return tuple(sorted(found))
