"""ModelScope Ultra-Fast Downloader script for VoiceSpirit local realtime voice engines.

Downloads GLM-4-Voice using ModelScope high-speed CDN.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from modelscope.hub.snapshot_download import snapshot_download

# Force unbuffered UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

os.environ["PYTHONUNBUFFERED"] = "1"

MODELS = [
    ("GLM-4-Voice 9B", "ZhipuAI/glm-4-voice-9b"),
    ("GLM-4-Voice Decoder", "ZhipuAI/glm-4-voice-decoder"),
    ("GLM-4-Voice Tokenizer", "ZhipuAI/glm-4-voice-tokenizer"),
]


def log_print(msg: str):
    print(msg, flush=True)


def download_modelscope_repo(name: str, repo_id: str, max_retries: int = 10) -> bool:
    for attempt in range(1, max_retries + 1):
        log_print(f"\n[{name}] Starting/Resuming download for ModelScope {repo_id} (Attempt {attempt}/{max_retries})...")
        try:
            path = snapshot_download(repo_id=repo_id)
            log_print(f"[OK] [{name}] Complete! Local cache path: {path}")
            return True
        except Exception as exc:
            log_print(f"[WARN] [{name}] Attempt {attempt} failed: {exc}")
            if attempt < max_retries:
                time.sleep(3)
    return False


def download_all():
    log_print("=" * 60)
    log_print(" VoiceSpirit ModelScope High-Speed Models Downloader")
    log_print("=" * 60)

    success_count = 0
    for name, repo_id in MODELS:
        if download_modelscope_repo(name, repo_id):
            success_count += 1

    log_print("\n" + "=" * 60)
    log_print(f" Download summary: {success_count}/{len(MODELS)} models ready!")
    log_print("=" * 60)


if __name__ == "__main__":
    download_all()
