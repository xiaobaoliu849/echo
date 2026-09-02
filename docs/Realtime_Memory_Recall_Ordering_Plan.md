# 实时语音记忆时序重构规划（Recall Ordering Redesign）

Date: 2026-09-02

## 背景与问题

用户反馈：实时语音对话中，记忆系统的时序逻辑反了。当前现象是「刚开会话就提示
已尝试回忆：本地待同步 0 条，云端 0 条」，但此时根本还没有存入任何记忆——
「你都没有存入，哪里来的记忆呢？」

用户期望的正确流程是：

1. **明确触发**要回忆哪些内容（而不是每一轮自动回忆）
2. 从云端调用对应记忆
3. 将结果注入当前回答

当前实现是「每轮自动回忆 → 生成回答 → 轮末存储」，顺序与期望相反，且在
新会话首轮必然命中空记忆。

---

## 一、现状分析（Current Behavior）

### 1.1 涉及的核心文件

| 层 | 文件 | 职责 |
|---|---|---|
| 后端核心 | `backend/services/realtime_memory_session.py` | `RealtimeMemorySession`：回忆 + 存储 + 本地待同步缓存 + 启动注入 |
| 后端云服务 | `backend/services/evermem_service.py` | `EverMemService`：EverOS Cloud v1 HTTP 客户端 |
| 后端配置 | `backend/services/evermem_config.py` | `EverMemConfig`：解析配置、scope/group_id |
| 后端 Provider | `realtime_dashscope_provider.py` 等 8 个 provider | 各自驱动「回忆→回答→存储」轮次 |
| 后端共享 | `realtime_voice_service.py` | `_build_realtime_instructions` / `_build_recall_miss_instructions` |
| 文字对话 | `backend/services/evermem_helper.py` + `llm_service.py` | 文字链路记忆（与语音链路独立） |
| 前端 | `frontend/src/hooks/useVoiceChat.ts` | 生成「已尝试回忆」状态文案、发送 config 命令、处理 `memory_context` 事件 |
| 前端 | `frontend/src/api/client.ts` | `buildVoiceChatWebSocketUrl` / `buildEverMemHeaders` |
| 前端 | `frontend/src/components/settings/MemorySettingsSection.tsx` | 记忆设置 UI |
| 前端 | `frontend/src/pages/ChatPage.tsx` | 渲染记忆标签 |

### 1.2 当前单轮执行时序（以 DashScope 为例，`realtime_dashscope_provider.py`）

```
用户说话 → 最终转写到达 (user_transcript)
  ① memory_session.note_user_transcript(user_text)      # line 553  记录查询文本
  ② retrieval = await memory_session.retrieve_memory_context()  # line 557  ★回忆——轮首
  ③ emit memory_context 事件                             # line 563
  ④ 重新配置 instructions（注入记忆）                    # line 579-593
  ⑤ 模型生成回答（assistant_text / assistant_audio）
  ⑥ turn_complete → memory_session.flush_turn()           # line 669  ★存储——轮末
  ⑦ emit memory_write 事件                               # line 673
```

**关键矛盾**：同一轮内，②回忆发生在⑥存储之前。回忆只能取到**之前轮次/会话**
存入的内容。在新会话首轮（缓存为空、`flush_turn` 尚未执行），②必然返回空，
前端渲染出「已尝试回忆：本地待同步 0 条，云端 0 条」。

### 1.3 三个触发点

| 触发点 | 位置 | 说明 |
|---|---|---|
| (A) 会话启动注入 | `kickoff_startup_context` (line 500) | **已默认禁用**（`_STARTUP_INJECTION_ENABLED = False`）。开启时在 WebSocket 打开后后台拉取「上次对话以来的记忆」注入首轮；关闭时为 no-op，会话开场不再自动搜云端。 |
| (B) 每轮自动回忆 | `retrieve_memory_context` (line 688) | 每个满足 `should_retrieve_context` 的轮次触发。**已收紧**：仅提示词命中或问句指向记忆主题才触发，删除了长度兜底和分类兜底。 |
| (C) 强制回忆兜底 | `is_forced_recall_query` (line 680) | 问题命中「记得/上次/回忆」等提示词但回忆为空时，切换到 `_build_recall_miss_instructions`。 |
| (D) 显式回忆命令 | `recall_by_query` + `recall` 命令 | 前端发送 `{type:"recall",query:"..."}`，后端绕过门控直接搜本地+云端，结果暂存为一次性注入块，下一轮注入回答。 |

