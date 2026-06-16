from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import httpx

from .config_loader import BackendConfig

try:
    import edge_tts
except ImportError:
    edge_tts = None


TTS_ENGINE_EDGE = "edge"
TTS_ENGINE_QWEN_FLASH = "qwen_flash"
TTS_ENGINE_MINIMAX = "minimax"
TTS_ENGINE_XIAOMI = "xiaomi"
TTS_ENGINE_OPENAI = "openai"
TTS_ENGINE_ELEVENLABS = "elevenlabs"

SUPPORTED_TTS_ENGINES = {
    TTS_ENGINE_EDGE,
    TTS_ENGINE_QWEN_FLASH,
    TTS_ENGINE_MINIMAX,
    TTS_ENGINE_XIAOMI,
    TTS_ENGINE_OPENAI,
    TTS_ENGINE_ELEVENLABS,
}

OPENAI_VOICES = [
    {"name": "alloy", "short_name": "Alloy", "locale": "multi", "gender": "Neutral"},
    {"name": "echo", "short_name": "Echo", "locale": "multi", "gender": "Male"},
    {"name": "fable", "short_name": "Fable", "locale": "multi", "gender": "Neutral"},
    {"name": "onyx", "short_name": "Onyx", "locale": "multi", "gender": "Male"},
    {"name": "nova", "short_name": "Nova", "locale": "multi", "gender": "Female"},
    {"name": "shimmer", "short_name": "Shimmer", "locale": "multi", "gender": "Female"},
]

ELEVENLABS_VOICES = [
    {"name": "21m0aEP3W9qOfdrWSyXx", "short_name": "Rachel", "locale": "en-US", "gender": "Female"},
    {"name": "2Ezo5yI4SP56xRC3pOI3", "short_name": "Clyde", "locale": "en-US", "gender": "Male"},
    {"name": "AZnzlk1XvdvUeBnXmlld", "short_name": "Dom", "locale": "en-US", "gender": "Male"},
    {"name": "CYw3db4g4HsRz56a4v7t", "short_name": "Dave", "locale": "en-GB", "gender": "Male"},
    {"name": "ErXwobaYiN019PkySvjV", "short_name": "Antoni", "locale": "en-US", "gender": "Male"},
    {"name": "Lcfc5NaZ2c0U3L90tI6C", "short_name": "Emily", "locale": "en-US", "gender": "Female"},
    {"name": "pNInz6obpgqAjEL4s7P5", "short_name": "Adam", "locale": "en-US", "gender": "Male"},
    {"name": "pi50t7uMc9ZUB5L7vew", "short_name": "Nicole", "locale": "en-US", "gender": "Female"},
    {"name": "EXAVITQu4vr4xnSDxMaL", "short_name": "Bella", "locale": "en-US", "gender": "Female"},
]

DEFAULT_EDGE_VOICE = "zh-CN-XiaoxiaoNeural"
DEFAULT_QWEN_FLASH_MODEL = "qwen3-tts-flash-2025-11-27"
DEFAULT_MINIMAX_MODEL = "speech-02-turbo"
DEFAULT_MINIMAX_URL = "https://api.minimax.chat/v1/t2a_v2"
DEFAULT_XIAOMI_MODEL = "mimo-v2.5-tts"
DEFAULT_XIAOMI_URL = "https://api.xiaomimimo.com"

FALLBACK_EDGE_VOICES = [
    {"name": "zh-CN-XiaoxiaoNeural", "short_name": "Xiaoxiao", "locale": "zh-CN", "gender": "Female"},
    {"name": "zh-CN-YunxiNeural", "short_name": "Yunxi", "locale": "zh-CN", "gender": "Male"},
    {"name": "en-US-JennyNeural", "short_name": "Jenny", "locale": "en-US", "gender": "Female"},
    {"name": "en-US-GuyNeural", "short_name": "Guy", "locale": "en-US", "gender": "Male"},
]

