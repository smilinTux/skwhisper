"""Sensitive name matching for digest-derived whisper.md sections.

A name is sensitive when it appears as a tag on a sensitive-tagged memory (digests
tag people as ``first-last``), was recorded from a sensitive digest, or is a
patterns.json person whose normalized form equals such a tag. Each name token of 3+
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
GENERIC_TAGS = frozenset({"skwhisper", "auto-digest", "human", "cron", "digest"})


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
    """Keys from sensitive memories' tags (stem-bearing and generic tags excluded)."""
    multi, single = [], set()
    for t in sens_tags:
        if is_sensitive([t]) or normalize(t) in GENERIC_TAGS or not normalize(t):
            continue
        parts = [p for p in re.split(r"[\s_\-.]+", _clean(t)) if p]
        if len(parts) > 1:
            multi.append(t)
        else:
            single.add(t)
    names = list(multi) + list(recorded_people)
    # a single-word tag is a name only when it is also a known person
    known = {normalize(p) for p in people}
    names += [t for t in single if normalize(t) in known]
    names += [p for p in people if is_sensitive([p])]
    return name_keys(names)


def mentions(text: object, keys: set[str]) -> bool:
    return is_sensitive([text]) or bool(tokens(text) & keys)
