from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .realtime_constants import (
    DASHSCOPE_AUDIO_REALTIME_PATTERN,
    DASHSCOPE_OMNI_REALTIME_PATTERN,
)
from .voice_agent_tools import VoiceToolRequest


@dataclass(frozen=True)
class RealtimeToolCall:
    provider: str
    provider_call_id: str
    tool_name: str
    arguments: dict[str, Any]


_TOOL_DECLARATIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "search_web",
        "description": "Search current public web information about news, facts, products, or events. Only invoke when the user explicitly asks you to search the web or needs real-time external information that you cannot answer directly. Do NOT use for translating words or phrases, defining terms, answering general knowledge questions, or recalling personal memory / past conversations.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "A concise standalone search query."}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "recall_memory",
        "description": "Recall and retrieve long-term memories, user personal preferences, past conversations, or historical topics from the user's private EverMem / EverOS memory center. Always call this tool when the user asks what was previously discussed, asks you to recall or remember past conversations, or asks about their saved profile or preferences. Never use search_web to look up user-specific past conversations or personal memories.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keywords or topic to look up in the user's long-term memory.",
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "render_canvas",
        "description": (
            "Render, draw, sketch, or update an interactive UI component, canvas diagram, or HTML/React visual mockup directly on the user's screen in real time. Call this tool whenever the user asks to create, draw, sketch, build, preview, or update a UI, component, form, dashboard, game, card, or visual design on the canvas."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Complete, self-contained React functional component (exported as default or App) or complete HTML with embedded CSS/Tailwind classes to render in the user's visual canvas side panel.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["react", "html"],
                    "description": "The render framework mode: 'react' for a React component or 'html' for pure HTML/CSS/Tailwind.",
                },
                "title": {
                    "type": "string",
                    "description": "Short title or label describing what was rendered.",
                },
            },
            "required": ["code"],
            "additionalProperties": False,
        },
    },
)


def native_tool_declarations() -> list[dict[str, Any]]:
    """Return detached declaration dictionaries safe for provider serialization."""
    return json.loads(json.dumps(_TOOL_DECLARATIONS, ensure_ascii=False))


def dashscope_tool_declarations() -> list[dict[str, Any]]:
    return [
        {"type": "function", "function": declaration}
        for declaration in native_tool_declarations()
    ]


def vercel_tool_declarations() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": declaration["name"],
            "description": declaration["description"],
            "parameters": declaration["parameters"],
        }
        for declaration in native_tool_declarations()
    ]


def dashscope_supports_native_tools(model: str | None) -> bool:
    """True for DashScope realtime models that accept Function Calling.

    Both family patterns are shared with realtime_constants.py (the omni and
    Qwen-Audio detectors) so the picker and the runtime cannot drift apart: every
    omni generation we support (3.5, 3.8) and every Qwen-Audio generation
    (3.0, 3.1) is accepted here.
    """
    normalized = str(model or "").strip().lower()
    return bool(
        re.fullmatch(
            rf"(?:{DASHSCOPE_OMNI_REALTIME_PATTERN}|{DASHSCOPE_AUDIO_REALTIME_PATTERN})",
            normalized,
        )
    )


def parse_tool_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return dict(arguments)
    if isinstance(arguments, str):
        try:
            decoded = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise ValueError("Tool arguments are not valid JSON.") from exc
        if isinstance(decoded, dict):
            return decoded
    raise ValueError("Tool arguments must be a JSON object.")


def tool_call_to_request(call: RealtimeToolCall) -> VoiceToolRequest:
    call_id = str(call.provider_call_id or "").strip()
    if not call_id:
        raise ValueError("Native tool call is missing provider_call_id.")
    arguments = parse_tool_arguments(call.arguments)
    name = str(call.tool_name or "").strip()

    if name == "search_web":
        return VoiceToolRequest(name, _required_text(arguments, "query", max_length=240), "搜索网页资料")
    if name == "recall_memory":
        return VoiceToolRequest(name, _required_text(arguments, "query", max_length=240), "检索长期记忆")
    if name == "translate_text":
        source = _required_text(arguments, "text", max_length=4000)
        target = _required_text(arguments, "target_language", max_length=80)
        return VoiceToolRequest(name, f"{source}\n目标语言:{target}", "翻译文本")
    if name == "summarize_transcript":
        return VoiceToolRequest(name, _required_text(arguments, "text", max_length=4000), "总结转录文本")
    if name == "render_canvas":
        code = _required_text(arguments, "code", max_length=50000)
        mode = str(arguments.get("mode") or "react").strip().lower()
        if mode not in {"react", "html"}:
            mode = "react"
        title = str(arguments.get("title") or "Canvas Component").strip()[:100]
        return VoiceToolRequest(
            name,
            json.dumps({"code": code, "mode": mode, "title": title}, ensure_ascii=False),
            "渲染画布组件",
        )
    raise ValueError(f"Unsupported realtime tool: {name or '<empty>'}")


def tool_result_payload(result: dict[str, Any]) -> dict[str, Any]:
    """Keep provider responses structured and JSON-safe without prompt injection."""
    return {
        "ok": True,
        "tool_name": str(result.get("tool_name", "")),
        "query": str(result.get("query", "")),
        "answer": str(result.get("answer", "")),
        "sources": result.get("sources", []) if isinstance(result.get("sources"), list) else [],
        "artifact": result.get("artifact", {}) if isinstance(result.get("artifact"), dict) else {},
        "source_count": int(result.get("source_count", 0) or 0),
        "elapsed_ms": int(result.get("elapsed_ms", 0) or 0),
    }


def tool_error_payload(message: str) -> dict[str, Any]:
    return {"ok": False, "error": str(message or "Tool execution failed.")[:1000]}


def _required_text(arguments: dict[str, Any], name: str, *, max_length: int) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Tool argument '{name}' must be a non-empty string.")
    return value.strip()[:max_length]
