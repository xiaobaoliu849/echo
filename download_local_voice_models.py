"""Model downloader script for VoiceSpirit local realtime voice engines.

Per-file resilient downloader with automatic resume and unbuffered stdout logging.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from huggingface_hub import HfApi, hf_hub_download

# Force unbuffered UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

os.environ["PYTHONUNBUFFERED"] = "1"
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

TOKEN_FILE = Path.home() / ".cache" / "huggingface" / "token"
HF_TOKEN = None
if TOKEN_FILE.exists():
    HF_TOKEN = TOKEN_FILE.read_text(encoding="utf-8").strip()

MODELS = [
    ("GLM-4-Voice 9B", "THUDM/glm-4-voice-9b", False),
    ("GLM-4-Voice Decoder", "THUDM/glm-4-voice-decoder", False),
    ("GLM-4-Voice Tokenizer", "THUDM/glm-4-voice-tokenizer", False),
    ("Sesame CSM-1B", "sesame/csm-1b", True),
    ("Llama 3.2 1B (Sesame Backbone)", "meta-llama/Llama-3.2-1B", True),
]


def log_print(msg: str):
    print(msg, flush=True)


def download_repo_files(name: str, repo_id: str, requires_token: bool) -> bool:
    token = HF_TOKEN if requires_token else None
    api = HfApi(token=token)
    try:
        log_print(f"\n[{name}] Fetching file list for {repo_id}...")
        files = api.list_repo_files(repo_id=repo_id)
        log_print(f"[{name}] Found {len(files)} files in repository.")
    except Exception as exc:
        log_print(f"[FAIL] [{name}] Could not list files for {repo_id}: {exc}")
        return False

    success_files = 0
    for file in files:
        if file.startswith(".git") or file.endswith(".gitattributes"):
            continue

        file_done = False
        for attempt in range(1, 20):
            log_print(f"[{name}] Downloading file: {file} (Attempt {attempt}/20)...")
            try:
                hf_hub_download(
                    repo_id=repo_id,
                    filename=file,
                    token=token,
                    resume_download=True,
                )
                log_print(f"[OK] [{name}] File ready: {file}")
                file_done = True
                break
            except Exception as exc:
                log_print(f"[WARN] [{name}] File {file} attempt {attempt} failed: {exc}")
                time.sleep(3)

        if file_done:
            success_files += 1

    log_print(f"[SUMMARY] [{name}] Downloaded {success_files} files for {repo_id}.\n")
    return True


def download_all():
    log_print("=" * 60)
    log_print(" VoiceSpirit Resilient Local Voice Models Downloader")
    log_print("=" * 60)
    log_print(f"HF Mirror Endpoint: {os.environ['HF_ENDPOINT']}")
    log_print(f"Hugging Face Token: {'Detected (' + HF_TOKEN[:10] + '...)' if HF_TOKEN else 'Not set'}\n")

    for name, repo_id, requires_token in MODELS:
        download_repo_files(name, repo_id, requires_token)

    log_print("=" * 60)
    log_print(" All local voice model downloads finished!")
    log_print("=" * 60)


if __name__ == "__main__":
    download_all()
