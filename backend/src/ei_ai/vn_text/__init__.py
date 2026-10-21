"""Vietnamese text normalisation (EA-28): one canonical form for ingestion, the Gate and Glossary.

The rules (pipeline, tone placement, cleanup list, what is left unchanged) are documented in
``README.md`` next to this file.
"""

from ei_ai.vn_text.accents import strip_accents
from ei_ai.vn_text.normalize import normalize

__all__ = ["normalize", "strip_accents"]
