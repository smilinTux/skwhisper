# Changelog

## [Unreleased]

### Removed
- ChromaDB and Qdrant clients (`clients/chroma.py`, `clients/qdrant.py`) and
  their config keys. pgvector is the only vector backend; requesting another
  raises (SKMEM-P5-07).

### Fixed
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
