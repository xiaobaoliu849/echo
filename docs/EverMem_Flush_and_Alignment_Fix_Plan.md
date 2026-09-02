# EverMem/EverOS 记忆集成修复计划

Date: 2026-09-02
Status: 待实施
Related: `docs/Realtime_Memory_Recall_Ordering_Plan.md`, `D:\Projects\vocabbook-modern\EVERMEM_ALIGNMENT_NOTES.md`

## 问题背景

Echo 的实时语音记忆功能经过多轮修复（收紧回忆门控、禁用启动注入、分层超时、scoped+global 合并搜索），但实测仍搜不到记忆。经过对比 EverOS 官方文档和 VocabBook 的集成实现，找到了根因。

## 根因诊断

### 根因 1：不 flush，记忆永远不会被提取（最高优先级）

Echo 的 `add_memory` 调用默认 `async_mode=True` 且不调用 flush。官方文档明确：

> 新写入的消息在提取完成前不可作为 episode 检索；只存在于会话的 raw buffer 中，只能通过 session-pinned search 返回 raw_messages/pending_messages。flush 强制提取。

VocabBook 的对齐文档也记录了这一陷阱：「不 flush 的记忆停留在 pending 状态，不会被提取成可搜索的 episodic_memory」。VocabBook 在每轮助手回复后强制 flush。

**Echo 的 `flush_turn`（`realtime_memory_session.py:341`）写入记忆后没有调用 flush**——这是记忆搜不到的主因。

- 相关文件：`backend/services/realtime_memory_session.py` 的 `flush_turn` → `_persist_entries`（line 582）
- EverOS flush 端点：`POST /api/v1/memories/flush`，参数 `{user_id, session_id}`，已在 `evermem_service.py:88` 实现（`flush_pending_memories`）但从未被调用

### 根因 2：user_id 命名空间不一致（跨 App 互不可见）

| App | user_id 来源 |
|---|---|
| VocabBook | `cloud_<normalized_email>`（从认证服务 `/users/me` 拿到 email） |
| Echo | `token_<sha256[:24]>` 或 `client_<sha256[:24]>`（JWT/客户端 ID 的 hash） |

即使同一个人、同一个 EverOS 账号，两个 App 的 `user_id` 完全不同，EverOS 按 `user_id` 隔离记忆。所以 VocabBook 存的记忆 Echo 搜不到，反之亦然。

- 相关文件：`backend/services/evermem_config.py` 的 `_resolve_scope`（line 101）
- VocabBook 对比：`backend/services/ai_service.py` 的 `_resolve_chat_owner_key`（用 email），`backend/utils/evermem_helpers.py` 的 `normalize_scope_value`

### 根因 3：写入端点和搜索过滤字段不同

| App | 写入端点 | 搜索过滤字段 |
|---|---|---|
| VocabBook | `POST /api/v1/memories/group`（group 端点） | `group_id` |
| Echo | `POST /api/v1/memories`（个人端点） | `session_id`（Echo 把 group_id 映射成 v1 的 session_id） |

Echo 的 `evermem_service.py:34` 的 `_session_id_for` 把 `group_id` 映射成 `session_id`。VocabBook 用 `group_id` 字段过滤。这是不同的 v1 分区字段。

- 相关文件：`backend/services/evermem_service.py` 的 `add_memory`（line 39）、`search_memories`（line 143）、`_session_id_for`（line 34）

## 修复计划

### 第一阶段：flush 修复（最高优先级，最小改动）

**目标**：让写入的记忆及时被 EverOS 提取成可搜索的 episodic_memory。

**改动**：

1. `realtime_memory_session.py` 的 `_persist_entries`（line 582）：在写入所有 entries 后调用 `service.flush_pending_memories(user_id, session_id=group_id)`，让云端立即提取。

   ```python
   # 在 _persist_entries 的循环之后添加：
   if saved_count > 0:
       try:
           await service.flush_pending_memories(
               user_id=self._config.memory_scope,
               session_id=self._config.group_id or None,
           )
       except Exception:
           logger.warning("voice_memory_flush_failed scope=%s", self._config.memory_scope)
   ```

2. `realtime_memory_session.py` 的 `finalize_session`（会话结束时写摘要）：同样在写入摘要后 flush。

3. `evermem_service.py` 的 `flush_pending_memories`（line 88）：确认参数正确——v1 端点 `POST /api/v1/memories/flush` 需要 `{user_id, session_id}`。

**测试**：
- 新增测试验证 `flush_pending_memories` 被调用
- 新增测试验证 `flush` 失败不阻塞主流程（fail-open）

**风险**：
- flush 增加一次云端往返，可能增加 `flush_turn` 的延迟。实时语音的 `flush_turn` 在 `turn_complete` 时调用（轮末），不阻塞用户等待回答。但需确认不会拖慢下一轮的开始。
- flush 频率：每轮都 flush 可能给 EverOS 带来压力。可考虑批量 flush（每 N 轮或会话结束时）。

