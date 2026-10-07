"""Speaking coach for realtime calls.

The coach itself is the realtime voice model (tutor mode, see
``build_tutor_instructions``): it corrects the learner live, in its spoken
replies. Optional written feedback cards come on top of that: when a session
enables them (client command ``coach_config``), every finalized user turn is
reviewed in the background by a text LLM. The review never touches the live
audio pipeline: the result is pushed to the client as a ``coach_feedback``
event and persisted so the learner can review mistakes and vocabulary after
the call.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from .db_utils import get_db_connection

logger = logging.getLogger(__name__)

COACH_LEVELS = ("beginner", "intermediate", "advanced", "ielts")
ISSUE_TYPES = ("grammar", "word_choice", "naturalness", "pronunciation", "fluency")

# Realtime-only users usually have a DashScope key but no default chat model,
# so the coach resolves providers tolerantly and falls back to known models.
COACH_PROVIDER_ORDER = ("DashScope", "DeepSeek", "Google", "OpenRouter", "SiliconFlow", "Groq")
COACH_DEFAULT_MODELS = {
    "DashScope": "qwen-flash",
    "DeepSeek": "deepseek-v4-flash",
    "Google": "gemini-3.7-flash",
    "OpenRouter": "deepseek/deepseek-chat",
    "SiliconFlow": "deepseek-ai/DeepSeek-V3",
    "Groq": "llama-3.3-70b-versatile",
}

MIN_REVIEW_CHARS = 4
MAX_REVIEW_CHARS = 1200
MAX_ISSUES = 3
MAX_VOCABULARY = 3


def normalize_coach_config(payload: Any) -> dict[str, Any] | None:
    """Return a sanitized coach config, or None when coaching is disabled."""
    if not isinstance(payload, dict) or not payload.get("enabled"):
        return None

    def _clean(value: Any, default: str, limit: int = 40) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()[:limit]
        return text or default

    level = str(payload.get("level") or "").strip().lower()
    return {
        "enabled": True,
        "target_language": _clean(payload.get("target_language"), "English"),
        "native_language": _clean(payload.get("native_language"), "Chinese"),
        "level": level if level in COACH_LEVELS else "intermediate",
    }


# -- tutor mode: the realtime model itself plays a language partner ----------

TUTOR_SCENARIOS: dict[str, str] = {
    "free_talk": "Free conversation: chat about the learner's day, interests and opinions.",
    "daily_life": "Daily life: shopping, ordering food, making plans with friends, small talk with neighbours.",
    "workplace": "Workplace: self-introduction at work, meetings, giving updates, polite disagreement, emails read aloud.",
    "travel": "Travel: airport check-in, hotel, asking for directions, restaurants, solving problems on a trip.",
    "job_interview": (
        "Job interview: you are the interviewer. Ask typical interview questions one by one "
        "and follow up on the learner's answers."
    ),
    "ielts": (
        "IELTS Speaking mock test: you are the examiner. Run Part 1 (short questions about familiar topics), "
        "then Part 2 (give a cue card topic and ask the learner to speak for 1-2 minutes), "
        "then Part 3 (abstract discussion questions). Stay in examiner role; at the end give a brief, "
        "honest estimate of fluency, vocabulary, grammar and pronunciation."
    ),
}
DEFAULT_TUTOR_SCENARIO = "free_talk"

_tutor_session: ContextVar[dict[str, Any] | None] = ContextVar("speaking_tutor_session", default=None)


def normalize_tutor_config(
    *,
    enabled: bool,
    target_language: str | None = None,
    native_language: str | None = None,
    level: str | None = None,
    scenario: str | None = None,
) -> dict[str, Any] | None:
    """Sanitized tutor config, or None when tutor mode is off."""
    if not enabled:
        return None
    base = normalize_coach_config(
        {
            "enabled": True,
            "target_language": target_language,
            "native_language": native_language,
            "level": level,
        }
    )
    assert base is not None
    clean_scenario = str(scenario or "").strip().lower()
    base["scenario"] = clean_scenario if clean_scenario in TUTOR_SCENARIOS else DEFAULT_TUTOR_SCENARIO
    return base


def build_tutor_instructions(config: dict[str, Any]) -> str:
    """Coach persona appended to the realtime system prompt.

    The realtime voice model itself does the coaching, live in the
    conversation: it hears the learner and corrects them in its spoken reply,
    so no separate text model is needed for the core experience.
    """
    target = config["target_language"]
    native = config["native_language"]
    level_hint = {
        "beginner": "Use very simple words and short sentences, speak slowly, and repeat key words.",
        "intermediate": "Use everyday vocabulary and natural sentences; introduce a few new expressions.",
        "advanced": "Speak naturally at native pace and use idioms; push the learner to elaborate.",
        "ielts": "Speak naturally and push for extended, well-organised answers with precise vocabulary.",
    }[config["level"]]
    correction_hint = {
        "beginner": (
            "Only correct mistakes that change or block the meaning. You may add one short explanation "
            f"in {native}, then say the correct {target} sentence slowly so the learner can repeat it."
        ),
        "intermediate": "Correct clear grammar mistakes and wrong words; leave small slips alone.",
        "advanced": (
            "Correct mistakes and also phrasing a native speaker would find unnatural, offering the more "
            "idiomatic way to say it."
        ),
        "ielts": (
            "Correct mistakes and offer a higher-band word or collocation when it clearly fits what the "
            "learner meant."
        ),
    }[config["level"]]
    examiner = config["scenario"] == "ielts"
    correction_timing = (
        "- While the mock test is running, stay in examiner role and do not correct; at the end give the "
        "estimate plus the three most useful corrections, each as 'you said ..., better: ...'.\n"
        if examiner
        else (
            "- When the learner makes a real mistake, fix it right away in your spoken reply: say the "
            "correct version in one short sentence (for example: 'Quick tip: for yesterday, say I went, "
            "not I go.'), then carry on with the conversation. "
            f"{correction_hint}\n"
            "- At most ONE correction per turn: pick the most useful one. If what the learner said was "
            "correct, do not correct anything; now and then briefly praise a good expression instead.\n"
        )
    )
    return (
        "\n\n[Language Tutor Mode]\n"
        f"You are now a friendly {target} speaking coach in a live voice call with a learner whose native "
        f"language is {native}. You hear the learner directly and coach them inside the conversation. "
        "These rules override the general assistant persona and language rules above.\n"
        f"- Scenario: {TUTOR_SCENARIOS[config['scenario']]}\n"
        f"- Speak {target} by default. {level_hint}\n"
        "- Keep the conversation going: each reply is short (1-3 sentences) so the learner does most of the "
        "talking, and ends with exactly one question or prompt.\n"
        f"{correction_timing}"
        "- Never invent mistakes, never comment on accent, and only mention pronunciation when a word was "
        "clearly mispronounced. Be patient with hesitation; never finish the learner's sentences.\n"
        "- If the learner asks whether something was correct, how to say something, or for feedback, answer "
        "directly and concretely.\n"
        f"- If the learner speaks {native} or is stuck, help briefly in {native}, give them the {target} "
        f"phrase to try, then switch back to {target}.\n"
        "- Your replies are spoken aloud: no emoji, markdown, lists or special symbols.\n"
        "- In your first reply, greet the learner and open the scenario with a simple question."
    )


def set_tutor_session(config: dict[str, Any] | None) -> Any:
    """Bind tutor config to the current realtime session task; returns a reset token."""
    return _tutor_session.set(config)


def reset_tutor_session(token: Any) -> None:
    _tutor_session.reset(token)


def current_tutor_instructions() -> str:
    config = _tutor_session.get()
    return build_tutor_instructions(config) if config else ""


def build_coach_instructions(config: dict[str, Any]) -> str:
    """System prompt for the per-turn review model."""
    level_hint = {
        "beginner": "The learner is a beginner: flag only clear errors and keep explanations very simple.",
        "intermediate": "The learner is intermediate: flag errors and the most unnatural phrasing.",
        "advanced": (
            "The learner is advanced: also flag subtle unnaturalness. Put more idiomatic alternatives in "
            "\"vocabulary\", not in \"issues\"."
        ),
        "ielts": (
            "The learner is preparing for the IELTS Speaking test. Put higher-band vocabulary, collocations and "
            "cohesive devices in \"vocabulary\" only; they are upgrades, NOT errors, and never make the verdict "
            "\"improve\" on their own."
        ),
    }[config["level"]]
    target = config["target_language"]
    native = config["native_language"]
    return (
        f"You are a concise {target} speaking coach. You review ONE spoken utterance by a learner, "
        f"transcribed by speech recognition. {level_hint}\n"
        "Rules:\n"
        f"- Only judge the learner's {target}. If the utterance is not in {target}, or is a filler/backchannel "
        "(e.g. 'ok', 'yeah', 'hmm'), return verdict \"skip\".\n"
        "- Punctuation and capitalization come from the speech recognizer, not the learner: NEVER comment on "
        "or change them. Also ignore obvious speech-recognition artifacts.\n"
        "- Only flag REAL problems: a grammar error, a wrong word, or phrasing a native speaker would find "
        "clearly unnatural. Do NOT flag stylistic preferences, synonyms, making it more formal/enthusiastic/"
        "specific, or adding information the learner did not say. Short, simple sentences can be perfect.\n"
        "- Every issue has a severity: \"error\" = actually incorrect (grammar mistake, wrong word, clearly "
        "unnatural to a native speaker); \"style\" = the original is acceptable and yours is only an alternative. "
        "The verdict is \"improve\" only if there is at least one \"error\".\n"
        "- If the utterance is already correct and natural, return verdict \"good\" with no issues. "
        "When in doubt, choose \"good\" — a false correction hurts the learner more than a missed one.\n"
        f"- At most {MAX_ISSUES} issues and {MAX_VOCABULARY} vocabulary items, most important first.\n"
        f"- LANGUAGE: every \"explanation\", \"meaning\" and \"tip\" MUST be written in {native} "
        f"(the learner's native language), never in {target}; keep each under 30 words. "
        f"Only \"corrected\", \"original\", \"suggestion\" and \"term\" are in {target}.\n"
        "Return ONLY a JSON object, no markdown:\n"
        '{"verdict": "good" | "improve" | "skip", '
        '"corrected": "the full utterance rewritten correctly and naturally (empty if good/skip)", '
        '"issues": [{"severity": "error" | "style", "type": "grammar" | "word_choice" | "naturalness" | "fluency", '
        f'"original": "exact fragment", "suggestion": "better fragment", "explanation": "why, in {native}"}}], '
        f'"vocabulary": [{{"term": "useful word or phrase for this context", "meaning": "short gloss in {native}"}}], '
        f'"tip": "one short encouraging tip in {native}, may be empty"}}'
    )


def _strip_code_fence(text: str) -> str:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
    if fence:
        return fence.group(1).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        return cleaned[start : end + 1]
    return cleaned


def _surface_key(text: str) -> str:
    """Comparison key ignoring case, punctuation and spacing."""
    return re.sub(r"[\W_]+", " ", str(text or "").casefold()).strip()


def parse_coach_reply(reply: str, user_text: str = "") -> dict[str, Any] | None:
    """Parse and sanitize the model's JSON review. Returns None when unusable."""
    try:
        data = json.loads(_strip_code_fence(str(reply or "")))
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    verdict = str(data.get("verdict") or "").strip().lower()
    if verdict not in ("good", "improve", "skip"):
        return None

    issues: list[dict[str, str]] = []
    style_vocabulary: list[dict[str, str]] = []
    for raw in data.get("issues") or []:
        if not isinstance(raw, dict):
            continue
        suggestion = str(raw.get("suggestion") or "").strip()
        if not suggestion:
            continue
        original = str(raw.get("original") or "").strip()
        # Punctuation/case come from ASR, not the learner: drop cosmetic "fixes".
        if original and _surface_key(original) == _surface_key(suggestion):
            continue
        issue_type = str(raw.get("type") or "").strip().lower()
        if str(raw.get("severity") or "error").strip().lower() == "style":
            # Acceptable as said: offer the alternative as a phrase, not a mistake.
            style_vocabulary.append(
                {"term": suggestion[:80], "meaning": str(raw.get("explanation") or "").strip()[:160]}
            )
            continue
        issues.append(
            {
                "type": issue_type if issue_type in ISSUE_TYPES else "naturalness",
                "original": original[:200],
                "suggestion": suggestion[:200],
                "explanation": str(raw.get("explanation") or "").strip()[:240],
            }
        )
        if len(issues) >= MAX_ISSUES:
            break

    vocabulary: list[dict[str, str]] = []
    for raw in [*style_vocabulary, *(data.get("vocabulary") or [])]:
        if not isinstance(raw, dict):
            continue
        term = str(raw.get("term") or "").strip()
        if not term or any(_surface_key(term) == _surface_key(v["term"]) for v in vocabulary):
            continue
        if user_text and _surface_key(term) == _surface_key(user_text):
            continue
        vocabulary.append({"term": term[:80], "meaning": str(raw.get("meaning") or "").strip()[:160]})
        if len(vocabulary) >= MAX_VOCABULARY:
            break

    corrected = str(data.get("corrected") or "").strip()[:MAX_REVIEW_CHARS]
    if verdict == "improve" and (
        not issues or (user_text and _surface_key(corrected) == _surface_key(user_text))
    ):
        verdict = "good"
    if verdict != "improve":
        corrected = ""
    return {
        "verdict": verdict,
        "corrected": corrected,
        "issues": issues if verdict == "improve" else [],
        "vocabulary": vocabulary if verdict != "skip" else [],
        "tip": str(data.get("tip") or "").strip()[:240] if verdict != "skip" else "",
    }


