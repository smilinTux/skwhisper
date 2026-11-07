"""Sensitive-tag stems for whisper.md (port of skmemory/hooks/sensitivity.py).

skwhisper's clients are deliberately decoupled from skmemory (no import, raw SQL),
and the packaged skmemory may predate its sensitivity helper, so the stem list and
the normalization are PORTED here and pinned to the skmemory copy by
tests/test_sensitivity_parity.py. Change them together.

whisper.md is injected into every session start and read directly by agents, so
memories tagged sacred, grief, medical, family-private, private, ... must never be
selected for it. Matching is by stem after normalization (NFKC, casefold, Cyrillic
and Greek look-alikes folded, ``- _ .`` and whitespace dropped).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

# A superset of eval.harvest.SENSITIVE_TAGS / SENSITIVE_TAG_SUBSTRINGS (pinned by
# tests/test_query_slice.py).
SENSITIVE_STEMS = (
    "medical",
    "health",
    "legal",
    "sacred",
    "private",
    "personal",
    "financ",
    "family-private",
    "grief",
    "therap",
    "sarah",
    "bereave",
    "diagnos",
    "medication",
    "nootropic",
)

OWNER_ONLY_STEMS = ("sacred", "grief", "family-private", "personal-history")

# Common look-alikes folded to ASCII before matching (Cyrillic and Greek).
_HOMOGLYPHS = str.maketrans(
    {
        "\u0430": "a",  # Cyrillic a
        "\u0435": "e",
        "\u043e": "o",
        "\u0440": "p",
        "\u0441": "c",
        "\u0443": "y",
        "\u0445": "x",
        "\u0456": "i",
        "\u0455": "s",
        "\u0458": "j",
        "\u03bf": "o",  # Greek omicron
        "\u03b1": "a",
        "\u03b5": "e",
        "\u03c1": "p",
    }
)
_SEPARATORS = re.compile(r"[-_\s.]+")


def normalize(text: object) -> str:
    """NFKC, casefold, fold homoglyphs, then drop ``- _ . whitespace``.

    So ``Family_Private``, ``family private``, ``familyprivate``, fullwidth
    ``sacred`` and Cyrillic-a ``sacred`` all compare equal to the plain stem.
    """
    t = unicodedata.normalize("NFKC", str(text)).casefold().translate(_HOMOGLYPHS)
    return _SEPARATORS.sub("", t)


_NORM_SENSITIVE = tuple(normalize(x) for x in SENSITIVE_STEMS)
_NORM_OWNER_ONLY = tuple(normalize(x) for x in OWNER_ONLY_STEMS)


def _hit(tags: Iterable[str] | None, stems: tuple[str, ...]) -> bool:
    if tags is None:
        return False
    if isinstance(tags, str):
        tags = [tags]
    return any(s in n for n in (normalize(t) for t in tags) for s in stems)


def is_sensitive(tags: Iterable[str] | None) -> bool:
    """True when any tag contains a sensitive stem (after normalization)."""
    return _hit(tags, _NORM_SENSITIVE)


def is_owner_only(tags: Iterable[str] | None) -> bool:
    """True when any tag contains an owner-only stem (after normalization)."""
    return _hit(tags, _NORM_OWNER_ONLY)


def csv_is_sensitive(csv: object) -> bool:
    """True when a CSV tag string (as stored in the SQLite index) has a sensitive tag."""
    return is_sensitive(str(csv or "").split(","))
