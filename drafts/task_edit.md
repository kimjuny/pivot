# Task Edit / Rewind 功能实现规划

## 概述

在已执行的 Task 的用户 Chat Input 上新增 **Edit** 功能。用户编辑历史消息后，可选择两种模式重新执行：

1. **仅回退对话** — 丢弃该消息之后的所有对话和任务记录，从编辑后的消息重新开始
2. **回退对话 + 撤销沙箱变更** — 除上述外，还要将沙箱中的文件变更回退到编辑点之前的状态

类似 Claude Code 的 `/rewind` 功能。

---

## Claude Code `/rewind` 参考分析

### 核心机制

Claude Code 的 rewind 在两个独立维度上操作：

| 维度 | 机制 | 说明 |
|------|------|------|
| **对话回退** | 内存数组截断 | `messages.slice(0, selectedIndex)`，截断后生成新 `conversationId`，重置缓存状态 |
| **代码回退** | 文件快照恢复 | 在每次文件写入/编辑前，将文件备份到 `{configDir}/file-history/{sessionId}/`，回退时从备份恢复 |

### Compaction 与 Rewind 的交互（关键参考）

Claude Code 对 compaction + rewind 冲突的处理策略：**不允许 rewind 到 compaction 之前。**

- Compaction 发生后，pre-compact 的消息从内存数组中移除
- MessageSelector 只显示当前 `messages` 数组中的用户消息
- Pre-compact 的用户消息根本不出现在选择列表里
- 如果尝试 rewind 到已不存在的消息，代码会检测到并跳过
- **Compaction 是一扇单向门**

### 快照系统

- 最多保留 100 个快照（LRU 淘汰）
- 在 `FileEditTool`、`FileWriteTool`、`NotebookEditTool` 和 `BashTool` 执行前触发备份
- 每条 User Message 后生成一次聚合快照 `fileHistoryMakeSnapshot()`
- 备份文件以 `{hash}@v{version}` 命名存储在本地文件系统
- `resetMicrocompactState()` 在 rewind 时清除过时的 cache edit 引用

### 与 Pivot 的关键差异

| 维度 | Claude Code | Pivot |
|------|-------------|-------|
| 运行环境 | 本地单机 | 多用户 + 沙箱容器 + 可能的 K8s 分布式 |
| 消息存储 | 内存 + JSONL 文件 | 数据库 (SQLite/PostgreSQL) |
| 文件操作 | 直接操作本地文件系统 | 通过 sandbox-manager HTTP API 操作容器内文件 |
| 已有快照机制 | 完整的文件备份系统 | 无 |
| Task History 持久性 | 非全屏模式下 compaction 后丢失 | 数据库中永久存在 |

---

## Pivot 架构关键点

### 数据模型层次

```
Session (1) ──< ReactTask (N) ──< ReactRecursion (N, cascade delete)
                               ──< ReactPlanStep (N, cascade delete)
              ──< ReactTaskEvent (N, 手动删除)
              ──< ReactRecursionState (N, 手动删除)
              ──< TaskAttachment (N)
```

- **ReactTask** = 一次用户请求（一条用户消息 + Agent 全部回复）
- **ReactRecursion** = 一次 ReAct 思考-行动循环
- **ReactTaskEvent** = SSE 事件日志（append-only，用于流式推送和重连）
- ORM cascade 仅覆盖 `ReactRecursion` 和 `ReactPlanStep`，`ReactTaskEvent`、`ReactRecursionState`、`TaskAttachment` 需手动清理

### Compaction 对 Pivot Session 的影响

Compaction 发生后，`Session.react_llm_messages` 变为：

```
[system_prompt(0), compact_result(1), ...current_task_messages(2+)]
```

- `compact_result` 是一个不可逆的有损摘要，混合了所有被压缩 task 的信息
- 被压缩 task 的 `runtime_message_start_index` 变得无效（指向已不存在的消息位置）
- Compaction 后的第一个 task 的 `runtime_message_start_index` 被更新为 2（system + compact 之后）

### 前端消息模型

