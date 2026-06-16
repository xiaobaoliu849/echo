from __future__ import annotations

import re
from typing import Any

from .llm_service import LLMService

SCRIPT_LINE_PATTERN = re.compile(r"^([AB])[：:]\s*(.+)$")


class AudioScriptWriter:
    def __init__(self, llm_service: LLMService | None = None) -> None:
        self.llm_service = llm_service or LLMService()

    @staticmethod
    def _normalize_language(value: str | None) -> str:
        text = str(value or "").strip().lower()
        if text.startswith("en"):
            return "en"
        return "zh"

    @staticmethod
    def _parse_script_from_text(text: str) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for raw in text.strip().splitlines():
            line = raw.strip()
            if not line:
                continue
            match = SCRIPT_LINE_PATTERN.match(line)
            if not match:
                continue
            role = match.group(1).strip().upper()
            content = match.group(2).strip()
            if content:
                result.append({"role": role, "text": content})
        return result

    def _parse_script_with_fallback(self, text: str) -> list[dict[str, str]]:
        parsed = self._parse_script_from_text(text)
        if len(parsed) >= 2:
            return parsed

        candidates = [line.strip() for line in text.splitlines() if line.strip()]
        fallback: list[dict[str, str]] = []
        for idx, line in enumerate(candidates):
            role = "A" if idx % 2 == 0 else "B"
            fallback.append({"role": role, "text": line})
        return fallback

    @staticmethod
    def _normalize_script_lines(script_lines: list[dict[str, Any]]) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for item in script_lines:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "A")).strip().upper()[:1] or "A"
            if role not in {"A", "B"}:
                role = "A"
            text = str(item.get("text", item.get("content", ""))).strip()
            if not text:
                continue
            normalized.append({"role": role, "text": text})
        return normalized

    @staticmethod
    def _build_evidence_summary(sources: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for idx, source in enumerate(sources[:6], start=1):
            title = str(source.get("title", "")).strip()
            uri = str(source.get("uri", "")).strip()
            snippet = str(source.get("snippet", "")).strip()
            content = str(source.get("content", "")).strip()
            body = snippet or content
            if not body:
                body = f"参考来源：{uri}" if uri else ""
            if not body:
                continue
            prefix = f"{idx}. {title}: " if title else f"{idx}. "
            if uri:
                prefix = f"{prefix}[{uri}] "
            lines.append(f"{prefix}{body[:480]}")
        return "\n".join(lines)

    @staticmethod
    def _build_research_brief(sources: list[dict[str, Any]]) -> str:
        if not sources:
            return ""

        source_type_counts: dict[str, int] = {}
        key_points: list[str] = []
        citations: list[str] = []
        for source in sources[:8]:
            source_type = str(source.get("source_type", "unknown")).strip() or "unknown"
            source_type_counts[source_type] = source_type_counts.get(source_type, 0) + 1
            title = str(source.get("title", "")).strip()
            uri = str(source.get("uri", "")).strip()
            snippet = str(source.get("snippet", "")).strip()
            content = str(source.get("content", "")).strip()
            point = snippet or content[:280]
            if point:
                key_points.append(f"- {title or source_type}: {point[:360]}")
            if uri:
                citations.append(f"- {title or uri}: {uri}")

        type_summary = ", ".join(
            f"{name}={count}" for name, count in sorted(source_type_counts.items())
        )
        sections = [f"Source mix: {type_summary}"]
        if key_points:
            sections.append("Key evidence:\n" + "\n".join(key_points[:8]))
        if citations:
            sections.append("Citations:\n" + "\n".join(citations[:8]))
        return "\n\n".join(sections)

    @staticmethod
    def _build_system_prompt(language: str, has_evidence: bool) -> str:
        if language == "en":
            base = (
                "You are an audio script writer for a two-speaker podcast. "
                "Return only dialogue lines in the format 'A: ...' and 'B: ...'. "
                "Write naturally for spoken audio."
            )
            if has_evidence:
                return (
                    base
                    + " Use the supplied evidence when it helps. Do not invent unsupported specifics."
                )
            return base + " Keep claims general and avoid unsupported specifics."

        base = (
            "你是一个双人播客脚本写手。"
            "只输出对话台词，每行严格使用 'A: ...' 或 'B: ...' 的格式。"
            "语气自然、适合口播。"
        )
        if has_evidence:
            return base + " 优先利用提供的资料，不要编造没有依据的细节。"
        return base + " 在资料不足时保持概括表达，不要编造事实。"

    @staticmethod
    def _build_user_prompt(
        *,
        topic: str,
        language: str,
        turn_count: int,
        evidence_summary: str,
        generation_constraints: str,
    ) -> str:
        if language == "en":
            prompt = (
                f"Topic: {topic}\n\n"
                f"Please write a two-speaker podcast dialogue with {turn_count} rounds.\n"
                "A is the host and B is the guest expert.\n"
                "Include a natural opening and closing.\n"
                "Each line should be concise and easy to read aloud.\n"
            )
            if evidence_summary:
                prompt += f"\nEvidence:\n{evidence_summary}\n"
            if generation_constraints:
                prompt += f"\nAdditional constraints:\n{generation_constraints[:1800]}\n"
            return prompt

        prompt = (
            f"主题：{topic}\n\n"
            f"请写一段双人播客对话，共 {turn_count} 轮。\n"
            "A 是主持人，B 是嘉宾专家。\n"
            "包含自然开场和收尾。\n"
            "每句适合口播，不要太书面化。\n"
        )
        if evidence_summary:
            prompt += f"\n可参考资料：\n{evidence_summary}\n"
        if generation_constraints:
            prompt += f"\n额外约束：\n{generation_constraints[:1800]}\n"
        return prompt

    async def generate_script(
        self,
        *,
        topic: str,
        language: str,
        turn_count: int,
        provider: str,
        model: str | None,
        sources: list[dict[str, Any]],
        generation_constraints: str = "",
    ) -> dict[str, Any]:
        clean_language = self._normalize_language(language)
        evidence_summary = self._build_evidence_summary(sources)
        research_brief = self._build_research_brief(sources)
        prompt_evidence = "\n\n".join(
            item for item in [research_brief, evidence_summary] if item
        )
        completion = await self.llm_service.chat_completion(
            provider=provider,
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": self._build_system_prompt(
                        clean_language,
                        has_evidence=bool(evidence_summary),
                    ),
                },
                {
                    "role": "user",
                    "content": self._build_user_prompt(
                        topic=topic,
                        language=clean_language,
                        turn_count=max(2, min(int(turn_count), 40)),
                        evidence_summary=prompt_evidence,
                        generation_constraints=str(generation_constraints or "").strip(),
                    ),
                },
            ],
            temperature=0.7,
            max_tokens=max(1200, max(2, min(int(turn_count), 40)) * 220),
        )
        reply = str(completion.get("reply", "")).strip()
        parsed = self._parse_script_with_fallback(reply)
        normalized = self._normalize_script_lines(parsed)
        if len(normalized) < 2:
            raise RuntimeError("Generated script is too short or cannot be parsed.")
        return {
            "provider": str(completion.get("provider", provider)),
            "model": str(completion.get("model", model or "")),
            "reply": reply,
            "script_lines": normalized,
            "evidence_summary": evidence_summary,
            "research_brief": research_brief,
        }
