from __future__ import annotations

import asyncio
from typing import Any

from .audio_research_service import AudioResearchService
from .evermem_config import EverMemConfig


class AudioRetrievalService:
    def __init__(self, research_service: AudioResearchService | None = None) -> None:
        self.research_service = research_service or AudioResearchService()

    @staticmethod
    def _clean_text(value: str | None, *, limit: int) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return text[:limit]

    async def collect_sources(
        self,
        *,
        topic: str,
        use_memory: bool,
        source_urls: list[str] | None = None,
        source_text: str | None = None,
        request_headers: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []

        clean_source_text = self._clean_text(source_text, limit=4000)
        if clean_source_text:
            sources.append(
                {
                    "source_type": "manual_text",
                    "title": "User provided context",
                    "uri": "",
                    "snippet": clean_source_text[:280],
                    "content": clean_source_text,
                    "score": 1.0,
                    "meta": {"origin": "user_input"},
                }
            )

        clean_source_urls = [
            str(item or "").strip()
            for item in (source_urls or [])
            if str(item or "").strip()
        ][:10]

        fetched_documents = await asyncio.gather(
            *[
                self.research_service.fetch_document(
                    clean_url,
                    title_hint=f"Manual source {idx}",
                    source_type="manual_url",
                    score=0.75,
                )
                for idx, clean_url in enumerate(clean_source_urls, start=1)
            ],
            return_exceptions=True,
        )
        for idx, item in enumerate(fetched_documents, start=1):
            if isinstance(item, Exception):
                clean_url = clean_source_urls[idx - 1]
                sources.append(
                    {
                        "source_type": "manual_url",
                        "title": f"Manual source {idx}",
                        "uri": clean_url[:1000],
                        "snippet": f"Failed to fetch source: {item}",
                        "content": "",
                        "score": 0.2,
                        "meta": {"origin": "user_url", "fetch_status": "failed"},
                    }
                )
                continue
            source = item.to_source()
            source["meta"] = {**source.get("meta", {}), "origin": "user_url"}
            sources.append(source)

        if not clean_source_text and len(sources) < 3:
            search_results = await self.research_service.search(topic, limit=5)
            web_documents = await asyncio.gather(
                *[
                    self.research_service.fetch_document(
                        item["url"],
                        title_hint=item.get("title", ""),
                        snippet_hint=item.get("snippet", ""),
                        source_type="web_search",
                        score=0.65,
                    )
                    for item in search_results
                ],
                return_exceptions=True,
            )
            for item in web_documents:
                if isinstance(item, Exception):
                    continue
                source = item.to_source()
                source["meta"] = {**source.get("meta", {}), "origin": "web_search"}
                sources.append(source)

        deduped: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for source in sources:
            key = str(source.get("uri") or source.get("content", ""))[:500]
            if key and key in seen_keys:
                continue
            if key:
                seen_keys.add(key)
            deduped.append(source)
            if len(deduped) >= 8:
                break
        sources = deduped

        if not use_memory:
            return sources

        evermem_config = EverMemConfig()
        if request_headers:
            evermem_config.update_from_headers(request_headers)
        evermem_service = evermem_config.get_service()
        if not evermem_service:
            return sources
        if evermem_service.should_skip_memory(topic):
            return sources

        memories = await evermem_service.search_memories(
            query=topic,
            user_id=evermem_config.memory_scope,
            min_score=0.3,
        )
        for idx, memory in enumerate(memories[:5], start=1):
            content = self._clean_text(str(memory.get("content", "")), limit=1200)
            if not content:
                continue
            sources.append(
                {
                    "source_type": "evermem",
                    "title": f"Memory {idx}",
                    "uri": "",
                    "snippet": content[:280],
                    "content": content,
                    "score": float(memory.get("score", 0.0) or 0.0),
                    "meta": {
                        "memory_type": str(memory.get("type", "")),
                        "origin": "evermem",
                    },
                }
            )
        return sources