- 前端通过 `buildMessagesFromHistory(tasks)` 将 `TaskMessage[]` 转为 `ChatMessage[]`
- 每个 Task 生成一对 `user-{task_id}` + `assistant-{task_id}` 消息
- 可能因 CLARIFY 动作拆分为多段

### 沙箱系统

- sandbox-manager 是独立的 FastAPI 服务，通过 Podman API 管理容器
- 容器按 `{user_id}-{workspace_id}` 命名，有池化和 LRU 淘汰机制
- **当前没有任何快照或检查点 API**
- Workspace 挂载在 `/workspace/`，是持久化存储；其他路径随容器销毁消失

### 会话状态

- `Session.react_llm_messages` — LLM 消息数组（serialized OpenAI-style messages）
- `Session.react_compact_result` — context compaction 摘要 JSON
- `Session.react_file_read_tracker` — 已读文件跟踪
- `ReactTask.runtime_message_start_index` — 该 task 消息在 react_llm_messages 中的起始位置

---

## 已确认的设计决策

### 1. Compaction 交互策略

**Phase 1：与 Claude Code 一致 — compaction 是单向门。**

- 只允许编辑 current context 中仍存在的 task
- 如果 task 的信息已被 compaction 到 `compact_result` 中，edit 按钮置灰/隐藏
- 前端判断：task 是否在已加载的消息列表中（最简单的方式）
- 后端做二次校验：检查 `runtime_message_start_index` 是否在当前 `react_llm_messages` 范围内

**Phase 2（可选优化）：允许编辑 pre-compact 的 task，但需清空整个 current context。**

如果用户确实需要编辑很早之前的消息，可以接受"失忆"代价。实现时需要在 `Session` 上新增 `compact_last_task_id` 字段来追踪 compaction 边界。

### 2. 编辑后的 Task 归属关系

暂不需要。编辑产生全新 task，不记录来源。

### 3. 并发安全

编辑前必须确保：
- 目标 task 已结束（status 为 completed/failed/cancelled）
- Session 中无正在运行的 task（runtime_status != "running"）
- 使用 `SELECT ... FOR UPDATE` on session row 防止竞态

### 4. 批量删除性能

使用子查询批量 DELETE，每张表一条 SQL：

```sql
DELETE FROM react_task_event
WHERE session_id = ? AND task_id IN (
    SELECT task_id FROM react_task
    WHERE session_id = ? AND created_at >= ?
);

DELETE FROM react_recursion_state
WHERE task_id IN (
    SELECT task_id FROM react_task
    WHERE session_id = ? AND created_at >= ?
);

DELETE FROM task_attachment
WHERE task_id IN (
    SELECT task_id FROM react_task
    WHERE session_id = ? AND created_at >= ?
);

-- ReactTask cascade 自动删 ReactRecursion 和 ReactPlanStep
DELETE FROM react_task
WHERE session_id = ? AND created_at >= ?;
```

### 5. 沙箱快照方案（Phase 2）

**使用独立隐藏 git repo，存储在 `/workspace/.pivot/git/`。**

- 使用 `--git-dir=/workspace/.pivot/git --work-tree=/workspace` 操作，完全不影响用户 repo
- `/workspace/` 是 volume mount，sandbox 容器回收后数据仍在
- Task 开始前 `git add -A && git commit`，rewind 时 `git reset --hard`
- 用户的 `.git` 不受影响（独立的 GIT_DIR）
- `.pivot/` 会出现在用户 `git status` 中（隐藏目录，影响极小）

不选其他方案的原因：
- Podman commit 不捕获 volume 内容，不可行
- Orphan branch 侵入用户 repo
- 文件级备份实现成本太高

---

## Phase 1 实现详细设计

### 1.1 后端 API

**新增端点**：`POST /react/tasks/{task_id}/edit`

```python
class TaskEditRequest(AppBaseModel):
    new_message: str

class TaskEditResponse(AppBaseModel):
    task_id: str
    session_id: str
    cursor_before_start: int
```

### 1.2 后端 Service 层