### 1.4 `should_retrieve_context` 的门控逻辑（line 611）

- 禁用/空文本 → 跳过
- `should_skip_memory`（寒暄、感叹等琐碎消息）→ 跳过
- 命中 `_RETRIEVE_HINT_PATTERNS`（之前/上次/记得/回忆/搜索…）→ 触发
- 可分类为偏好/约束/待办/任务上下文 → 触发
- 是问题且指向记忆主题（≥8 字）→ 触发
- 兜底：长度 ≥18 字 → 触发

**问题**：兜底条件太宽。任何 18 字以上的正常对话都会自动触发回忆，导致用户
在普通对话中也看到「已尝试回忆」的提示，且首轮必然为空。

### 1.5 存储逻辑（`flush_turn`, line 333）

- 轮末提取用户发言中的记忆条目（最多 2 条/轮）
- 分类：语音偏好/用户偏好/约束条件/待办事项/当前任务上下文/会话摘要
- **问题类语句永不存储**（line 831）
- 写入本地待同步缓存 + 云端 `add_memory`

### 1.6 前端文案生成（`useVoiceChat.ts`）

- `buildMemorySourceSummary` (line 672)：`total===0` 时生成
  `已尝试回忆：本地待同步 ${local} 条，云端 ${cloud} 条`
- `describeMemoryContext` (line 695)：`memories_retrieved>0` 显示
  `已回忆 N 条…`；`attempted && count===0` 显示
  `已尝试回忆，但未命中匹配记忆…`
- `memory_context` 事件处理 (line 960) 设置状态并触发文案

---

## 二、问题总结

| # | 问题 | 影响 |
|---|---|---|
| P1 | 时序倒置：回忆在轮首、存储在轮末 | 首轮及新内容永远无法在当前轮被回忆 |
| P2 | 自动回忆门控过宽（≥18 字兜底） | 普通对话也触发回忆，产生无意义的「0 条」提示，干扰对话流 |
| P3 | 首轮启动注入只覆盖历史会话 | 当前轮刚说的内容无法即时回溯 |
| P4 | 「0 条」提示语义错误 | 给用户「在回忆」的错觉，实则无记忆可回 |
| P5 | 显式回忆与自动回忆边界模糊 | 用户无法区分「我问了所以它回忆」与「它自作主张回忆」 |

---

## 三、目标设计（Target Design）

### 3.1 核心原则

1. **回忆是显式行为**：仅当用户明确表达回忆意图时才触发云端检索，
   不再对普通对话自动回忆。
2. **先存后忆**：当前轮的有价值内容先落盘（本地待同步），再决定是否
   需要跨轮/跨会话回忆。
3. **零命中不打扰**：回忆触发但无结果时，不向用户展示「已尝试回忆 0 条」
   这类噪声；改为静默或仅在显式回忆时给出「没有找到相关记忆」的简短说明。
4. **低延迟安全**：实时语音回忆仍需短超时 + fail-open，不阻塞对话。

### 3.2 期望时序

```
用户说话 → 最终转写
  ① 记录用户文本
  ② 判断是否「显式回忆请求」(is_explicit_recall)
     ├─ 是 → 触发云端检索（含本地待同步缓存）→ 注入 → 回答
     └─ 否 → 不触发自动回忆，直接回答
  ③ 模型生成回答
  ④ turn_complete → flush_turn（存储当前轮有价值内容）
```

### 3.3 显式回忆的判定（新 `is_explicit_recall`）

替换当前的宽兜底逻辑，仅在以下情况触发回忆：

- **A. 提示词命中**（保留并收紧 `_RETRIEVE_HINT_PATTERNS`）：
  - 中文：「记得」「上次」「之前我们」「上次聊」「回忆一下」「你记得吗」「我之前说过」
  - 英文：「do you remember」「last time」「previously」「recall」「we talked about」
- **B. 指向记忆主题的问题**：问题 + 命中任务/语音/偏好/约束类模式词
  （保留现有 `question_targets_memory` 逻辑，删除 ≥18 字长度兜底）
- **C. 用户主动指令**（新增）：前端可发送显式回忆命令
  `{type:"recall", query:"..."}`
  让用户能主动指定「回忆什么」，而不必把意图塞进自然对话里。

