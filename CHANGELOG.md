# Changelog

## [Unreleased]

### Removed
- ChromaDB and Qdrant clients (`clients/chroma.py`, `clients/qdrant.py`) and
  their config keys. pgvector is the only vector backend; requesting another
  raises (SKMEM-P5-07).

### Fixed
- whisper.md hot topics, repeated questions and people no longer come from sensitive session digests (SKMEM-P1-18). A digest tagged sensitive feeds no pattern counts. At curation time the sensitive name set is built from person-like sources only (people recorded from sensitive digests, and known people whose name tokens are a subset or superset of a sensitive memory tag's hyphen-split parts; arbitrary hyphenated tags are never split into names), matched per whole word with possessives and plurals stripped; matching topics, questions, people, projects and behaviors are dropped at render time (whisper.md and the `patterns`/`status` CLI output; patterns.json is never rewritten), as are topics from sessions behind sensitive digests. If the sensitivity sources cannot be read the digest-derived sections fail closed to a `source unavailable` line.
- whisper.md keeps the Relevant Memories header and says `source unavailable: <cause class>` when the semantic source fails, instead of silently dropping the section (SKMEM-P1-19). The cause is chosen by phase then exception type: embedding service unreachable, timed out, returned an error or failed; postgres auth failed (including a libpq rejected login, which carries no sqlstate), unreachable or query failed; search failed. The warning log and health banner carry the cause class only, never the DSN, user or host.
- whisper.md hot topics, repeated questions and people no longer come from sensitive session digests (SKMEM-P1-18). A digest tagged sensitive feeds no pattern counts. At curation time the sensitive name set is built from person-like sources only (people recorded from sensitive digests, and known people whose name equals a tag on a sensitive memory; arbitrary hyphenated tags are never split into names), matched per whole word with possessives and plurals stripped; matching topics, questions, people, projects and behaviors are dropped at render time (whisper.md and the `patterns`/`status` CLI output; patterns.json is never rewritten), as are topics from sessions behind sensitive digests. If the sensitivity sources cannot be read the digest-derived sections fail closed to a `source unavailable` line.
- whisper.md no longer selects sensitive memories. The SQLite recency feed and the pg hybrid search drop rows tagged sacred, grief, medical, family-private, private and the other skmemory sensitive stems (normalized: NFKD with marks and format controls dropped, look-alike letters folded, every dash, space, `_` and `.` stripped), and take the next candidate instead. `skwhisper/sensitivity.py` ports skmemory's helper; a parity test pins them.

### Added
- `.github/workflows/test.yml`: runs pytest on every PR with skmemory installed from git main; the skmemory parity test is required there, not skipped.
- Digest memories carry `source_ref=session:<id>@<start>-<end>` (byte range of the session JSONL),
  so skmemory `memory_expand` can return the raw episode (SKMEM-P3-07).

### Fixed
- Relative-date resolver no longer raises on a weekday phrase with extra whitespace or a newline
  ("last  Friday", "next\nMonday"); the phrase is whitespace-normalised before lookup.
- Session digests resolve relative dates (yesterday, last week, tomorrow, weekday names)
  against the session's event time (newest message timestamp; with none the text is left unchanged),
  never the digest-time wall clock. The summarizer is told the conversation date
  and a deterministic pass appends the ISO date in parentheses after each phrase,
  keeping the original words (SKMEM-P3-05).
- The pg DSN resolves from `SKMEMORY_PG_DSN` / `~/.config/environment.d/skmemory.conf`
  only. No per-agent `pg_dsn` override and no hardcoded fallback password
  (SKMEM-P0-13).
- A failed graph write, an unavailable AGE graph, or a failed vector upsert or
  search now puts a GRAPH DEGRADED or VECTOR DEGRADED banner at the top of
  whisper.md instead of regenerating silently (SKMEM-P0-13).

## [0.6.3] - 2026-10-30

### Added
- Export Hermes `state.db` conversations as digestible sessions, and digest
  short real chats instead of skipping them (#3).
- PyPI publish workflow on `v*` tags, asserting the tag matches the static
  pyproject version (#1).

### Fixed
- Digest content written to skmem-pg is the full digest, not `content[:2000]` (#6).
- The transcript is fenced in the summarize prompt so short chats are digested,
  not answered (#5).
- Reasoning models are asked not to think during digests (#4).
- Neutral default `user_label` instead of "Casey" (#2).
- `skwhisper.__version__` was stuck at 0.6.0 since v0.6.0; it now matches
  pyproject.

## [0.6.2] - 2026-08-15

- systemd unit logs to journald, not an unbounded append file (0.6.1, re-tagged
  as 0.6.2 because the v0.6.1 tag was already taken remotely).