在 `SessionService` 中新增方法 `rewind_and_edit_task()`：

```
1. 查询目标任务，获取其 session_id 和 created_at
2. 验证：
   a. 任务属于当前用户
   b. 任务 status 为 completed/failed/cancelled
   c. session.runtime_status != "running"（无正在运行的任务）
   d. 任务的 runtime_message_start_index 在当前 react_llm_messages 范围内
      （防止编辑 pre-compact 的 task）
3. SELECT ... FOR UPDATE on session row（锁定，防竞态）
4. 批量删除同一 session 中 created_at >= 目标任务.created_at 的所有数据：
   a. ReactTaskEvent（子查询批量 DELETE）
   b. ReactRecursionState（子查询批量 DELETE）
   c. TaskAttachment（子查询批量 DELETE）
   d. ReactTask（ORM cascade 自动删 ReactRecursion + ReactPlanStep）
5. 更新 session 状态：
   a. 截断 react_llm_messages 至目标 task 的 runtime_message_start_index
   b. 如果截断导致 compact_result 仍存在但引用了已删除 task → 保留即可
     （因为 Phase 1 不允许编辑 pre-compact 的 task，compact_result 只引用更早的、仍在的 task）
   c. 清除 react_file_read_tracker（被删除的 task 可能修改了文件）
   d. 清除 react_pending_action_result
   e. 清除 react_llm_cache_state
   f. 更新 runtime_status 为 "idle"
6. 创建新的 ReactTask：
   a. 使用编辑后的 new_message 作为 user_message
   b. status = "pending"
7. 调用 ReactTaskSupervisor.start_task() 执行新 task
8. 返回 TaskEditResponse
```

### 1.3 前端 UI

**UserMessageBubble 改造**（`UserMessageBubble.tsx`）：

在现有的 copy 按钮旁添加 edit 按钮：

```
[Copy] [Edit]  |  12:34 PM
```

Edit 按钮仅对满足条件的消息显示：
- task 已完成（非 running/pending）
- session 中无正在运行的任务
- 该 task 在当前已加载的消息列表中（隐式保证：前端只渲染已加载的消息）

点击 Edit 后进入编辑模式：

```
┌─────────────────────────────────────┐
│ [Editable textarea with original    │
│  message text, auto-resize]         │
│                                     │
│ [Cancel]  [▶ Rewind & Resend]      │
└─────────────────────────────────────┘
```

Phase 1 只有一个按钮"Rewind & Resend"（仅对话回退）。Phase 2 时扩展为下拉菜单增加"Rewind + Undo changes"选项。

**交互流程**：

1. 用户点击 Edit 按钮 → bubble 切换为 textarea，预填原始消息
2. 用户编辑文本
3. 用户点击 "Rewind & Resend"
4. 前端调用 `POST /react/tasks/{task_id}/edit` API
5. 收到响应后：
   a. 从 messages 数组中移除该 task_id 及之后的所有消息
   b. 创建乐观的 user + assistant 消息对（与正常发送流程一致）
   c. 通过返回的 cursor 打开 SSE stream
   d. 正常的 applyStreamEvent 流程处理后续事件

### 1.4 可编辑范围限制

| 条件 | 处理 |
|------|------|
| task status 为 running/pending | Edit 按钮隐藏 |
| session 有正在运行的 task | 所有 Edit 按钮隐藏 |
| task 已被 compaction（不在 current context 中） | Edit 按钮隐藏（前端通过已加载消息列表隐式保证） |
| 编辑中间的 task | 丢弃其后所有 task 并重新开始 |

### 1.5 Session 状态处理

回退后需要重置/更新的 session 级别状态：

| 字段 | 处理方式 | 原因 |
|------|----------|------|
| `react_llm_messages` | 截断到 runtime_message_start_index | 移除被删除 task 的消息 |
| `react_compact_result` | 保留 | Phase 1 不允许编辑 pre-compact 的 task，compact_result 仍有效 |
| `react_file_read_tracker` | 清除 | 被删除的 task 可能修改了文件，缓存失效 |
| `react_pending_action_result` | 清除 | 无意义的残留 |
| `react_llm_cache_state` | 清除 | 消息已变更，cache 失效 |
| `runtime_status` | 重置为 idle | 准备启动新 task |