### 第二阶段：user_id 对齐（跨 App 记忆共享）

**目标**：让 Echo 和 VocabBook 使用相同的 user_id，使记忆跨 App 可见。

**改动**：

1. `evermem_config.py` 的 `_resolve_scope`：改为优先从 Bearer token 解析 email，生成 `cloud_<normalized_email>`（对齐 VocabBook 的 `normalize_scope_value` 逻辑）。
2. 需要调用 EverOS 认证服务 `GET {API_URL}/users/me` 拿到 email，或者从 JWT payload 直接解析 `sub`/`email`。
3. 保留现有的 `client_<hash>` 作为未登录用户的 fallback。

**风险**：
- 改变 user_id 会导致旧记忆（存储在 `token_<hash>` 命名空间下）变成孤儿，无法被新 user_id 搜到。需要在设置 UI 提示用户。
- 需要确认 Echo 的前端是否携带 Bearer token（目前可能只传 `X-EverMem-Key` 和 `scope_id`）。

### 第三阶段：写入端点对齐（可选）

**目标**：让 Echo 和 VocabBook 使用相同的 v1 端点和过滤字段。

**改动**：

1. `evermem_service.py` 的 `add_memory`：改为使用 `POST /api/v1/mories/group`（group 端点），与 VocabBook 一致。
2. `search_memories`：过滤字段从 `session_id` 改为 `group_id`。

**风险**：这是较大的改动，可能影响已有的搜索逻辑。如果第一阶段和第二阶段已经能让记忆工作，此阶段可延后。

## 验证方法

### 查看云端实际存储了什么

用 `POST /api/v1/memories/get`（不是 search）分页列出所有存储的记忆：

```python
# 列出 episodic_memory
POST https://api.evermind.ai/api/v1/memories/get
{
  "filters": {"user_id": "<你的 user_id>"},
  "memory_type": "episodic_memory",
  "page": 1,
  "page_size": 20
}

# 列出 profile
POST https://api.evermind.ai/api/v1/memories/get
{
  "filters": {"user_id": "<你的 user_id>"},
  "memory_type": "profile",
  "page": 1,
  "page_size": 20
}
```

注意：`get` 是分页列表（非搜索排序），pending raw messages 无法通过 `get` 列出——只能通过 session-pinned search 返回 `raw_messages`/`pending_messages`。

### 测试跨会话回忆

1. 开一个语音会话，聊几轮有价值的内容（偏好、任务等）
2. 结束会话（触发 `finalize_session` + flush）
3. 开新会话
4. 说「你还记得我们上次聊了什么吗？」（触发 forced recall + global search）
5. 验证 EverOS 后台有两条 search 调用（scoped + global）
6. 验证模型回答包含上次会话的内容

## 官方文档参考

- 官方文档：https://docs.evermind.ai（完整索引 https://docs.evermind.ai/llms.txt）
- API Keys：https://everos.evermind.ai/api-keys
- 开源仓库：https://github.com/EverMind-AI/EverOS
- v1 vs v2：Echo 的 EverOS 账号被 gated 到 v1（v2 返回 `VERSION_NOT_ALLOWED`），必须继续用 v1 端点

### v1 API 关键行为

- `POST /api/v1/memories`：写入，默认 async（HTTP 202），后台提取；`async_mode: false` 同步
- `POST /api/v1/memories/flush`：强制提取指定 session 的 pending messages
- `POST /api/v1/memories/search`：搜索，`filters: {user_id}` 跨会话，加 `session_id` 限定单会话并返回 raw buffer
- `POST /api/v1/memories/get`：分页列表（非搜索），列出所有 episodic_memory / profile
- `POST /api/v1/groups`：注册 group 元数据（v1-only，v2 已移除）；不负责分区——分区靠 add/search 时传 `session_id`

### user_id 是跨会话/跨 App 的关键维度

- `user_id` 是 EverOS 的记忆归属分区
- 只用 `filters: {user_id}` 搜索 = 跨所有会话的提取记忆
- 加 `session_id` = 限定单会话 + 返回未提取的 raw buffer
- 不同 App 用不同 `user_id` = 记忆互不可见

## VocabBook 对齐参考

文件：`D:\Projects\vocabbook-modern\EVERMEM_ALIGNMENT_NOTES.md`

VocabBook 记录的关键陷阱：
1. 写入时必须用 `group_id=session_id`，否则跨会话找不到
2. **flush 是必须的**——不 flush 的记忆停留在 pending 状态
3. review 记录在云端即使写入了也搜不到，只能靠本地 SQLite 补偿
4. `sender_id` 必须与 `user_id` 对齐（EverOS 内部用 sender_id 做记忆归属）
5. `pending_messages` 必须显式处理（搜索结果可能包含 pending_messages）
6. 新 UI 对话不自动意味着新 EverMem group——需要显式创建并持久化 group_id
