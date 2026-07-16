from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .audio_agent_service import AudioAgentService
from .audio_research_service import AudioResearchService
from .llm_service import LLMService
from .tts_service import TTSService


SendEvent = Callable[[str, Any], Awaitable[None]]
ToolResultHandler = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class VoiceToolRequest:
    tool_name: str
    query: str
    display_name: str
    requires_confirmation: bool = False


class VoiceAgentToolService:
    _SEARCH_INTENT_PATTERNS = (
        r"帮我查",
        r"查一下",
        r"查找",
        r"查询",
        r"搜索",
        r"检索",
        r"搜一下",
        r"找一下",
        r"look up",
        r"search",
        r"find information",
    )
    _LEADING_COMMAND_PATTERN = re.compile(
        r"^(请|麻烦你|帮我|你帮我)?\s*(查一下|查找|查询|搜索|检索|搜一下|找一下|look up|search)\s*",
        flags=re.IGNORECASE,
    )
    _AUDIO_AGENT_PATTERNS = (
        r"做.*播客",
        r"生成.*播客",
        r"创建.*播客",
        r"写.*播客",
        r"做.*音频",
        r"生成.*音频",
        r"创建.*音频",
        r"音频.*草稿",
        r"播客.*草稿",
        r"podcast",
    )
    _AUDIO_AGENT_COMMAND_PATTERN = re.compile(
        r"^(请|麻烦你|帮我|你帮我)?\s*(做|生成|创建|写|制作)\s*(一期|一个|一段)?\s*(播客|音频|podcast)?\s*",
        flags=re.IGNORECASE,
    )
    _TRANSLATE_PATTERNS = (
        r"翻译",
        r"译成",
        r"翻成",
        r"translate",
    )
    _SUMMARIZE_PATTERNS = (
        r"总结",
        r"摘要",
        r"归纳",
        r"概括",
        r"summarize",
        r"summary",
    )
    _TTS_TRANSFORM_COMMAND = re.compile(
        r"^(?:(?:请|麻烦你)\s*)?(?:(?:你)?帮我\s*)?(?:把|将)\s*(?P<content>.+?)\s*"
        r"(?:生成语音|合成语音|转成语音)\s*[。！？!?]?$",
        flags=re.IGNORECASE,
    )
    _TTS_SPEAK_COMMAND = re.compile(
        r"^(?:(?:请|麻烦你)\s*)?(?:(?:你)?帮我\s*)?(?:朗读|配音|念一下)\s*"
        r"(?P<content>.+?)\s*[。！？!?]?$",
        flags=re.IGNORECASE,
    )
    _TARGET_LANGUAGE_PATTERN = re.compile(
        r"(?:翻译|译|翻)?(?:成|为|到|into|to)\s*(中文|英文|英语|日文|日语|韩文|韩语|法文|法语|德文|德语|西班牙语|Spanish|English|Chinese|Japanese|Korean|French|German)",
        flags=re.IGNORECASE,
    )

    def __init__(
        self,
        research_service: AudioResearchService | None = None,
        audio_agent_service: AudioAgentService | None = None,
        llm_service: LLMService | None = None,
        tts_service: TTSService | None = None,
    ) -> None:
        self.research_service = research_service or AudioResearchService()
        self.audio_agent_service = audio_agent_service or AudioAgentService()
        self.llm_service = llm_service or LLMService()
        self.tts_service = tts_service or TTSService()

    @classmethod
    def extract_search_query(cls, text: str) -> str:
        candidate = re.sub(r"\s+", " ", str(text or "")).strip()
        if not candidate:
            return ""
        if not any(re.search(pattern, candidate, flags=re.IGNORECASE) for pattern in cls._SEARCH_INTENT_PATTERNS):
            return ""
        query = cls._LEADING_COMMAND_PATTERN.sub("", candidate).strip()
        query = re.sub(r"^(一下|下|关于|有关)\s*", "", query).strip()
        query = re.sub(r"(并|然后)?\s*(总结|整理|回答|告诉我).*$", "", query).strip()
        query = re.sub(r"[,，。；;：:\s]+$", "", query).strip()
        return query[:240] or candidate[:240]

    @classmethod
    def extract_audio_agent_topic(cls, text: str) -> str:
        candidate = re.sub(r"\s+", " ", str(text or "")).strip()
        if not candidate:
            return ""
        if not any(re.search(pattern, candidate, flags=re.IGNORECASE) for pattern in cls._AUDIO_AGENT_PATTERNS):
            return ""
        topic = cls._AUDIO_AGENT_COMMAND_PATTERN.sub("", candidate).strip()
        topic = re.sub(r"^(关于|有关|主题是|主题为)\s*", "", topic).strip()
        topic = re.sub(r"(并|然后)?\s*(生成草稿|创建草稿|先建个任务|保存下来).*$", "", topic).strip()
        topic = re.sub(r"[,，。；;：:\s]+$", "", topic).strip()
        return topic[:240] or candidate[:240]

    @classmethod
    def extract_tool_request(cls, text: str) -> VoiceToolRequest | None:
        tts_request = cls.extract_tts_request(text)
        if tts_request:
            return tts_request
        summary_request = cls.extract_summary_request(text)
        if summary_request:
            return summary_request
        translate_request = cls.extract_translate_request(text)
        if translate_request:
            return translate_request
        audio_topic = cls.extract_audio_agent_topic(text)
        if audio_topic:
            return VoiceToolRequest(
                tool_name="create_audio_agent_run",
                query=audio_topic,
                display_name="创建音频 Agent 草稿任务",
                requires_confirmation=True,
            )
        search_query = cls.extract_search_query(text)
        if search_query:
            return VoiceToolRequest(
                tool_name="search_web",
                query=search_query,
                display_name="搜索网页资料",
            )
        return None

    @classmethod
    def extract_tts_request(cls, text: str) -> VoiceToolRequest | None:
        candidate = re.sub(r"\s+", " ", str(text or "")).strip()
        if not candidate:
            return None
        command_match = cls._TTS_TRANSFORM_COMMAND.fullmatch(candidate)
        if command_match is None:
            command_match = cls._TTS_SPEAK_COMMAND.fullmatch(candidate)
        if command_match is None:
            return None
        content = str(command_match.group("content") or "").strip()
        content = re.sub(r"^(这句|这段|下面这句|下面这段|文本|内容)\s*", "", content).strip()
        content = re.sub(r"^[,，。；;：:\s]+", "", content).strip()
        content = re.sub(r"[,，。；;：:\s]+$", "", content).strip()
        if len(content) < 2:
            return None
        return VoiceToolRequest(
            tool_name="synthesize_tts",
            query=content[:3000],
            display_name="生成语音文件",
            requires_confirmation=True,
        )

    @classmethod
    def extract_summary_request(cls, text: str) -> VoiceToolRequest | None:
        candidate = re.sub(r"\s+", " ", str(text or "")).strip()
        if not candidate:
            return None
        if not any(re.search(pattern, candidate, flags=re.IGNORECASE) for pattern in cls._SUMMARIZE_PATTERNS):
            return None
        content = re.sub(
            r"^(请|麻烦你|帮我|你帮我)?\s*(总结|摘要|归纳|概括|summarize|summary)\s*",
            "",
            candidate,
            flags=re.IGNORECASE,
        ).strip()
        content = re.sub(r"^(一下|这段|这份|下面这段|下面这份|转录|转写|transcript|文本|内容)\s*", "", content, flags=re.IGNORECASE).strip()
        content = re.sub(r"^[,，。；;：:\s]+", "", content).strip()
        content = re.sub(r"[,，。；;：:\s]+$", "", content).strip()
        if len(content) < 12:
            return None
        return VoiceToolRequest(
            tool_name="summarize_transcript",
            query=content[:4000],
            display_name="总结转录文本",
        )

    @classmethod
    def extract_translate_request(cls, text: str) -> VoiceToolRequest | None:
        candidate = re.sub(r"\s+", " ", str(text or "")).strip()
        if not candidate:
            return None
        if not any(re.search(pattern, candidate, flags=re.IGNORECASE) for pattern in cls._TRANSLATE_PATTERNS):
            return None

        source_text = candidate
        source_text = re.sub(r"^(请|麻烦你|帮我|你帮我)?\s*(把|将)?\s*", "", source_text, flags=re.IGNORECASE).strip()
        source_text = re.sub(r"^(翻译|translate)\s*", "", source_text, flags=re.IGNORECASE).strip()
        target_match = cls._TARGET_LANGUAGE_PATTERN.search(source_text)
        target_language = target_match.group(1).strip() if target_match else "英文"
        if target_match:
            source_text = f"{source_text[:target_match.start()]}{source_text[target_match.end():]}".strip()
        source_text = re.sub(r"^(这句|这段|下面这句|下面这段|文本|内容)\s*", "", source_text).strip()
        source_text = re.sub(r"[,，。；;：:\s]+$", "", source_text).strip()
        if not source_text or source_text == candidate:
            return None
        query = f"{source_text}\n目标语言: {target_language}"
        return VoiceToolRequest(
            tool_name="translate_text",
            query=query[:500],
            display_name="翻译文本",
        )

    async def run_tool(
        self,
        request: VoiceToolRequest,
        *,
        send_event: SendEvent,
        turn_id: str = "",
    ) -> dict[str, Any]:
        if request.tool_name == "create_audio_agent_run":
            return await self.run_create_audio_agent_run(
                request.query,
                send_event=send_event,
                turn_id=turn_id,
            )
        if request.tool_name == "translate_text":
            source_text, target_language = self._split_translate_query(request.query)
            return await self.run_translate_text(
                source_text,
                target_language=target_language,
                send_event=send_event,
                turn_id=turn_id,
            )
        if request.tool_name == "summarize_transcript":
            return await self.run_summarize_transcript(
                request.query,
                send_event=send_event,
                turn_id=turn_id,
            )
        if request.tool_name == "synthesize_tts":
            return await self.run_synthesize_tts(
                request.query,
                send_event=send_event,
                turn_id=turn_id,
            )
        if request.tool_name == "search_web":
            return await self.run_search(request.query, send_event=send_event, turn_id=turn_id)
        raise ValueError(f"Unsupported voice agent tool: {request.tool_name}")

    @staticmethod
    def _split_translate_query(query: str) -> tuple[str, str]:
        text = str(query or "").strip()
        marker = "\n目标语言:"
        if marker not in text:
            return text, "英文"
        source_text, target_language = text.split(marker, 1)
        return source_text.strip(), target_language.strip() or "英文"

    async def run_search(
        self,
        query: str,
        *,
        send_event: SendEvent,
        turn_id: str = "",
    ) -> dict[str, Any]:
        clean_query = str(query or "").strip()
        if not clean_query:
            raise ValueError("Search query is empty.")

        started_at = time.perf_counter()
        await send_event(
            "tool_call_started",
            {
                "tool_name": "search_web",
                "query": clean_query,
                "turn_id": turn_id,
                "message": "正在搜索相关资料...",
            },
        )
        search_results = await self.research_service.search(clean_query, limit=3)
        await send_event(
            "agent_progress",
            {
                "stage": "search_web",
                "message": f"找到 {len(search_results)} 条候选结果，正在读取来源...",
                "turn_id": turn_id,
                "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
            },
        )

        documents = await asyncio.gather(
            *[
                self.research_service.fetch_document(
                    item.get("url", ""),
                    title_hint=item.get("title", ""),
                    snippet_hint=item.get("snippet", ""),
                    source_type="web_search",
                    score=0.7,
                )
                for item in search_results[:3]
            ],
            return_exceptions=True,
        )

        sources: list[dict[str, Any]] = []
        for item in documents:
            if isinstance(item, Exception):
                continue
            source = item.to_source()
            if not str(source.get("snippet") or source.get("content") or "").strip():
                continue
            sources.append(
                {
                    "title": str(source.get("title", ""))[:240],
                    "uri": str(source.get("uri", ""))[:1000],
                    "snippet": str(source.get("snippet") or source.get("content") or "")[:500],
                    "source_type": str(source.get("source_type", "web_search")),
                    "score": float(source.get("score", 0.0) or 0.0),
                }
            )

        answer = self._build_grounded_answer(clean_query, sources)
        await send_event(
            "tool_call_completed",
            {
                "tool_name": "search_web",
                "query": clean_query,
                "turn_id": turn_id,
                "source_count": len(sources),
                "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
            },
        )
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        await send_event(
            "agent_result",
            {
                "query": clean_query,
                "turn_id": turn_id,
                "answer": answer,
                "sources": sources,
                "source_count": len(sources),
                "elapsed_ms": elapsed_ms,
            },
        )
        return {
            "tool_name": "search_web",
            "query": clean_query,
            "turn_id": turn_id,
            "answer": answer,
            "sources": sources,
            "source_count": len(sources),
            "elapsed_ms": elapsed_ms,
        }

    async def run_create_audio_agent_run(
        self,
        topic: str,
        *,
        send_event: SendEvent,
        turn_id: str = "",
    ) -> dict[str, Any]:
        clean_topic = str(topic or "").strip()
        if not clean_topic:
            raise ValueError("Audio agent topic is empty.")

        started_at = time.perf_counter()
        await send_event(
            "tool_call_started",
            {
                "tool_name": "create_audio_agent_run",
                "query": clean_topic,
                "turn_id": turn_id,
                "message": "正在创建音频 Agent 草稿任务...",
            },
        )
        run = self.audio_agent_service.create_run(
            topic=clean_topic,
            language="zh",
            provider="DashScope",
            use_memory=True,
            auto_execute=False,
        )
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        run_id = int(run.get("id", 0) or 0)
        status = str(run.get("status", "queued"))
        answer = f"已创建音频 Agent 草稿任务，运行 ID 是 {run_id}，状态为 {status}。你可以到播客工作台继续执行生成草稿。"
        await send_event(
            "tool_call_completed",
            {
                "tool_name": "create_audio_agent_run",
                "query": clean_topic,
                "turn_id": turn_id,
                "source_count": 0,
                "elapsed_ms": elapsed_ms,
            },
        )
        await send_event(
            "agent_result",
            {
                "tool_name": "create_audio_agent_run",
                "query": clean_topic,
                "turn_id": turn_id,
                "answer": answer,
                "sources": [],
                "source_count": 0,
                "elapsed_ms": elapsed_ms,
                "artifact": {
                    "type": "audio_agent_run",
                    "run_id": run_id,
                    "status": status,
                    "topic": clean_topic,
                    "current_step": str(run.get("current_step", "")),
                    "provider": str(run.get("provider", "")),
                    "model": str(run.get("model", "")),
                },
            },
        )
        return {
            "tool_name": "create_audio_agent_run",
            "query": clean_topic,
            "turn_id": turn_id,
            "answer": answer,
            "sources": [],
            "source_count": 0,
            "elapsed_ms": elapsed_ms,
            "artifact": {
                "type": "audio_agent_run",
                "run_id": run_id,
                "status": status,
                "topic": clean_topic,
                "current_step": str(run.get("current_step", "")),
                "provider": str(run.get("provider", "")),
                "model": str(run.get("model", "")),
            },
        }

    async def run_translate_text(
        self,
        text: str,
        *,
        target_language: str,
        send_event: SendEvent,
        turn_id: str = "",
    ) -> dict[str, Any]:
        clean_text = str(text or "").strip()
        clean_target = str(target_language or "英文").strip() or "英文"
        if not clean_text:
            raise ValueError("Translation text is empty.")

        started_at = time.perf_counter()
        await send_event(
            "tool_call_started",
            {
                "tool_name": "translate_text",
                "query": clean_text[:240],
                "turn_id": turn_id,
                "message": f"正在翻译成{clean_target}...",
            },
        )
        translated = await self.llm_service.translate_text(
            text=clean_text,
            source_language="auto",
            target_language=clean_target,
            provider="DashScope",
            model=None,
        )
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        translated_text = str(translated.get("translated_text", "")).strip()
        provider = str(translated.get("provider", "DashScope"))
        model = str(translated.get("model", ""))
        answer = f"翻译完成：{translated_text}"
        await send_event(
            "tool_call_completed",
            {
                "tool_name": "translate_text",
                "query": clean_text[:240],
                "turn_id": turn_id,
                "source_count": 0,
                "elapsed_ms": elapsed_ms,
            },
        )
        await send_event(
            "agent_result",
            {
                "tool_name": "translate_text",
                "query": clean_text[:240],
                "turn_id": turn_id,
                "answer": answer,
                "sources": [],
                "source_count": 0,
                "elapsed_ms": elapsed_ms,
                "artifact": {
                    "type": "translation",
                    "source_text": clean_text,
                    "target_language": clean_target,
                    "translated_text": translated_text,
                    "provider": provider,
                    "model": model,
                },
            },
        )
        return {
            "tool_name": "translate_text",
            "query": clean_text[:240],
            "turn_id": turn_id,
            "answer": answer,
            "sources": [],
            "source_count": 0,
            "elapsed_ms": elapsed_ms,
            "artifact": {
                "type": "translation",
                "source_text": clean_text,
                "target_language": clean_target,
                "translated_text": translated_text,
                "provider": provider,
                "model": model,
            },
        }

    async def run_summarize_transcript(
        self,
        transcript_text: str,
        *,
        send_event: SendEvent,
        turn_id: str = "",
    ) -> dict[str, Any]:
        clean_text = str(transcript_text or "").strip()
        if not clean_text:
            raise ValueError("Transcript text is empty.")

        started_at = time.perf_counter()
        await send_event(
            "tool_call_started",
            {
                "tool_name": "summarize_transcript",
                "query": clean_text[:240],
                "turn_id": turn_id,
                "message": "正在总结转录文本...",
            },
        )
        result = await self.llm_service.chat_completion(
            provider="DashScope",
            model=None,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You summarize transcripts for a voice productivity app. "
                        "Return a concise Chinese summary with 3-5 bullet points and no extra preface."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Transcript:\n{clean_text[:6000]}",
                },
            ],
            temperature=0.2,
            max_tokens=800,
            use_memory=False,
        )
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        summary = str(result.get("reply", "")).strip()
        provider = str(result.get("provider", "DashScope"))
        model = str(result.get("model", ""))
        answer = f"总结完成：\n{summary}"
        await send_event(
            "tool_call_completed",
            {
                "tool_name": "summarize_transcript",
                "query": clean_text[:240],
                "turn_id": turn_id,
                "source_count": 0,
                "elapsed_ms": elapsed_ms,
            },
        )
        await send_event(
            "agent_result",
            {
                "tool_name": "summarize_transcript",
                "query": clean_text[:240],
                "turn_id": turn_id,
                "answer": answer,
                "sources": [],
                "source_count": 0,
                "elapsed_ms": elapsed_ms,
                "artifact": {
                    "type": "transcript_summary",
                    "transcript_excerpt": clean_text[:500],
                    "summary": summary,
                    "provider": provider,
                    "model": model,
                },
            },
        )
        return {
            "tool_name": "summarize_transcript",
            "query": clean_text[:240],
            "turn_id": turn_id,
            "answer": answer,
            "sources": [],
            "source_count": 0,
            "elapsed_ms": elapsed_ms,
            "artifact": {
                "type": "transcript_summary",
                "transcript_excerpt": clean_text[:500],
                "summary": summary,
                "provider": provider,
                "model": model,
            },
        }

    async def run_synthesize_tts(
        self,
        text: str,
        *,
        send_event: SendEvent,
        turn_id: str = "",
    ) -> dict[str, Any]:
        clean_text = str(text or "").strip()
        if not clean_text:
            raise ValueError("TTS text is empty.")

        started_at = time.perf_counter()
        await send_event(
            "tool_call_started",
            {
                "tool_name": "synthesize_tts",
                "query": clean_text[:240],
                "turn_id": turn_id,
                "message": "正在生成语音文件...",
            },
        )
        audio_path, used_voice, cache_hit = await self.tts_service.generate_audio(
            text=clean_text,
            voice=None,
            rate="+0%",
            engine="edge",
        )
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        answer = f"语音文件已生成，音色是 {used_voice}。"
        await send_event(
            "tool_call_completed",
            {
                "tool_name": "synthesize_tts",
                "query": clean_text[:240],
                "turn_id": turn_id,
                "source_count": 0,
                "elapsed_ms": elapsed_ms,
            },
        )
        await send_event(
            "agent_result",
            {
                "tool_name": "synthesize_tts",
                "query": clean_text[:240],
                "turn_id": turn_id,
                "answer": answer,
                "sources": [],
                "source_count": 0,
                "elapsed_ms": elapsed_ms,
                "artifact": {
                    "type": "tts_audio",
                    "text": clean_text,
                    "audio_path": str(audio_path),
                    "voice": used_voice,
                    "engine": "edge",
                    "rate": "+0%",
                    "cache_hit": bool(cache_hit),
                },
            },
        )
        return {
            "tool_name": "synthesize_tts",
            "query": clean_text[:240],
            "turn_id": turn_id,
            "answer": answer,
            "sources": [],
            "source_count": 0,
            "elapsed_ms": elapsed_ms,
            "artifact": {
                "type": "tts_audio",
                "text": clean_text,
                "audio_path": str(audio_path),
                "voice": used_voice,
                "engine": "edge",
                "rate": "+0%",
                "cache_hit": bool(cache_hit),
            },
        }

    @staticmethod
    def build_tools_schema() -> list[dict[str, Any]]:
        """Build OpenAI-compatible tools schema for native function calling.

        Returns a list of tool definitions that can be sent in
        ``session.update`` to Qwen-Audio (or any OpenAI Realtime API
        compatible model).  The backend regex-based extraction
        (``extract_tool_request``) remains active as a fallback.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_web",
                    "description": (
                        "搜索互联网获取实时信息。当用户询问需要最新数据、事实核查、"
                        "新闻、或当前事件相关问题时调用此工具。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "用户想要搜索的关键词或问题，用用户当前使用的语言",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "translate_text",
                    "description": (
                        "将文本翻译成其他语言。当用户明确要求翻译某段内容时调用此工具。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "需要翻译的原文内容",
                            },
                            "target_language": {
                                "type": "string",
                                "description": "目标语言，如：英文、中文、日文、法文、德文、韩文等",
                            },
                        },
                        "required": ["text", "target_language"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "summarize_transcript",
                    "description": (
                        "对一段文本进行摘要总结。当用户要求总结、归纳、概括某段内容时调用此工具。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "需要被总结的文本内容",
                            },
                        },
                        "required": ["content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "synthesize_tts",
                    "description": (
                        "将文字内容生成语音音频文件。当用户要求朗读、配音、"
                        "或把文字转成语音时调用此工具。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "需要转换成语音的文字内容",
                            },
                        },
                        "required": ["content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "create_audio_agent_run",
                    "description": (
                        "创建一个播客/音频草稿任务。当用户要求做播客、生成播客、"
                        "创建音频节目或类似需求时调用此工具。调用后需要等待用户确认。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "topic": {
                                "type": "string",
                                "description": "播客/音频节目的主题",
                            },
                        },
                        "required": ["topic"],
                    },
                },
            },
        ]

    @staticmethod
    def build_model_context_prompt(result: dict[str, Any]) -> str:
        tool_name = str(result.get("tool_name", "")).strip()
        query = str(result.get("query", "")).strip()
        answer = str(result.get("answer", "")).strip()
        if tool_name == "create_audio_agent_run":
            artifact = result.get("artifact", {})
            run_id = ""
            status = ""
            if isinstance(artifact, dict):
                run_id = str(artifact.get("run_id", "")).strip()
                status = str(artifact.get("status", "")).strip()
            return (
                "An application action has completed inside VoiceSpirit. Continue the live voice conversation "
                "naturally and tell the user what was created and what they can do next. Keep it brief.\n\n"
                f"Action: create_audio_agent_run\nTopic: {query}\nRun ID: {run_id}\nStatus: {status}\n\n"
                f"Tool summary:\n{answer}"
            )
        if tool_name == "translate_text":
            artifact = result.get("artifact", {})
            translated_text = ""
            target_language = ""
            if isinstance(artifact, dict):
                translated_text = str(artifact.get("translated_text", "")).strip()
                target_language = str(artifact.get("target_language", "")).strip()
            return (
                "A translation action has completed inside VoiceSpirit. Continue the live voice conversation "
                "naturally. Read the translated text if it is short; otherwise summarize that the translation is ready.\n\n"
                f"Source text: {query}\nTarget language: {target_language}\nTranslated text: {translated_text}\n\n"
                f"Tool summary:\n{answer}"
            )
        if tool_name == "summarize_transcript":
            artifact = result.get("artifact", {})
            summary = ""
            if isinstance(artifact, dict):
                summary = str(artifact.get("summary", "")).strip()
            return (
                "A transcript summarization action has completed inside VoiceSpirit. Continue the live voice "
                "conversation naturally and read the summary briefly.\n\n"
                f"Transcript excerpt: {query}\nSummary:\n{summary}\n\n"
                f"Tool summary:\n{answer}"
            )
        if tool_name == "synthesize_tts":
            artifact = result.get("artifact", {})
            audio_path = ""
            voice = ""
            if isinstance(artifact, dict):
                audio_path = str(artifact.get("audio_path", "")).strip()
                voice = str(artifact.get("voice", "")).strip()
            return (
                "A TTS generation action has completed inside VoiceSpirit. Continue the live voice conversation "
                "naturally and tell the user the audio file is ready. Do not attempt to play the generated file "
                "through the realtime model; the application will expose it as an artifact.\n\n"
                f"Text: {query}\nAudio path: {audio_path}\nVoice: {voice}\n\n"
                f"Tool summary:\n{answer}"
            )
        sources = result.get("sources", [])
        source_lines: list[str] = []
        if isinstance(sources, list):
            for idx, source in enumerate(sources[:3], start=1):
                if not isinstance(source, dict):
                    continue
                title = str(source.get("title", "")).strip() or f"Source {idx}"
                uri = str(source.get("uri", "")).strip()
                snippet = re.sub(r"\s+", " ", str(source.get("snippet", "")).strip())[:500]
                source_lines.append(f"{idx}. {title}\nURL: {uri}\nSnippet: {snippet}")
        source_block = "\n\n".join(source_lines) or "No usable sources were found."
        return (
            "External search tool context is ready. Continue the live voice conversation naturally, "
            "answer the user's search request from this context, and mention source titles briefly when useful. "
            "If sources are weak or missing, say that clearly. Keep the reply concise and conversational.\n\n"
            f"User search query: {query}\n\n"
            f"Tool summary:\n{answer}\n\n"
            f"Sources:\n{source_block}"
        )

    @staticmethod
    def _build_grounded_answer(query: str, sources: list[dict[str, Any]]) -> str:
        if not sources:
            return f"我尝试搜索“{query}”，但没有拿到可用来源。你可以换一个更具体的关键词再试。"

        bullets: list[str] = []
        for idx, source in enumerate(sources[:3], start=1):
            title = str(source.get("title", "")).strip() or f"来源 {idx}"
            snippet = re.sub(r"\s+", " ", str(source.get("snippet", "")).strip())
            if len(snippet) > 180:
                snippet = f"{snippet[:180]}..."
            bullets.append(f"{idx}. {title}: {snippet}")
        return "我查到这些信息，可以先按来源做一个简要整合：\n" + "\n".join(bullets)


class VoiceAgentToolSession:
    def __init__(self, service: VoiceAgentToolService | None = None) -> None:
        self.service = service or VoiceAgentToolService()
        self._current_task: asyncio.Task[None] | None = None
        self._cancel_reason = "cancelled"
        self._current_turn_id = ""
        self._current_query = ""
        self._current_started_at = 0.0
        self._turn_index = 0

    @property
    def has_active_task(self) -> bool:
        return self._current_task is not None and not self._current_task.done()

    @property
    def current_turn_id(self) -> str:
        return self._current_turn_id

    def _next_turn_id(self) -> str:
        self._turn_index += 1
        return f"voice-tool-{self._turn_index}"

    async def handle_user_transcript(
        self,
        text: str,
        *,
        send_event: SendEvent,
        on_result: ToolResultHandler | None = None,
    ) -> str:
        request = self.service.extract_tool_request(text)
        if request is None:
            return ""
        await self.cancel(send_event=send_event, reason="superseded")
        turn_id = self._next_turn_id()
        self._current_turn_id = turn_id
        self._current_query = request.query
        self._current_started_at = time.perf_counter()

        async def runner() -> None:
            try:
                result = await self.service.run_tool(request, send_event=send_event, turn_id=turn_id)
                if on_result is not None:
                    await on_result(result)
            except asyncio.CancelledError:
                await send_event(
                    "tool_call_cancelled",
                    {
                        "tool_name": request.tool_name,
                        "query": request.query,
                        "turn_id": turn_id,
                        "reason": self._cancel_reason,
                        "elapsed_ms": int((time.perf_counter() - self._current_started_at) * 1000),
                    },
                )
                raise
            except Exception as exc:
                await send_event(
                    "tool_call_failed",
                    {
                        "tool_name": request.tool_name,
                        "query": request.query,
                        "turn_id": turn_id,
                        "message": str(exc),
                        "elapsed_ms": int((time.perf_counter() - self._current_started_at) * 1000),
                    },
                )
            finally:
                if self._current_turn_id == turn_id:
                    self._current_task = None
                    self._current_turn_id = ""
                    self._current_query = ""
                    self._current_started_at = 0.0

        self._current_task = asyncio.create_task(runner())
        return turn_id

    async def cancel(self, *, send_event: SendEvent, reason: str = "cancelled") -> None:
        task = self._current_task
        if task is None or task.done():
            self._current_task = None
            self._current_turn_id = ""
            self._current_query = ""
            self._current_started_at = 0.0
            return
        self._cancel_reason = reason
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            self._current_task = None
            self._current_turn_id = ""
            self._current_query = ""
            self._current_started_at = 0.0
            self._cancel_reason = "cancelled"

    async def drain(self) -> None:
        task = self._current_task
        if task is not None and not task.done():
            await asyncio.gather(task, return_exceptions=True)
        self._current_task = None
        self._current_turn_id = ""
        self._current_query = ""
        self._current_started_at = 0.0
