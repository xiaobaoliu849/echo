"""Local realtime voice runtime management endpoints.

Mounted at ``/api/realtime-local``. Lets the frontend check whether the
local full-duplex providers (GLM-4-Voice / PersonaPlex) are installed,
download their runtimes + models as a background job, and start/stop the
local servers — no cloud API key required.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.local_voice_runtime import (
    PROVIDER_SPECS,
    LocalVoiceRuntimeError,
    LocalProviderSpec,
    runtime,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Strong references for in-flight setup tasks — asyncio only weakly refs
# tasks, so without this a 20GB model download could be GC'd mid-run
# (same pattern as routers/transcription.py).
_SETUP_TASKS: dict[str, asyncio.Task] = {}
_SETUP_JOBS: dict[str, dict[str, Any]] = {}


def _get_spec(provider: str) -> LocalProviderSpec:
    spec = PROVIDER_SPECS.get((provider or "").strip())
    if spec is None:
        raise HTTPException(status_code=404, detail={
            "code": "unknown_local_provider",
            "message": f"未知的本地语音提供方 / Unknown local provider: {provider}",
        })
    return spec


class SetupRequest(BaseModel):
    provider: str
    hf_token: str = ""


class ServerRequest(BaseModel):
    provider: str
    hf_token: str = ""


@router.get("/status")
async def local_status() -> dict[str, Any]:
    return {
        "providers": [runtime.status(spec) for spec in PROVIDER_SPECS.values()],
    }


@router.post("/setup")
async def start_setup(req: SetupRequest) -> dict[str, Any]:
    spec = _get_spec(req.provider)
    for job in _SETUP_JOBS.values():
        if job["provider"] == spec.key and job["status"] == "running":
            return {"job_id": job["job_id"], "status": "running"}

    job_id = uuid.uuid4().hex[:12]
    job: dict[str, Any] = {
        "job_id": job_id,
        "provider": spec.key,
        "status": "running",
        "percent": 0,
        "step": "queued",
        "message": "任务已创建 / Setup queued",
        "error": None,
    }
    _SETUP_JOBS[job_id] = job

    def on_progress(info: dict[str, Any]) -> None:
        job.update({k: v for k, v in info.items() if k in ("percent", "step", "message")})

    async def run() -> None:
        try:
            await runtime.setup(spec, hf_token=req.hf_token,
                                progress=on_progress,
                                cancel=lambda: job["status"] == "cancelled")
            job.update(status="done", percent=100)
        except LocalVoiceRuntimeError as exc:
            if job["status"] != "cancelled":
                job.update(status="error", error=str(exc))
        except Exception as exc:  # surfaced so polling never hangs on "running"
            logger.exception("local runtime setup failed")
            job.update(status="error", error=f"{type(exc).__name__}: {exc}")

    task = asyncio.create_task(run())
    _SETUP_TASKS[job_id] = task

    def _on_done(done: asyncio.Task) -> None:
        if _SETUP_TASKS.get(job_id) is done:
            del _SETUP_TASKS[job_id]
        if not done.cancelled() and done.exception() is not None:
            logger.error("setup task crashed: %s", done.exception())

    task.add_done_callback(_on_done)
    return {"job_id": job_id, "status": "running"}


@router.get("/setup/{job_id}")
async def get_setup(job_id: str) -> dict[str, Any]:
    job = _SETUP_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={
            "code": "setup_job_not_found",
            "message": "安装任务不存在 / Setup job not found",
        })
    return job


@router.delete("/setup/{job_id}")
async def cancel_setup(job_id: str) -> dict[str, Any]:
    job = _SETUP_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={
            "code": "setup_job_not_found",
            "message": "安装任务不存在 / Setup job not found",
        })
    job["status"] = "cancelled"
    task = _SETUP_TASKS.pop(job_id, None)
    if task is not None and not task.done():
        task.cancel()
    return {"job_id": job_id, "status": "cancelled"}


@router.post("/server/start")
async def start_server(req: ServerRequest) -> dict[str, Any]:
    spec = _get_spec(req.provider)
    try:
        await runtime.start_server(spec, hf_token=req.hf_token)
    except LocalVoiceRuntimeError as exc:
        raise HTTPException(status_code=400, detail={
            "code": "local_server_start_failed",
            "message": str(exc),
        }) from exc
    return {"provider": spec.key, "server_running": True}


@router.post("/server/stop")
async def stop_server(req: ServerRequest) -> dict[str, Any]:
    spec = _get_spec(req.provider)
    await runtime.stop_server(spec)
    return {"provider": spec.key, "server_running": runtime.server_running(spec)}


@router.get("/server/logs/{provider}")
async def server_logs(provider: str) -> dict[str, Any]:
    spec = _get_spec(provider)
    return {"provider": spec.key, "logs": runtime.read_logs(spec)}
