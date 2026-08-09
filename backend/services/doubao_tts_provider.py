from __future__ import annotations

import base64
import json
import uuid
from typing import AsyncGenerator

import httpx

DOUBAO_VOICES = [
    # 大模型通用/情感音色 (BigTTS / Uranus / Mars / Jupiter)
    {"name": "zh_female_vv_uranus_bigtts", "short_name": "活泼女声 (VV)", "locale": "zh-CN", "gender": "Female"},
    {"name": "zh_female_cancan_mars_bigtts", "short_name": "灿灿 (大模型)", "locale": "zh-CN", "gender": "Female"},
    {"name": "zh_female_shuangkuai_bigtts", "short_name": "爽快女声 (大模型)", "locale": "zh-CN", "gender": "Female"},
    {"name": "zh_female_shenyue_mars_bigtts", "short_name": "沈悦 (大模型)", "locale": "zh-CN", "gender": "Female"},
    {"name": "zh_female_tianmei_mars_bigtts", "short_name": "甜美女声 (大模型)", "locale": "zh-CN", "gender": "Female"},
    {"name": "zh_female_yuanqi_mars_bigtts", "short_name": "元气女声 (大模型)", "locale": "zh-CN", "gender": "Female"},
    {"name": "zh_female_vv_jupiter_bigtts", "short_name": "灵动女声 (VV Jupiter)", "locale": "zh-CN", "gender": "Female"},
    {"name": "zh_female_xiaohe_jupiter_bigtts", "short_name": "甜美台腔 (小何)", "locale": "zh-CN", "gender": "Female"},
    {"name": "zh_male_M392_conversation_wvae_bigtts", "short_name": "对话男声 (M392)", "locale": "zh-CN", "gender": "Male"},
    {"name": "zh_male_yunzhou_jupiter_bigtts", "short_name": "沉稳男声 (云洲)", "locale": "zh-CN", "gender": "Male"},
    {"name": "zh_male_xiaotian_jupiter_bigtts", "short_name": "磁性男声 (小天)", "locale": "zh-CN", "gender": "Male"},
    {"name": "zh_male_chunhou_mars_bigtts", "short_name": "醇厚男声 (大模型)", "locale": "zh-CN", "gender": "Male"},
    {"name": "zh_male_baqi_mars_bigtts", "short_name": "霸道男声 (大模型)", "locale": "zh-CN", "gender": "Male"},
    {"name": "zh_male_qingnian_mars_bigtts", "short_name": "青年男声 (大模型)", "locale": "zh-CN", "gender": "Male"},
    # 英文大模型
    {"name": "en_female_dacey_uranus_bigtts", "short_name": "Dacey (美语女声)", "locale": "en-US", "gender": "Female"},
    {"name": "en_male_tim_uranus_bigtts", "short_name": "Tim (美语男声)", "locale": "en-US", "gender": "Male"},
    {"name": "en_female_stokie_uranus_bigtts", "short_name": "Stokie (美语女声)", "locale": "en-US", "gender": "Female"},
    # 基础/流式常用音色
    {"name": "BV001_streaming", "short_name": "灿灿 (通用女声)", "locale": "zh-CN", "gender": "Female"},
    {"name": "BV002_streaming", "short_name": "超超 (通用男声)", "locale": "zh-CN", "gender": "Male"},
    {"name": "BV007_streaming", "short_name": "丫丫 (趣味童声)", "locale": "zh-CN", "gender": "Female"},
    {"name": "BV011_streaming", "short_name": "小天 (广播播报)", "locale": "zh-CN", "gender": "Male"},
    {"name": "BV700_streaming", "short_name": "动漫小新", "locale": "zh-CN", "gender": "Male"},
]

DEFAULT_DOUBAO_TTS_VOICE = DOUBAO_VOICES[0]["name"]

DOUBAO_TTS_V1_URL = "https://openspeech.bytedance.com/api/v1/tts"
DOUBAO_TTS_V3_SSE_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse"
DEFAULT_DOUBAO_TTS_CLUSTER = "volcano_tts"

DOUBAO_ERROR_CODES = {
    3000: "Success / 成功",
    3001: "Invalid request parameters / 请求参数错误",
    3002: "Authentication failed / 鉴权失败",
    3003: "Concurrency limit exceeded / 并发限制",
    3010: "Text length exceeded limit / 文本过长",
    3050: "Voice not found / 音色不存在或未开通",
    3051: "Backend service error / 后端服务异常",
}

def is_doubao_voice(voice: str) -> bool:
    """Check if a given voice name belongs to Doubao."""
    if not voice:
        return False
    if any(v["name"] == voice for v in DOUBAO_VOICES):
        return True
    lower_voice = voice.lower()
    return any(kw in lower_voice for kw in ["_bigtts", "_jupiter", "_uranus", "_mars", "_wvae", "bv0", "bv1", "bv7"])

