"""Managed local realtime voice runtimes (GLM-4-Voice / PersonaPlex).

The packaged app deliberately ships no torch stack (see
``backend/voicespirit-backend.spec``). This service downloads everything a
local full-duplex voice provider needs ON DEMAND into the user data dir:

    <data>/local-runtime/
        bin/uv.exe                      # astral-sh/uv, bootstrapped once
        glm4voice/venv/                 # torch + GLM inference deps
        glm4voice/src/GLM-4-Voice/      # upstream THUDM repo (zipball)
        glm4voice/src/Matcha-TTS/       # upstream submodule (zipball)
        personaplex/venv/               # torch + moshi-personaplex
        personaplex/src/personaplex/    # NVIDIA repo (zipball, moshi/ pkg)
    <data>/models/
        glm-4-voice-9b/ ...             # ModelScope snapshots (GLM)
        hf/                             # HF_HOME cache (PersonaPlex)

Setup and server lifecycle are driven from ``routers/realtime_local.py``;
the frontend polls job status like transcription jobs do.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

from services.config_loader import get_data_dir

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Download sources
# ---------------------------------------------------------------------------

UV_ZIP_URL = (
    "https://github.com/astral-sh/uv/releases/latest/download/"
    "uv-x86_64-pc-windows-msvc.zip"
)
GLM_SOURCE_URL = "https://codeload.github.com/THUDM/GLM-4-Voice/zip/refs/heads/main"
# GLM-4-Voice's flow decoder imports Matcha-TTS as a git submodule, which
# codeload zipballs leave empty — so it is fetched separately.
MATCHA_SOURCE_URL = "https://codeload.github.com/shivammehta25/Matcha-TTS/zip/refs/heads/main"
PERSONAPLEX_SOURCE_URL = "https://codeload.github.com/NVIDIA/personaplex/zip/refs/heads/main"

TORCH_INDEX_URL = "https://download.pytorch.org/whl/cu121"

GLM_MODEL_REPOS: tuple[tuple[str, str, float], ...] = (
    # (ModelScope repo, target dir name, approx size in GB — used only for
    # progress display; the directory size is polled during download)
    ("ZhipuAI/glm-4-voice-tokenizer", "glm-4-voice-tokenizer", 2.6),
    ("ZhipuAI/glm-4-voice-decoder", "glm-4-voice-decoder", 1.2),
    ("ZhipuAI/glm-4-voice-9b", "glm-4-voice-9b", 18.0),
)
PERSONAPLEX_HF_REPO = "nvidia/personaplex-7b-v1"
PERSONAPLEX_APPROX_GB = 16.0

# Dependency sets proven on the development machine (C:\pp-eval\venv):
# torch 2.4.1+cu121, transformers 4.44.1, accelerate 0.33.0, numpy<2,
# scipy 1.13.1, hyperpyyaml, conformer 0.3.2, diffusers 0.27.2.
GLM_REQUIREMENTS: tuple[str, ...] = (
    "transformers==4.44.1",
    "accelerate==0.33.0",
    "bitsandbytes>=0.45.5",  # model_server.py loads the 9B LM via BitsAndBytesConfig int4
    "numpy<2",
    "scipy==1.13.1",
    "hyperpyyaml",
    "conformer==0.3.2",
    "diffusers==0.27.2",
    "einops",
    "librosa",
    "soundfile",
    "safetensors",
    "omegaconf",
    "modelscope",
    "huggingface_hub",
    "fastapi",
    "uvicorn",
    "requests",
)

# moshi-personaplex pins huggingface-hub <0.25 (see its METADATA).
PERSONAPLEX_REQUIREMENTS: tuple[str, ...] = (
    "bitsandbytes>=0.45.5",
    "sphn==0.1.12",
    "huggingface-hub<0.25,>=0.24",
    "safetensors<0.5,>=0.4.0",
    "numpy<2.2,>=1.26",
    "soundfile",
)

# Download helper executed by the runtime venv python (which has
# modelscope / huggingface-hub installed). Emits JSON lines on stdout.
_DOWNLOAD_WORKER = r'''
import argparse, json, sys

def emit(**kw):
    print(json.dumps(kw), flush=True)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--engine", choices=["modelscope", "hf"], required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--token", default="")
    args = p.parse_args()
    emit(type="start", repo=args.repo)
    if args.engine == "modelscope":
        from modelscope import snapshot_download
        snapshot_download(repo_id=args.repo, local_dir=args.target)
    else:
        # No local_dir: moshi.server resolves weights through the standard
        # HF cache layout (HF_HOME/hub/models--*), so keep that layout.
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=args.repo, token=args.token or None)
    emit(type="done", repo=args.repo)

try:
    main()
except Exception as exc:  # surfaced to the caller as a setup failure
    emit(type="error", message=f"{type(exc).__name__}: {exc}")
    sys.exit(1)
'''


@dataclass(frozen=True)
class LocalProviderSpec:
    key: str                 # matches PROVIDER_KEY_MAP keys in config_loader
    slug: str                # runtime subdirectory
    server_port: int
    extra_ports: tuple[int, ...] = ()
    min_vram_gb: float = 0.0
    approx_download_gb: float = 0.0


PROVIDER_SPECS: dict[str, LocalProviderSpec] = {
    "GLM4Voice": LocalProviderSpec(
        key="GLM4Voice",
        slug="glm4voice",
        server_port=8999,          # glm4voice_s2s_server.py (see realtime_constants)
        extra_ports=(10000,),      # upstream model_server.py LLM worker
        min_vram_gb=10.0,
        approx_download_gb=sum(size for _, _, size in GLM_MODEL_REPOS) + 3.0,
    ),
    "PersonaPlex": LocalProviderSpec(
        key="PersonaPlex",
        slug="personaplex",
        server_port=8998,          # moshi.server (see realtime_constants)
        min_vram_gb=6.0,
        approx_download_gb=PERSONAPLEX_APPROX_GB + 3.0,
    ),
}

ProgressCallback = Callable[[dict[str, Any]], None]


def _dir_size_bytes(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """extractall without the zip-slip: reject members escaping ``dest``."""
    dest_resolved = dest.resolve()
    for member in zf.namelist():
        target = (dest_resolved / member).resolve()
        if target != dest_resolved and dest_resolved not in target.parents:
            raise LocalVoiceRuntimeError(
                f"压缩包含非法路径 / Archive contains an unsafe path: {member}")
    zf.extractall(dest)


class LocalVoiceRuntimeError(RuntimeError):
    """User-facing setup/launch failure (bilingual message)."""


class LocalVoiceRuntime:
    """Owns runtime paths, setup jobs, and server child processes."""

    def __init__(self, root: Path | None = None, models_root: Path | None = None) -> None:
        data = get_data_dir()
        self.root = root or data / "local-runtime"
        self.models_root = models_root or data / "models"
        self._processes: dict[str, list[subprocess.Popen]] = {}
        self._lock = asyncio.Lock()
        self._gpu_cache: tuple[float, dict[str, Any]] | None = None

    _GPU_CACHE_TTL_S = 60.0

    # -- paths -------------------------------------------------------------

    def provider_dir(self, spec: LocalProviderSpec) -> Path:
        return self.root / spec.slug

    def venv_python(self, spec: LocalProviderSpec) -> Path:
        return self.provider_dir(spec) / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    def uv_path(self) -> Path:
        return self.root / "bin" / ("uv.exe" if os.name == "nt" else "uv")

    def _marker(self, spec: LocalProviderSpec) -> Path:
        return self.provider_dir(spec) / ".setup_done"

    def glm_source_dir(self) -> Path:
        return self.root / "glm4voice" / "src" / "GLM-4-Voice"

    def personaplex_source_dir(self) -> Path:
        return self.root / "personaplex" / "src" / "personaplex"

    def model_dir(self, name: str) -> Path:
        return self.models_root / name

    def log_path(self, spec: LocalProviderSpec, name: str = "server") -> Path:
        log_dir = get_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / f"local-{spec.slug}-{name}.log"

    # -- status ------------------------------------------------------------

    def is_installed(self, spec: LocalProviderSpec) -> bool:
        return self._marker(spec).exists()

    def models_downloaded(self, spec: LocalProviderSpec) -> bool:
        if spec.key == "GLM4Voice":
            weights = self.model_dir("glm-4-voice-9b")
            decoder = self.model_dir("glm-4-voice-decoder")
            tokenizer = self.model_dir("glm-4-voice-tokenizer")
            return (
                any(weights.glob("*.safetensors"))
                and (decoder / "flow.pt").exists()
                and tokenizer.is_dir()
                and any(tokenizer.iterdir())
            )
        # PersonaPlex: weights live in the HF cache layout under HF_HOME.
        hf_cache = self.models_root / "hf" / "hub" / "models--nvidia--personaplex-7b-v1"
        return hf_cache.is_dir() and _dir_size_bytes(hf_cache) > 1 << 30

    def server_running(self, spec: LocalProviderSpec) -> bool:
        return _port_open(spec.server_port)

    def detect_gpu(self) -> dict[str, Any]:
        """Query nvidia-smi for GPU name/VRAM (60s cache). Never raises."""
        now = time.monotonic()
        if self._gpu_cache and now - self._gpu_cache[0] < self._GPU_CACHE_TTL_S:
            return self._gpu_cache[1]
        result = self._query_gpu()
        self._gpu_cache = (now, result)
        return result

    def _query_gpu(self) -> dict[str, Any]:
        exe = shutil.which("nvidia-smi")
        if not exe:
            return {"available": False}
        try:
            out = subprocess.run(
                [exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
            )
            if out.returncode != 0 or not out.stdout.strip():
                return {"available": False}
            name, mem_mb = out.stdout.strip().splitlines()[0].split(",", 1)
            return {
                "available": True,
                "name": name.strip(),
                "vram_gb": round(float(mem_mb.strip()) / 1024, 1),
            }
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            logger.warning("gpu_detect_failed: %s", exc)
            return {"available": False}

    def status(self, spec: LocalProviderSpec) -> dict[str, Any]:
        disk = shutil.disk_usage(self.root.anchor or self.root)
        return {
            "provider": spec.key,
            "server_running": self.server_running(spec),
            "installed": self.is_installed(spec),
            "models_downloaded": self.models_downloaded(spec),
            "requirements": {
                "min_vram_gb": spec.min_vram_gb,
                "approx_download_gb": spec.approx_download_gb,
            },
            "gpu": self.detect_gpu(),
            "disk_free_gb": round(disk.free / (1 << 30), 1),
        }

    # -- setup pipeline ----------------------------------------------------

    async def setup(self, spec: LocalProviderSpec, hf_token: str = "",
                    progress: ProgressCallback = lambda info: None,
                    cancel: Callable[[], bool] = lambda: False) -> None:
        """Download runtime + models. Runs blocking work in threads."""

        def check_cancel() -> None:
            if cancel():
                raise LocalVoiceRuntimeError("安装已取消 / Setup cancelled by user.")

        disk = shutil.disk_usage(self.root.anchor or self.root)
        need_gb = spec.approx_download_gb + 2.0
        if disk.free < need_gb * (1 << 30):
            raise LocalVoiceRuntimeError(
                f"磁盘空间不足：需要约 {need_gb:.0f} GB，剩余 "
                f"{disk.free / (1 << 30):.0f} GB。 / Not enough disk space: "
                f"need ~{need_gb:.0f} GB, only {disk.free / (1 << 30):.0f} GB free."
            )

        async with self._lock:
            progress({"percent": 1, "step": "download_uv",
                      "message": "下载 Python 环境管理器 (uv)… / Downloading uv…"})
            await asyncio.to_thread(self._ensure_uv)
            check_cancel()

            progress({"percent": 5, "step": "download_source",
                      "message": "下载模型服务源码… / Downloading server source…"})
            if spec.key == "GLM4Voice":
                await asyncio.to_thread(self._fetch_zip, GLM_SOURCE_URL,
                                        self.glm_source_dir().parent, "GLM-4-Voice")
                matcha_dir = self.glm_source_dir() / "third_party" / "Matcha-TTS"
                await asyncio.to_thread(self._fetch_zip, MATCHA_SOURCE_URL,
                                        matcha_dir.parent, "Matcha-TTS")
            else:
                await asyncio.to_thread(self._fetch_zip, PERSONAPLEX_SOURCE_URL,
                                        self.personaplex_source_dir().parent, "personaplex")
            check_cancel()

            progress({"percent": 12, "step": "create_venv",
                      "message": "创建 Python 环境（含 torch，约 3GB）… / Creating Python env (torch, ~3GB)…"})
            await asyncio.to_thread(self._create_venv, spec)
            check_cancel()

            progress({"percent": 40, "step": "download_models",
                      "message": "下载模型权重… / Downloading model weights…"})
            await self._download_models(spec, hf_token, progress, check_cancel)
            check_cancel()

            self._marker(spec).write_text(json.dumps({
                "provider": spec.key,
                "python": sys.version.split()[0],
            }), encoding="utf-8")
            progress({"percent": 100, "step": "done",
                      "message": "安装完成 / Setup complete"})

    def _ensure_uv(self) -> None:
        uv = self.uv_path()
        if uv.exists():
            return
        uv.parent.mkdir(parents=True, exist_ok=True)
        zip_path = uv.parent / "uv.zip"
        with httpx.stream("GET", UV_ZIP_URL, follow_redirects=True, timeout=300) as resp:
            resp.raise_for_status()
            with open(zip_path, "wb") as fh:
                for chunk in resp.iter_bytes(1 << 20):
                    fh.write(chunk)
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extract(zf, uv.parent)
        zip_path.unlink(missing_ok=True)
        if not uv.exists():
            raise LocalVoiceRuntimeError(
                "uv 解压失败 / Failed to extract the uv package manager.")

    def _fetch_zip(self, url: str, dest_parent: Path, folder: str) -> None:
        """Download a GitHub codeload zipball into dest_parent/folder."""
        target = dest_parent / folder
        if (target / ".source_ok").exists():
            return
        dest_parent.mkdir(parents=True, exist_ok=True)
        zip_path = dest_parent / f"{folder}.zip"
        with httpx.stream("GET", url, follow_redirects=True, timeout=300) as resp:
            resp.raise_for_status()
            with open(zip_path, "wb") as fh:
                for chunk in resp.iter_bytes(1 << 20):
                    fh.write(chunk)
        staging = dest_parent / f".{folder}-extract"
        shutil.rmtree(staging, ignore_errors=True)
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extract(zf, staging)
        zip_path.unlink(missing_ok=True)
        roots = [p for p in staging.iterdir() if p.is_dir()]
        if len(roots) != 1:
            raise LocalVoiceRuntimeError(
                f"源码压缩包结构异常 / Unexpected archive layout for {folder}.")
        shutil.rmtree(target, ignore_errors=True)
        shutil.move(str(roots[0]), str(target))
        shutil.rmtree(staging, ignore_errors=True)
        (target / ".source_ok").write_text(url, encoding="utf-8")

    def _run_uv(self, args: list[str], step: str) -> None:
        cmd = [str(self.uv_path()), *args]
        logger.info("local_runtime uv: %s", " ".join(cmd))
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-800:]
            raise LocalVoiceRuntimeError(
                f"环境安装失败（{step}）/ Environment setup failed ({step}): {tail}")

    def _create_venv(self, spec: LocalProviderSpec) -> None:
        python = self.venv_python(spec)
        if not python.exists():
            venv_dir = python.parent.parent
            # `uv venv` auto-downloads a managed CPython when 3.12 is absent.
            self._run_uv(["venv", "--python", "3.12", str(venv_dir)], "venv")
        # torch first (separate index), then the provider deps from PyPI.
        self._run_uv(["pip", "install", "--python", str(python),
                      "torch==2.4.1", "torchaudio==2.4.1",
                      "--index-url", TORCH_INDEX_URL], "torch")
        reqs = (GLM_REQUIREMENTS if spec.key == "GLM4Voice"
                else PERSONAPLEX_REQUIREMENTS)
        self._run_uv(["pip", "install", "--python", str(python), *reqs], "deps")
        if spec.key == "PersonaPlex":
            # moshi-personaplex ships as a subdirectory of the NVIDIA repo.
            moshi_pkg = self.personaplex_source_dir() / "moshi"
            if not (moshi_pkg / "pyproject.toml").exists():
                raise LocalVoiceRuntimeError(
                    "PersonaPlex 源码缺少 moshi 包 / moshi package missing in the PersonaPlex source tree.")
            self._run_uv(["pip", "install", "--python", str(python), str(moshi_pkg)], "moshi")

    async def _download_models(self, spec: LocalProviderSpec, hf_token: str,
                               progress: ProgressCallback,
                               check_cancel: Callable[[], None]) -> None:
        worker = self.root / "bin" / "download_worker.py"
        worker.parent.mkdir(parents=True, exist_ok=True)
        worker.write_text(_DOWNLOAD_WORKER, encoding="utf-8")
        python = self.venv_python(spec)

        if spec.key == "GLM4Voice":
            jobs = [(repo, self.model_dir(name), size)
                    for repo, name, size in GLM_MODEL_REPOS]
            for idx, (repo, target, size_gb) in enumerate(jobs):
                check_cancel()
                base = 40 + int(50 * idx / len(jobs))
                span = int(50 / len(jobs))
                await self._run_download(
                    python, worker, "modelscope", repo, target, "", size_gb,
                    progress, check_cancel, base, span)
        else:
            if not hf_token:
                raise LocalVoiceRuntimeError(
                    "PersonaPlex 权重托管在 HuggingFace 受限仓库，需要先在 "
                    "huggingface.co 接受 nvidia/personaplex-7b-v1 的许可协议，"
                    "然后在设置里填入你的 HF Access Token。 / PersonaPlex weights "
                    "live in a gated HuggingFace repo: accept the "
                    "nvidia/personaplex-7b-v1 license, then paste your HF token.")
            target = self.models_root / "hf"
            env = {"HF_HOME": str(target), "HF_TOKEN": hf_token}
            await self._run_download(
                python, worker, "hf", PERSONAPLEX_HF_REPO, target, hf_token,
                PERSONAPLEX_APPROX_GB, progress, check_cancel, 40, 55, extra_env=env)

    async def _run_download(self, python: Path, worker: Path, engine: str,
                            repo: str, target: Path, token: str,
                            size_gb: float, progress: ProgressCallback,
                            check_cancel: Callable[[], None],
                            base: int, span: int,
                            extra_env: dict[str, str] | None = None) -> None:
        """Run the download worker; report byte progress via dir-size polling."""
        target.mkdir(parents=True, exist_ok=True)
        # Silence tqdm/rich progress bars: the worker's stdout is a pipe and
        # would deadlock once the 64KB buffer fills with progress spam.
        env = {
            **os.environ,
            "TQDM_DISABLE": "1",
            "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            **(extra_env or {}),
        }
        cmd = [str(python), str(worker), "--engine", engine,
               "--repo", repo, "--target", str(target)]
        # The HF token travels via the HF_TOKEN env var (huggingface_hub picks
        # it up automatically) so it never appears in the process cmdline.
        logger.info("local_runtime download: %s", repo)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        # Drain stdout concurrently so the child can never block on a full
        # pipe buffer; keep only the tail for error reporting.
        output_tail: list[str] = []

        async def _drain() -> None:
            assert proc.stdout is not None
            async for raw in proc.stdout:
                output_tail.append(raw.decode("utf-8", errors="replace"))
                del output_tail[:-200]

        drain = asyncio.create_task(_drain())
        last_error = ""
        try:
            while proc.returncode is None:
                check_cancel()
                done = _dir_size_bytes(target)
                pct = base + min(span - 1, int(span * done / max(1, size_gb * (1 << 30))))
                progress({
                    "percent": pct, "step": "download_models",
                    "message": f"下载 {repo}：{done / (1 << 30):.1f} / ~{size_gb:.0f} GB",
                })
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass
            await drain
            output = "".join(output_tail)
            for line in output.splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "error":
                    last_error = event.get("message", "")
            if proc.returncode != 0:
                detail = last_error or output[-600:]
                raise LocalVoiceRuntimeError(
                    f"模型下载失败（{repo}）/ Model download failed ({repo}): {detail}")
            progress({"percent": base + span, "step": "download_models",
                      "message": f"{repo} 下载完成 / {repo} downloaded"})
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            if not drain.done():
                drain.cancel()

    # -- server lifecycle ----------------------------------------------------

    async def start_server(self, spec: LocalProviderSpec, hf_token: str = "") -> None:
        if not self.is_installed(spec):
            raise LocalVoiceRuntimeError(
                "本地运行时尚未安装 / Local runtime is not set up yet.")
        if self.server_running(spec):
            return
        commands = self._server_commands(spec, hf_token)
        procs: list[subprocess.Popen] = []
        try:
            for name, cmd, env_extra in commands:
                # Popen duplicates the handle for the child, so the parent's
                # copy can be closed right after spawn (no fd leak).
                with open(self.log_path(spec, name), "ab") as log_fh:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=log_fh,
                        stderr=subprocess.STDOUT,
                        env={**os.environ, **env_extra},
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                procs.append(proc)
                logger.info("local_runtime started %s pid=%s", name, proc.pid)
        except OSError:
            for proc in procs:
                if proc.poll() is None:
                    proc.kill()
            raise
        self._processes[spec.key] = procs
        # The GLM LLM worker must finish loading the 9B checkpoint before the
        # s2s server can serve; give it generous time and wait for every port.
        ports = (spec.server_port, *spec.extra_ports)
        deadline = time.monotonic() + 300
        while not all(_port_open(p) for p in ports):
            if time.monotonic() > deadline:
                await self.stop_server(spec)
                raise LocalVoiceRuntimeError(
                    "本地服务启动超时，请查看日志 / Local server startup timed out; "
                    f"see {self.log_path(spec)}")
            if any(p.poll() is not None for p in procs):
                code = next(p.returncode for p in procs if p.poll() is not None)
                # Kill the survivors (e.g. worker died but s2s is up) so a
                # failed start never leaves a half-running stack behind.
                await self.stop_server(spec)
                raise LocalVoiceRuntimeError(
                    f"本地服务进程退出（code {code}），请查看日志 / Local server "
                    f"exited (code {code}); see {self.log_path(spec)}")
            await asyncio.sleep(2)

    def _server_commands(self, spec: LocalProviderSpec,
                         hf_token: str) -> list[tuple[str, list[str], dict[str, str]]]:
        python = str(self.venv_python(spec))
        if spec.key == "GLM4Voice":
            glm_src = self.glm_source_dir()
            pythonpath = os.pathsep.join([
                str(glm_src), str(glm_src / "third_party" / "Matcha-TTS")])
            env = {"PYTHONPATH": pythonpath, "PYTHONUTF8": "1"}
            model = str(self.model_dir("glm-4-voice-9b"))
            s2s_script = self._s2s_script_path()
            return [
                ("worker", [python, str(glm_src / "model_server.py"),
                            "--host", "127.0.0.1", "--port", "10000",
                            "--model-path", model, "--dtype", "int4"], env),
                ("s2s", [python, str(s2s_script),
                         "--tokenizer-path", str(self.model_dir("glm-4-voice-tokenizer")),
                         "--model-path", model,
                         "--flow-path", str(self.model_dir("glm-4-voice-decoder")),
                         "--llm-url", "http://127.0.0.1:10000/generate_stream",
                         "--host", "127.0.0.1", "--port", "8999"], env),
            ]
        env = {"HF_HOME": str(self.models_root / "hf"), "NO_TORCH_COMPILE": "1",
               "PYTHONUTF8": "1"}
        if hf_token:
            env["HF_TOKEN"] = hf_token
        return [("server", [python, "-m", "moshi.server",
                            "--host", "127.0.0.1", "--port", "8998",
                            "--hf-repo", PERSONAPLEX_HF_REPO,
                            "--quantize-4bit"], env)]

    def _s2s_script_path(self) -> Path:
        """glm4voice_s2s_server.py: repo root in dev, bundled data when frozen."""
        if getattr(sys, "frozen", False):
            bundled = Path(getattr(sys, "_MEIPASS", ".")) / "local_runtime" / "glm4voice_s2s_server.py"
            if bundled.exists():
                return bundled
        return Path(__file__).resolve().parents[2] / "glm4voice_s2s_server.py"

    async def stop_server(self, spec: LocalProviderSpec) -> None:
        procs = self._processes.pop(spec.key, [])
        for proc in procs:
            if proc.poll() is not None:
                continue
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True, timeout=10,
                )
            else:
                proc.kill()
        # Only kill stray listeners we actually own: if we never started the
        # server (e.g. dev .bat flow), leave it alone.
        for _ in range(10):
            if not self.server_running(spec):
                break
            await asyncio.sleep(0.5)

    async def shutdown(self) -> None:
        """Kill every server this process started (backend lifespan teardown)."""
        for key in list(self._processes):
            spec = PROVIDER_SPECS.get(key)
            if spec:
                await self.stop_server(spec)

    def read_logs(self, spec: LocalProviderSpec, max_bytes: int = 20000) -> dict[str, str]:
        logs: dict[str, str] = {}
        names = ("worker", "s2s") if spec.key == "GLM4Voice" else ("server",)
        for name in names:
            path = self.log_path(spec, name)
            if not path.exists():
                continue
            size = path.stat().st_size
            with open(path, "rb") as fh:
                if size > max_bytes:
                    fh.seek(-max_bytes, os.SEEK_END)
                logs[name] = fh.read().decode("utf-8", errors="replace")
        return logs


runtime = LocalVoiceRuntime()
