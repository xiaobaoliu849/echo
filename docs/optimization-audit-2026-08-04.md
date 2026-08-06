# 优化审计报告（2026-08-04）

> 三路 agent 全面审计（后端 / 前端 / 仓库卫生），分支 `feat/realtime-asr`。
> 结论：无会直接崩溃或丢数据的 P0 逻辑 bug；有两个 P0 安全缺口 + 一批"长跑才暴露"的健壮性/性能问题。
> 2026-07-22 旧 backlog 条目经核验全部仍然有效。

## 建议动手顺序（总览）

1. **P0 安全**（WS 鉴权 + settings mask）— 便宜，堵住计费/窃密洞
2. **挂起三件套**（Qwen/DashScope WS keepalive + edge_tts 超时）+ **前端 WS 重连** — 语音产品核心可靠性
3. **hook 下沉出 App 根** + `useSettings` 拆分 — 最大渲染收益
4. **transcription/tts 大拆分**（S2/S3）— 拆分时同时拿到 registry、事件循环修复、缓存淘汰修复
5. **测试补齐**（batch-delete 等）+ 卫生清理

---

## 🔴 P0 — 安全

### 1. 两个 WebSocket 端点完全无鉴权
- `/api/voice-chat/ws`（`backend/routers/voice_chat.py:183`）和 `/api/transcription/realtime`（`backend/routers/transcription.py:855`，本分支新增）都是 `accept()` 零检查。
- auth 只挂在 `@app.middleware("http")`（`main.py:189`），结构上不覆盖 WS 握手；`api_auth_guard.py:59` 的 `should_enforce_auth` 基于 HTTP 方法，无法应用到 WS。
- 影响：任何能摸到端口的进程都能用服务器配置的 API key 烧上游 quota（DashScope/Google/OpenAI），是计费漏洞。目前唯一防线是绑 `127.0.0.1`。
- 修法：WS 握手加 token 校验（query param 或首条消息认证，复用 `validate_auth_header`），在 `accept()` 之前拒绝。

### 2. GET /api/settings 明文返回全部 API key，且无鉴权
- `routers/settings.py:53` 返回完整 `SettingsResponse` 含 `api_keys` dict（`settings_service.py:34-46`），全仓库无 mask 逻辑。
- auth guard 只保护 `/api/agent-runs` 和 `/api/voice-chat/sessions` 两个 GET 前缀 → 即使开了 auth，所有 provider key 可被无鉴权 GET 读走。本地进程或浏览器 DNS-rebinding 可窃取。
- 修法：GET 响应 mask key，或把 `/api/settings` 加进敏感读取前缀。

---

## 🟡 P1 — 大文件拆分

旧 backlog 三项全部没拆反涨。审计已给出具体方案（模块 + 行数 + 风险）。

| 文件 | 行数 | 拆分方案 |
|------|------|----------|
| `backend/services/voice_agent_tools.py` | 1471→1732 | `voice_tool_intent.py`（意图正则+提取，~330）/ `voice_tool_search.py`（搜索+fallback，~400）/ `voice_tool_prompts.py`（schema+context prompt，~250）/ facade 保留 `VoiceAgentToolSession` 状态机（~750，打断时序敏感不盲拆） |
| `backend/services/transcription_service.py` | 1306→1495 | `asr_providers/` 包（5 个 adapter，~550，统一 `(path,key)->{text,duration,words}` 协议）/ `transcription_job_store.py`（~330）/ `dashscope_filetrans.py`（~330）/ facade（~300）。顺带消掉 100 行 if/elif 自动选择阶梯 → registry |
| `backend/services/tts_service.py` | 1346 | `tts_voices.py`（音色目录纯数据，~230）/ `tts_engines/` 注册表（9 adapter，~650，消掉 4 段 if/elif；注意 `detect_engine_by_voice` 启发式有顺序依赖，迁移时保持优先级不变）/ `tts_voice_store.py`（本地克隆 CRUD，~180）/ facade（~300） |
| `frontend/src/hooks/useVoiceChat.ts` | 1750→1860 | 拆 6 块：事件 reducer（~620，switch 按域拆 handler 模块）+ 5 个子 hook（config/audio engine/live-translate flow/turn state/agent history）。`useVoiceAgentHistory` 与 socket 零耦合先拆；3 处重复的会话重置逻辑收敛为一处 |
| `frontend/src/api/client.ts` | 1567 | 按域拆 9 模块（auth/evermem/tts/chat/translate/voices/settings/audioOverview/transcription/audioAgent）+ 共享 `core.ts`（apiFetch/cachedGetJson/错误处理），re-export barrel 保持调用点不变 |
| `frontend/src/hooks/useSettings.ts` | 970 | 45 个扁平 useState → 主题子 hook（provider/evermem/transcription/desktop/runtime） |
| `frontend/src/hooks/useAudioOverview.ts` | 949 | ~40 useState → 播客 CRUD / agent 轮询 / 合成 / 脚本编辑 |
| `backend/tests/test_api_smoke.py` | 2443 | 60 测试跨 13 域 → 按域拆 7 个文件；活跃分支上是冲突磁铁 |

