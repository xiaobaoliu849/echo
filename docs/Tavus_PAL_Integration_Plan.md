# Tavus PAL 集成规划（Tavus PAL Integration Plan）

> 基于 docs.tavus.io 2026-08 文档快照整理。结论先行：**Phase 1（核心视频对话）已落地并全量测试通过**；
> 本文档给出平台能力全景、差距分析和 Phase 2–6 的演进路线，供后续迭代按阶段取用。

---

## 1. 背景与目标

Echo 要把 Tavus PAL（实时视频 AI 分身，Tavus 称其管线为 CVI — Conversational Video Interface）
作为一个新的对话面集成进应用，与现有的文字聊天、实时语音（WebSocket 管线）并列。

约束：

- **本地优先**：Echo 桌面端通常没有公网可达的回调地址，任何依赖 webhook 的能力必须有轮询（polling）替代路径。
- **Key 不进前端**：API key 只在 FastAPI 后端与 Tavus 之间传输（前端仅按请求经 header 转交）。
- **Provider 边界**：Tavus 相关调用全部收敛在 `backend/services/tavus_*` 与 `frontend/src/hooks/useTavusConversation.ts`，
  不与现有 realtime 语音管线耦合（两者是并列的对话面，不是同一条管线）。

## 2. Tavus 平台能力全景

