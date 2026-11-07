"""Sensitive name matching for digest-derived whisper.md sections.

A name is sensitive when it was recorded from a sensitive digest, or is a known
patterns.json person whose normalized form equals a tag on a sensitive memory
(digests tag people as ``first-last``). Each name token of 3+
chars is matched on whole-word boundaries after stripping possessives and plurals,
so "Quillan's birthday" matches Quillan Marrowby while "annual planning" does not
match "Ann".
"""

from __future__ import annotations

import re
import unicodedata

from .sensitivity import _drop, is_sensitive, normalize

_POSSESSIVE = re.compile(r"[’'`]s?\b", re.I)
_TOKEN = re.compile(r"[^\W_]+")


def _clean(text: object) -> str:
    t = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in t if not _drop(c))


def tokens(text: object) -> set[str]:
    """Whole-word keys: possessives and plural 's' stripped, homoglyphs folded."""
    t = _POSSESSIVE.sub("", _clean(text))
    out = set()
    for w in _TOKEN.findall(t):
        k = normalize(w)
        if len(k) > 3 and k.endswith("s"):
            k = k[:-1]
        if k:
            out.add(k)
    return out


def name_keys(names) -> set[str]:
    """Token keys (3+ chars) for every name string."""
    keys: set[str] = set()
    for n in names:
        keys.update(k for k in tokens(n) if len(k) >= 3)
    return keys


def sensitive_name_keys(sens_tags, recorded_people, people) -> set[str]:
    """Name keys from PERSON-LIKE sources only.

    Sources: people recorded from sensitive digests, and known people (patterns.json
    entries) that carry a stem themselves or equal a tag of a sensitive memory.
    Arbitrary tags are never split into names: ``morning-routine`` or ``2026-11-07``
    on a sacred memory must not hide "morning standup" or "2026 goals".
    """
    tag_forms = {normalize(t) for t in sens_tags}
    names = list(recorded_people)
    names += [p for p in people if is_sensitive([p]) or normalize(p) in tag_forms]
    return name_keys(names)


def mentions(text: object, keys: set[str]) -> bool:
    return is_sensitive([text]) or bool(tokens(text) & keys)