**realtime mixin 去重（暂缓）**：memory-inject 块在 4 个 provider 复制（dashscope:462-508, qwen_audio:454-473, google:426-453, openai:229-257），`memory_write`/`turn_complete` 内联了 3 处但 facade 里已有 `_finalize_realtime_turn`（realtime_voice_service.py:616-644）没用上。这些在打断时序状态机里，需先有集成测试再动。`_google_to_client_loop`（google:316-944）是全库最长单函数（630 行），拆它高风险，排在共享块提取之后。

---

## 🟡 P1 — 后端健壮性

### 挂起风险（最严重三类）
- `realtime_qwen_audio_provider.py:900-906`：`websockets.connect(ping_interval=None, ping_timeout=None)` 无 keepalive → TCP 半死时收发循环永久挂起（recv 等满 300s，mic 循环无限挂）。
- `realtime_dashscope_client.py:238-247`：同样禁 ping；半开连接下 `on_close` 不触发，`queue.get()` 循环无 watchdog 无限阻塞。
- `tts_service.py:712-730`：`edge_tts.Communicate.save()` 无超时，微软端点卡住调用方永久挂起；被实时语音 `synthesize_tts` 工具使用。
- `voice_agent_tools.py:635-666`：搜索 LLM fallback 无总时限，最坏 3 模型 × 20s = 实时一轮 +60s，且每次新建 AsyncClient。

### 事件循环阻塞（转写模块重灾区，随 S2 拆分顺手修）
- `transcription_service.py:480/566/674/752/828`：整份音频 `read_bytes()`（可 100MB+）在 async handler 同步执行；仅 Qwen 路径有 10MB 检查，Deepgram/OpenAI/AssemblyAI 无大小保护。
- `routers/transcription.py:226-233`：上传整个读进内存 + 同步写盘，无大小限制。
- `routers/transcription.py:182-223`：`_job_to_response` 对每个 job 同步读**全文转写**，列表接口（limit 200）逐个调用 → 阻塞 + MB 级响应。列表应只回元数据。
- `tts_service.py:1166-1181`：对话合成 pydub/ffmpeg 重活同步跑在事件循环。
- `voice_agent_tools.py:719`：`create_run()` 同步 SQLite 在 async 里直接调，阻塞事件循环（实时语音会话同循环）。

### 资源/并发
- `tts_service.py:221` + `routers/tts.py:10`：TTS 缓存淘汰只在 `__init__` 跑，而 `TTSService()` 是模块级单例 → 长运行服务器 `temp_audio/` **无限增长**（比旧记录更严重）。
- `realtime_session_recorder.py:93-105`：每个 assistant 文本 delta 写 2 次 SQLite；与 ChatTTS 推理（`tts_service.py:570-653` 持全局锁数秒~数分钟）、Qwen SDK 共用默认线程池 → 队头阻塞，实时语音轮次中途卡顿。
- `transcription_service.py:169-195/337-367`：job JSON 读-改-写无锁，并发更新可丢写。
- `transcription_service.py:1247-1254`：`_download_remote_transcript` 抓取远端 payload 里的任意 URL，无 scheme/host 校验（SSRF 面）。
- `tts_service.py:767`：`dashscope.api_key = ...` 改进程全局，多 key 并发有竞态。
- `tts_service.py:1254-1347`：Azure 流式 SDK 对象不 dispose（每请求泄漏）；队列无界。
- `llm_service.py:744-751`：`reason_about_text` 裸 `except: pass`，记忆保存失败不可见。

---

## 🟡 P1 — 后端性能

- `tts_service.py:1147-1160`：对话多行 TTS 串行 await → 改 `asyncio.gather` 并行。
- `llm_service.py:42-68`：system prompt 每秒注入时间戳 → **干掉上游 prompt 缓存**（DashScope context caching 是明确目标），便宜修复。
- `transcription_service.py:221-268`：`list_jobs` 每次 GET 读+解析全部 job JSON 再排序；jobs 目录无 TTL 清理，N 只增不减。
- `config_loader.py:108` + `voice_agent_tools.py:214-245`：每次语音工具调用对 ~7 个 provider 循环 `deepcopy` 全配置 + reload stat。
- `routers/transcription.py:300-319`：同步转写路径一次请求 4 次 JSON 文件写。
- `voice_agent_session_repository.py`：SQLite 会话表无保留/淘汰策略，长期无限增长。

---

## 🟡 P1 — 前端

