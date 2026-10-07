from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from services.realtime_memory_session import RealtimeMemorySession
from services.realtime_voice_service import RealtimeVoiceService
from services.speaking_coach import (
    CoachRepository,
    SpeakingCoach,
    normalize_coach_config,
    parse_coach_reply,
)


class FakeConfig:
    def __init__(self, keys: dict[str, str]) -> None:
        self._keys = keys

    def get_provider_settings(self, provider: str, model: str | None = None) -> dict[str, str]:
        return {
            "api_key": self._keys.get(provider, ""),
            "base_url": "https://example.test/v1",
            "model": model or "",
        }


class FakeLLM:
    def __init__(self, reply: str, keys: dict[str, str] | None = None) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []
        self.config = FakeConfig(keys if keys is not None else {"DashScope": "sk-test"})

    async def chat_completion(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"reply": self.reply}


class FakeWebSocket:
    def __init__(self) -> None:
        self.state = SimpleNamespace()
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)


IMPROVE_REPLY = json.dumps(
    {
        "verdict": "improve",
        "corrected": "I went to the park yesterday.",
        "issues": [
            {"type": "grammar", "original": "I go", "suggestion": "I went", "explanation": "过去时"},
            {"type": "bogus", "original": "", "suggestion": "", "explanation": "dropped: no suggestion"},
        ],
        "vocabulary": [{"term": "stroll", "meaning": "散步"}],
        "tip": "Nice!",
    }
)


def test_normalize_coach_config_defaults_and_disable() -> None:
    assert normalize_coach_config(None) is None
    assert normalize_coach_config({"enabled": False}) is None
    cfg = normalize_coach_config({"enabled": True, "level": "EXPERT", "target_language": "  Japanese "})
    assert cfg == {
        "enabled": True,
        "target_language": "Japanese",
        "native_language": "Chinese",
        "level": "intermediate",
    }


def test_parse_coach_reply_sanitizes() -> None:
    review = parse_coach_reply(f"```json\n{IMPROVE_REPLY}\n```")
    assert review is not None
    assert review["verdict"] == "improve"
    assert review["issues"] == [
        {"type": "grammar", "original": "I go", "suggestion": "I went", "explanation": "过去时"}
    ]
    assert review["vocabulary"] == [{"term": "stroll", "meaning": "散步"}]

    assert parse_coach_reply("not json") is None
    assert parse_coach_reply('{"verdict": "maybe"}') is None
    # "improve" without any usable issue degrades to "good".
    degraded = parse_coach_reply('{"verdict": "improve", "corrected": "x", "issues": []}')
    assert degraded is not None and degraded["verdict"] == "good" and degraded["corrected"] == ""


def test_review_uses_fallback_model_and_skips_short_text() -> None:
    llm = FakeLLM(IMPROVE_REPLY)
    coach = SpeakingCoach(llm_service=llm)
    cfg = normalize_coach_config({"enabled": True})
    assert cfg is not None

    assert asyncio.run(coach.review(cfg, "ok")) is None
    assert llm.calls == []

    review = asyncio.run(coach.review(cfg, "I go to the park yesterday", "What did you do?"))
    assert review is not None and review["verdict"] == "improve"
    call = llm.calls[0]
    assert call["provider"] == "DashScope"
    assert call["model"] == "qwen-flash"
    assert call["use_memory"] is False
    assert "What did you do?" in call["messages"][1]["content"]


def test_review_without_any_provider_returns_none() -> None:
    coach = SpeakingCoach(llm_service=FakeLLM(IMPROVE_REPLY, keys={}))
    cfg = normalize_coach_config({"enabled": True})
    assert asyncio.run(coach.review(cfg, "I go to the park yesterday")) is None


def test_repository_round_trip(tmp_path) -> None:
    repo = CoachRepository(db_path=tmp_path / "coach.db")
    cfg = normalize_coach_config({"enabled": True, "level": "ielts"})
    review = parse_coach_reply(IMPROVE_REPLY)
    item_id = repo.add(review=review, user_text="I go to the park yesterday", config=cfg, session_id="s1")
    repo.add(
        review=parse_coach_reply('{"verdict": "good"}'),
        user_text="That sounds great.",
        config=cfg,
        session_id="s1",
    )

    items = repo.list_recent(limit=10)
    assert [item["verdict"] for item in items] == ["good", "improve"]
    assert items[1]["issues"][0]["suggestion"] == "I went"
    assert items[1]["level"] == "ielts"
    assert len(repo.list_recent(verdict="improve")) == 1

    summary = repo.summary()
    assert summary["reviewed_turns"] == 2
    assert summary["good_ratio"] == 0.5
    assert summary["issue_counts"] == {"grammar": 1}

    assert repo.delete(item_id) is True
    assert repo.delete(item_id) is False


