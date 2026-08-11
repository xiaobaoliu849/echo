"""GLM-4-Voice realtime speech-to-speech WebSocket server (VoiceSpirit edition).

Reuses the official THUDM/GLM-4-Voice pipeline exactly like web_demo.py does:

    user audio -> WhisperVQEncoder (speech tokenizer) -> speech tokens
        -> model_server.py (/generate_stream, the GLM-4-Voice-9B worker)
        -> streamed text + speech tokens -> AudioDecoder (CosyVoice flow + HiFi-GAN)
        -> reply audio back to the client

The LLM worker runs as a separate process (model_server.py on port 10000);
this script only loads the (small) tokenizer + decoder and proxies.

Wire protocol (matches backend/services/realtime_glm4voice_provider.py):

  * binary  0x01 + PCM16 mono @ 22050 Hz   client -> server : user audio frames
  * binary  0x01 + PCM16 mono @ 22050 Hz   server -> client : reply audio chunks
  * text    0x02 + utf-8                   server -> client : handshake / assistant text
  * text    JSON {"type": "ping"|"stop"}   client -> server : control

Usage:
    python glm4voice_s2s_server.py --tokenizer-path <glm-4-voice-tokenizer> \
        --model-path <glm-4-voice-9b> --flow-path <glm-4-voice-decoder> \
        --llm-url http://127.0.0.1:10000/generate_stream --port 8999
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import os
import sys
import time
import uuid
from typing import Any, Callable

import fastapi
import numpy as np
import uvicorn

logger = logging.getLogger("glm4voice_s2s")

SAMPLE_RATE = 22050
_MSG_AUDIO = 1
_MSG_TEXT = 2

# VAD parameters (RMS energy based).  Defaults are overridable on the command
# line so the mic/room can be tuned without editing this file.
VAD_FRAME_MS = 20
VAD_THRESHOLD = 900          # int16 RMS threshold for "speech" (~ -37 dBFS)
VAD_MIN_SPEECH_S = 0.40      # longest *consecutive* speech run needed to arm a turn
VAD_TRAIL_SILENCE_S = 0.55   # trailing silence that closes the turn
VAD_MAX_TURN_S = 12.0        # hard cap: force-close the turn
VAD_PREROLL_S = 0.25         # audio retained ahead of speech onset
VAD_MAX_UTTERANCE_S = 20.0   # never send more than this much audio to the encoder
POST_TURN_COOLDOWN_S = 0.30  # ignore the mic briefly after we stop speaking

# The prompt carries every previous turn as raw audio/text tokens, so it grows by
# ~12.5 tokens per second of conversation.  Prefill is the dominant cost on an
# int4 worker, so keep only the most recent exchanges.
MAX_HISTORY_TURNS = 4

# Audio tokens per streamed decode block.  The first block gates time-to-first-
# sound, so it is much smaller than upstream's 25; later blocks grow to amortize
# the flow-matching decoder.
BLOCK_SIZE_LIST = (10, 25, 50, 100, 150, 200)

DEFAULT_SYSTEM_PROMPT = (
    "User will provide you with a speech instruction. Do it step by step. "
    "First, think about the instruction and respond in a interleaved manner, "
    "with 13 text token followed by 26 audio tokens."
)

_GLOBAL_GENERATION_LOCK: asyncio.Lock | None = None


def _pcm16_to_float(data: bytes) -> np.ndarray:
    if not data:
        return np.zeros(0, dtype=np.float32)
    s16 = np.frombuffer(data, dtype=np.int16)
    return s16.astype(np.float32) / 32768.0


def _float_to_pcm16(data: np.ndarray) -> bytes:
    clipped = np.clip(data, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16).tobytes()


class Glm4VoicePipeline:
    """Owns the tokenizer + decoder and the streaming conversation logic."""

    def __init__(
        self,
        tokenizer_path: str,
        model_path: str,
        flow_path: str,
        llm_url: str,
        device: str,
        max_history_turns: int = MAX_HISTORY_TURNS,
        block_size_list: tuple[int, ...] = BLOCK_SIZE_LIST,
    ) -> None:
        self.tokenizer_path = tokenizer_path
        self.model_path = model_path
        self.flow_path = flow_path
        self.llm_url = llm_url
        self.device = device
        self.max_history_turns = max_history_turns
        self.block_size_list = block_size_list
        self.whisper_model = None
        self.feature_extractor = None
        self.text_tokenizer = None
        self.audio_decoder = None
        self._audio_offset = None

    def load(self) -> None:
        import torch

        # diffusers 0.27.x imports huggingface_hub.cached_download at module
        # import time, but recent huggingface_hub removed it.  The decoder only
        # loads local checkpoints, so a raising stub is enough to satisfy the
        # import and never gets called.
        import huggingface_hub

        if not hasattr(huggingface_hub, "cached_download"):

            def _cached_download_unavailable(*args, **kwargs):
                raise RuntimeError(
                    "huggingface_hub.cached_download is unavailable in this environment; "
                    "GLM-4-Voice decoder uses local checkpoints."
                )

            huggingface_hub.cached_download = _cached_download_unavailable

        from transformers import (
            AutoTokenizer,
            WhisperFeatureExtractor,
        )
        from speech_tokenizer.modeling_whisper import WhisperVQEncoder
        from speech_tokenizer.utils import extract_speech_token  # noqa: F401
        from flow_inference import AudioDecoder

        logger.info("Loading GLM-4-Voice tokenizer from %s ...", self.tokenizer_path)
        self.whisper_model = WhisperVQEncoder.from_pretrained(self.tokenizer_path).eval().to(self.device)
        self.feature_extractor = WhisperFeatureExtractor.from_pretrained(self.tokenizer_path)

        logger.info("Loading text tokenizer from %s ...", self.model_path)
        self.text_tokenizer = AutoTokenizer.from_pretrained(self.model_path, trust_remote_code=True)

        logger.info("Loading GLM-4-Voice decoder from %s ...", self.flow_path)
        self.audio_decoder = AudioDecoder(
            config_path=os.path.join(self.flow_path, "config.yaml"),
            flow_ckpt_path=os.path.join(self.flow_path, "flow.pt"),
            hift_ckpt_path=os.path.join(self.flow_path, "hift.pt"),
            device=self.device,
        )
        self._audio_offset = self.text_tokenizer.convert_tokens_to_ids("<|audio_0|>")

        # Warm up the decoder: the first token2wav call pays one-off CUDA kernel
        # compile / init costs that otherwise land on the user's first turn.
        logger.info("Warming up GLM-4-Voice decoder ...")
        with torch.no_grad():
            warmup = torch.zeros(1, 25, dtype=torch.int64, device=self.device)
            self.audio_decoder.token2wav(
                warmup,
                uuid="warmup",
                prompt_token=torch.zeros(1, 0, dtype=torch.int64, device=self.device),
                prompt_feat=torch.zeros(1, 0, 80, device=self.device),
                finalize=True,
            )
        logger.info("GLM-4-Voice pipeline ready (sample_rate=%d).", SAMPLE_RATE)

    def _encode_utterance(self, pcm16: bytes) -> str:
        """PCM16@22050 -> serialized <|audio_x|> token string."""
        import torch

        from speech_tokenizer.utils import extract_speech_token

        # extract_speech_token accepts (waveform, sample_rate) tuples, so the
        # utterance goes straight to the GPU instead of through a temp WAV that
        # torchaudio would immediately read back.
        wav = torch.from_numpy(_pcm16_to_float(pcm16)).unsqueeze(0)
        tokens = extract_speech_token(
            self.whisper_model, self.feature_extractor, [(wav, SAMPLE_RATE)]
        )[0]
        if not tokens:
            raise ValueError("No audio tokens extracted from the utterance.")
        inner = "".join(f"<|audio_{int(t)}|>" for t in tokens)
        return f"<|begin_of_audio|>{inner}<|end_of_audio|>"

    @staticmethod
    def _trim_history(prompt: str, max_turns: int) -> str:
        """Keep the system header plus the most recent `max_turns` exchanges."""
        if max_turns <= 0 or not prompt:
            return prompt
        parts = prompt.split("<|user|>")
        if len(parts) <= max_turns + 1:
            return prompt
        return parts[0] + "<|user|>" + "<|user|>".join(parts[-max_turns:])

    def _run_turn(
        self,
        prompt: str,
        system_prompt: str,
        pcm16: bytes,
        *,
        temperature: float = 0.8,
        top_p: float = 0.8,
        max_new_tokens: int = 512,
        chunk_sink: Callable[[tuple[str, Any]], None] | None = None,
    ) -> tuple[str, list[tuple[str, Any]]]:
        """Encode user audio, stream the LLM reply, decode audio blocks.

        Returns (next_prompt, chunks) where each chunk is ("audio", bytes) or
        ("text", str).  When chunk_sink is provided, every chunk is pushed to
        it the moment it is ready so the caller can stream replies as they are
        decoded instead of waiting for the whole turn.
        """
        import requests
        import torch

        t_prof = {"start": time.monotonic()}
        user_input = self._encode_utterance(pcm16)
        t_prof["encode"] = time.monotonic()

        inputs = self._trim_history(prompt, self.max_history_turns)
        if "<|system|>" not in inputs:
            inputs += f"<|system|>\n{system_prompt}"
        inputs += f"<|user|>\n{user_input}<|assistant|>streaming_transcription\n"

        response = requests.post(
            self.llm_url,
            data=json.dumps(
                {
                    "prompt": inputs,
                    "temperature": temperature,
                    "top_p": top_p,
                    "max_new_tokens": max_new_tokens,
                }
            ),
            stream=True,
            timeout=(10, 600),
        )
        response.raise_for_status()

        audio_offset = self._audio_offset
        end_token_id = self.text_tokenizer.convert_tokens_to_ids("<|user|>")

        text_tokens: list[int] = []
        audio_tokens: list[int] = []
        all_completion_segments: list[tuple[str, Any]] = []  # ("text", ids) | ("audio", ids)
        chunks: list[tuple[str, Any]] = []

        def _emit(kind: str, payload: Any) -> None:
            if chunk_sink is not None:
                chunk_sink((kind, payload))
            else:
                chunks.append((kind, payload))

        tts_mels: list[Any] = []
        flow_prompt_speech_token = torch.zeros(1, 0, dtype=torch.int64).to(self.device)
        this_uuid = str(uuid.uuid4())
        prev_mel = None
        is_finalize = False
        block_size_list = list(self.block_size_list)
        block_size_idx = 0
        block_size = block_size_list[block_size_idx]

        first_block = True

        for line in response.iter_lines(chunk_size=1):
            if not line:
                continue
            token_id = json.loads(line)["token_id"]
            if "llm_first_byte" not in t_prof:
                t_prof["llm_first_byte"] = time.monotonic()
            if token_id == end_token_id:
                is_finalize = True

            # Flush accumulated audio tokens (official web_demo order: the
            # end-of-turn token triggers one last decode of the pending block).
            if len(audio_tokens) >= block_size or (is_finalize and audio_tokens):
                if block_size_idx < len(block_size_list) - 1:
                    block_size_idx += 1
                    block_size = block_size_list[block_size_idx]
                tts_token = torch.tensor(audio_tokens, device=self.device).unsqueeze(0)

                prompt_feat = None
                if prev_mel is not None:
                    prompt_feat = torch.cat(tts_mels, dim=-1).transpose(1, 2)
                if prompt_feat is None:
                    prompt_feat = torch.zeros(1, 0, 80).to(self.device)

                tts_speech, tts_mel = self.audio_decoder.token2wav(
                    tts_token,
                    uuid=this_uuid,
                    prompt_token=flow_prompt_speech_token.to(self.device),
                    prompt_feat=prompt_feat.to(self.device),
                    finalize=is_finalize,
                )
                prev_mel = tts_mel
                tts_mels.append(tts_mel)
                flow_prompt_speech_token = torch.cat((flow_prompt_speech_token, tts_token), dim=-1)

                pcm = _float_to_pcm16(tts_speech.detach().cpu().numpy()[0])
                block_tokens = len(audio_tokens)
                _emit("audio", pcm)
                audio_tokens = []
                if first_block:
                    first_block = False
                    t_prof["decode_first_block"] = time.monotonic()
                    logger.info(
                        "glm4voice_turn_profile encode=%.2fs llm_first_byte=%.2fs "
                        "decode_first_block=%.2fs total_to_first_audio=%.2fs "
                        "(utterance=%.2fs, prompt_chars=%d, block_tokens=%d)",
                        t_prof["encode"] - t_prof["start"],
                        t_prof["llm_first_byte"] - t_prof["encode"],
                        t_prof["decode_first_block"] - t_prof["llm_first_byte"],
                        t_prof["decode_first_block"] - t_prof["start"],
                        len(pcm16) / 2 / SAMPLE_RATE,
                        len(inputs),
                        block_tokens,
                    )

            # The end-of-turn token is a delimiter, never part of the reply.
            if not is_finalize:
                if token_id >= audio_offset:
                    audio_tokens.append(token_id - audio_offset)
                    all_completion_segments.append(("audio", token_id - audio_offset))
                else:
                    text_tokens.append(token_id)
                    all_completion_segments.append(("text", token_id))

        if is_finalize:
            # Serialize the assistant completion so the next turn keeps context.
            completion_parts: list[str] = []
            text_run: list[int] = []
            for kind, value in all_completion_segments:
                if kind == "text":
                    text_run.append(value)
                else:
                    if text_run:
                        completion_parts.append(
                            self.text_tokenizer.decode(text_run, spaces_between_special_tokens=False)
                        )
                        text_run = []
                    completion_parts.append(f"<|audio_{value}|>")
            if text_run:
                completion_parts.append(
                    self.text_tokenizer.decode(text_run, spaces_between_special_tokens=False)
                )
            completion = "".join(completion_parts).strip()
            next_prompt = inputs + completion + "\n"
            if text_tokens:
                _emit(
                    "text",
                    self.text_tokenizer.decode(text_tokens, spaces_between_special_tokens=False),
                )
            return next_prompt, chunks

        return inputs, chunks

    async def _stream_turn(
        self,
        prompt: str,
        system_prompt: str,
        pcm16: bytes,
    ) -> tuple[asyncio.Queue[tuple[str, Any]], asyncio.Task[Any]]:
        """Run _run_turn in a worker thread, streaming chunks through a queue.

        Queue items are ("audio", bytes), ("text", str), ("error", Exception)
        or ("done", next_prompt).  Caller must await the task after the loop.
        """
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        async def produce() -> None:
            try:
                next_prompt, _ = await asyncio.to_thread(
                    self._run_turn,
                    prompt,
                    system_prompt,
                    pcm16,
                    chunk_sink=queue.put_nowait,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("turn failed")
                queue.put_nowait(("error", exc))
                return
            queue.put_nowait(("done", next_prompt))

        task = asyncio.create_task(produce())
        return queue, task


class VadConfig:
    """Tunable VAD thresholds (mutable copy of the module defaults)."""

    def __init__(self) -> None:
        self.threshold = VAD_THRESHOLD
        self.min_speech_s = VAD_MIN_SPEECH_S
        self.trail_silence_s = VAD_TRAIL_SILENCE_S
        self.max_turn_s = VAD_MAX_TURN_S
        self.preroll_s = VAD_PREROLL_S
        self.max_utterance_s = VAD_MAX_UTTERANCE_S


class ConversationState:
    def __init__(self, system_prompt: str, vad: VadConfig | None = None) -> None:
        self.system_prompt = system_prompt
        self.vad = vad or VadConfig()
        self.prompt = ""
        self.buffer = bytearray()
        self.trailing_silence_s = 0.0
        self.speech_s = 0.0
        self.last_energy_sample = 0.0
        self.turn_started = time.monotonic()
        # While the assistant is generating/speaking we drop mic input entirely:
        # the controller cannot act on it anyway, and keeping it would fold the
        # reply's own echo plus seconds of silence into the *next* utterance.
        self.muted = False

    def reset_turn_tracking(self) -> None:
        self.trailing_silence_s = 0.0
        self.speech_s = 0.0
        self.turn_started = time.monotonic()

    def _frame_energy(self, frame: np.ndarray) -> float:
        if frame.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(frame.astype(np.float32)))))

    def feed_audio(self, data: bytes) -> None:
        if self.muted:
            return
        self.buffer.extend(data)

    def clear(self) -> None:
        self.buffer.clear()
        self.reset_turn_tracking()

    def turn_ready(self) -> bool:
        """Check VAD on the buffered audio; returns True when to run a turn.

        Also trims the buffer in place: silence ahead of speech onset is dropped
        (apart from a short pre-roll) so a caller who stays quiet for a minute
        does not hand the encoder a minute of silence to tokenize.
        """
        vad = self.vad
        frame = VAD_FRAME_MS * SAMPLE_RATE // 1000
        frame_bytes = frame * 2
        n_frames = len(self.buffer) // frame_bytes
        if n_frames == 0:
            return False

        s16 = np.frombuffer(self.buffer[: n_frames * frame_bytes], dtype=np.int16)
        frames = s16.reshape(n_frames, frame)
        energies = np.sqrt(np.mean(np.square(frames.astype(np.float32)), axis=1))
        is_speech = energies > vad.threshold

        preroll_frames = max(1, int(vad.preroll_s * 1000 / VAD_FRAME_MS))

        if not bool(is_speech.any()):
            # Pure silence: keep only a short pre-roll so the buffer cannot grow
            # without bound while nobody is talking.
            keep = min(n_frames, preroll_frames)
            drop_bytes = (n_frames - keep) * frame_bytes
            if drop_bytes > 0:
                del self.buffer[:drop_bytes]
                self.turn_started = time.monotonic()
            self.speech_s = 0.0
            self.trailing_silence_s = 0.0
            return False

        speech_idx = np.flatnonzero(is_speech)
        onset = int(speech_idx[0])

        # Drop everything before the pre-roll ahead of speech onset.
        drop_frames = max(0, onset - preroll_frames)
        if drop_frames > 0:
            del self.buffer[: drop_frames * frame_bytes]
            energies = energies[drop_frames:]
            is_speech = is_speech[drop_frames:]
            n_frames -= drop_frames
            self.turn_started = time.monotonic() - (n_frames * VAD_FRAME_MS / 1000.0)

        # Longest *consecutive* speech run, so isolated clicks/keystrokes do not
        # accumulate into a false turn the way a total-frame count does.
        longest = 0
        run = 0
        for flag in is_speech:
            if flag:
                run += 1
                longest = max(longest, run)
            else:
                run = 0
        trailing = int(n_frames - 1 - np.flatnonzero(is_speech)[-1])

        self.speech_s = longest * VAD_FRAME_MS / 1000.0
        self.trailing_silence_s = trailing * VAD_FRAME_MS / 1000.0
        elapsed = n_frames * VAD_FRAME_MS / 1000.0

        has_speech = self.speech_s >= vad.min_speech_s
        closed_by_silence = has_speech and self.trailing_silence_s >= vad.trail_silence_s
        closed_by_timeout = has_speech and elapsed >= vad.max_turn_s
        return bool(closed_by_silence or closed_by_timeout)

    def take_utterance(self) -> bytes | None:
        if not self.buffer:
            return None
        max_bytes = int(self.vad.max_utterance_s * SAMPLE_RATE) * 2
        if len(self.buffer) > max_bytes:
            # Keep the tail: the most recent speech is what the user just said.
            data = bytes(self.buffer[-max_bytes:])
        else:
            data = bytes(self.buffer)
        self.buffer.clear()
        self.reset_turn_tracking()
        return data


async def handle_connection(
    ws: Any,
    pipeline: Glm4VoicePipeline,
    system_prompt: str,
    vad: VadConfig | None = None,
) -> None:
    await ws.accept()
    # Handshake: any first message from the server is treated as success by the
    # VoiceSpirit provider; send a text line so it also carries intent.
    await ws.send_bytes(bytes([_MSG_TEXT]) + "GLM-4-Voice ready".encode("utf-8"))

    state = ConversationState(system_prompt, vad)
    closed = asyncio.Event()

    async def reader() -> None:
        nonlocal state
        try:
            while True:
                message = await ws.receive()
                mtype = message.get("type")
                if mtype == "websocket.disconnect":
                    break
                if mtype == "websocket.receive":
                    if message.get("bytes"):
                        raw = message["bytes"]
                        if raw and raw[0] == _MSG_AUDIO:
                            state.feed_audio(raw[1:])
                    elif message.get("text"):
                        text = message["text"]
                        if text.startswith("\x02"):
                            text = text[1:]
                        try:
                            payload = json.loads(text)
                            if payload.get("type") == "stop":
                                break
                        except Exception:
                            pass
        except Exception:
            pass
        finally:
            closed.set()

    async def controller() -> None:
        nonlocal state
        global _GLOBAL_GENERATION_LOCK
        while not closed.is_set():
            await asyncio.sleep(0.04)
            if state.turn_ready():
                utterance = state.take_utterance()
                if not utterance:
                    continue
                logger.info(
                    "glm4voice_turn_start utterance=%dB speech=%.2fs trail=%.2fs",
                    len(utterance), state.speech_s, state.trailing_silence_s,
                )
                async with _GLOBAL_GENERATION_LOCK:
                    if closed.is_set():
                        return
                    # Deafen the mic for the whole reply.  Nothing can act on the
                    # audio until the turn ends, and keeping it would splice the
                    # reply's own speaker echo into the next utterance.
                    state.muted = True
                    try:
                        queue, produce_task = await pipeline._stream_turn(
                            state.prompt, state.system_prompt, utterance
                        )
                        while True:
                            kind, payload = await queue.get()
                            if closed.is_set():
                                break
                            if kind == "done":
                                state.prompt = payload
                                break
                            if kind == "error":
                                try:
                                    await ws.send_bytes(
                                        bytes([_MSG_TEXT])
                                        + f"GLM-4-Voice 会话错误: {payload}".encode("utf-8")
                                    )
                                except Exception:
                                    break
                                break
                            if kind == "audio":
                                await ws.send_bytes(bytes([_MSG_AUDIO]) + payload)
                            else:
                                await ws.send_bytes(bytes([_MSG_TEXT]) + str(payload).encode("utf-8"))
                        if not produce_task.done():
                            produce_task.cancel()
                        try:
                            await produce_task
                        except asyncio.CancelledError:
                            pass
                    finally:
                        # Let the tail of the reply finish leaving the speakers
                        # before listening again, then start from a clean buffer.
                        await asyncio.sleep(POST_TURN_COOLDOWN_S)
                        state.clear()
                        state.muted = False

    reader_task = asyncio.create_task(reader())
    controller_task = asyncio.create_task(controller())
    await asyncio.wait([reader_task, controller_task], return_when=asyncio.FIRST_COMPLETED)
    controller_task.cancel()
    try:
        await controller_task
    except asyncio.CancelledError:
        pass
    try:
        await ws.close()
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="GLM-4-Voice S2S WebSocket server")
    parser.add_argument("--tokenizer-path", required=True, help="glm-4-voice-tokenizer directory")
    parser.add_argument("--model-path", required=True, help="glm-4-voice-9b directory (for text tokenizer)")
    parser.add_argument("--flow-path", required=True, help="glm-4-voice-decoder directory (config.yaml/flow.pt/hift.pt)")
    parser.add_argument("--llm-url", default="http://127.0.0.1:10000/generate_stream")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8999)
    parser.add_argument("--device", default="cuda" if os.environ.get("CUDA_VISIBLE_DEVICES", "") else "cuda")
    parser.add_argument(
        "--vad-threshold", type=float, default=VAD_THRESHOLD,
        help="int16 RMS threshold for speech; raise it if the mic self-triggers",
    )
    parser.add_argument(
        "--vad-min-speech", type=float, default=VAD_MIN_SPEECH_S,
        help="seconds of consecutive speech needed before a turn can close",
    )
    parser.add_argument(
        "--vad-trail-silence", type=float, default=VAD_TRAIL_SILENCE_S,
        help="trailing silence that closes a turn; lower reacts faster",
    )
    parser.add_argument(
        "--max-history-turns", type=int, default=MAX_HISTORY_TURNS,
        help="conversation turns kept in the prompt (0 = unbounded, slower)",
    )
    parser.add_argument(
        "--first-block-tokens", type=int, default=BLOCK_SIZE_LIST[0],
        help="audio tokens in the first decode block; lower speaks sooner",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    global _GLOBAL_GENERATION_LOCK
    _GLOBAL_GENERATION_LOCK = asyncio.Lock()

    vad = VadConfig()
    vad.threshold = args.vad_threshold
    vad.min_speech_s = args.vad_min_speech
    vad.trail_silence_s = args.vad_trail_silence

    block_sizes = tuple(
        [max(1, args.first_block_tokens)]
        + [b for b in BLOCK_SIZE_LIST[1:] if b > args.first_block_tokens]
    ) or (max(1, args.first_block_tokens),)

    pipeline = Glm4VoicePipeline(
        tokenizer_path=args.tokenizer_path,
        model_path=args.model_path,
        flow_path=args.flow_path,
        llm_url=args.llm_url,
        device=args.device,
        max_history_turns=args.max_history_turns,
        block_size_list=block_sizes,
    )

    try:
        pipeline.load()
    except Exception as exc:
        logger.error("Failed to initialize GLM-4-Voice pipeline: %s", exc)
        return 1

    app = fastapi.FastAPI()

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "model": "GLM-4-Voice-9B", "sample_rate": SAMPLE_RATE}

    @app.websocket("/api/chat")
    async def api_chat(websocket: fastapi.WebSocket) -> None:
        query = dict(websocket.query_params)
        system_prompt = str(query.get("text_prompt", "")).strip() or DEFAULT_SYSTEM_PROMPT
        try:
            await handle_connection(websocket, pipeline, system_prompt, vad)
        except Exception:
            logger.exception("websocket handler failed")

    logger.info("GLM-4-Voice S2S server listening on ws://%s:%d/api/chat", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