**删除**：`should_retrieve_context` 中 `len(candidate) >= 18` 的长度兜底分支
（line 673-678）与「可分类即触发」分支中的非问题场景（保留分类用于存储，
但分类≠需要回忆）。

### 3.4 零命中处理

| 场景 | 现状 | 目标 |
|---|---|---|
| 自动回忆命中 0 条 | 展示「已尝试回忆 0 条」 | 不展示（因为不再自动回忆） |
| 显式回忆命中 0 条 | `_build_recall_miss_instructions` 兜底 | 保留：模型明确说「没有找到相关记忆」 |
| 显式回忆命中 N 条 | 展示「已回忆 N 条」 | 保留 |

### 3.5 会话启动注入（A 路径）的去留

**已默认禁用**（`_STARTUP_INJECTION_ENABLED = False`）。用户的需求是「明确触发
后才从云端调用」，启动注入在每次开语音会话时自动搜云端，与该需求矛盾。禁用后
会话开场不再有任何 `memory_context` 事件或云端 search 调用，模型当作全新对话
开始。用户可通过提示词（"记得/上次…"）或 `recall` 命令显式触发回忆。

如未来需要让模型开场自动知道上次聊了什么，可将 `_STARTUP_INJECTION_ENABLED`
设为 `True` 重新开启，或在设置 UI 中暴露为用户可选开关。

---

## 四、改动清单（Change Plan）

### 4.1 后端

#### 4.1.1 `realtime_memory_session.py`

- **新增** `is_explicit_recall(text) -> bool`：整合提示词命中 + 记忆主题问题 +
  外部指令判定，取代 `should_retrieve_context` 在回忆路径上的使用。
- **修改** `should_retrieve_context`：
  - 删除 `len(candidate) >= 18` 长度兜底（line 673-678）。
  - 删除「可分类即触发回忆」分支（line 638-650）——分类仍用于存储，但不再
    驱动回忆。
  - 仅保留：提示词命中 + 记忆主题问题 + （新增）外部 `recall` 命令。
- **修改** `retrieve_memory_context` / `_retrieve_turn_context`：
  - 仅在 `is_explicit_recall` 为真时执行本地+云端检索。
  - 非显式回忆时返回 `attempted: false`，不发事件。
- **禁用** `kickoff_startup_context`：新增 `_STARTUP_INJECTION_ENABLED = False`
  类级开关，默认禁用启动注入。`kickoff` 在关闭时为 no-op，不创建后台任务、
  不搜云端、不发事件。如需恢复设为 `True` 即可。
- **新增** `recall_by_query(query: str)`：供前端 `recall` 命令调用，
  强制走本地+云端检索，不受 `should_retrieve_context` 门控。

#### 4.1.2 `realtime_voice_service.py` 及各 provider

- **修改** `config` 命令处理器（line 558）：新增对 `{type:"recall",query:"..."}`
  的处理，调用 `memory_session.recall_by_query` 后注入 instructions 并发
  `memory_context` 事件。
- **修改** 各 provider 的轮首逻辑（如 DashScope line 557）：将
  `retrieve_memory_context()` 调用改为仅在 `is_explicit_recall` 为真时执行。
- 保留轮末 `flush_turn` 存储不变。

#### 4.1.3 不改动

- 文字链路（`evermem_helper.py` / `llm_service.py`）的 `prepare_memory_context`
  时序独立，本次不纳入（文字链路本身是「发送前检索」，无轮内倒置问题）。

### 4.2 前端

#### 4.2.1 `useVoiceChat.ts`

- **修改** `memory_context` 事件处理（line 960）：
  - `attempted=false` 或 `memories_retrieved===0 && !explicit` → 不设状态文案。
  - 仅在 `memories_retrieved>0` 或显式回忆零命中时展示。
- **修改** `buildMemorySourceSummary`（line 672）/ `describeMemoryContext`
  （line 695）：
  - 删除/隐藏 `total===0` 的「已尝试回忆 0 条」分支。
  - 显式回忆零命中时改为 `没有找到相关记忆`。
- **新增** 发送 `recall` 命令的能力：暴露 `recallMemory(query)` 给 UI，
  通过 WebSocket 发送 `{type:"recall",query}`。

#### 4.2.2 `ChatPage.tsx`

- `memorySourceSummary` 标签渲染保持，但空字符串不渲染（现状已如此）。

#### 4.2.3 `MemorySettingsSection.tsx`

- 无需改动；设置项不变。

