from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audio_overview_service import AudioOverviewService, AudioOverviewServiceError
from .audio_agent_repository import AudioAgentRepository
from .audio_retrieval_service import AudioRetrievalService
from .audio_script_writer import AudioScriptWriter


class AudioAgentServiceError(Exception):
    def __init__(self, *, code: str, message: str, meta: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.meta = meta or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "meta": self.meta,
        }


class AudioAgentService:
    def __init__(
        self,
        *,
        db_path: Path | None = None,
        repository: AudioAgentRepository | None = None,
        audio_overview_service: AudioOverviewService | None = None,
        retrieval_service: AudioRetrievalService | None = None,
        script_writer: AudioScriptWriter | None = None,
    ) -> None:
        self.repository = repository or AudioAgentRepository(db_path=db_path)
        self.audio_overview_service = audio_overview_service or AudioOverviewService(db_path=db_path)
        self.retrieval_service = retrieval_service or AudioRetrievalService()
        self.script_writer = script_writer or AudioScriptWriter(
            llm_service=self.audio_overview_service.llm_service,
        )

    @staticmethod
    def _normalize_language(value: str | None) -> str:
        text = str(value or "").strip().lower()
        if text.startswith("en"):
            return "en"
        return "zh"

    @staticmethod
    def _now_string() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def create_run(
        self,
        *,
        topic: str,
        language: str = "zh",
        provider: str = "DashScope",
        model: str | None = None,
        use_memory: bool = True,
        source_urls: list[str] | None = None,
        source_text: str | None = None,
        generation_constraints: str | None = None,
        turn_count: int = 8,
        auto_execute: bool = False,
        request_headers: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_topic = str(topic or "").strip()
        if not clean_topic:
            raise ValueError("topic is required.")

        clean_language = self._normalize_language(language)
        clean_provider = str(provider or "DashScope").strip() or "DashScope"
        clean_model = str(model or "").strip()
        clean_source_urls = [
            item.strip()
            for item in (source_urls or [])
            if isinstance(item, str) and item.strip()
        ][:10]
        clean_source_text = str(source_text or "").strip()
        clean_generation_constraints = str(generation_constraints or "").strip()
        safe_turn_count = max(2, min(int(turn_count), 40))

        input_payload = {
            "topic": clean_topic,
            "language": clean_language,
            "provider": clean_provider,
            "model": clean_model,
            "use_memory": bool(use_memory),
            "source_urls": clean_source_urls,
            "source_text": clean_source_text,
            "generation_constraints": clean_generation_constraints,
            "turn_count": safe_turn_count,
            "auto_execute": bool(auto_execute),
        }
        run = self.repository.create_run(
            topic=clean_topic,
            language=clean_language,
            status="queued",
            current_step="retrieve",
            provider=clean_provider,
            model=clean_model,
            use_memory=bool(use_memory),
            input_payload=input_payload,
        )

        now = self._now_string()
        self.repository.add_step(
            run_id=int(run["id"]),
            step_name="prepare",
            status="completed",
            attempt_index=1,
            started_at=now,
            finished_at=now,
            meta={
                "source_url_count": len(clean_source_urls),
                "has_source_text": bool(clean_source_text),
                "has_generation_constraints": bool(clean_generation_constraints),
                "turn_count": safe_turn_count,
            },
        )
        self.repository.add_event(
            run_id=int(run["id"]),
            event_type="run_created",
            payload={
                "status": "queued",
                "current_step": "retrieve",
                "topic": clean_topic,
                "language": clean_language,
                "provider": clean_provider,
            },
        )
        self.repository.add_event(
            run_id=int(run["id"]),
            event_type="step_completed",
            payload={
                "step_name": "prepare",
                "status": "completed",
            },
        )
        self.repository.add_event(
            run_id=int(run["id"]),
            event_type="execution_deferred",
            payload={
                "message": (
                    "Run created. Execution will be triggered immediately."
                    if auto_execute
                    else "Run created. Execution has not started yet."
                ),
            },
        )
        return self.get_run(int(run["id"]))

    def get_run(self, run_id: int) -> dict[str, Any]:
        run = self.repository.get_run(run_id)
        if run is None:
            raise AudioAgentServiceError(
                code="AUDIO_AGENT_RUN_NOT_FOUND",
                message=f"Audio agent run not found: {run_id}",
                meta={"run_id": run_id},
            )
        run["steps"] = self.repository.list_steps(run_id)
        run["sources"] = self.repository.list_sources(run_id)
        return run

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.repository.list_runs(limit=limit)

    def list_events(self, run_id: int, limit: int = 200) -> list[dict[str, Any]]:
        _ = self.get_run(run_id)
        return self.repository.list_events(run_id, limit=limit)

    async def synthesize_run(
        self,
        run_id: int,
        *,
        voice_a: str | None = None,
        voice_b: str | None = None,
        rate: str = "+0%",
        language: str | None = None,
        gap_ms: int = 250,
        merge_strategy: str = "auto",
        intro_music: bool = False,
        intro_music_style: str = "warm",
        intro_music_duration_ms: int = 2500,
    ) -> dict[str, Any]:
        run = self.get_run(run_id)
        podcast_id_raw = run.get("podcast_id")
        if not isinstance(podcast_id_raw, int) or podcast_id_raw <= 0:
            raise AudioAgentServiceError(
                code="AUDIO_AGENT_PODCAST_MISSING",
                message="Audio agent run has no saved podcast draft to synthesize.",
                meta={"run_id": run_id},
            )

        try:
            self.repository.update_run(
                run_id,
                status="synthesizing",
                current_step="synthesize_audio",
                error_code="",
                error_message="",
            )
            self.repository.add_event(
                run_id=run_id,
                event_type="synthesis_started",
                payload={"podcast_id": podcast_id_raw},
            )
            synth_started = self._now_string()
            result = await self.audio_overview_service.synthesize_podcast_audio(
                podcast_id_raw,
                voice_a=voice_a,
                voice_b=voice_b,
                rate=rate,
                language=language,
                gap_ms=gap_ms,
                merge_strategy=merge_strategy,
                intro_music=intro_music,
                intro_music_style=intro_music_style,
                intro_music_duration_ms=intro_music_duration_ms,
            )
            self.repository.add_step(
                run_id=run_id,
                step_name="synthesize_audio",
                status="completed",
                started_at=synth_started,
                finished_at=self._now_string(),
                meta={
                    "podcast_id": podcast_id_raw,
                    "line_count": int(result.get("line_count", 0)),
                    "merge_strategy": str(result.get("merge_strategy", "auto")),
                    "cache_hits": int(result.get("cache_hits", 0)),
                    "intro_music": bool(result.get("intro_music", False)),
                    "intro_music_style": str(result.get("intro_music_style", "off")),
                    "intro_music_duration_ms": int(result.get("intro_music_duration_ms", 0)),
                },
            )
            current_result_payload = dict(run.get("result_payload", {}))
            current_result_payload.update(
                {
                    "audio_path": str(result.get("audio_path", "")),
                    "line_count": int(result.get("line_count", 0)),
                    "voice_a": str(result.get("voice_a", "")),
                    "voice_b": str(result.get("voice_b", "")),
                    "rate": str(result.get("rate", rate)),
                    "cache_hits": int(result.get("cache_hits", 0)),
                    "gap_ms": int(result.get("gap_ms", gap_ms)),
                    "gap_ms_applied": int(result.get("gap_ms_applied", 0)),
                    "merge_strategy": str(result.get("merge_strategy", merge_strategy)),
                    "intro_music": bool(result.get("intro_music", False)),
                    "intro_music_style": str(result.get("intro_music_style", "off")),
                    "intro_music_duration_ms": int(result.get("intro_music_duration_ms", 0)),
                }
            )
            self.repository.add_event(
                run_id=run_id,
                event_type="synthesis_completed",
                payload={
                    "podcast_id": podcast_id_raw,
                    "audio_path": str(result.get("audio_path", "")),
                    "merge_strategy": str(result.get("merge_strategy", merge_strategy)),
                    "intro_music": bool(result.get("intro_music", False)),
                },
            )
            self.repository.update_run(
                run_id,
                status="completed",
                current_step="synthesize_audio",
                result_payload=current_result_payload,
                completed=True,
            )
            return self.get_run(run_id)
        except AudioAgentServiceError:
            raise
        except AudioOverviewServiceError as exc:
            meta = {"run_id": run_id, **exc.meta}
            self.repository.update_run(
                run_id,
                status="failed",
                current_step="synthesize_audio",
                error_code=exc.code,
                error_message=exc.message,
            )
            self.repository.add_event(
                run_id=run_id,
                event_type="run_failed",
                payload={"code": exc.code, "message": exc.message, "meta": exc.meta},
            )
            raise AudioAgentServiceError(
                code=exc.code,
                message=exc.message,
                meta=meta,
            ) from exc
        except ValueError as exc:
            self.repository.update_run(
                run_id,
                status="failed",
                current_step="synthesize_audio",
                error_code="AUDIO_AGENT_SYNTHESIZE_BAD_REQUEST",
                error_message=str(exc),
            )
            self.repository.add_event(
                run_id=run_id,
                event_type="run_failed",
                payload={"code": "AUDIO_AGENT_SYNTHESIZE_BAD_REQUEST", "message": str(exc)},
            )
            raise AudioAgentServiceError(
                code="AUDIO_AGENT_SYNTHESIZE_BAD_REQUEST",
                message=str(exc),
                meta={"run_id": run_id},
            ) from exc
        except RuntimeError as exc:
            self.repository.update_run(
                run_id,
                status="failed",
                current_step="synthesize_audio",
                error_code="AUDIO_AGENT_SYNTHESIZE_RUNTIME_ERROR",
                error_message=str(exc),
            )
            self.repository.add_event(
                run_id=run_id,
                event_type="run_failed",
                payload={"code": "AUDIO_AGENT_SYNTHESIZE_RUNTIME_ERROR", "message": str(exc)},
            )
            raise AudioAgentServiceError(
                code="AUDIO_AGENT_SYNTHESIZE_RUNTIME_ERROR",
                message=str(exc),
                meta={"run_id": run_id},
            ) from exc
        except Exception as exc:
            self.repository.update_run(
                run_id,
                status="failed",
                current_step="synthesize_audio",
                error_code="AUDIO_AGENT_SYNTHESIZE_FAILED",
                error_message=str(exc),
            )
            self.repository.add_event(
                run_id=run_id,
                event_type="run_failed",
                payload={"code": "AUDIO_AGENT_SYNTHESIZE_FAILED", "message": str(exc)},
            )
            raise AudioAgentServiceError(
                code="AUDIO_AGENT_SYNTHESIZE_FAILED",
                message=f"Audio agent synthesis failed: {exc}",
                meta={"run_id": run_id},
            ) from exc

    async def execute_until_draft(
        self,
        run_id: int,
        *,
        request_headers: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run["status"] == "draft_ready":
            return run

        input_payload = dict(run.get("input_payload", {}))
        topic = str(input_payload.get("topic", run["topic"])).strip()
        language = self._normalize_language(str(input_payload.get("language", run["language"])))
        provider = str(input_payload.get("provider", run["provider"])).strip() or "DashScope"
        model = str(input_payload.get("model", run["model"])).strip() or None
        use_memory = bool(input_payload.get("use_memory", run["use_memory"]))
        source_urls = [
            str(item).strip()
            for item in input_payload.get("source_urls", [])
            if str(item).strip()
        ]
        source_text = str(input_payload.get("source_text", "")).strip()
        generation_constraints = str(input_payload.get("generation_constraints", "")).strip()
        turn_count = max(2, min(int(input_payload.get("turn_count", 8) or 8), 40))

        try:
            self.repository.update_run(
                run_id,
                status="running",
                current_step="retrieve",
                error_code="",
                error_message="",
            )
            self.repository.add_event(
                run_id=run_id,
                event_type="step_started",
                payload={"step_name": "retrieve"},
            )
            retrieve_started = self._now_string()
            sources = await self.retrieval_service.collect_sources(
                topic=topic,
                use_memory=use_memory,
                source_urls=source_urls,
                source_text=source_text,
                request_headers=request_headers,
            )
            for source in sources:
                self.repository.add_source(
                    run_id=run_id,
                    source_type=str(source.get("source_type", "manual_text")),
                    title=str(source.get("title", "")),
                    uri=str(source.get("uri", "")),
                    snippet=str(source.get("snippet", "")),
                    content=str(source.get("content", "")),
                    score=float(source.get("score", 0.0) or 0.0),
                    meta=dict(source.get("meta", {})) if isinstance(source.get("meta"), dict) else {},
                )
            self.repository.add_step(
                run_id=run_id,
                step_name="retrieve",
                status="completed",
                started_at=retrieve_started,
                finished_at=self._now_string(),
                meta={
                    "source_count": len(sources),
                    "source_types": sorted({str(item.get("source_type", "")) for item in sources if item.get("source_type")}),
                },
            )
            self.repository.add_event(
                run_id=run_id,
                event_type="retrieval_summary",
                payload={"source_count": len(sources)},
            )

            self.repository.update_run(
                run_id,
                current_step="assemble_evidence",
            )
            evidence_summary = self.script_writer._build_evidence_summary(sources)
            research_brief = self.script_writer._build_research_brief(sources)
            self.repository.add_step(
                run_id=run_id,
                step_name="assemble_evidence",
                status="completed",
                started_at=self._now_string(),
                finished_at=self._now_string(),
                meta={
                    "summary_length": len(evidence_summary),
                    "brief_length": len(research_brief),
                    "source_count": len(sources),
                },
            )
            self.repository.add_event(
                run_id=run_id,
                event_type="step_completed",
                payload={"step_name": "assemble_evidence", "status": "completed"},
            )
            self.repository.add_event(
                run_id=run_id,
                event_type="research_brief_created",
                payload={
                    "source_count": len(sources),
                    "brief_length": len(research_brief),
                },
            )

            self.repository.update_run(
                run_id,
                current_step="generate_script",
            )
            self.repository.add_event(
                run_id=run_id,
                event_type="step_started",
                payload={"step_name": "generate_script"},
            )
            generate_started = self._now_string()
            script_result = await self.script_writer.generate_script(
                topic=topic,
                language=language,
                turn_count=turn_count,
                provider=provider,
                model=model,
                sources=sources,
                generation_constraints=generation_constraints,
            )
            self.repository.add_step(
                run_id=run_id,
                step_name="generate_script",
                status="completed",
                started_at=generate_started,
                finished_at=self._now_string(),
                meta={
                    "line_count": len(script_result["script_lines"]),
                    "provider": script_result["provider"],
                    "model": script_result["model"],
                },
            )
            self.repository.add_event(
                run_id=run_id,
                event_type="draft_created",
                payload={
                    "line_count": len(script_result["script_lines"]),
                    "provider": script_result["provider"],
                    "model": script_result["model"],
                },
            )

            self.repository.update_run(
                run_id,
                current_step="persist_draft",
            )
            persist_started = self._now_string()
            podcast_id_raw = run.get("podcast_id")
            if isinstance(podcast_id_raw, int) and podcast_id_raw > 0:
                podcast = self.audio_overview_service.update_podcast(
                    podcast_id_raw,
                    topic=topic,
                    language=language,
                    script_lines=script_result["script_lines"],
                )
            else:
                podcast = self.audio_overview_service.create_podcast(
                    topic=topic,
                    language=language,
                    script_lines=script_result["script_lines"],
                )
            podcast_id = int(podcast["id"])
            self.repository.add_step(
                run_id=run_id,
                step_name="persist_draft",
                status="completed",
                started_at=persist_started,
                finished_at=self._now_string(),
                meta={"podcast_id": podcast_id},
            )
            self.repository.add_event(
                run_id=run_id,
                event_type="podcast_saved",
                payload={"podcast_id": podcast_id},
            )
            self.repository.update_run(
                run_id,
                podcast_id=podcast_id,
                status="draft_ready",
                current_step="persist_draft",
                result_payload={
                    "podcast_id": podcast_id,
                    "script_lines": podcast.get("script_lines", []),
                    "evidence_summary": script_result.get("evidence_summary", ""),
                    "research_brief": script_result.get("research_brief", research_brief),
                    "provider": script_result["provider"],
                    "model": script_result["model"],
                },
            )
            return self.get_run(run_id)
        except AudioAgentServiceError:
            raise
        except ValueError as exc:
            latest = self.repository.get_run(run_id) or run
            self.repository.update_run(
                run_id,
                status="failed",
                current_step=latest.get("current_step", ""),
                error_code="AUDIO_AGENT_EXECUTION_BAD_REQUEST",
                error_message=str(exc),
            )
            self.repository.add_event(
                run_id=run_id,
                event_type="run_failed",
                payload={"code": "AUDIO_AGENT_EXECUTION_BAD_REQUEST", "message": str(exc)},
            )
            raise AudioAgentServiceError(
                code="AUDIO_AGENT_EXECUTION_BAD_REQUEST",
                message=str(exc),
                meta={"run_id": run_id},
            ) from exc
        except RuntimeError as exc:
            latest = self.repository.get_run(run_id) or run
            self.repository.update_run(
                run_id,
                status="failed",
                current_step=latest.get("current_step", ""),
                error_code="AUDIO_AGENT_EXECUTION_PROVIDER_ERROR",
                error_message=str(exc),
            )
            self.repository.add_event(
                run_id=run_id,
                event_type="run_failed",
                payload={"code": "AUDIO_AGENT_EXECUTION_PROVIDER_ERROR", "message": str(exc)},
            )
            raise AudioAgentServiceError(
                code="AUDIO_AGENT_EXECUTION_PROVIDER_ERROR",
                message=str(exc),
                meta={"run_id": run_id},
            ) from exc
        except Exception as exc:
            latest = self.repository.get_run(run_id) or run
            self.repository.update_run(
                run_id,
                status="failed",
                current_step=latest.get("current_step", ""),
                error_code="AUDIO_AGENT_EXECUTION_FAILED",
                error_message=str(exc),
            )
            self.repository.add_event(
                run_id=run_id,
                event_type="run_failed",
                payload={"code": "AUDIO_AGENT_EXECUTION_FAILED", "message": str(exc)},
            )
            raise AudioAgentServiceError(
                code="AUDIO_AGENT_EXECUTION_FAILED",
                message=f"Audio agent execution failed: {exc}",
                meta={"run_id": run_id},
            ) from exc
