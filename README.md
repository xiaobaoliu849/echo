# Echo · 回声

**开箱即用的本地实时语音 AI 助手** —— 全双工语音对话、TTS、语音克隆、实时转写，一个应用全搞定。

[English](README_EN.md) | 中文

---

## 这是什么？

Echo 是一个**面向最终用户**的语音 AI 桌面应用（FastAPI + React，浏览器或桌面窗口运行）。

GitHub 上的 [LiveKit Agents](https://github.com/livekit/agents)、[Pipecat](https://github.com/pipecat-ai/pipecat)、[TEN Framework](https://github.com/TEN-framework/ten-framework) 都很优秀，但它们是**给开发者的框架**——你拿到一堆积木，要自己写代码搭 Agent、接服务、做界面。

**Echo 是成品**：下载、填 API Key、开始说话。同时原生支持国内语音服务（通义 Qwen-Omni、豆包全双工、小米、MiniMax……），这是那几个框架基本不覆盖的。

## 功能

### 🎙️ 实时全双工语音对话
- 边说边听、随时打断（barge-in），VAD 静音检测 + 智能打断判定
- Provider：OpenAI Realtime · Google Gemini Live · 通义 Qwen-Omni · 豆包全双工 · GLM4Voice · PersonaPlex（英语口语陪练）
- 语音工具调用、EverMem 长期记忆、会话配置热更新

### 🔊 TTS 语音合成（9+ 引擎）
Edge TTS · 通义 Qwen TTS · MiniMax · OpenAI · ElevenLabs · ChatTTS · GPT-SoVITS · 小米 · Azure · Cartesia，内容哈希缓存免重复合成

### 🧬 语音中心
声音设计（text-to-voice）、声音克隆（上传样本即可）

### 📝 转写
- 长音频/视频转写：ffmpeg 自动分片、视频自动提取音轨，突破单文件时长限制
- 实时麦克风转写（Qwen-ASR-Flash-Streaming）
- 同步字幕播放器、SRT/VTT 导出、批量管理、一键存入记忆

### 🎧 更多
播客/多人对白生成 · 智能翻译 · AI 聊天（DeepSeek / OpenRouter / Groq / SiliconFlow / Gemini / 通义 / Ollama）· PDF 文档朗读与润色

## 快速开始

**环境要求**：Python 3.10+ · Node.js 18+ · ffmpeg（音频处理）

```bash
# Windows 一键启动（后端 + 前端开发服务器）
run_web.bat

# 桌面模式（构建前端 + pywebview 窗口）
run_web_desktop.bat
```

手动启动：

```bash
# 后端
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# 前端（另开一个终端）
cd frontend
npm install
npm run dev
```

首次运行自动生成 `config.json`，打开设置页填入各 Provider 的 API Key 即可。

## 架构

```
backend/    FastAPI · 14 个路由 · 服务层（实时语音 4-provider 组合 / TTS 9 引擎分发 / 多 Provider LLM）
frontend/   React 19 + Vite + TypeScript SPA（生产环境由 FastAPI 直接托管 dist/）
```

- **RealtimeVoiceService**：组合式架构，共享打断判定、回合收尾、工具事件分发，各 Provider 只实现传输层差异
- **TtsService**：引擎分发 + 内容哈希缓存（原子写入 + 容量淘汰）
- **ConfigLoader**：JSON 配置，mtime 增量热加载

```bash
# 运行测试
cd backend && python -m pytest tests/ -q
cd frontend && npm run test:run
```

## Roadmap

- [ ] 语义化打断检测（对标 SmartTurn）
- [ ] 更多实时 Provider
- [ ] 一键安装包

## License

[MIT](LICENSE)

---

> 名字彩蛋：Echo 也是 DOTA2 撼地者的大招「回音击」——敌人越多，回音越响。🎯