async def doubao_tts_synthesize(
    text: str,
    voice_type: str,
    access_token: str,
    appid: str,
    cluster: str = DEFAULT_DOUBAO_TTS_CLUSTER,
    encoding: str = "mp3",
    speed_ratio: float = 1.0,
    sample_rate: int = 24000
) -> bytes:
    """
    Non-streaming V1 HTTP synthesis for Doubao TTS.
    
    Args:
        text (str): The text to synthesize.
        voice_type (str): The voice identifier.
        access_token (str): Authentication token.
        appid (str): Application ID.
        cluster (str, optional): Cluster name. Defaults to DEFAULT_DOUBAO_TTS_CLUSTER.
        encoding (str, optional): Audio encoding. Defaults to "mp3".
        speed_ratio (float, optional): Speech speed. Defaults to 1.0.
        sample_rate (int, optional): Audio sample rate. Defaults to 24000.
        
    Returns:
        bytes: Synthesized audio data.
        
    Raises:
        RuntimeError: If synthesis fails.
    """
    reqid = uuid.uuid4().hex
    headers = {
        "Authorization": f"Bearer;{access_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "app": {
            "appid": appid,
            "token": "placeholder",
            "cluster": cluster
        },
        "user": {
            "uid": "voicespirit_user"
        },
        "audio": {
            "voice_type": voice_type,
            "encoding": encoding,
            "speed_ratio": speed_ratio,
            "rate": sample_rate
        },
        "request": {
            "reqid": reqid,
            "text": text,
            "operation": "query"
        }
    }
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(DOUBAO_TTS_V1_URL, headers=headers, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                raise ValueError(
                    f"音色未授权 (HTTP 403 Forbidden): 当前 App ID ({appid}) 未开通音色 '{voice_type}' 的调用权限。"
                    f"请在火山引擎「豆包语音」控制台开通该音色，或在界面中切换至已有权限的音色（如 活泼女声 VV / 对话男声 M392）。"
                ) from exc
            raise RuntimeError(f"Doubao TTS HTTP error {exc.response.status_code}: {exc.response.text}") from exc
        
        resp_data = response.json()
        code = resp_data.get("code")
        
        if code != 3000:
            error_msg = DOUBAO_ERROR_CODES.get(code, f"Unknown error / 未知错误: {code}")
            message = resp_data.get("message", "")
            raise RuntimeError(f"Doubao TTS error {code}: {error_msg}. Details: {message}")
            
        b64_audio = resp_data.get("data", "")
        if not b64_audio:
            raise RuntimeError("No audio data returned from Doubao TTS / 返回音频数据为空")
            
        return base64.b64decode(b64_audio)


async def doubao_tts_stream_sse(
    text: str,
    voice_type: str,
    access_token: str,
    appid: str,
    cluster: str = DEFAULT_DOUBAO_TTS_CLUSTER,
    encoding: str = "mp3",
    speed_ratio: float = 1.0,
    sample_rate: int = 24000
) -> AsyncGenerator[bytes, None]:
    """
    SSE streaming V3 synthesis for Doubao TTS.
    
    Args:
        text (str): The text to synthesize.
        voice_type (str): The voice identifier.
        access_token (str): Authentication token.
        appid (str): Application ID.
        cluster (str, optional): Cluster name. Defaults to DEFAULT_DOUBAO_TTS_CLUSTER.
        encoding (str, optional): Audio encoding. Defaults to "mp3".
        speed_ratio (float, optional): Speech speed. Defaults to 1.0.
        sample_rate (int, optional): Audio sample rate. Defaults to 24000.
        
    Yields:
        bytes: Chunks of synthesized audio data.
        
    Raises:
        RuntimeError: If SSE synthesis fails.
    """
    reqid = uuid.uuid4().hex
    headers = {
        "Authorization": f"Bearer;{access_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "app": {
            "appid": appid,
            "token": "placeholder",
            "cluster": cluster
        },
        "user": {
            "uid": "voicespirit_user"
        },
        "audio": {
            "voice_type": voice_type,
            "encoding": encoding,
            "speed_ratio": speed_ratio,
            "rate": sample_rate
        },
        "request": {
            "reqid": reqid,
            "text": text,
            "operation": "submit"
        }
    }
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", DOUBAO_TTS_V3_SSE_URL, headers=headers, json=payload) as response:
            response.raise_for_status()
            
            async for line in response.aiter_lines():
                line = line.strip()
                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    if not data_str:
                        continue
                        
                    try:
                        event_data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                        
                    if "code" in event_data and event_data["code"] != 3000:
                        code = event_data["code"]
                        error_msg = DOUBAO_ERROR_CODES.get(code, f"Unknown error / 未知错误: {code}")
                        message = event_data.get("message", "")
                        raise RuntimeError(f"Doubao TTS SSE error {code}: {error_msg}. Details: {message}")
                    
                    b64_chunk = event_data.get("data", "")
                    if b64_chunk:
                        yield base64.b64decode(b64_chunk)
                        
                    sequence = event_data.get("sequence", 0)
                    if sequence < 0:
                        break
