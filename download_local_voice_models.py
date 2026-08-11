"""Model downloader script for VoiceSpirit local realtime voice engines.

Downloads GLM-4-Voice (9B) and Sesame CSM-1B from HF Mirror using stored HF_TOKEN.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from huggingface_hub import snapshot_download

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


def download_all():
    print("=" * 60)
    print(" VoiceSpirit Local Realtime Models Downloader")
    print("=" * 60)
    print(f"HF Mirror Endpoint: {os.environ['HF_ENDPOINT']}")
    print(f"Hugging Face Token: {'Detected (' + HF_TOKEN[:10] + '...)' if HF_TOKEN else 'Not set'}\n")

    for name, repo_id, requires_token in MODELS:
        print(f"[{name}] Starting download for {repo_id}...")
        token = HF_TOKEN if requires_token else None
        try:
            path = snapshot_download(
                repo_id=repo_id,
                token=token,
                resume_download=True,
            )
            print(f"✓ [{name}] Download complete -> {path}\n")
        except Exception as exc:
            print(f"✗ [{name}] Error downloading {repo_id}: {exc}\n")

    print("=" * 60)
    print(" All local voice model downloads finished!")
    print("=" * 60)


if __name__ == "__main__":
    download_all()