def should_review(user_text: str) -> bool:
    text = str(user_text or "").strip()
    return len(text) >= MIN_REVIEW_CHARS and bool(re.search(r"\w", text))


class CoachRepository:
    """Durable store of coach reviews, used for post-call review and stats."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or self._default_db_path()
        self._init_db()

    @staticmethod
    def _default_db_path() -> Path:
        from .config_loader import get_data_file_path

        return get_data_file_path("voice_spirit.db")

    def _connect(self) -> sqlite3.Connection:
        return get_db_connection(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS coach_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL DEFAULT '',
                    turn_id TEXT NOT NULL DEFAULT '',
                    user_text TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    corrected TEXT NOT NULL DEFAULT '',
                    issues_json TEXT NOT NULL DEFAULT '[]',
                    vocabulary_json TEXT NOT NULL DEFAULT '[]',
                    tip TEXT NOT NULL DEFAULT '',
                    target_language TEXT NOT NULL DEFAULT '',
                    level TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_coach_feedback_created ON coach_feedback(created_at)"
            )
            conn.commit()

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
        def _decode(value: Any) -> list[Any]:
            try:
                parsed = json.loads(value or "[]")
            except (TypeError, ValueError):
                return []
            return parsed if isinstance(parsed, list) else []

        return {
            "id": int(row["id"]),
            "session_id": str(row["session_id"] or ""),
            "turn_id": str(row["turn_id"] or ""),
            "user_text": str(row["user_text"] or ""),
            "verdict": str(row["verdict"] or ""),
            "corrected": str(row["corrected"] or ""),
            "issues": _decode(row["issues_json"]),
            "vocabulary": _decode(row["vocabulary_json"]),
            "tip": str(row["tip"] or ""),
            "target_language": str(row["target_language"] or ""),
            "level": str(row["level"] or ""),
            "created_at": str(row["created_at"] or ""),
        }

    def add(
        self,
        *,
        review: dict[str, Any],
        user_text: str,
        config: dict[str, Any],
        session_id: str = "",
        turn_id: str = "",
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO coach_feedback (
                    session_id, turn_id, user_text, verdict, corrected,
                    issues_json, vocabulary_json, tip, target_language, level
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    turn_id,
                    user_text,
                    review["verdict"],
                    review["corrected"],
                    json.dumps(review["issues"], ensure_ascii=False),
                    json.dumps(review["vocabulary"], ensure_ascii=False),
                    review["tip"],
                    config.get("target_language", ""),
                    config.get("level", ""),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid or 0)

    def list_recent(
        self, *, limit: int = 50, verdict: str | None = None, session_id: str | None = None
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if verdict:
            clauses.append("verdict = ?")
            params.append(verdict)
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM coach_feedback {where} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT verdict, issues_json FROM coach_feedback WHERE verdict != 'skip'"
            ).fetchall()
        issue_counts: dict[str, int] = {}
        verdicts = {"good": 0, "improve": 0}
        for row in rows:
            verdict = str(row["verdict"])
            if verdict in verdicts:
                verdicts[verdict] += 1
            try:
                issues = json.loads(row["issues_json"] or "[]")
            except (TypeError, ValueError):
                issues = []
            for issue in issues if isinstance(issues, list) else []:
                issue_type = str(issue.get("type", "")) if isinstance(issue, dict) else ""
                if issue_type:
                    issue_counts[issue_type] = issue_counts.get(issue_type, 0) + 1
        total = verdicts["good"] + verdicts["improve"]
        return {
            "reviewed_turns": total,
            "good_turns": verdicts["good"],
            "improve_turns": verdicts["improve"],
            "good_ratio": round(verdicts["good"] / total, 3) if total else None,
            "issue_counts": issue_counts,
        }

    def delete(self, item_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM coach_feedback WHERE id = ?", (int(item_id),))
            conn.commit()
            return cursor.rowcount > 0


class SpeakingCoach:
    """Reviews learner utterances with a text LLM."""

    def __init__(self, llm_service: Any = None, repository: CoachRepository | None = None) -> None:
        self._llm_service = llm_service
        self._repository = repository

    @property
    def llm_service(self) -> Any:
        if self._llm_service is None:
            from .llm_service import LLMService

            self._llm_service = LLMService()
        return self._llm_service

    @property
    def repository(self) -> CoachRepository:
        if self._repository is None:
            self._repository = CoachRepository()
        return self._repository

    def resolve_model(self) -> tuple[str, str] | None:
        """Pick the first provider with an API key; tolerate a missing default model."""
        config = self.llm_service.config
        for provider in COACH_PROVIDER_ORDER:
            try:
                settings = config.get_provider_settings(provider, None)
            except Exception:
                continue
            if not str(settings.get("api_key", "")).strip():
                continue
            if not str(settings.get("base_url", "")).strip():
                continue
            model = str(settings.get("model", "")).strip() or COACH_DEFAULT_MODELS[provider]
            return provider, model
        return None

    async def review(
        self,
        config: dict[str, Any],
        user_text: str,
        assistant_text: str = "",
    ) -> dict[str, Any] | None:
        text = str(user_text or "").strip()[:MAX_REVIEW_CHARS]
        if not should_review(text):
            return None
        resolved = self.resolve_model()
        if resolved is None:
            logger.info("speaking_coach skipped: no text LLM provider configured")
            return None
        provider, model = resolved
        context = str(assistant_text or "").strip()[:400]
        user_prompt = f"Learner utterance:\n{text}"
        if context:
            user_prompt = f"Tutor's previous reply (context only, do not review):\n{context}\n\n{user_prompt}"
        result = await self.llm_service.chat_completion(
            provider=provider,
            model=model,
            messages=[
                {"role": "system", "content": build_coach_instructions(config)},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=600,
            use_memory=False,
        )
        review = parse_coach_reply(str(result.get("reply", "")), text)
        if review is None:
            logger.info("speaking_coach unparsable reply provider=%s model=%s", provider, model)
            return None
        # Shown on the card so it's clear a separate text model wrote the review.
        review["reviewer"] = model
        return review
