"""Model downloader script for VoiceSpirit local realtime voice engines.

Downloads GLM-4-Voice (9B) and Sesame CSM-1B from HF Mirror using stored HF_TOKEN
with automatic retry for uninterrupted large file downloads.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from huggingface_hub import snapshot_download

# Force UTF-8 output encoding for Windows CMD
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Use HF mirror for high-speed download in China
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


def download_with_retry(name: str, repo_id: str, requires_token: bool, max_retries: int = 15) -> bool:
    token = HF_TOKEN if requires_token else None
    for attempt in range(1, max_retries + 1):
        print(f"[{name}] Starting/Resuming download for {repo_id} (Attempt {attempt}/{max_retries})...")
        try:
            path = snapshot_download(
                repo_id=repo_id,
                token=token,
                resume_download=True,
                max_workers=4,
            )
            print(f"[OK] [{name}] Download complete -> {path}\n")
            return True
        except Exception as exc:
            print(f"[WARN] [{name}] Attempt {attempt} failed: {exc}")
            if attempt < max_retries:
                print("Retrying in 5 seconds...")
                time.sleep(5)
            else:
                print(f"[FAIL] [{name}] Failed after {max_retries} attempts.\n")
                return False
    return False


def download_all():
    print("=" * 60)
    print(" VoiceSpirit Local Realtime Models Downloader")
    print("=" * 60)
    print(f"HF Mirror Endpoint: {os.environ['HF_ENDPOINT']}")
    print(f"Hugging Face Token: {'Detected (' + HF_TOKEN[:10] + '...)' if HF_TOKEN else 'Not set'}\n")

    success_count = 0
    for name, repo_id, requires_token in MODELS:
        if download_with_retry(name, repo_id, requires_token):
            success_count += 1

    print("=" * 60)
    print(f" Download summary: {success_count}/{len(MODELS)} models ready!")
    print("=" * 60)


if __name__ == "__main__":
    download_all()