### 性能（最大收益点）
- **`App.tsx:201-232`：7 个功能 hook 全部在 App 根实例化**（旧文档遗留项 a，仍未做）。实时语音每个 ASR delta / 聊天每个 token → **整棵树重渲染**。`ChatPage`/`ChatInputBar` 未 memo 且 props 对象每渲染变身份，memo 也无效。修法：hook 下沉到页面/context，稳定返回值身份。
- `useSettings.ts:88-161`：任何设置项敲一键 → 全树重渲染。
- `useChat.ts:296-613`：`onSubmit`/`regenerateMessage` 重复 ~135 行 → 提取 `runChatStream()`。

### 健壮性
- **WS 无自动重连 + 无心跳**（`useVoiceChat.ts:1465-1482`）：`case "pong"`（1329）是死代码（客户端从不发 ping）。NAT 超时/合盖 → UI 显示已连接但 mic 帧静默丢弃。`RealtimeTranscriptionPanel.tsx:326-333` 同样问题。
- `wasConnected` 闭包 bug 仍在（`useVoiceChat.ts:1469`）：永远是 false，长会话断开后误报吓人错误。改读 ref。
- **全应用无 ErrorBoundary**：任何渲染抛错白屏。`main.tsx` 裸渲染 `<App/>`。最便宜高回报修复。
- `client.ts:861`：SSE 循环里 `JSON.parse` 未捕获 → 一条坏事件中断整个聊天流。
- **`/api/tts/speak` 仍是 GET 带全文 query**（`client.ts:689-723`）：PDF 长文会撞 URL 长度限制，文本进访问日志。改 POST。
- `useChat.ts:296`：`onSubmit` 无 `chatBusy` 守卫，快速双击 Enter 会留幽灵空气泡。
- `useVoiceChat.ts:950`：`atob()` 遇坏 base64 抛错 → 每帧未捕获 promise rejection。
- `useVoiceChat.ts:1495`：用已废弃的 `ScriptProcessorNode`，长期应迁 AudioWorklet。

---

## 🟢 P2 — 仓库卫生

### 根目录 12 个未跟踪文件（已核实内容，全是保存的文档/记录，无代码）
- `funasr_client_events/.html/.txt`、`funasr_rt.*`、`funasr_server_events.*`：阿里云 Fun-ASR 实时 WS API 文档页。
- `语音识别.txt`（Qwen-ASR-Flash）、`语音合成.txt`（Aliyun TTS WS）、`音色列表.txt`（Qwen-Omni 音色表）、`时时翻译.txt`（livetranslate 文档）、`新建文本文档.txt`（Gemini Live API）、`继续.txt`（agent 会话记录，纯 scratch）。
- 处理建议：**删 `继续.txt`**；文档可网络重新获取，要么删要么挪 `docs/reference/` 正式提交；保留则加**针对性** ignore 规则（仓库已有 `全模态.txt` 先例），**不要**加 `*.txt` 通配。

### 测试缺口（feat/realtime-asr 分支新增功能）
- 后端零测试：`POST /jobs/batch-delete`（routers/transcription.py:560，最高优先级）、`POST /jobs/{id}/save-memory`（596）、`GET /jobs/{id}/words`（735）、`/api/transcription/realtime` WS 路由注册。
- 前端零测试：`RealtimeTranscriptionPanel.tsx`（597 行新组件）、`TranscriptionSubtitlePlayer.tsx`、`TranscriptionTable.tsx`、`asrProviders.ts`、`subtitleGenerator.ts`。

### 死代码（可删）
- `frontend/src/styles.css.top.css`（3.8KB，无 import）
- `app/__pycache__/`（废弃布局残留）
- `backend/patch_tts_router.py`、`backend/patch_tts_service.py`、`backend/temp_stream_test.html`（一次性补丁脚本）
- `backup_before_cleanup/`（本地旧备份）

### 其他
- `.gitignore` 覆盖良好（.venv-win ✓ dist ✓ config.json ✓ 真实 key CSV ✓），唯一缺口就是上述 scratch 文件。
- `frontend/src/styles.css` 单文件 8637 行 / 179KB，未按路由拆分（旧遗留项 d 未做）。
- CORS localhost allowlist 良好，但含 `"null"` origin + `allow_credentials=True`（main.py:37-44）——绑非 127.0.0.1 时会成洞。
- `/api/voice-chat/ws` 无 idle 超时（对比 transcription realtime 有 `REALTIME_IDLE_TIMEOUT` 且有测试）。
- 中间件整体良好：统一错误处理 + request-id + 结构化 JSON 错误，无密钥泄漏；源码无硬编码 key。

---

## 已核验"仍未做"的旧遗留项（2026-07-23 文档）

| 项 | 状态 |
|---|---|
| 功能 hook 移出 App 根 | ❌ 未做（App.tsx:201-232 仍 7 个） |
| WS 自动重连 + 心跳 | ❌ 未做（grep 0 命中，pong 是死代码） |
| /api/tts/speak 改 POST | ❌ 未做 |
| styles.css 拆分 + 删 top.css | ❌ 未做（涨到 8637 行） |