QWEN_FLASH_VOICES = [
    {"name": "Cherry", "short_name": "芊悦 (Cherry)", "locale": "zh-CN", "gender": "Female"},
    {"name": "Serena", "short_name": "苏瑶 (Serena)", "locale": "zh-CN", "gender": "Female"},
    {"name": "Ethan", "short_name": "晨煦 (Ethan)", "locale": "zh-CN", "gender": "Male"},
    {"name": "Bella", "short_name": "萌宝 (Bella)", "locale": "zh-CN", "gender": "Female"},
    {"name": "Ryan", "short_name": "甜茶 (Ryan)", "locale": "zh-CN", "gender": "Male"},
    {"name": "Mia", "short_name": "乖小妹 (Mia)", "locale": "zh-CN", "gender": "Female"},
    {"name": "Moon", "short_name": "月白 (Moon)", "locale": "zh-CN", "gender": "Male"},
    {"name": "Ono Anna", "short_name": "小野杏 (Ono Anna)", "locale": "ja-JP", "gender": "Female"},
    {"name": "Sohee", "short_name": "素熙 (Sohee)", "locale": "ko-KR", "gender": "Female"},
    {"name": "Andre", "short_name": "安德雷 (Andre)", "locale": "multi", "gender": "Male"},
]

MINIMAX_VOICES = [
    {"name": "female-shaonv", "short_name": "少女音色", "locale": "zh-CN", "gender": "Female"},
    {"name": "female-yujie", "short_name": "御姐音色", "locale": "zh-CN", "gender": "Female"},
    {"name": "male-qn-jingying", "short_name": "精英青年音色", "locale": "zh-CN", "gender": "Male"},
    {"name": "male-qn-badao", "short_name": "霸道青年音色", "locale": "zh-CN", "gender": "Male"},
    {"name": "female-tianmei", "short_name": "甜美女性音色", "locale": "zh-CN", "gender": "Female"},
    {"name": "clever_boy", "short_name": "聪明男童", "locale": "zh-CN", "gender": "Male"},
    {"name": "English_Graceful_Lady", "short_name": "Graceful Lady", "locale": "en-US", "gender": "Female"},
    {"name": "English_Trustworthy_Man", "short_name": "Trustworthy Man", "locale": "en-US", "gender": "Male"},
    {"name": "Japanese_GracefulMaiden", "short_name": "Graceful Maiden", "locale": "ja-JP", "gender": "Female"},
    {"name": "Korean_CalmLady", "short_name": "Calm Lady", "locale": "ko-KR", "gender": "Female"},
]

XIAOMI_VOICES = [
    {"name": "mimo_default", "short_name": "小米默认 (mimo_default)", "locale": "zh-CN", "gender": "Female"},
    {"name": "茉莉", "short_name": "茉莉 (Moli)", "locale": "zh-CN", "gender": "Female"},
    {"name": "冰糖", "short_name": "冰糖 (Bingtang)", "locale": "zh-CN", "gender": "Female"},
    {"name": "苏打", "short_name": "苏打 (Soda)", "locale": "zh-CN", "gender": "Male"},
    {"name": "白桦", "short_name": "白桦 (Baihua)", "locale": "zh-CN", "gender": "Male"},
    {"name": "Mia", "short_name": "Mia (Mia)", "locale": "en-US", "gender": "Female"},
    {"name": "Chloe", "short_name": "Chloe (Chloe)", "locale": "en-US", "gender": "Female"},
    {"name": "Milo", "short_name": "Milo (Milo)", "locale": "en-US", "gender": "Male"},
]


