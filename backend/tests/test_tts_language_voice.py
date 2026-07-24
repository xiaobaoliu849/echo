import pytest
from services.tts_service import TTSService, DEFAULT_EDGE_VOICE, DEFAULT_EDGE_EN_VOICE

def test_detect_edge_voice_language():
    service = TTSService()

    # Chinese text
    assert service._detect_edge_voice("你好，欢迎使用 VoiceSpirit AI 助手") == DEFAULT_EDGE_VOICE

    # English text
    assert service._detect_edge_voice("Hello, welcome to VoiceSpirit AI assistant!") == DEFAULT_EDGE_EN_VOICE

    # Japanese text
    assert service._detect_edge_voice("こんにちは") == "ja-JP-NanamiNeural"

    # Korean text
    assert service._detect_edge_voice("안녕하세요") == "ko-KR-SunHiNeural"


def test_resolve_edge_voice_for_text():
    service = TTSService()

    # English text with Chinese voice requested -> switches to English voice
    en_text = "Here is the summary of your latest audio recordings and notes."
    res = service._resolve_edge_voice_for_text(en_text, "zh-CN-XiaoxiaoNeural")
    assert res == DEFAULT_EDGE_EN_VOICE

    # Chinese text with English voice requested -> switches to Chinese voice
    zh_text = "这是为您总结的最新录音与笔记摘要。"
    res = service._resolve_edge_voice_for_text(zh_text, "en-US-JennyNeural")
    assert res == DEFAULT_EDGE_VOICE

    # Chinese text with Chinese voice requested -> keeps Chinese voice
    res = service._resolve_edge_voice_for_text(zh_text, "zh-CN-YunxiNeural")
    assert res == "zh-CN-YunxiNeural"

    # English text with English voice requested -> keeps requested English voice
    res = service._resolve_edge_voice_for_text(en_text, "en-US-JennyNeural")
    assert res == "en-US-JennyNeural"

    # Mixed text with Chinese -> keeps requested Chinese voice
    mixed_text = "VoiceSpirit 支持 Edge TTS 和 Qwen 语音。"
    res = service._resolve_edge_voice_for_text(mixed_text, "zh-CN-XiaoxiaoNeural")
    assert res == "zh-CN-XiaoxiaoNeural"

    # Japanese text with Chinese voice requested -> switches to Japanese voice
    ja_text = "こんにちは、今日は良い天気ですね。"
    res = service._resolve_edge_voice_for_text(ja_text, "zh-CN-XiaoxiaoNeural")
    assert res == "ja-JP-NanamiNeural"

    # Korean text with Chinese voice requested -> switches to Korean voice
    ko_text = "안녕하세요, 반갑습니다."
    res = service._resolve_edge_voice_for_text(ko_text, "zh-CN-XiaoxiaoNeural")
    assert res == "ko-KR-SunHiNeural"

    # Japanese text with Japanese voice requested -> keeps requested Japanese voice
    res = service._resolve_edge_voice_for_text(ja_text, "ja-JP-KeitaNeural")
    assert res == "ja-JP-KeitaNeural"

