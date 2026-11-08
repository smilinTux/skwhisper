"""Sensitive name matching for digest-derived whisper.md sections.

A name is sensitive when it was recorded from a sensitive digest, or is a known
patterns.json person whose name tokens are a subset or superset of a sensitive
memory's tag parts (digests tag people as ``first-last``). Each name token of 3+
chars is matched on whole-word boundaries after stripping possessives and plurals,
so "Quillan's birthday" matches Quillan Marrowby while "annual planning" does not
match "Ann". Role and self words (the, user, chef, queen, lumina) are never name
keys, but relation words (wife, mother, late) are kept so they still hide.
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


# Role, self and function words that digests list as "people": keys from them would hide every topic.
_STOP_WORDS = frozenset(
    tokens(
        "the a an and this that his her our your their she him they "
        "user assistant agent bot chef king queen lumina opus jarvis ava claude"
    )
)


def name_keys(names) -> set[str]:
    """Token keys (3+ chars) for every name string, minus the stoplist."""
    keys: set[str] = set()
    for n in names:
        keys.update(k for k in tokens(n) if len(k) >= 3 and k not in _STOP_WORDS)
    return keys


def sensitive_name_keys(sens_tags, recorded_people, people) -> set[str]:
    """Name keys from KNOWN people only (never from arbitrary tags).

    A known person (a patterns.json entry or a person recorded from a sensitive
    digest) is sensitive when it carries a stem, was recorded from a sensitive
    digest, or its name tokens are a subset or superset of the hyphen-split parts of
    a tag on a sensitive memory (so tag ``quillan-marrowby`` covers "Quillan",
    "Quillan Marrowby's" and tag ``quillan`` covers "Quillan Marrowby"). Because a
    known person must exist, tags such as ``2026-11-07`` or ``morning-routine`` hide
    nothing. A sacred person with no known entry at all is out of scope. The
    sensitive person's own name tokens (3+ chars) are then the match keys.
    """
    tag_parts = []
    for t in sens_tags:
        if is_sensitive([t]):
            continue
        parts = tokens(t)
        if parts:
            tag_parts.append(parts)
    names = list(recorded_people)
    for p in people:
        pt = tokens(p)
        if is_sensitive([p]) or any(pt and (pt <= tp or tp <= pt) for tp in tag_parts):
            names.append(p)
    return name_keys(names)


def mentions(text: object, keys: set[str]) -> bool:
    return is_sensitive([text]) or bool(tokens(text) & keys)
