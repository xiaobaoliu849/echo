"""Speaking coach: non-blocking per-turn language feedback for realtime calls.

When a realtime voice session enables coaching (client command
``coach_config``), every finalized user turn is reviewed in the background by
a text LLM. The review never touches the live audio pipeline: the result is
pushed to the client as a ``coach_feedback`` event and persisted so the
learner can review mistakes and vocabulary after the call.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
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


def build_coach_instructions(config: dict[str, Any]) -> str:
    """System prompt for the per-turn review model."""
    level_hint = {
        "beginner": "The learner is a beginner: flag only clear errors and keep explanations very simple.",
        "intermediate": "The learner is intermediate: flag errors and the most unnatural phrasing.",
        "advanced": "The learner is advanced: also flag subtle unnaturalness and suggest more idiomatic wording.",
        "ielts": (
            "The learner is preparing for the IELTS Speaking test: also suggest higher-band vocabulary, "
            "collocations and cohesive devices where they fit naturally."
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
        "- Ignore punctuation, capitalization and obvious speech-recognition artifacts.\n"
        "- If the utterance is already correct and natural, return verdict \"good\" with no issues.\n"
        f"- At most {MAX_ISSUES} issues and {MAX_VOCABULARY} vocabulary items, most important first.\n"
        f"- LANGUAGE: every \"explanation\", \"meaning\" and \"tip\" MUST be written in {native} "
        f"(the learner's native language), never in {target}; keep each under 30 words. "
        f"Only \"corrected\", \"original\", \"suggestion\" and \"term\" are in {target}.\n"
        "Return ONLY a JSON object, no markdown:\n"
        '{"verdict": "good" | "improve" | "skip", '
        '"corrected": "the full utterance rewritten correctly and naturally (empty if good/skip)", '
        '"issues": [{"type": "grammar" | "word_choice" | "naturalness" | "fluency", '
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


def parse_coach_reply(reply: str) -> dict[str, Any] | None:
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
    for raw in data.get("issues") or []:
        if not isinstance(raw, dict):
            continue
        suggestion = str(raw.get("suggestion") or "").strip()
        if not suggestion:
            continue
        issue_type = str(raw.get("type") or "").strip().lower()
        issues.append(
            {
                "type": issue_type if issue_type in ISSUE_TYPES else "naturalness",
                "original": str(raw.get("original") or "").strip()[:200],
                "suggestion": suggestion[:200],
                "explanation": str(raw.get("explanation") or "").strip()[:240],
            }
        )
        if len(issues) >= MAX_ISSUES:
            break

    vocabulary: list[dict[str, str]] = []
    for raw in data.get("vocabulary") or []:
        if not isinstance(raw, dict):
            continue
        term = str(raw.get("term") or "").strip()
        if not term:
            continue
        vocabulary.append({"term": term[:80], "meaning": str(raw.get("meaning") or "").strip()[:160]})
        if len(vocabulary) >= MAX_VOCABULARY:
            break

    if verdict == "improve" and not issues:
        verdict = "good"
    corrected = str(data.get("corrected") or "").strip()[:MAX_REVIEW_CHARS] if verdict == "improve" else ""
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
        review = parse_coach_reply(str(result.get("reply", "")))
        if review is None:
            logger.info("speaking_coach unparsable reply provider=%s model=%s", provider, model)
        return review
