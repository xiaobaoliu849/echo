# Soniox 语音识别（STT）与语音合成（TTS）接入技术指南

本文档介绍如何在 Echo 语音助手架构中接入并使用 **Soniox** 高精度多语言语音识别（ASR）与超低延迟语音合成（TTS）服务。

---

## 1. 关于 Soniox

**Soniox** 是一家专注于端到端多语言语音人工智能（Speech AI）的技术公司。其核心优势包括：
- **超低字错误率（WER）**：在真实会议、嘈杂背景、多人交谈场景下具备优异的识别鲁棒性，主力识别模型为 `stt-async-v5`。
- **真正的字级时间戳（Word-level Timestamps）**：返回精确到毫秒级的 Token/Word 时间切片，天然适用于精准字幕（SRT/VTT）生成及词级高亮播放。
- **超低延迟语音合成（TTS）**：提供 `tts-rt-v2` 旗舰语音合成模型，具备拟真度高、支持情绪与语气标签（如 `[laughing]`, `[whisper]`）、跨 60+ 种语言保持一致音色及支持声音克隆。
- **隐私保护与临时存储**：支持上传音频处理完成后即时删除，不留存用户隐私语音。

---

## 2. API 接口规格与调用生命周期

Soniox 服务体系主要包括两大端点：
- **管理与 STT 接口**：`https://api.soniox.com/v1`
- **实时与 TTS 接口**：`https://tts-rt.soniox.com`

### 2.1 鉴权方式
所有请求均需要在 HTTP Header 中包含 API Key：
```http
Authorization: Bearer <SONIOX_API_KEY>
```

### 2.2 语音识别（STT）流程
1. 上传音频文件：`POST https://api.soniox.com/v1/files`（`multipart/form-data`），获取临时 `file_id`。
2. 触发异步转录任务：`POST https://api.soniox.com/v1/transcriptions`（传入 `file_id` 与模型 `stt-async-v5`）。
3. 轮询转录状态：`GET https://api.soniox.com/v1/transcriptions/{id}`，直至 `status === "completed"`。
4. 拉取词级结果：`GET https://api.soniox.com/v1/transcriptions/{id}/transcript`，解析每个字词的毫秒级时间戳。
5. 清理云端临时文件：在 `finally` 保护块中调用 `DELETE https://api.soniox.com/v1/files/{file_id}`。

### 2.3 语音合成（TTS）流程
1. 语音列表获取：`GET https://api.soniox.com/v1/tts-models` 获取内置预设声音；`GET https://api.soniox.com/v1/voices` 获取用户自定义克隆音色。
2. 音频合成生成：`POST https://tts-rt.soniox.com/tts`
   ```json
   {
     "text": "Hello world! [laughing] This is Soniox TTS.",
     "voice": "Adrian",
     "model": "tts-rt-v2",
     "speed": 1.0,
     "audio_format": "mp3"
   }
   ```
   返回直接为音频二进制数据流（`audio/mpeg`），即下即播并写入本地缓存。

---

## 3. Echo 中的集成实现

### 3.1 识别模块适配
- 毫秒级时间戳归一化为秒级浮点数，适配 SRT/VTT 导出与播放器高亮。
- 自动 `finally` 清理上传文件，杜绝配额泄漏。

### 3.2 合成模块适配
- `soniox_tts_provider.py` 负责与 `tts-rt.soniox.com/tts` 交互，并预设了 Adrian、Daniel、Mina、Elena、Alex、Sophia 等多语言音色。
- `TTSService` 支持 `engine="soniox"` 与音色自动探测 `is_soniox_voice`。
- 支持单人朗读、双人多角色对话合成（Dialogue TTS）与本地音频缓存哈希管理。

---

## 4. 配置与使用指南

1. 登录 [Soniox 控制台](https://console.soniox.com) 并创建 API Key。
2. 打开 Echo 客户端或网页版。
3. 进入 **设置（Settings）** -> **服务商设置**，选择 **Soniox**，填写您的 API Key 并保存。
4. **语音识别使用**：在 **转录中心** 中选择 **Soniox (stt-async-v5)** 即可一键转写。
5. **语音合成使用**：在 **语音中心（TTS 页面）** 中将合成引擎切换为 **Soniox TTS**，选择所需音色（如 Adrian / Mina 等），输入文字即可即时合成。