def test_finalize_turn_emits_coach_feedback_when_enabled(tmp_path) -> None:
    async def scenario() -> FakeWebSocket:
        service = RealtimeVoiceService()
        service.speaking_coach = SpeakingCoach(
            llm_service=FakeLLM(IMPROVE_REPLY),
            repository=CoachRepository(db_path=tmp_path / "coach.db"),
        )
        websocket = FakeWebSocket()
        memory_session = RealtimeMemorySession()
        memory_session.configure(None)

        # Disabled by default: no review is scheduled.
        memory_session.note_user_transcript("I go to the park yesterday")
        await service._finalize_realtime_turn(websocket, memory_session, None)
        assert not service._coach_tasks

        result = await service._handle_common_client_command(
            "coach_config",
            {"coach": {"enabled": True, "level": "advanced"}},
            websocket=websocket,
            memory_session=memory_session,
            tool_session=None,  # type: ignore[arg-type]
            recorder=None,
            interruption=None,  # type: ignore[arg-type]
            provider="DashScope",
        )
        assert result == "handled"

        memory_session.note_user_transcript("I go to the park yesterday")
        memory_session.note_assistant_text("Sounds fun!")
        await service._finalize_realtime_turn(websocket, memory_session, None)
        await asyncio.gather(*list(service._coach_tasks))
        return websocket

    websocket = asyncio.run(scenario())
    types = [event["type"] for event in websocket.sent]
    assert "coach_config" in types
    feedback = [event for event in websocket.sent if event["type"] == "coach_feedback"]
    assert len(feedback) == 1
    assert feedback[0]["user_text"] == "I go to the park yesterday"
    assert feedback[0]["corrected"] == "I went to the park yesterday."
    assert feedback[0]["id"] > 0


@pytest.mark.parametrize("payload", [None, {"enabled": False}])
def test_coach_config_disable(payload: Any) -> None:
    async def scenario() -> FakeWebSocket:
        service = RealtimeVoiceService()
        websocket = FakeWebSocket()
        await service._handle_common_client_command(
            "coach_config",
            {"coach": payload},
            websocket=websocket,
            memory_session=RealtimeMemorySession(),
            tool_session=None,  # type: ignore[arg-type]
            recorder=None,
            interruption=None,  # type: ignore[arg-type]
            provider="DashScope",
        )
        return websocket

    websocket = asyncio.run(scenario())
    assert websocket.sent == [{"type": "coach_config", "enabled": False, "coach": None}]


def test_tutor_config_and_base_instructions_binding() -> None:
    from services.speaking_coach import (
        TUTOR_SCENARIOS,
        normalize_tutor_config,
        reset_tutor_session,
        set_tutor_session,
    )

    assert normalize_tutor_config(enabled=False, scenario="ielts") is None
    cfg = normalize_tutor_config(enabled=True, target_language="Japanese", level="beginner", scenario="bogus")
    assert cfg is not None
    assert cfg["scenario"] == "free_talk"
    assert cfg["target_language"] == "Japanese"

    plain = RealtimeVoiceService._get_base_instructions()
    assert "[Language Tutor Mode]" not in plain

    ielts = normalize_tutor_config(enabled=True, level="ielts", scenario="ielts")
    token = set_tutor_session(ielts)
    try:
        tutored = RealtimeVoiceService._get_base_instructions()
        built = RealtimeVoiceService._build_realtime_instructions("memory ctx")
    finally:
        reset_tutor_session(token)
    assert tutored.startswith(plain)
    assert "[Language Tutor Mode]" in tutored
    assert TUTOR_SCENARIOS["ielts"] in tutored
    assert "native language is Chinese" in tutored
    assert "[Language Tutor Mode]" in built
    assert "[Language Tutor Mode]" not in RealtimeVoiceService._get_base_instructions()


def test_tutor_session_is_isolated_per_task() -> None:
    from services.speaking_coach import normalize_tutor_config, set_tutor_session

    async def session(enabled: bool) -> str:
        set_tutor_session(normalize_tutor_config(enabled=enabled))
        await asyncio.sleep(0)
        return RealtimeVoiceService._get_base_instructions()

    async def main() -> list[str]:
        return list(await asyncio.gather(session(True), session(False)))

    tutored, plain = asyncio.run(main())
    assert "[Language Tutor Mode]" in tutored
    assert "[Language Tutor Mode]" not in plain
