# `ei_ai.vn_text` - Vietnamese text normalisation

## Purpose

One canonical form for Vietnamese text (D60, F9), so that a question typed with one Unicode
encoding or tone placement matches a document written with another. Consumers: KB-02
(ingestion), PIPE-01 (the Gate) and KB-08 (the Glossary). Standard library only; the rules in
this file and the tables in `backend/tests/vn_text/cases.py` are the spec for any later port.

## API

```python
from ei_ai.vn_text import normalize, strip_accents

def normalize(text: str) -> str
def strip_accents(text: str) -> str
```

Both are pure functions: no state, no cache of input text (R10), no logging (D52). A
non-`str` argument raises `TypeError`; `""` returns `""`. `normalize` is idempotent and gives
the same result for NFC and NFD input.

## `normalize` pipeline

1. **Cleanup** (one `str.translate` plus one regex):
   - removed: U+200B, U+2060, U+FEFF, U+00AD, C0 controls except `\t \n \v \f \r`
     (U+0000-0008, U+000E-001F), U+007F, C1 controls U+0080-009F;
   - mapped one-for-one to a space: U+00A0, U+1680, U+2000-200A, U+202F, U+205F, U+3000;
     U+2028 and U+2029 become `\n`;
   - kept: ZWJ U+200D, ZWNJ U+200C, variation selectors, emoji modifiers, tabs, newlines, CR,
     runs of spaces, U+FFFD. Spaces are never collapsed or trimmed;
   - reordered: a vowel modifier (U+0302, U+0306, U+031B) typed after a tone mark moves in
     front of it, so `e` + U+0301 + U+0302 composes to "ế" (R15).
2. **NFC**, never NFKC: NFKC would change English and code ("ﬁ", "²", fullwidth forms).
3. **Tone placement**, described next.

## Tone rule

Only a letter run that is **one well-formed Vietnamese syllable with exactly one tone mark** is
rewritten. The syllable is parsed on its lower-cased, tone-free letters:

- initial (longest match): `ngh ng gh gi qu ch kh nh ph th tr b c d đ g h k l m n p q r s t v x`,
  or none;
- vowel cluster: must be one of the valid Vietnamese nuclei in `VOWEL_NUCLEI`
  (`letters.py`, 54 entries: `a ă â e ê i o ô ơ u ư y`, `ai ao au ay âu ây eo êu ia iê iu oa oă
  oe oi oo ôi ơi ua uâ uê ui uô uơ uy ưa ưi ươ ưu yê`, `iêu yêu oai oay oeo uây uôi uya uyê uyu
  ươi ươu`);
- final: `""`, `c ch m n ng nh p t`; nothing may follow.

`qu` is always the initial ("qủa" -> `qu` + `a`). `gi` is the initial only when a vowel follows
("gía" -> `gi` + `a`; "gì" and "gìn" -> `g` + `i`).

The tone goes on:

1. the **last modified vowel** (ă â ê ô ơ ư) of the cluster: "ngừơi" -> "người", "quyển",
   "lưả" -> "lửa", "khúây" -> "khuấy";
2. otherwise, with a **final consonant**, the **last vowel**: "hòang" -> "hoàng", "tóan" ->
   "toán", "xóong" -> "xoóng";
3. otherwise (open syllable): the only vowel; the **first** of two ("hoà" -> "hòa", "thuỷ" ->
   "thủy", "khoẻ" -> "khỏe", "cuả" -> "của"); the **middle** of three ("ngòai" -> "ngoài",
   "khủyu" -> "khuỷu").

Every letter keeps its case by position: "HOÀ" -> "HÒA", "Thuỷ" -> "Thủy", "HoÀ" -> "HòA".

**R1:** the canonical forms are "hòa", "thủy", "khỏe", "quả". This is the traditional placement,
often called the "old" style (the "new" style writes "hoà"); it is the most common on the web and
what users see in cited text. D60 only requires one consistent form, so search works either way,
but changing it later means re-ingesting every document.

Left unchanged:

- words with two or more tone marks ("hòà");
- words that are not one valid syllable: foreign words ("café", "résumé", "José", "Pokémon",
  "naïve"), unknown clusters ("où"), stray letters ("hoàx");
- a single-vowel word such as "né": its tone is already on the only vowel;
- letter runs that touch a leftover combining mark of any block (`unicodedata.combining`); other scripts, emoji and code layout.

Vietnamese words inside code or URLs are normalised like any other text (R9).

### Known collisions

A foreign word whose accented cluster is also a valid Vietnamese nucleus gets the canonical
tone position, because the rule cannot tell it from Vietnamese: "più" -> "pìu", "aí" -> "ái",
"caí" -> "cái", "huí" -> "húi", "maí" -> "mái", "Noé" -> "Nóe" (clusters `iu`, `ai`, `ui`,
`oe`). Two common classes are Hanyu Pinyin written with tone marks ("huà" -> "hùa", "duì" ->
"dùi", "liú" -> "líu", "xià" -> "xìa", "huì" -> "hùi") and Spanish "oí" -> "ói". Only words whose cluster is in `VOWEL_NUCLEI` are ever
rewritten. `strip_accents` gives the same result either way ("più" and "pìu" both become
"piu"), so only the displayed form differs and keyword search is not affected.

## `strip_accents`

NFD, then remove every mark U+0300-U+036F that follows a Latin letter (ASCII letters,
U+00C0-U+024F, U+1E00-U+1EFF), map `đ` -> `d` and `Đ` -> `D`, then NFC. It removes Vietnamese
and foreign marks alike ("café" -> "cafe", "Ñandú" -> "Nandu"), accepts NFC or NFD input, and
leaves other scripts (Cyrillic, Greek, CJK, Thai, Arabic), emoji, digits and symbols unchanged.
It does no cleanup, no tone step and no case change.

**Keyword key convention (R8):** callers build the key as `strip_accents(normalize(x)).casefold()`.
Case folding is not done in this library, because `normalize` output is shown to users.

## Not handled (R14)

- i/y spelling variants (kĩ / kỹ, lí / lý);
- the Icelandic `Ð` (U+00D0) typed for `Đ`;
- word segmentation, spelling correction;
- legacy byte encodings (TCVN3, VNI, Windows-1258).

## Tests

`npm run backend -- test` (tables in `backend/tests/vn_text/cases.py`; at least 100 cases, at
least 10 mixed Vietnamese-English, checked by `test_vn_text_case_count.py`).

## Benchmark

`npm run backend -- bench-vn-text` (`backend/tests/perf/test_vn_text_throughput.py`; not part of
`npm run check`). NFR: at least 1 MB of text per second (1 000 000 UTF-8 bytes), for each function.

Corpus: 2 000 009 bytes built with `random.Random(2028)`: 70 % Vietnamese lines (the mixed cases
and NFC/NFD sentences of `cases.py`, half in NFD), 20 % ASCII English/code lines, 10 % lines with
emoji and old-style tone marks. Median of 5 runs after 1 warm-up.

Results (2026-10, backend-tools container on the dev machine):

| Function        | Throughput |
| --------------- | ---------- |
| `normalize`     | 1.90 MB/s  |
| `strip_accents` | 8.19 MB/s  |
