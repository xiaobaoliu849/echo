from typing import AsyncGenerator, Any

try:
    from services.llm_service import LLMService
    from services.config_loader import BackendConfig
except ImportError:
    from backend.services.llm_service import LLMService
    from backend.services.config_loader import BackendConfig

import json

class CanvasService:
    def __init__(self, config: BackendConfig | None = None):
        self.config = config or BackendConfig()
        self.llm_service = LLMService(self.config)

    async def generate_code_stream(
        self,
        prompt: str,
        images: list[str],
        mode: str,
        existing_code: str | None,
        provider: str | None,
        model: str | None,
    ) -> AsyncGenerator[str, None]:
        
        system_prompt = ""
        if mode == "react":
            system_prompt = (
                "You are an expert frontend developer. "
                "Generate a single, self-contained React functional component using TypeScript and inline styles or Tailwind classes (if available). "
                "Do NOT use external imports other than React. "
                "Export the component as default. "
                "Return ONLY the code, with no markdown formatting or explanations."
            )
        elif mode == "html":
            system_prompt = (
                "You are an expert frontend developer. "
                "Generate a complete HTML page with embedded CSS and JavaScript. "
                "Use Tailwind CSS via CDN. "
                "Return ONLY the code, with no markdown formatting or explanations."
            )
        else:
            raise ValueError(f"Unsupported mode: {mode}")

        user_text = prompt
        if existing_code:
            user_text += f"\n\nExisting code:\n```\n{existing_code}\n```\n\nPlease apply the requested changes to this code."

        user_content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
        for img_data_url in images:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": img_data_url},
            })

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content if images else user_text},
        ]

        resolved_provider, resolved_model = self.llm_service._resolve_available_provider(provider, model)

        try:
            async for event in self.llm_service.chat_completion_stream(
                provider=resolved_provider,
                messages=messages,
                model=resolved_model,
                temperature=0.2,
                max_tokens=4096,
                use_memory=False,
            ):
                # event is a dict. We just yield it as SSE.
                # Types can be meta, reasoning, delta, done, error
                event_type = event.get("type", "message")
                event_data = {k: v for k, v in event.items() if k != "type"}
                
                # Canvas wants the whole event dumped as JSON
                # Wait, the instruction: "SSE event types: meta, reasoning, delta, done, error. Each event is a line: f'data: {json.dumps(event_dict)}\n\n'"
                # Let's map it.
                payload = {"type": event_type, **event_data}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                
        except Exception as exc:
            payload = {"type": "error", "detail": str(exc), "code": "internal_error"}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
