"""Tests for services/local_voice_runtime.py and routers/realtime_local.py.

All filesystem state is isolated under tmp_path; no network or subprocesses
are exercised — uv/torch/model downloads are out of scope here.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.local_voice_runtime import PROVIDER_SPECS, LocalVoiceRuntime
from routers import realtime_local


@pytest.fixture()
def rt(tmp_path: Path) -> LocalVoiceRuntime:
    return LocalVoiceRuntime(root=tmp_path / "rt", models_root=tmp_path / "models")


@pytest.fixture()
def glm_spec():
    return PROVIDER_SPECS["GLM4Voice"]


@pytest.fixture()
def personaplex_spec():
    return PROVIDER_SPECS["PersonaPlex"]


def _touch_glm_models(rt: LocalVoiceRuntime) -> None:
    weights = rt.model_dir("glm-4-voice-9b")
    weights.mkdir(parents=True)
    (weights / "model-00001.safetensors").write_bytes(b"x")
    decoder = rt.model_dir("glm-4-voice-decoder")
    decoder.mkdir(parents=True)
    (decoder / "flow.pt").write_bytes(b"x")
    tokenizer = rt.model_dir("glm-4-voice-tokenizer")
    tokenizer.mkdir(parents=True)
    (tokenizer / "tokenizer.model").write_bytes(b"x")


class TestStatus:
    def test_fresh_runtime_is_not_installed(self, rt: LocalVoiceRuntime, glm_spec) -> None:
        status = rt.status(glm_spec)
        assert status["provider"] == "GLM4Voice"
        assert status["installed"] is False
        assert status["models_downloaded"] is False
        assert status["server_running"] is False
        assert status["requirements"]["min_vram_gb"] == pytest.approx(10.0)
        assert status["disk_free_gb"] > 0
        assert "gpu" in status  # available flag depends on the machine

    def test_glm_models_detected_only_when_complete(self, rt: LocalVoiceRuntime, glm_spec) -> None:
        assert rt.models_downloaded(glm_spec) is False
        _touch_glm_models(rt)
        assert rt.models_downloaded(glm_spec) is True
        # Removing the decoder flow weights breaks readiness again.
        (rt.model_dir("glm-4-voice-decoder") / "flow.pt").unlink()
        assert rt.models_downloaded(glm_spec) is False

    def test_personaplex_models_need_hf_cache_layout(
        self, rt: LocalVoiceRuntime, personaplex_spec
    ) -> None:
        assert rt.models_downloaded(personaplex_spec) is False
        cache = rt.models_root / "hf" / "hub" / "models--nvidia--personaplex-7b-v1"
        cache.mkdir(parents=True)
        (cache / "weights.bin").write_bytes(b"x" * 16)
        # Too small (< 1 GiB) — partial downloads must not count.
        assert rt.models_downloaded(personaplex_spec) is False

    def test_installed_marker(self, rt: LocalVoiceRuntime, glm_spec, tmp_path: Path) -> None:
        assert rt.is_installed(glm_spec) is False
        marker = tmp_path / "rt" / "glm4voice" / ".setup_done"
        marker.parent.mkdir(parents=True)
        marker.write_text("{}", encoding="utf-8")
        assert rt.is_installed(glm_spec) is True


class TestServerCommands:
    def test_glm_commands_cover_both_processes(self, rt: LocalVoiceRuntime, glm_spec) -> None:
        commands = rt._server_commands(glm_spec, hf_token="")
        names = [name for name, _cmd, _env in commands]
        assert names == ["worker", "s2s"]
        worker_cmd = commands[0][1]
        s2s_cmd = commands[1][1]
        assert "model_server.py" in worker_cmd[1]
        assert "10000" in worker_cmd
        assert "glm4voice_s2s_server.py" in s2s_cmd[1]
        assert "8999" in s2s_cmd
        # The upstream repo + Matcha-TTS must be importable.
        pythonpath = commands[0][2]["PYTHONPATH"]
        assert "GLM-4-Voice" in pythonpath
        assert "Matcha-TTS" in pythonpath

    def test_personaplex_command_uses_official_hf_repo(
        self, rt: LocalVoiceRuntime, personaplex_spec
    ) -> None:
        commands = rt._server_commands(personaplex_spec, hf_token="tok123")
        name, cmd, env = commands[0]
        assert name == "server"
        assert cmd[1:3] == ["-m", "moshi.server"]
        assert "nvidia/personaplex-7b-v1" in cmd
        assert "--quantize-4bit" in cmd
        assert "8998" in cmd
        assert env["HF_TOKEN"] == "tok123"
        assert env["NO_TORCH_COMPILE"] == "1"

    def test_personaplex_command_without_token(
        self, rt: LocalVoiceRuntime, personaplex_spec
    ) -> None:
        _name, _cmd, env = rt._server_commands(personaplex_spec, hf_token="")[0]
        assert "HF_TOKEN" not in env


class TestSafeExtract:
    def test_rejects_zip_slip(self, tmp_path: Path) -> None:
        from services.local_voice_runtime import (
            LocalVoiceRuntimeError,
            _safe_extract,
        )

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("evil/../../escape.txt", "x")
        with zipfile.ZipFile(buf) as zf:
            with pytest.raises(LocalVoiceRuntimeError, match="unsafe path"):
                _safe_extract(zf, tmp_path / "dest")

    def test_extracts_normal_archive(self, tmp_path: Path) -> None:
        from services.local_voice_runtime import _safe_extract

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("pkg-main/file.py", "print(1)")
        dest = tmp_path / "dest"
        with zipfile.ZipFile(buf) as zf:
            _safe_extract(zf, dest)
        assert (dest / "pkg-main" / "file.py").read_text() == "print(1)"


class TestSetupValidation:
    def test_personaplex_requires_hf_token(
        self, rt: LocalVoiceRuntime, personaplex_spec
    ) -> None:
        import asyncio

        from services.local_voice_runtime import LocalVoiceRuntimeError

        def fail_progress(_info):
            raise AssertionError("should not progress past token gate")

        with pytest.raises(LocalVoiceRuntimeError, match="HuggingFace"):
            asyncio.run(rt._download_models(personaplex_spec, "", fail_progress, lambda: False))


# ── router ────────────────────────────────────────────────────────────────────


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    isolated = LocalVoiceRuntime(root=tmp_path / "rt", models_root=tmp_path / "models")
    monkeypatch.setattr(realtime_local, "runtime", isolated)
    app = FastAPI()
    app.include_router(realtime_local.router, prefix="/api/realtime-local")
    return TestClient(app)


def test_status_endpoint_lists_both_providers(client: TestClient) -> None:
    resp = client.get("/api/realtime-local/status")
    assert resp.status_code == 200
    providers = {p["provider"]: p for p in resp.json()["providers"]}
    assert set(providers) == {"GLM4Voice", "PersonaPlex"}
    assert providers["GLM4Voice"]["installed"] is False


def test_unknown_provider_404(client: TestClient) -> None:
    resp = client.post("/api/realtime-local/server/start", json={"provider": "Nope"})
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "unknown_local_provider"


def test_start_without_setup_returns_400(client: TestClient) -> None:
    resp = client.post("/api/realtime-local/server/start", json={"provider": "GLM4Voice"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "local_server_start_failed"


def test_setup_job_lifecycle(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_setup(spec, hf_token="", progress=lambda info: None, cancel=lambda: False):
        progress({"percent": 50, "step": "download_models", "message": "halfway"})
        progress({"percent": 100, "step": "done", "message": "done"})

    monkeypatch.setattr(realtime_local.runtime, "setup", fake_setup)
    resp = client.post("/api/realtime-local/setup", json={"provider": "GLM4Voice"})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    # Let the background task run to completion.
    import time

    for _ in range(50):
        job = client.get(f"/api/realtime-local/setup/{job_id}").json()
        if job["status"] != "running":
            break
        time.sleep(0.05)
    assert job["status"] == "done"
    assert job["percent"] == 100


def test_setup_job_not_found(client: TestClient) -> None:
    resp = client.get("/api/realtime-local/setup/nope")
    assert resp.status_code == 404


def test_duplicate_setup_reuses_running_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    started = asyncio.Event()

    async def slow_setup(spec, hf_token="", progress=lambda info: None, cancel=lambda: False):
        started.set()
        await asyncio.sleep(5)

    monkeypatch.setattr(realtime_local.runtime, "setup", slow_setup)
    first = client.post("/api/realtime-local/setup", json={"provider": "GLM4Voice"}).json()
    # Give the background task a chance to start before re-posting.
    import time

    time.sleep(0.1)
    second = client.post("/api/realtime-local/setup", json={"provider": "GLM4Voice"}).json()
    assert first["job_id"] == second["job_id"]

    # Cancel and confirm the job reports cancellation.
    cancel = client.delete(f"/api/realtime-local/setup/{first['job_id']}")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"
