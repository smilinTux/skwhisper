# Changelog

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
