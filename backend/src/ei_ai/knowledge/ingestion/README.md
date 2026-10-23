# Document ingestion (EA-33)

Pure extraction: bytes in, normalised text and chunks out. No database, no storage, no logging.
`extract_document(fmt, data, progress)` is the entry point; the job (T3) and the upload route (T4)
build on it.

## Supported formats

| Extension (case-insensitive) | Format | Notes |
|---|---|---|
| `.pdf` | `pdf` | needs a text layer; one block per page |
| `.docx` | `docx` | headings, paragraphs and table rows |
| `.md` | `md` | headings from the Markdown parser, not from code fences |
| `.txt` | `txt` | UTF-8 (BOM stripped), else the best charset-normalizer guess |

Every other extension (`.doc`, `.xlsx`, `.csv`, `.exe`, ...) is unsupported; `format_for` returns `None`.

## Limits

| Limit | Value |
|---|---|
| `MAX_FILE_BYTES` | 52 428 800 (50 MiB) |
| `ORG_QUOTA_BYTES` | 1 073 741 824 (1 GiB of originals per Organization) |
| File name | base name, 1-255 characters, no control character (`clean_file_name`) |
| DOCX uncompressed size | 250 MiB for all parts (zip-bomb guard, checked before python-docx opens the file) |
| DOCX parsed XML size | 50 MiB for the parts whose content type is XML (or unknown); media parts do not count |
| Scanned PDF | fewer than 50 non-whitespace characters per page on average |

## Outcomes

`extract_document` raises `ExtractionOutcome(status, reason)`; the message is the reason code.

| Status | Reason | When |
|---|---|---|
| `failed` | `corrupt_file` | not a PDF/DOCX, truncated, a PDF with no pages, any unexpected parser error |
| `failed` | `password_protected` | PDF that does not open with an empty password |
| `failed` | `file_too_complex` | DOCX that expands past 250 MiB, or whose XML parts expand past 50 MiB |
| `failed` | `no_text` | DOCX, MD or TXT without non-whitespace text |
| `failed` | `unreadable_encoding` | TXT or MD with no usable encoding guess |
| `not_supported` | `scanned_pdf` | PDF below the scan threshold |
| `failed` | `processing_error` | reserved for the job (an unexpected exception); never raised here |

## Pipeline

1. Parse into blocks: a PDF page, or a heading section (DOCX, MD), or the whole TXT.
   A section block starts with its heading line; text before the first heading has an empty path.
   A DOCX `Title` sits above `Heading 1`; table rows are cells joined by ` | `.
2. `\r\n` and `\r` become `\n`, then `ei_ai.vn_text.normalize` on every block and heading, so NFC and
   NFD input give identical text, offsets and chunks.
3. Scan and empty-text checks, then blank blocks are dropped.
4. Blocks are joined with a blank line (`\n\n`) into the extracted text.
5. Chunking.

## Page count

PDF: the real count. DOCX: `<Pages>` of `docProps/app.xml` when above 0, else the estimate.
MD and TXT: the estimate `max(1, ceil(characters / 3000))`.

## Chunk rules

- A chunk never crosses a block, so `page` (PDF, 1-based) and `heading_path` are exact.
- Size in estimated tokens, `ceil(chars / 4)`: target 400, hard max 500, overlap 50 (200 characters).
- A block of at most 500 tokens is one chunk. Longer blocks are cut at the last paragraph break,
  else the last sentence end (`. ! ? ...` plus whitespace), else the last whitespace, else the hard
  max, searching only the window between the target and the max so every chunk but the last of a
  block holds 400-500 tokens.
- The next chunk starts about 50 tokens before the cut, moved forward to a word start.
- `char_start` and `char_end` index the extracted text: `chunk.text == text[char_start:char_end]`.

## Progress

PDF pages report 0-80; every format reports 90 after chunking. The job reports 100 when the row
is saved.