Base URL `https://tavusapi.com`，认证 `x-api-key`（在 PAL Maker [maker.tavus.io/dev](https://maker.tavus.io/dev) 创建）。

| API 分组 | 端点 | 用途 | 对 Echo 的价值 |
| --- | --- | --- | --- |
| Conversations | `POST/GET/DELETE /v2/conversations` | 创建/查询/列出/结束/删除实时会话 | **核心**，已接（create/end） |
| PALs | `POST/GET/PATCH/DELETE /v2/pals` | 分身行为层：prompt、LLM、STT/TTS、感知层、objectives、guardrails | **已接 list**；管理是 Phase 4 |
| Faces | `/v2/faces` | 形象：stock 或自训练（视频/照片训练） | Phase 4（形象选择器） |
| Voices | `/v2/voices` | 声音基元，挂在 PAL 的 TTS 层 | Phase 4 |
| Tools / PAL Tools | `/v2/tools` + attach/detach | 给 PAL 挂工具（LLM tool、感知 tool、post-call tool） | 远期 |
| Skills | `/v2/skills` + attach | 现成技能：联网搜索、演示文稿、浏览器操作 | 远期 |
| Objectives | `/v2/objectives` | 会话目标/引导式流程（如销售、面试场景） | 远期 |
| Guardrails | `/v2/guardrails` | 行为护栏 | 远期 |
| Documents | `/v2/documents` | 知识库上传 + 检索策略（`document_ids` 直接传入会话） | Phase 5（与转写库联动） |
| Pronunciation Dictionaries | `/v2/pronunciation-dictionaries` | 发音词典 | 远期 |
| Memories | `memory_stores` 标签 + `DELETE /v2/memories/...` | 跨会话记忆（Tavus 侧托管） | Phase 5（与 EverMem 双轨评估） |
| Webhooks | 会话创建时传 `callback_url` | 事件回调（见 §4.3） | Phase 6（可选，桌面默认用轮询） |
| Deployments | `/v2/deployments` | 托管 widget / embed / landing page | 远期 |
| Video | `/v2/video-request` | 异步视频生成（非实时） | 不在当前范围 |

概念模型：**PAL**（你构建的行为）+ **Face**（形象）+ **Voice**（声音）→ **Conversation**（一次实时通话，Daily WebRTC 房间）。
旧命名 `persona`/`replica` 仅为兼容；新代码一律 `pal_id` / `face_id`。

## 3. 当前已落地（Phase 1）

**功能**：侧边栏「视频分身 / Video PAL」→ 配置 API Key（本机 localStorage）与分身 →
创建会话 → daily-js `createFrame` 接入房间 → 通话中状态条/结束按钮 → PAL 离开后自动结束并销毁 →
离开/关闭页面时向上游结束会话。

**代码**：

| 文件 | 职责 |
| --- | --- |
| `backend/services/tavus_service.py` | Tavus REST 客户端（create/end conversation、list pals），结构化 `TavusError` |
| `backend/services/tavus_config.py` | 凭证解析：`X-Tavus-Api-Key` header 优先，`TAVUS_API_KEY`/`TAVUS_PAL_ID` 环境变量兜底 |
| `backend/routers/tavus.py` | `GET /api/tavus/pals`、`POST /api/tavus/conversations`、`DELETE /api/tavus/conversations/{id}` |
| `frontend/src/api/client.ts` + `types.ts` | Tavus 请求头构建、会话创建/结束、分身列表、本地持久化（key 只经 header 转交） |
| `frontend/src/hooks/useTavusConversation.ts` | WebRTC 生命周期：创建→join（含 `meeting_token`）→participant-left 自动离开→destroy 清理；join 失败也会向上游 end（计费卫生） |
| `frontend/src/pages/PalPage.tsx` | 配置面板 + 全屏视频区 + 通话状态条，双语 |
| `run_web_desktop.py`（已有） | WebView2 已带 `--use-fake-ui-for-media-stream --enable-media-stream`，桌面端摄像头/麦克风免改动 |

**验证**：后端 pytest 全量 642+ 通过（含 `test_tavus_service.py`/`test_tavus_router.py`）；
前端 vitest 全量 323+ 通过（含 `useTavusConversation.test.ts`/`PalPage.test.tsx`）；`npm run build` 通过，
daily-js 为独立懒加载 chunk，不进主包。

**尚未做的事（明确排除在 Phase 1 外）**：真实账号端到端验证（需要用户自己的 Tavus key）、会话历史、创建参数 UI。

## 4. 关键平台事实与约束（规划依据）

1. **计费起点 = 会话创建**。PAL 创建后即进入房间等待，积分开始累计并占用一个并发槽位，
   直到会话结束或超时。⇒ 任何"创建了但没用上"的会话必须尽快 `DELETE /v2/conversations/{id}`；
   前端 join 失败路径已做此处理（`endConversationUpstream`）。
2. **超时三参数**（`properties` 内，均秒为单位）：`max_call_duration`（通话上限，受套餐封顶）、
   `participant_left_timeout`（默认 0）、`participant_absent_timeout`（默认 300，无人加入自动结束）。
   ⇒ Phase 2 应在创建时显式设置，作为成本护栏；`participant_absent_timeout` 同时是私有房间 token 的有效期。
3. **本地优先取转写：不依赖 webhook**。`GET /v2/conversations/{id}?verbose=true` 返回 `status`、
   `shutdown_reason` 和 `events`（含 `application.transcription_ready` 的完整逐句转写、
   `application.perception_analysis` 等）。⇒ 通话结束后轮询该端点即可拿到记录，
   webhook（需公网 `callback_url`）只作为部署了公网入口时的增强路径（对标 transcription 的
   `public_base_url` 模式）。
4. **Webhook 事件面**（Phase 6 备用）：`system.pal_joined`（PAL 就绪）、`system.shutdown`（含关闭原因）、
   `application.transcription_ready`（转写）、`application.recording_ready`（录制落 S3/GCS/Azure）、
   `application.perception_analysis`（需 raven-1 感知层）、`application.post_call_action_executed`。
5. **私有房间**：`require_auth: true` → 响应带 `meeting_token`，前端 join 时以 `token` 传入
   （已实现链路，默认关闭）。
6. **Pipeline 模式**：默认 Full pipeline（STT+LLM+TTS+感知全托管）是唯一推荐模式；
   Echo Mode / 自定义 LLM / LiveKit / Pipecat 属于另类集成，与 Echo 现有 realtime 管线定位重叠，
   暂不引入。
7. **记忆双轨**：Tavus `memory_stores`（会话创建时传标签，如 `["client-<id>-<pal_id>"]`）是 Tavus 侧托管记忆；
   Echo 已有 EverMemOS 长期记忆。两者并存可行，但要避免同源信息双写造成语义漂移（见 §9 待决）。
8. **区域**：创建会话可传 `policy: "eu"`；EU AI Act 合规相关。中国大陆网络访问 tavusapi.com/Daily 的
   连通性需要实测（风险项 R3）。

## 5. 差距分析

| 能力 | Tavus 支持 | Echo 现状 | 阶段 |
| --- | --- | --- | --- |
| 创建/结束会话、加入房间 | ✅ | ✅ | P1 ✅ |
| 分身列表选择 / 手动 PAL ID | ✅ | ✅ | P1 ✅ |
| 私有房间 meeting_token join | ✅ | ✅（链路已通，UI 未暴露开关） | P3 |
| 孤儿会话计费卫生 | — | ✅ join 失败自动 end | P1 ✅ |
| 创建参数：context/greeting/时长/超时/字幕/语言/audio_only | ✅ | ❌ service 已留 `properties` 入参，UI 未暴露 | P2 |
| 会话历史 + 逐句转写 | ✅（GET verbose） | ❌ | P2 |
| 状态轮询/结束回执（本地优先） | ✅ | ❌ | P2 |
| Faces/Voice 选择器、stock 分身浏览 | ✅ | ❌（仅 pal 列表） | P4 |
| PAL 创建/编辑（prompt、LLM、objectives…） | ✅ | ❌ | P4 |
| 知识库 documents 上传/挂载 | ✅ | ❌ | P5 |
| memory_stores 自动标注 | ✅ | ❌ | P5 |
| Webhook 回调接收端 | ✅（需公网） | ❌（轮询替代） | P6 可选 |
| 录制 / Magic Canvas / Skills / Deployments / 异步视频 | ✅ | ❌ | 远期 |

## 6. 路线图

### Phase 2 — 会话体验与成本护栏（短平快，建议下一个迭代）

目标：把创建参数和事后记录补齐，形成"可日常使用"的闭环。

1. **创建参数透传**（`PalPage` 高级选项折叠区 → `POST /api/tavus/conversations`）：
   - `conversational_context`（场景设定）、`custom_greeting`（开场白）
   - `properties.max_call_duration`（默认建议 1800s）、`properties.enable_closed_captions`（默认开）
   - `audio_only` 开关（低带宽/纯语音场景）
   - 后端 `TavusCreateConversationRequest` 增加上述字段，service 已有 `properties` 入参可直挂
2. **默认成本护栏**：后端在 payload 未显式提供时注入 `properties.participant_absent_timeout=120`、
   `participant_left_timeout=60`，防止忘关页面导致空转计费。
3. **通话记录**：会话结束后前端轮询 `GET /v2/conversations/{id}?verbose=true`（后端加只读代理端点，
   指数退避直到 `status=ended`，上限 ~2 分钟），取 `transcription_ready` 转写：
   - 页面内展示本次对话记录
   - 写入本地会话归档（复用 `vs_conversation_history` 机制），后续可一键"发送到聊天"
4. **验收**：创建带 context 的会话 → PAL 开场白生效；结束后转写出现在记录区；全程无孤儿会话（Tavus 控制台核对）。

### Phase 3 — 可靠性与安全加固

1. **私有房间默认化评估**：`require_auth` 开关 + token 有效期说明（与 `participant_absent_timeout` 联动）。
2. **状态对账**：leave/卸载后对 `DELETE` 结果做一次 `GET` 复核，失败重试一次，消除计费悬挂。
3. **错误映射完善**：按 `sections/errors-and-status-details.md` 把上游 4xx 映射为可操作的双语提示
   （key 无效 / 并发槽满 / 套餐时长上限）。
4. **EU 区域选项**（`policy: "eu"`）作为高级配置。
5. **验收**：断网/错 key/并发占满三类故障演练，均有明确 UI 反馈且无残留会话。

### Phase 4 — 分身工作台（PAL/Face/Voice 管理）

1. Faces 列表接入（`GET /v2/faces`），会话创建时可选 `face_id`（stock face 直接可用）。
2. PAL 详情只读展示（`GET /v2/pals/{id}`）：pipeline 层、objectives 概览。
3. PAL 创建/编辑（`POST/PATCH /v2/pals`）：prompt、LLM 选型、TTS voice —— 建议先做"从 stock PAL 复制再改"路径。
4. 验收：在 Echo 内完成"挑 stock PAL → 换 stock Face → 存为我的分身 → 发起会话"。

### Phase 5 — 知识与记忆

1. **memory_stores 自动标注**：创建会话时默认带 `["client-<clientId>-<palId>"]`（clientId 复用前端现有
   `getClientId()`），实现跨会话记忆；记忆删除走 `DELETE /v2/memories/...`（可放进设置页）。
2. **知识库**：`POST /v2/documents` 上传 → `document_ids` 挂到会话。与 Echo 转写库联动：
   把已有转写文本直接作为 document 提供给 PAL（"和我的会议记录对话"场景）。
3. **与 EverMem 的边界**（见 §9）：Tavus memories 管"分身的长期人设记忆"，EverMem 管 Echo 全场景记忆，
   默认不互写。

### Phase 6 — 数据闭环（可选增强）

1. 仅当用户配置了公网入口（沿用 transcription `public_base_url` 的思路）时启用 webhook：
   后端新增回调接收端（校验 `conversation_id` 存在性；Tavus 无签名机制，不能当鉴权边界），
   事件写入会话存储。
2. 默认路径仍是 Phase 2 的轮询；webhook 只做"更快的就绪通知"（`system.pal_joined` → UI 提示）。
3. 录制（`enable_recording` + 自备 S3/GCS/Azure）按需开启。

### 明确不做（当前）

- Echo Mode / 自定义 LLM / LiveKit / Pipecat 集成模式（与现有 realtime 管线重叠）
- Magic Canvas、Skills、Deployments、异步 Video 生成
- 移动端（React Native via Daily）

## 7. 安全与配置规范

- API key 只存两处：本机 localStorage（经 `X-Tavus-Api-Key` header 按请求转交）或后端环境变量。
  **永不提交仓库、永不出现在前端 bundle**（官方文档同款要求）。
- 后端对 header key 与 env key 的取舍逻辑收敛在 `tavus_config.py`，禁止在 router 层直接读环境变量。
- 新增端点继续走 `/api/tavus` 前缀，自动纳入现有鉴权中间件（写方法需 Bearer）。
- `meeting_token` 属于短期凭证：仅驻内存与 join 调用，不落 localStorage。

## 8. 风险与对策

| # | 风险 | 对策 |
| --- | --- | --- |
| R1 | 计费/并发：异常路径残留活跃会话 | P1 已处理 join 失败路径；P3 状态对账兜底；默认超时参数（P2） |
| R2 | WebView2 桌面端 WebRTC 兼容性（回声消除、设备枚举差异） | 已有 media 参数放行；真实设备端到端测试列入用户验收 |
| R3 | 大陆网络访问 tavusapi.com 与 tavus.daily.co 的连通性/延迟 | 用户实测；必要时记录代理配置说明（不放默认逻辑） |
| R4 | 套餐差异（max_call_duration 上限、并发数）随套餐变化 | 上游自动封顶（文档确认）；错误信息透传原始 message |
| R5 | 记忆双写（Tavus memories vs EverMem）语义冲突 | 默认不互通；如需打通只允许单向导出（见 §9） |

## 9. 待决问题（需要产品拍板）

1. **记忆策略**：是否启用 Tavus `memory_stores`（默认标签 `client-<id>-<palId>`）？与 EverMem 是否需要打通？
2. **私有房间**是否默认开启（更安全，但 token 过期重进需要重建会话）？
3. **通话记录留存范围**：仅本机会话归档，还是同时写入 EverMem 记忆？
4. **Phase 4 的深度**：只做只读选择器（Faces + stock PAL），还是开放 PAL 编辑器（工作量约 3–5 倍）？
5. 真实账号端到端验证与网络连通性（R2/R3）需要用户提供 key 后联测。
