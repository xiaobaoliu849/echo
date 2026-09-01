from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncGenerator
import base64

import httpx # type: ignore

logger = logging.getLogger(__name__)

from .config_loader import BackendConfig
from .evermem_config import EverMemConfig
from .evermem_helper import prepare_memory_context, save_assistant_memory
from .background_tasks import spawn_background_task

SUPPORTED_PROVIDERS = {"DeepSeek", "OpenRouter", "SiliconFlow", "Groq", "DashScope", "Ollama", "Google"}


class LLMService:
    def __init__(self, config: BackendConfig | None = None):
        self.config = config or BackendConfig()

    @staticmethod
    def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in messages:
            role = str(item.get("role", "")).strip()
            content = item.get("content", "")
            if not role:
                continue
            if isinstance(content, str):
                cleaned = content.strip()
                if not cleaned:
                    continue
                normalized.append({"role": role, "content": cleaned})
                continue
            if isinstance(content, list):
                parts = [part for part in content if isinstance(part, dict)]
                if not parts:
                    continue
                normalized.append({"role": role, "content": parts})
        if not normalized:
            raise ValueError("messages is empty.")

        import datetime
        now = datetime.datetime.now().astimezone()
        weekdays = ["一", "二", "三", "四", "五", "六", "日"]
        # Date precision only. The previous second-level clock rewrote the
        # system prompt on every single request, which defeated upstream
        # prompt caching entirely (a fresh prefix each second). Date-level
        # awareness still answers "今天星期几" style questions correctly.
        time_tag = f"【系统当前日期】：{now.strftime('%Y-%m-%d')} (星期{weekdays[now.weekday()]})\n"

        result: list[dict[str, Any]] = []
        has_system = False

        for msg in normalized:
            if msg.get("role") == "system":
                has_system = True
                content = msg.get("content", "")
                if isinstance(content, str) and "【系统当前日期】" not in content:
                    result.append({**msg, "content": f"{time_tag}{content}"})
                else:
                    result.append(msg)
            else:
                result.append(msg)

        if not has_system:
            result.insert(0, {
                "role": "system",
                "content": f"{time_tag}你是一个智能语音与文本助手。请依据【系统当前日期】解答用户涉及日期与时间的疑问。",
            })

        return result

    @staticmethod
    def _extract_reply(data: dict[str, Any]) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first = choices[0]
        if not isinstance(first, dict):
            return ""
        message = first.get("message")
        if not isinstance(message, dict):
            return ""
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            text_parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    text_parts.append(part["text"])
            return "\n".join(text_parts).strip()
        return ""

    @staticmethod
    def _extract_delta_parts(data: dict[str, Any]) -> tuple[str, str]:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return "", ""
        first = choices[0]
        if not isinstance(first, dict):
            return "", ""

        content_str = ""
        reasoning_str = ""

        delta = first.get("delta")
        if isinstance(delta, dict):
            r_val = delta.get("reasoning_content") or delta.get("reasoning") or delta.get("thinking")
            if isinstance(r_val, str):
                reasoning_str = r_val

            c_val = delta.get("content")
            if isinstance(c_val, str):
                content_str = c_val
            elif isinstance(c_val, list):
                parts = [p.get("text", "") for p in c_val if isinstance(p, dict) and isinstance(p.get("text"), str)]
                content_str = "".join(parts)

        message = first.get("message")
        if isinstance(message, dict) and not content_str and not reasoning_str:
            r_val = message.get("reasoning_content") or message.get("reasoning") or message.get("thinking")
            if isinstance(r_val, str):
                reasoning_str = r_val

            c_val = message.get("content")
            if isinstance(c_val, str):
                content_str = c_val
            elif isinstance(c_val, list):
                parts = [p.get("text", "") for p in c_val if isinstance(p, dict) and isinstance(p.get("text"), str)]
                content_str = "".join(parts)

        return content_str, reasoning_str

    @staticmethod
    def _extract_delta(data: dict[str, Any]) -> str:
        content, _ = LLMService._extract_delta_parts(data)
        return content

    def _resolve_settings(self, provider: str, model: str | None) -> dict[str, str]:
        self.config.reload()

        # Check if custom provider
        custom_providers = self.config.get_all().get("custom_providers", [])
        is_custom = any(p.get("id") == provider for p in custom_providers if isinstance(p, dict))

        if provider not in SUPPORTED_PROVIDERS and not is_custom:
            raise ValueError(f"Unsupported provider: {provider}")

        settings = self.config.get_provider_settings(provider, model=model)
        if not settings["api_key"]:
            if provider == "Ollama":
                settings["api_key"] = "ollama"
            else:
                raise ValueError(f"Missing API key for provider: {provider}")
        if not settings["base_url"]:
            raise ValueError(f"Missing base URL for provider: {provider}")
        if not settings["model"]:
            raise ValueError(f"Missing model for provider: {provider}")
        return settings

    @staticmethod
    def _build_headers(provider: str, api_key: str) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if provider == "OpenRouter":
            headers["HTTP-Referer"] = "https://echo.local"
            headers["X-Title"] = "Echo"
        return headers

    @staticmethod
    def _build_google_headers(api_key: str) -> dict[str, str]:
        return {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _build_interactions_input(
        messages: list[dict[str, Any]],
    ) -> tuple[str | list[dict[str, Any]], str | None]:
        """Convert OpenAI-style messages to Interactions API input format.

        Returns (input, system_instruction).
        """
        system_instruction: str | None = None
        user_messages: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                if isinstance(content, str):
                    system_instruction = (system_instruction or "") + content
                continue
            if role == "user":
                if isinstance(content, str):
                    user_messages.append({"role": "user", "text": content})
                elif isinstance(content, list):
                    # Multimodal — flatten to text for now
                    text_parts = [
                        p.get("text", "") for p in content
                        if isinstance(p, dict) and p.get("type") in ("text", "image_url")
                    ]
                    user_messages.append({"role": "user", "text": " ".join(text_parts)})
            elif role == "assistant":
                if isinstance(content, str):
                    user_messages.append({"role": "model", "text": content})

        if not user_messages:
            raise ValueError("No user messages found.")

        # Single user message — use plain string input
        if len(user_messages) == 1 and user_messages[0]["role"] == "user":
            return user_messages[0]["text"], system_instruction

        # Multi-turn — build input array for stateless mode
        input_items: list[dict[str, Any]] = []
        for msg in user_messages:
            if msg["role"] == "user":
                input_items.append({
                    "type": "user_input",
                    "content": [{"type": "text", "text": msg["text"]}],
                })
            else:
                # Model turn — include as prior context
                input_items.append({
                    "type": "model_output",
                    "content": [{"type": "text", "text": msg["text"]}],
                })
        return input_items, system_instruction

    @staticmethod
    def _extract_interactions_reply(data: dict[str, Any]) -> str:
        """Extract text reply from Interactions API response."""
        # Try output_text convenience property first
        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        # Fall back to parsing steps
        reply_parts: list[str] = []
        for step in data.get("steps", []):
            if step.get("type") == "model_output":
                for content in step.get("content", []):
                    if isinstance(content, dict) and content.get("type") == "text":
                        text = content.get("text", "")
                        if text:
                            reply_parts.append(text)
        return "\n".join(reply_parts).strip()

    @staticmethod
    def _is_vertex_ai(settings: dict[str, str]) -> bool:
        base_url = settings.get("base_url", "").strip()
        return "aiplatform.googleapis.com" in base_url

    @staticmethod
    def _get_vertex_auth(api_key: str = "") -> tuple[dict[str, str], str]:
        sa_file = "gen-lang-client-0313108616-b62670b6c2cb.json"
        if os.path.exists(sa_file):
            try:
                from google.oauth2 import service_account
                from google.auth.transport.requests import Request
                creds = service_account.Credentials.from_service_account_file(
                    sa_file,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"],
                )
                creds.refresh(Request())
                if creds.token:
                    return {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}, ""
            except Exception as e:
                logger.warning("vertex_sa_oauth_failed: %s", e)
        headers = {"Content-Type": "application/json"}
        key_param = f"key={api_key}" if api_key else ""
        return headers, key_param

    @staticmethod
    def _build_vertex_payload(
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        contents: list[dict[str, Any]] = []
        system_instruction_text = ""
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                if isinstance(content, str):
                    system_instruction_text += content + "\n"
                continue
            v_role = "model" if role == "assistant" else "user"
            if isinstance(content, str):
                contents.append({"role": v_role, "parts": [{"text": content}]})
            elif isinstance(content, list):
                parts = []
                for p in content:
                    if isinstance(p, dict) and p.get("type") == "text":
                        parts.append({"text": p.get("text", "")})
                if parts:
                    contents.append({"role": v_role, "parts": parts})
        if not contents:
            contents.append({"role": "user", "parts": [{"text": "Hello"}]})
        payload: dict[str, Any] = {"contents": contents}
        if system_instruction_text.strip():
            payload["systemInstruction"] = {"parts": [{"text": system_instruction_text.strip()}]}
        if temperature is not None:
            payload["generationConfig"] = {"temperature": float(temperature)}
        return payload

    async def _chat_completion_google(
        self,
        *,
        settings: dict[str, str],
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        """Non-streaming chat completion via Google Interactions API or Vertex AI."""
        if self._is_vertex_ai(settings):
            project_id = "gen-lang-client-0313108616"
            location = "us-central1"
            model = settings.get("model", "").strip() or "gemini-2.5-flash"
            headers, key_param = self._get_vertex_auth(settings.get("api_key", ""))
            param_str = f"?{key_param}" if key_param else ""
            url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/{location}/publishers/google/models/{model}:generateContent{param_str}"
            payload = self._build_vertex_payload(messages, temperature)
            try:
                async with httpx.AsyncClient(timeout=90.0) as client:
                    response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text[:500] if exc.response is not None else str(exc)
                raise RuntimeError(f"Google Vertex AI API error: {detail}") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Network error: {exc}") from exc

            from typing import cast
            data = cast(dict[str, Any], response.json())
            candidates = data.get("candidates", [])
            reply = ""
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                reply = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
            if not reply:
                raise RuntimeError("Google Vertex AI returned empty response.")

            return {
                "provider": "Google",
                "model": model,
                "reply": reply,
                "raw": data,
            }

        url = f"{settings['base_url']}/interactions"
        input_data, system_instruction = self._build_interactions_input(messages)

        payload: dict[str, Any] = {
            "model": settings["model"],
            "input": input_data,
            "store": False,
        }
        if system_instruction:
            payload["system_instruction"] = system_instruction
        if temperature is not None:
            payload["generation_config"] = {"temperature": float(temperature)}

        headers = self._build_google_headers(settings["api_key"])

        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500] if exc.response is not None else str(exc)
            raise RuntimeError(f"Google Interactions API error: {detail}") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Network error: {exc}") from exc

        from typing import cast
        data = cast(dict[str, Any], response.json())
        reply = self._extract_interactions_reply(data)
        if not reply:
            raise RuntimeError("Google Interactions API returned empty response.")

        return {
            "provider": "Google",
            "model": settings["model"],
            "reply": reply,
            "raw": data,
        }

    async def _chat_completion_stream_google(
        self,
        *,
        settings: dict[str, str],
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Streaming chat completion via Google Interactions API or Vertex AI (SSE)."""
        if self._is_vertex_ai(settings):
            project_id = "gen-lang-client-0313108616"
            location = "us-central1"
            model = settings.get("model", "").strip() or "gemini-3.7-flash"
            headers, key_param = self._get_vertex_auth(settings.get("api_key", ""))
            param_str = f"?{key_param}&alt=sse" if key_param else "?alt=sse"
            url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/{location}/publishers/google/models/{model}:streamGenerateContent{param_str}"
            payload = self._build_vertex_payload(messages, temperature)

            yield {"type": "meta", "provider": "Google", "model": model}
            chunks: list[str] = []
            try:
                timeout = httpx.Timeout(timeout=120.0, read=120.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream("POST", url, json=payload, headers=headers) as response:
                        response.raise_for_status()
                        async for raw_line in response.aiter_lines():
                            line = raw_line.strip()
                            if line.startswith("data:"):
                                raw_data = line[5:].strip()
                                if not raw_data:
                                    continue
                                try:
                                    data = json.loads(raw_data)
                                    candidates = data.get("candidates", [])
                                    if candidates:
                                        parts = candidates[0].get("content", {}).get("parts", [])
                                        for p in parts:
                                            if isinstance(p, dict) and "text" in p:
                                                text = p["text"]
                                                if text:
                                                    chunks.append(text)
                                                    yield {"type": "delta", "content": text}
                                except Exception:
                                    continue
            except httpx.HTTPStatusError as exc:
                try:
                    await exc.response.aread()
                    detail = exc.response.text[:500]
                except Exception:
                    detail = str(exc)
                raise RuntimeError(f"Google Vertex AI stream error: {detail}") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Stream network error: {exc}") from exc

            reply = "".join(chunks).strip()
            if not reply:
                raise RuntimeError("Google Vertex AI returned empty stream response.")

            yield {
                "type": "done",
                "provider": "Google",
                "model": model,
                "reply": reply,
            }
            return
        url = f"{settings['base_url']}/interactions?alt=sse"
        input_data, system_instruction = self._build_interactions_input(messages)

        payload: dict[str, Any] = {
            "model": settings["model"],
            "input": input_data,
            "store": False,
            "stream": True,
        }
        if system_instruction:
            payload["system_instruction"] = system_instruction
        if temperature is not None:
            payload["generation_config"] = {"temperature": float(temperature)}

        headers = self._build_google_headers(settings["api_key"])

        yield {"type": "meta", "provider": "Google", "model": settings["model"]}
        chunks: list[str] = []
        saw_completed = False

        try:
            timeout = httpx.Timeout(timeout=120.0, read=120.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    response.raise_for_status()
                    event_type = ""
                    data_lines: list[str] = []
                    async for raw_line in response.aiter_lines():
                        line = raw_line.strip()
                        if not line:
                            # Empty line = end of SSE event, process buffered data
                            if data_lines:
                                data_str = "\n".join(data_lines)
                                data_lines = []
                                try:
                                    data = json.loads(data_str)
                                except json.JSONDecodeError:
                                    event_type = ""
                                    continue

                                if event_type == "step.delta":
                                    delta = data.get("delta", {})
                                    if delta.get("type") == "text":
                                        text = delta.get("text", "")
                                        if text:
                                            chunks.append(text)
                                            yield {"type": "delta", "content": text}
                                elif event_type == "interaction.completed":
                                    saw_completed = True
                                    break
                                event_type = ""
                            continue
                        if line.startswith(":"):
                            continue

                        if line.startswith("event:"):
                            event_type = line[6:].strip()
                            continue

                        if line.startswith("data:"):
                            data_str = line[5:].strip()
                            if data_str:
                                data_lines.append(data_str)
                            continue
        except httpx.HTTPStatusError as exc:
            try:
                await exc.response.aread()
                detail = exc.response.text[:500]
            except Exception:
                detail = str(exc)
            raise RuntimeError(f"Google Interactions stream error: {detail}") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Stream network error: {exc}") from exc

        if not saw_completed:
            raise RuntimeError(
                "Google Interactions stream closed before completion; the response was truncated."
            )

        reply = "".join(chunks).strip()
        if not reply:
            raise RuntimeError("Google Interactions API returned empty stream response.")

        yield {
            "type": "done",
            "provider": "Google",
            "model": settings["model"],
            "reply": reply,
        }

    async def chat_completion(
        self,
        *,
        provider: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        use_memory: bool = True,
        deep_thinking: bool = False,
    ) -> dict[str, Any]:
        settings = self._resolve_settings(provider, model)
        if deep_thinking and provider == "DashScope" and settings["model"] != "qwen-max":
             # Force qwen-max for deep thinking if not already set
             settings["model"] = "qwen-max"

        normalized_messages = self._normalize_messages(messages)

        # --- EverMem: prepare memory context before any LLM call ---
        mem_ctx = await prepare_memory_context(
            normalized_messages, use_memory=use_memory,
        )

        # Route Google provider to Interactions API
        if provider == "Google":
            result = await self._chat_completion_google(
                settings=settings,
                messages=normalized_messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            save_assistant_memory(mem_ctx, result.get("reply", ""))
            result["memories_retrieved"] = mem_ctx.memories_retrieved
            result["memory_saved"] = mem_ctx.memory_saved
            return result
        
        # Memory context already prepared above (mem_ctx)

        url = f"{settings['base_url']}/chat/completions"
        payload = {
            "model": settings["model"],
            "messages": normalized_messages,
            "temperature": float(temperature),
            "stream": False,
        }
        if settings.get("use_max_completion_tokens") == "True":
            payload["max_completion_tokens"] = int(max_tokens)
        else:
            payload["max_tokens"] = int(max_tokens)

        headers = self._build_headers(provider, settings["api_key"])
        custom_headers_str = settings.get("custom_headers")
        if custom_headers_str:
            try:
                custom_headers = json.loads(custom_headers_str)
                if isinstance(custom_headers, dict):
                    headers.update({str(k): str(v) for k, v in custom_headers.items()})
            except Exception:
                pass

        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500] if exc.response is not None else str(exc)
            raise RuntimeError(f"Provider request failed: {detail}") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Network error: {exc}") from exc

        from typing import cast # type: ignore
        data = cast(dict[str, Any], response.json())
        reply = self._extract_reply(data)
        if not reply:
            raise RuntimeError("Provider returned empty response.")

        save_assistant_memory(mem_ctx, reply)

        return {
            "provider": provider,
            "model": settings["model"],
            "reply": reply,
            "raw": data,
            "memories_retrieved": mem_ctx.memories_retrieved,
            "memory_saved": mem_ctx.memory_saved,
        }

    async def chat_completion_stream(
        self,
        *,
        provider: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        request_headers: dict[str, Any] | None = None,
        use_memory: bool = True,
        deep_thinking: bool = False,
    ) -> AsyncGenerator[dict[str, Any], None]:
        settings = self._resolve_settings(provider, model)
        if deep_thinking and provider == "DashScope" and settings["model"] != "qwen-max":
            settings["model"] = "qwen-max"

        normalized_messages = self._normalize_messages(messages)

        # Route Google provider to Interactions API
        if provider == "Google":
            # EverMem integration (shared helper, two-stage search for streaming)
            mem_ctx = await prepare_memory_context(
                normalized_messages,
                use_memory=use_memory,
                request_headers=request_headers,
                use_two_stage=True,
            )

            async for event in self._chat_completion_stream_google(
                settings=settings,
                messages=normalized_messages,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                if event.get("type") == "done":
                    reply = event.get("reply", "")
                    save_assistant_memory(mem_ctx, reply, reasoner=self.reason_about_text)
                    yield {
                        "type": "done",
                        "provider": "Google",
                        "model": settings["model"],
                        "reply": reply,
                        "memories_retrieved": mem_ctx.memories_retrieved,
                        "memory_saved": mem_ctx.memory_saved,
                    }
                else:
                    yield event
            return
        
        # EverMem integration for non-Google streaming (shared helper)
        mem_ctx = await prepare_memory_context(
            normalized_messages,
            use_memory=use_memory,
            request_headers=request_headers,
            use_two_stage=True,
        )

        url = f"{settings['base_url']}/chat/completions"
        payload = {
            "model": settings["model"],
            "messages": normalized_messages,
            "temperature": float(temperature),
            "stream": True,
        }
        if settings.get("use_max_completion_tokens") == "True":
            payload["max_completion_tokens"] = int(max_tokens)
        else:
            payload["max_tokens"] = int(max_tokens)

        headers = self._build_headers(provider, settings["api_key"])
        custom_headers_str = settings.get("custom_headers")
        if custom_headers_str:
            try:
                custom_headers = json.loads(custom_headers_str)
                if isinstance(custom_headers, dict):
                    headers.update({str(k): str(v) for k, v in custom_headers.items()})
            except Exception:
                pass

        yield {"type": "meta", "provider": provider, "model": settings["model"]}
        chunks: list[str] = []
        # A stream that ends without the [DONE] sentinel or any finish_reason
        # was cut off mid-generation — report it instead of presenting a
        # truncated reply as complete.
        saw_done = False
        saw_finish_reason = False
        try:
            timeout = httpx.Timeout(timeout=120.0, read=120.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    response.raise_for_status()
                    async for raw_line in response.aiter_lines():
                        line = raw_line.strip()
                        if not line or line.startswith(":"):
                            continue

                        data_line = line[5:].strip() if line.startswith("data:") else line
                        if not data_line:
                            continue
                        if data_line == "[DONE]":
                            saw_done = True
                            break

                        try:
                            chunk = json.loads(data_line)
                        except json.JSONDecodeError:
                            continue

                        choices = chunk.get("choices")
                        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                            if choices[0].get("finish_reason"):
                                saw_finish_reason = True

                        delta, reasoning_delta = self._extract_delta_parts(chunk)
                        if reasoning_delta:
                            yield {"type": "reasoning", "content": reasoning_delta}
                        if delta:
                            chunks.append(delta)
                            yield {"type": "delta", "content": delta}
        except httpx.HTTPStatusError as exc:
            try:
                await exc.response.aread()
                detail = exc.response.text[:500]
            except Exception:
                detail = str(exc)
            raise RuntimeError(f"Provider stream request failed: {detail}") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Stream network error: {exc}") from exc

        if not saw_done and not saw_finish_reason:
            raise RuntimeError(
                "Provider closed the stream before completion; the response was truncated."
            )

        reply = "".join(chunks).strip()
        if not reply:
            raise RuntimeError("Provider returned empty stream response.")

        save_assistant_memory(mem_ctx, reply, reasoner=self.reason_about_text)

        yield {
            "type": "done",
            "provider": provider,
            "model": settings["model"],
            "reply": reply,
            "memories_retrieved": mem_ctx.memories_retrieved,
            "memory_saved": mem_ctx.memory_saved,
        }

    async def translate_text(
        self,
        *,
        text: str,
        target_language: str,
        source_language: str | None = None,
        provider: str = "DashScope",
        model: str | None = None,
    ) -> dict[str, Any]:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("text is empty.")

        source = (source_language or "auto").strip()
        target = target_language.strip()
        if not target:
            raise ValueError("target_language is required.")

        system_prompt = (
            "You are a professional translator. "
            "Translate accurately and naturally. "
            "Return only the translated text, without explanation."
        )
        user_prompt = (
            f"Source language: {source}\n"
            f"Target language: {target}\n"
            f"Text:\n{cleaned}"
        )
        result = await self.chat_completion(
            provider=provider,
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=2048,
        )
        return {
            "provider": result["provider"],
            "model": result["model"],
            "translated_text": result["reply"],
        }

    async def translate_image(
        self,
        *,
        image_bytes: bytes,
        image_mime_type: str,
        target_language: str,
        source_language: str | None = None,
        provider: str = "DashScope",
        model: str | None = None,
    ) -> dict[str, Any]:
        if not image_bytes:
            raise ValueError("image_file is empty.")
        if not image_mime_type.startswith("image/"):
            raise ValueError("image_file must be an image.")

        source = (source_language or "auto").strip()
        target = target_language.strip()
        if not target:
            raise ValueError("target_language is required.")

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        system_prompt = (
            "You are a professional translator with OCR ability. "
            "Read the text from the image and translate it accurately and naturally. "
            "Return only the translated text, without explanation."
        )
        user_content = [
            {
                "type": "text",
                "text": (
                    f"Source language: {source}\n"
                    f"Target language: {target}\n"
                    "Task: extract and translate all readable text in the image."
                ),
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:{image_mime_type};base64,{image_b64}"},
            },
        ]
        result = await self.chat_completion(
            provider=provider,
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            max_tokens=2048,
        )
        return {
            "provider": result["provider"],
            "model": result["model"],
            "translated_text": result["reply"],
        }

    async def reason_about_text(self, text: str, mode: str = "memory") -> str | None:
        """Use an LLM to extract essence/reasoning/summary from text."""
        if not text or len(text.strip()) < 10:
            return None

        # Prefer DeepSeek for reasoning if available
        provider = "DeepSeek"
        settings = self.config.get_provider_settings(provider)
        if not settings.get("api_key"):
            provider = "DashScope"
            settings = self.config.get_provider_settings(provider)
            
        if not settings.get("api_key"):
            return None

        url = f"{settings['base_url']}/chat/completions"
        headers = self._build_headers(provider, settings["api_key"])
        model = settings.get("model") or ("deepseek-v4-flash" if provider == "DeepSeek" else "qwen-plus")

        if mode == "memory":
            prompt = (
                "你是一个专业的记忆提取助手。请阅读以下文本，并将其精炼为一个适合长期记忆的条目。\n"
                "输出要求：简洁、包含核心信息、提及关键实体（人/项目/日期/动作）。\n"
                "不要有任何开场白。语言与原文保持一致。\n\n"
                f"文本：\n{text}"
            )
        elif mode == "intent":
            prompt = (
                "阅读以下用户对话片段，提取其核心查询意图或提到的关键背景信息，限制在20字以内。"
                "用于帮助搜索引擎检索相关历史记忆。\n\n"
                f"用户：\n{text}"
            )
        else:
            prompt = text

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 512,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    return self._extract_reply(data)
        except Exception:
            pass
        return None