class TTSService:
    def __init__(
        self,
        output_dir: Path | None = None,
        config: BackendConfig | None = None,
    ):
        self.config = config or BackendConfig()
        from .config_loader import get_data_dir
        resolved_output = output_dir or (get_data_dir() / "temp_audio")
        self.output_dir = resolved_output
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _clean_text(self, text: str) -> str:
        cleaned = text.strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", cleaned)
        cleaned = cleaned.strip()
        if not cleaned:
            raise ValueError("Text is empty after cleanup.")
        if len(cleaned) > 3000:
            raise ValueError("Text is too long. Maximum length is 3000 characters.")
        return cleaned

    def _normalize_engine(self, engine: str | None) -> str:
        candidate = str(engine or TTS_ENGINE_EDGE).strip().lower()
        if candidate not in SUPPORTED_TTS_ENGINES:
            raise ValueError(f"Unsupported TTS engine: {candidate}")
        return candidate

    def _detect_edge_voice(self, text: str) -> str:
        if re.search(r"[\u4e00-\u9fff]", text):
            return "zh-CN-XiaoxiaoNeural"
        if re.search(r"[\u3040-\u30ff]", text):
            return "ja-JP-NanamiNeural"
        if re.search(r"[\uac00-\ud7af]", text):
            return "ko-KR-SunHiNeural"
        return DEFAULT_EDGE_VOICE

    def _make_filename(self, text: str, voice: str, rate: str, engine: str) -> str:
        digest = hashlib.md5(f"{engine}|{voice}|{rate}|{text}".encode("utf-8")).hexdigest()[:16]
        return f"{engine}_{digest}.mp3"

    def _filter_by_locale(self, voices: list[dict[str, Any]], locale: str | None) -> list[dict[str, Any]]:
        if not locale:
            return voices
        return [voice for voice in voices if str(voice.get("locale", "")).startswith(locale)]

    def _dashscope_key(self) -> str:
        return self.config.get_provider_settings("DashScope").get("api_key", "").strip()

    def _minimax_settings(self) -> tuple[str, str]:
        self.config.reload()
        settings = self.config.get_all().get("minimax", {})
        api_key = str(settings.get("api_key", "")).strip()
        base_url = str(settings.get("api_url", "")).strip()
        if not base_url:
            base_url = str(self.config.get_all().get("api_urls", {}).get("MiniMax", "")).strip()
        if not base_url:
            base_url = DEFAULT_MINIMAX_URL
        if not base_url.startswith(("http://", "https://")):
            base_url = f"https://{base_url}"
        return api_key, base_url

    def _xiaomi_settings(self) -> tuple[str, str]:
        self.config.reload()
        settings = self.config.get_all().get("xiaomi", {})
        api_key = str(settings.get("api_key", "")).strip()
        base_url = str(settings.get("api_url", "")).strip()
        if not base_url:
            base_url = str(self.config.get_all().get("api_urls", {}).get("Xiaomi", "")).strip()
        if not base_url:
            base_url = DEFAULT_XIAOMI_URL
        if not base_url.startswith(("http://", "https://")):
            base_url = f"https://{base_url}"
        return api_key, base_url

    async def _generate_edge_audio(self, text: str, voice: str, rate: str, path: Path) -> None:
        if edge_tts is None:
            raise RuntimeError("edge-tts is not installed on backend.")
        communicator = edge_tts.Communicate(text, voice, rate=rate)
        await communicator.save(str(path))

    async def _generate_qwen_flash_audio(self, text: str, voice: str, path: Path) -> None:
        api_key = self._dashscope_key()
        if not api_key:
            raise RuntimeError("DashScope API Key is not configured.")
        try:
            import dashscope
            from dashscope.audio.tts_v2 import SpeechSynthesizer
        except ImportError as exc:
            raise RuntimeError("dashscope SDK is not installed on backend.") from exc

        dashscope.api_key = api_key
        synthesizer = SpeechSynthesizer(model=DEFAULT_QWEN_FLASH_MODEL, voice=voice)
        audio = synthesizer.call(text)
        path.write_bytes(audio)

    async def _generate_minimax_audio(self, text: str, voice: str, path: Path) -> None:
        api_key, base_url = self._minimax_settings()
        if not api_key:
            raise RuntimeError("MiniMax API Key is not configured.")

        payload = {
            "model": DEFAULT_MINIMAX_MODEL,
            "text": text,
            "voice_setting": {
                "voice_id": voice,
                "speed": 1.0,
                "vol": 1.0,
                "pitch": 0,
            },
            "stream": False,
            "audio_setting": {
                "sample_rate": 32000,
                "format": "mp3",
            },
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=120.0) as client:
            response = client.post(base_url, json=payload, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"MiniMax API error: {response.status_code} - {response.text}")

        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError("MiniMax returned an invalid JSON payload.") from exc

        if data.get("base_resp", {}).get("status_code", 0) != 0:
            raise RuntimeError(data.get("base_resp", {}).get("status_msg", "MiniMax TTS failed."))

        audio_obj = data.get("data", {}).get("audio")
        if isinstance(audio_obj, dict):
            audio_hex = str(audio_obj.get("data", "")).strip()
        elif isinstance(audio_obj, str):
            audio_hex = audio_obj.strip()
        else:
            audio_hex = str(data.get("audio", "")).strip()

        if not audio_hex:
            raise RuntimeError("MiniMax returned no audio data.")

        path.write_bytes(bytes.fromhex(audio_hex))

    async def _generate_xiaomi_audio(self, text: str, voice: str, path: Path) -> None:
        api_key, base_url = self._xiaomi_settings()
        if not api_key:
            raise RuntimeError("Xiaomi API Key is not configured.")

        url = f"{base_url}/v1/chat/completions"
        payload = {
            "model": DEFAULT_XIAOMI_MODEL,
            "messages": [{"role": "assistant", "content": text}],
            "audio": {
                "format": "mp3",
                "voice": voice or "mimo_default",
            },
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Run asynchronous HTTP request
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code != 200:
            raise RuntimeError(f"Xiaomi API error: {response.status_code} - {response.text}")

        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError("Xiaomi returned an invalid JSON payload.") from exc

        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError(f"Xiaomi TTS returned no choices. Response: {data}")

        message = choices[0].get("message", {})
        audio_data = message.get("audio", {}).get("data", "")
        if not audio_data:
            raise RuntimeError(f"Xiaomi TTS returned no audio data. Response: {data}")

        import base64
        audio_bytes = base64.b64decode(audio_data)
        path.write_bytes(audio_bytes)

    async def _generate_openai_audio(self, text: str, voice: str, rate: str, path: Path) -> None:
        self.config.reload()
        api_key = str(self.config.get_all().get("api_keys", {}).get("openai_api_key", "")).strip()
        if not api_key:
            raise RuntimeError("OpenAI API Key is not configured.")

        base_url = str(self.config.get_all().get("api_urls", {}).get("OpenAI", "")).strip()
        if not base_url:
            base_url = "https://api.openai.com/v1"
        if not base_url.startswith(("http://", "https://")):
            base_url = f"https://{base_url}"
        base_url = base_url.rstrip("/")

        speed = 1.0
        if rate:
            match = re.match(r"^([+-]?)(\d+)%$", rate.strip())
            if match:
                sign = match.group(1)
                percent = float(match.group(2)) / 100.0
                if sign == "-":
                    speed = max(0.25, 1.0 - percent)
                else:
                    speed = min(4.0, 1.0 + percent)

        model = self.config.get_provider_settings("OpenAI").get("model", "").strip() or "tts-1"

        payload = {
            "model": model,
            "input": text,
            "voice": voice.lower() if voice else "alloy",
            "response_format": "mp3",
            "speed": speed,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{base_url}/audio/speech", json=payload, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"OpenAI TTS API error: {response.status_code} - {response.text}")
        
        path.write_bytes(response.content)

    async def _generate_elevenlabs_audio(self, text: str, voice: str, path: Path) -> None:
        self.config.reload()
        api_key = str(self.config.get_all().get("api_keys", {}).get("elevenlabs_api_key", "")).strip()
        if not api_key:
            raise RuntimeError("ElevenLabs API Key is not configured.")

        base_url = str(self.config.get_all().get("api_urls", {}).get("ElevenLabs", "")).strip()
        if not base_url:
            base_url = "https://api.elevenlabs.io/v1"
        if not base_url.startswith(("http://", "https://")):
            base_url = f"https://{base_url}"
        base_url = base_url.rstrip("/")

        voice_id = voice or "21m0aEP3W9qOfdrWSyXx"
        url = f"{base_url}/text-to-speech/{voice_id}"

        model = self.config.get_provider_settings("ElevenLabs").get("model", "").strip() or "eleven_multilingual_v2"

        payload = {
            "text": text,
            "model_id": model,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
        }
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"ElevenLabs TTS API error: {response.status_code} - {response.text}")

        path.write_bytes(response.content)

    async def _fetch_elevenlabs_voices(self) -> list[dict[str, Any]]:
        self.config.reload()
        api_key = str(self.config.get_all().get("api_keys", {}).get("elevenlabs_api_key", "")).strip()
        if not api_key:
            return ELEVENLABS_VOICES
        
        base_url = str(self.config.get_all().get("api_urls", {}).get("ElevenLabs", "")).strip()
        if not base_url:
            base_url = "https://api.elevenlabs.io/v1"
        if not base_url.startswith(("http://", "https://")):
            base_url = f"https://{base_url}"
        base_url = base_url.rstrip("/")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{base_url}/voices", headers={"xi-api-key": api_key})
                if response.status_code == 200:
                    data = response.json()
                    voices_data = data.get("voices", [])
                    if voices_data:
                        loaded = []
                        for v in voices_data:
                            labels = v.get("labels", {})
                            gender = labels.get("gender", "Unknown")
                            accent = labels.get("accent", "multi")
                            loaded.append({
                                "name": v.get("voice_id"),
                                "short_name": f"{v.get('name')} (ElevenLabs)",
                                "locale": accent,
                                "gender": gender.capitalize(),
                            })
                        return loaded
        except Exception:
            pass
        return ELEVENLABS_VOICES

    def detect_engine_by_voice(self, voice: str | None) -> str:
        if not voice:
            return TTS_ENGINE_EDGE
        # Check OpenAI voices
        if any(v["name"] == voice for v in OPENAI_VOICES):
            return TTS_ENGINE_OPENAI
        # Check ElevenLabs voices
        if any(v["name"] == voice for v in ELEVENLABS_VOICES) or (voice and len(voice) == 20 and voice.isalnum()):
            return TTS_ENGINE_ELEVENLABS
        # 1. Check Qwen custom/designed/cloned prefixes or names
        if voice.startswith(("qwen3-tts-vd", "qwen3-tts-vc")):
            return TTS_ENGINE_QWEN_FLASH
        if any(v["name"] == voice for v in QWEN_FLASH_VOICES):
            return TTS_ENGINE_QWEN_FLASH
        # 2. Check MiniMax voices
        if any(v["name"] == voice for v in MINIMAX_VOICES):
            return TTS_ENGINE_MINIMAX
        # 3. Check Xiaomi voices
        if any(v["name"] == voice for v in XIAOMI_VOICES):
            return TTS_ENGINE_XIAOMI
        # 4. Check standard edge names
        if voice.endswith("Neural") or "-" in voice:
            return TTS_ENGINE_EDGE
        # Fallback default for other custom voice design/clones
        return TTS_ENGINE_QWEN_FLASH

    async def generate_audio(
        self,
        text: str,
        voice: str | None,
        rate: str = "+0%",
        engine: str | None = None,
    ) -> tuple[str, str, bool]:
        cleaned = self._clean_text(text)

        # Auto-detect or correct the engine based on the selected voice
        if engine is None or engine == TTS_ENGINE_EDGE:
            detected_engine = self.detect_engine_by_voice(voice)
        else:
            detected_engine = self._normalize_engine(engine)
            # If the voice is specific to another engine, correct it!
            if voice:
                detected_engine = self.detect_engine_by_voice(voice)

        normalized_engine = detected_engine

        if normalized_engine == TTS_ENGINE_EDGE:
            selected_voice = voice or self._detect_edge_voice(cleaned)
        elif normalized_engine == TTS_ENGINE_QWEN_FLASH:
            selected_voice = voice or QWEN_FLASH_VOICES[0]["name"]
        elif normalized_engine == TTS_ENGINE_MINIMAX:
            selected_voice = voice or MINIMAX_VOICES[0]["name"]
        elif normalized_engine == TTS_ENGINE_OPENAI:
            selected_voice = voice or OPENAI_VOICES[0]["name"]
        elif normalized_engine == TTS_ENGINE_ELEVENLABS:
            selected_voice = voice or ELEVENLABS_VOICES[0]["name"]
        else:
            selected_voice = voice or XIAOMI_VOICES[0]["name"]

        filename = self._make_filename(cleaned, selected_voice, rate, normalized_engine)
        path = self.output_dir / filename

        if path.exists() and path.stat().st_size > 0:
            return str(path), selected_voice, True

        if normalized_engine == TTS_ENGINE_EDGE:
            await self._generate_edge_audio(cleaned, selected_voice, rate, path)
        elif normalized_engine == TTS_ENGINE_QWEN_FLASH:
            await self._generate_qwen_flash_audio(cleaned, selected_voice, path)
        elif normalized_engine == TTS_ENGINE_MINIMAX:
            await self._generate_minimax_audio(cleaned, selected_voice, path)
        elif normalized_engine == TTS_ENGINE_OPENAI:
            await self._generate_openai_audio(cleaned, selected_voice, rate, path)
        elif normalized_engine == TTS_ENGINE_ELEVENLABS:
            await self._generate_elevenlabs_audio(cleaned, selected_voice, path)
        else:
            await self._generate_xiaomi_audio(cleaned, selected_voice, path)

        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError("Failed to generate audio file.")

        return str(path), selected_voice, False

    async def generate_dialogue_audio(
        self,
        text: str,
        voice_a: str | None,
        voice_b: str | None,
        rate: str = "+0%",
        engine: str = "edge",
    ) -> str:
        import shutil
        import uuid
        from pathlib import Path
        import re

        # 1. Parse dialogue text into alternating script lines
        lines = []
        SCRIPT_LINE_PATTERN = re.compile(r"^([ABab])[：:]\s*(.+)$")
        for raw in text.strip().splitlines():
            line = raw.strip()
            if not line:
                continue
            match = SCRIPT_LINE_PATTERN.match(line)
            if match:
                role = match.group(1).strip().upper()
                content = match.group(2).strip()
                if content:
                    lines.append({"role": role, "text": content})
            else:
                role = "A" if len(lines) % 2 == 0 else "B"
                lines.append({"role": role, "text": line})

        if not lines:
            raise ValueError("No valid dialogue lines found.")

        # 2. Synthesize each line using the respective speaker's voice
        segment_paths = []
        for idx, line in enumerate(lines):
            selected_voice = voice_a if line["role"] == "A" else voice_b
            file_path, _, _ = await self.generate_audio(
                text=line["text"],
                voice=selected_voice,
                rate=rate,
                engine=engine,
            )
            segment_paths.append(Path(file_path))

        # 3. Merge audio files using pydub (with 250ms silence gap) or binary concat fallback
        output_name = f"dialogue_{uuid.uuid4().hex[:8]}.mp3"
        output_path = self.output_dir / output_name

        try:
            from pydub import AudioSegment
            combined = None
            silence = AudioSegment.silent(duration=250)
            for idx, segment in enumerate(segment_paths):
                audio = AudioSegment.from_file(str(segment))
                if combined is None:
                    combined = audio
                else:
                    combined += silence + audio
            if combined is not None:
                combined.export(str(output_path), format="mp3", bitrate="192k")
                return str(output_path)
        except Exception:
            pass

        # Fallback merge via concat
        with output_path.open("wb") as target:
            for segment in segment_paths:
                with segment.open("rb") as source:
                    shutil.copyfileobj(source, target, length=1024 * 1024)

        return str(output_path)

    def _clean_edge_voice_short_name(self, short_name: str) -> str:
        if "-" in short_name:
            short_name = short_name.split("-")[-1]
        if short_name.endswith("Neural"):
            short_name = short_name[:-6]
        return short_name

    async def list_voices(
        self,
        locale: str | None = None,
        engine: str = TTS_ENGINE_EDGE,
    ) -> list[dict[str, Any]]:
        normalized_engine = self._normalize_engine(engine)
        if normalized_engine == TTS_ENGINE_QWEN_FLASH:
            return self._filter_by_locale(QWEN_FLASH_VOICES, locale)
        if normalized_engine == TTS_ENGINE_MINIMAX:
            return self._filter_by_locale(MINIMAX_VOICES, locale)
        if normalized_engine == TTS_ENGINE_XIAOMI:
            return self._filter_by_locale(XIAOMI_VOICES, locale)
        if normalized_engine == TTS_ENGINE_OPENAI:
            return self._filter_by_locale(OPENAI_VOICES, locale)
        if normalized_engine == TTS_ENGINE_ELEVENLABS:
            voices = await self._fetch_elevenlabs_voices()
            return self._filter_by_locale(voices, locale)

        if edge_tts is None:
            return self._filter_by_locale(FALLBACK_EDGE_VOICES, locale)

        try:
            voices_manager = await edge_tts.VoicesManager.create()
            voices = voices_manager.voices
            normalized = [
                {
                    "name": item.get("Name", ""),
                    "short_name": self._clean_edge_voice_short_name(item.get("ShortName", "")),
                    "locale": item.get("Locale", ""),
                    "gender": item.get("Gender", ""),
                }
                for item in voices
            ]
            normalized = [v for v in normalized if v["name"]]
            return self._filter_by_locale(normalized, locale)
        except Exception:
            return self._filter_by_locale(FALLBACK_EDGE_VOICES, locale)