---

## Phase 2：沙箱变更回退

在 Phase 1 基础上，增加对沙箱文件操作的回退能力。

### 2.1 沙箱 Git 快照系统

**存储位置**：`/workspace/.pivot/git/`（在 workspace volume 内，持久化）

**sandbox-manager 新增端点**：

```python
POST /sandboxes/checkpoint
# 请求: { container_name: str, label: str }
# 执行: git --git-dir=/workspace/.pivot/git --work-tree=/workspace add -A
#       git --git-dir=/workspace/.pivot/git --work-tree=/workspace commit -m "{label}"
# 返回: { commit_hash: str, files_changed: int }

POST /sandboxes/restore
# 请求: { container_name: str, commit_hash: str }
# 执行: git --git-dir=/workspace/.pivot/git --work-tree=/workspace reset --hard {hash}
#       git --git-dir=/workspace/.pivot/git --work-tree=/workspace clean -fd
# 返回: { files_restored: int }
```

**初始化**（sandbox 创建时）：

```bash
git --git-dir=/workspace/.pivot/git --work-tree=/workspace init
echo -e "node_modules/\n__pycache__/\n.git/\n*.pyc\n.pivot/" > /workspace/.pivot/.gitignore
git --git-dir=/workspace/.pivot/git --work-tree=/workspace add -A
git --git-dir=/workspace/.pivot/git --work-tree=/workspace commit -m "initial"
```

### 2.2 ReactTask 模型变更

```python
sandbox_checkpoint_hash: str | None = Field(default=None, index=True)
# task 开始前的 git commit hash，用于 rewind 时恢复沙箱
```

### 2.3 Task 执行流程改造

在 `ReactTaskSupervisor._run_task()` 中：
- Task 开始前：调用 sandbox checkpoint，将 commit_hash 写入 ReactTask
- Task 结束后：不额外操作

### 2.4 Rewind 流程扩展

```python
class TaskEditRequest(AppBaseModel):
    new_message: str
    rewind_scope: Literal["conversation", "full"] = "conversation"
```

选择 `"full"` 时，在 Phase 1 步骤之前：
1. 获取编辑目标 task 的 `sandbox_checkpoint_hash`
2. 调用 sandbox-manager restore API，恢复到该 checkpoint
3. 然后执行 Phase 1 的所有步骤

### 2.5 前端 UI 扩展

```
[▶ Rewind & Resend ▾]
  ├─ Rewind conversation only
  └─ Rewind + Undo changes     ← Phase 2 启用
```

---

## 实现顺序

| 步骤 | 内容 | 涉及文件 |
|------|------|----------|
| 1 | 后端 API 端点 + Schema | `server/app/api/react.py`, `server/app/schemas/react.py` |
| 2 | Service 层 rewind_and_edit_task() | `server/app/services/session_service.py` |
| 3 | react_llm_messages 截断逻辑 | `server/app/services/session_service.py` |
| 4 | 前端 UserMessageBubble Edit UI | `web/src/pages/chat/components/UserMessageBubble.tsx` |
| 5 | 前端 API 调用 + 状态管理 | `web/src/utils/api/react.ts`, `web/src/pages/chat/ChatContainer.tsx` |
| 6 | 前端 SSE 重连逻辑 | `web/src/pages/chat/ChatContainer.tsx` |
| 7 | Phase 2: Sandbox git 初始化 | `sandbox_manager/main.py` |
| 8 | Phase 2: Sandbox checkpoint/restore API | `sandbox_manager/main.py` |
| 9 | Phase 2: ReactTask model + supervisor 改造 | `server/app/models/react.py`, `server/app/services/react_task_supervisor.py` |
| 10 | Phase 2: 前端 full rewind UI | `UserMessageBubble.tsx` |

建议先完成 Phase 1（步骤 1-6），验证后再启动 Phase 2。