### 4.3 测试

- `backend/tests/`：新增/修改 `realtime_memory_session` 测试：
  - 普通长对话（≥18 字、非回忆意图）不再触发检索。
  - 提示词命中触发检索。
  - `recall` 命令触发检索。
  - 启动注入为空时不产生 `attempted=true`。
- `frontend/src/`：修改 `useVoiceChat` 测试：
  - `memory_context` 事件 `attempted=false` 时不展示状态。
  - 显式回忆零命中展示「没有找到相关记忆」。

---

## 五、深度检查：更好融入的考量（Deep Integration Check）

### 5.1 与文字对话链路的一致性

文字链路（`useChat.ts` → `llm_service.prepare_memory_context`）是「发送前检索」，
无轮内倒置问题。但同样存在「0 条」噪声的可能。建议统一两路文案策略：
零命中静默，命中才提示。本次聚焦语音链路，文字链路作为后续对齐项。

### 5.2 本地待同步缓存的角色

本地待同步缓存（`%APPDATA%\Echo\realtime_pending_memory.json`）是「刚写入、
云端尚未索引」的即时回溯桥梁。在显式回忆中应优先搜本地缓存（已实现），
保证「这一轮说了，下一轮问就能取到」——这恰好是用户「先存后忆」诉求的
技术落点。需确保显式回忆即使云端超时，本地缓存仍能返回结果。

### 5.3 实时语音延迟安全

显式回忆仍需短超时（`_FORCED_RETRIEVE_TIMEOUT_SECONDS = 0.35` 已较合理）。
云端超时 → fail-open，模型按无记忆回答，但不阻塞对话。本地缓存检索是同步
操作，几乎零延迟，应作为显式回忆的保底。

### 5.4 「深度检查」建议项

| 项 | 现状 | 建议 |
|---|---|---|
| 记忆条目质量 | 启发式分类，最多 2 条/轮 | 可引入 LLM 辅助提取（后续），本次不改 |
| 问题永不存储 | line 831 | 合理，保留；但显式回忆的查询本身可记为「会话上下文」 |
| 跨 provider 一致性 | 8 个 provider 各自实现轮首逻辑 | 抽取到 `realtime_voice_service` 共享方法，减少散落 |
| 启动注入超时 | 3.0s | 对实时首轴略长，建议降到 1.5s，超时则跳过不阻塞首轮 |
| `recall` 命令 UX | 无 | 可在 ChatPage 提供「回忆」按钮或语音指令「回忆一下…」 |

### 5.5 风险

- 收紧门控后，部分原本能自动触发的回忆场景会变成「不触发」。需确认这些
  场景是否可由用户显式发起（提示词或命令）覆盖。若否，需保留一个「轻量
  自动回忆」开关，让高级用户可选开启。
- 删除长度兜底可能影响「长但无提示词」的记忆性陈述。建议保留「可分类为
  偏好/约束/待办」的触发，但仅限问题语句——陈述句不触发回忆，只触发存储。

---

## 六、实施顺序

1. **后端门控收紧**：修改 `should_retrieve_context`，删除长度兜底和分类兜底，
   新增 `recall_by_query`。
2. **后端启动注入禁用**：`_STARTUP_INJECTION_ENABLED = False`，会话开场不自动搜云端。
3. **后端 provider 接入**：`recall` 命令处理 + 轮首门控。
4. **前端文案**：零命中静默 + 显式零命中文案。
5. **前端 `recall` 命令**：`recallMemory(query)` + UI 入口（可选，先做命令通道）。
6. **测试**：后端 + 前端单测。
7. **验证**：`npm run test:run` + `npm run build` + `python -m pytest -q`。

---

## 七、验收标准

- [ ] 新会话首轮普通对话不再出现「已尝试回忆 0 条」。
- [ ] 18 字以上的普通陈述句不触发自动回忆。
- [ ] 命中「记得/上次/之前」等提示词时正常回忆并注入。
- [ ] 前端 `recall` 命令能主动触发指定查询的回忆。
- [ ] 会话开场不再自动搜云端（启动注入默认禁用，无 `memory_context` 事件）。
- [ ] 显式回忆零命中时模型回答「没有找到相关记忆」，而非「已尝试回忆 0 条」。
- [ ] 后端 pytest、前端 vitest、前端 build 全部通过。
- [ ] 各 provider 行为一致（至少 DashScope / OpenAI / Google 三条主线）。
