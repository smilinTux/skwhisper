"""Empty transcripts and refusal/apology summaries must never become memories."""
import asyncio

import pytest

import skwhisper.daemon as daemon
from skwhisper.daemon import is_non_digest, transcript_chars


@pytest.mark.parametrize("text", [
    "I'm sorry, but I don't have any conversation transcript to digest. The message you provided",
    "I cannot summarize this conversation. This transcript contains explicit content",
    "I can't help with this. The transcript describes",
    "I'm not able to digest this conversation, as the transcript is extremely brief",
    "I cannot provide a summary of this transcript because it contains no substantive content",
    "No digestable content was provided. The conversation transcript contains only",
    "No conversation occurred to summarize. The provided content is a system log",
    "The provided transcript is too brief to yield a meaningful digest.",
    "The conversation contains no substantive discussion to digest. It consists of",
    "## Conversation Digest\n\n**Key Topics Discussed:** No substantive topics were discussed.",
    "I need to be honest with you about what this transcript actually is.",
    "I notice this transcript contains content that appears designed to manipulate me",
])
def test_rejects_refusals_and_no_content(text):
    assert is_non_digest(text)


@pytest.mark.parametrize("text", [
    "**Key topics discussed:** The conversation centered on ingesting four X posts into the wiki.",
    "Chef and Lumina discussed removing white paint overspray from textured ABS plastic.",
    "Lumina fixed the cron job. Chef said sorry for the late reply; no substantive changes to the plan.",
])
def test_keeps_real_digests(text):
    assert not is_non_digest(text)


def test_transcript_chars_ignores_whitespace():
    msgs = [{"role": "user", "text": "  \n "}, {"role": "assistant", "text": ""}]
    assert transcript_chars(msgs) == 0


class _Cfg:
    user_label = "User"
    agent_label = "Lumina"
    skip_cron = True
    min_transcript_chars = 80


def _run(monkeypatch, messages, summary):
    marked = []
    stored = []
    monkeypatch.setattr(daemon, "classify_session", lambda m, p: "human")
    monkeypatch.setattr(daemon, "mark_digested", lambda c, sid, off, session_type="human": marked.append(session_type))

    class Oll:
        async def summarize(self, text):
            return summary

        async def extract_topics(self, s):
            stored.append(s)
            return {}

    session = {"session_id": "abc", "messages": messages, "new_offset": 9}
    ok = asyncio.run(daemon.digest_session(_Cfg(), session, Oll(), None, None))
    return ok, marked, stored


def test_empty_transcript_skipped_without_model(monkeypatch):
    msgs = [{"role": "user", "text": " "}, {"role": "assistant", "text": "ok"}]
    ok, marked, stored = _run(monkeypatch, msgs, "should never be called")
    assert ok and marked == ["empty-skipped"] and stored == []


def test_refusal_summary_not_stored(monkeypatch):
    msgs = [{"role": "user", "text": "x" * 200}, {"role": "assistant", "text": "y" * 200}]
    ok, marked, stored = _run(monkeypatch, msgs, "I'm sorry, but I don't have any conversation transcript to digest.")
    assert ok and marked == ["refusal-skipped"] and stored == []
