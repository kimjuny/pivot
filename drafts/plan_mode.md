# Plan Mode Redesign Draft

> 状态：设计已对齐，待实现（2026-06-10）
> 目标：将 Plan 和 Steps 解耦为两个独立 tool，Plan 是人读的 Markdown，Steps 是机器追踪的结构化数据

---

## 已达成共识

### 1. Plan 和 Steps 解耦为两个独立 Tool

**核心哲学：Plan 是 Plan，Steps 是 Steps。**

- **Plan** = 人读的自由 Markdown，零格式要求。由 `plan` tool 生成，触发用户审阅。
- **Steps** = 机器追踪的结构化数据。由 `task` tool 创建和更新，跟踪执行进度。
- 两者**没有因果关系**。可以只 Plan 不建 Steps，可以只建 Steps 不 Plan，也可以两个都用。
- Agent 自己根据任务复杂度判断用哪个。

**为什么解耦**：
- 用户编辑 Plan 后，Steps 不会自动同步 → Plan 和 Steps 不一致，Agent 按 Steps 走不按 Plan 走
- 解耦后：Plan 只是文档，Steps 在 Approve 后根据（可能已编辑的）Plan 独立创建
- 未来天然支持多 Agent 并行（不同 Agent 认领不同 step）

### 2. Action Types：5 → 3

| 保留 | 理由 |
|------|------|
| `CALL_TOOL` | 执行工具时的控制信号 |
| `CLARIFY` | engine 需要知道"暂停等用户输入" |
| `ANSWER` | engine 需要知道"任务结束" |

| 移除 | 理由 |
|------|------|
| ~~`PLAN`~~ | 改为 `plan` tool。结构化数据不应塞在 envelope 里 |
| ~~`REFLECT`~~ | 无副作用，思考内容放进 `message` 字段即可 |

### 3. `plan` tool

**作用**：生成 Markdown 计划文档供用户审阅。调用后暂停任务，等待用户 Approve / Edit / Reject。

```python
# 入参
{
    "plan_text": "# Plan: 重构认证模块\n\n当前认证逻辑散落在..."  # 自由 Markdown
}

# 出参
{ "success": true }
# 或
{ "success": false, "error": "reason" }
```

**Tool Description**：

```
Generate a markdown plan for the user to review before execution. 
Pauses the task until the user approves, edits, or rejects the plan.

Use when: ambiguous requirements, multiple valid approaches, or high-impact 
changes where getting sign-off first prevents rework.

Skip when: straightforward tasks, clear implementation path, or the user 
gave specific detailed instructions.

After approval, use the `task` tool to create execution steps based on the 
(possibly edited) plan.
```

**参数 Schema**：

| 参数 | 类型 | description |
|------|------|------------|
| `plan_text` | `string` | Full plan in markdown. Include: brief context, step-by-step approach, key files to modify, and how to verify. Concise and actionable. |

### 4. `task` tool

**作用**：创建和更新结构化执行步骤，跟踪任务进度。

```python
# 模式 A：创建 steps（批量）
{
    "action": "create",
    "steps": [
        {"step_id": "1", "subject": "Add auth middleware", "description": "Implement JWT verification middleware"},
        {"step_id": "2", "subject": "Write login endpoint", "description": "Add POST /auth/login with credential validation"},
        {"step_id": "3", "subject": "Write tests", "description": "Integration tests for auth flow"}
    ]
}

# 模式 B：更新 steps（只传有变化的）
{
    "action": "update",
    "steps": [
        {"step_id": "1", "status": "completed"},
        {"step_id": "2", "status": "in_progress"}
    ]
}

# 出参
{ "success": true }
# 或
{ "success": false, "error": "Step '99' not found" }
```

**Tool Description**：

```
Create or update structured execution steps to track progress.

Create: batch-create steps after plan approval, or directly for clear 
multi-step tasks (3+ steps). Assign step_id in execution order.

Update: batch-update only the steps whose status changed this iteration.

Skip when: single straightforward task, or trivial 1-2 step work.
```

**参数 Schema**：

| 参数 | 类型 | description |
|------|------|------------|
| `action` | `"create" \| "update"` | create = new steps, update = change existing step statuses |
| `steps` | `array` | See below |

**steps (create)**：

| 字段 | description |
|------|------------|
| `step_id` | Logical execution order: "1", "2", "3"... |
| `subject` | Concise imperative title, e.g. "Add auth middleware" |
| `description` | What to do and how |

**steps (update)**：

| 字段 | description |
|------|------------|
| `step_id` | Which step to update |
| `status` | `"in_progress"` when starting, `"completed"` only when fully done |

**设计要点**：
- create 和 update 都接受 list，一次 tool call 搞定
- create 批量是因为**创建时机集中**（Plan Approve 后一次性拆分）
- update 批量是因为**一轮 iteration 可能同时完成多个 step**
- `step_id` 由 Agent 指定（不是自增），Agent 按执行顺序编号 1, 2, 3...
- Step 状态枚举：`pending` / `in_progress` / `completed` / `error`

### 5. 存储设计：`.md` + `.json` 文件对

**核心原则：文件是 source of truth，没有 Plan 专属 DB 表。**

```
.pivot/plans/
  ├── {task_id}.md     ← plan tool 写入，自由 Markdown
  └── {task_id}.json   ← task tool 写入，结构化 steps
```

**`.md` 文件**：`plan` tool 写入，零格式要求。承载背景、推理、风险、文件引用、验证命令等。
**`.json` 文件**：`task` tool 写入，结构化数据，前端进度条依赖。

```json
{
  "steps": [
    { "step_id": "1", "subject": "Read auth implementation", "status": "completed" },
    { "step_id": "2", "subject": "Create AuthConfig model", "status": "in_progress" },
    { "step_id": "3", "subject": "Implement AuthService", "status": "pending" }
  ]
}
```

**现有 `ReactPlanStep` 表**：项目未上线，直接移除。

### 6. Envelope 简化

**改前：**
```json
{
  "message": "...",
  "thinking_next_turn": false,
  "action": {
    "action_type": "CALL_TOOL | PLAN | REFLECT | CLARIFY | ANSWER",
    "output": {},
    "step_id": "2",
    "step_status_update": [...]
  }
}
```

**改后：**
```json
{
  "message": "...",
  "thinking_next_turn": false,
  "action": {
    "action_type": "CALL_TOOL | CLARIFY | ANSWER",
    "output": {}
  }
}
```

移除了 `step_id`、`step_status_update`，以及 `PLAN` / `REFLECT` action types。

### 7. Engine 侧改动

| 当前 | 改后 |
|------|------|
| `_parse_call_tool_meta` 用 partial parse 恢复截断的 `step_status_update` | **删除** |
| `_normalize_step_status_update_location` 处理模型位置漂移 | **删除** |
| `_replace_plan` 由 PLAN action 触发 | 由 `plan` tool call 的 `plan_text` + `steps` 入参触发 |
| `_apply_step_status_updates` 由 envelope 字段触发 | 由 `plan` tool call 的 `updates` 入参触发 |
| `ReactPlanStep` DB 表读写 | **删除**，改为文件 I/O |
| `build_current_plan_payload` 从 DB 构建 plan payload | 改为从 `.json` 文件解析 |
| `build_plan_status_line` 一行摘要 | 改为读 `.json` 生成一行摘要 |
| `_link_recursion_to_context` per-step history 构建 | **删除** |

### 8. 为什么要改为文件 + Tool 模式

**三个问题，一次解决**：

| 问题 | 根因 | 解决方式 |
|------|------|---------|
| **Streaming 截断** | `step_status_update` 嵌在 JSON envelope 中，与 native tool_calls 并存时被截断 | Plan 数据走 `plan` tool call，API 保证完整性 |
| **Plan 内容深度浅** | 结构化字段（goal/description/criteria）无法承载推理上下文 | `.md` 文件自由 Markdown，无格式限制 |
| **DB 冗余** | Plan 数据在 DB 和 prompt 中双重维护 | 文件即 source of truth，无 Plan 专属 DB 表 |

### 9. 为什么要改为 Tool 模式

核心问题：当前 `step_status_update` 嵌在 CALL_TOOL 的 JSON envelope 中，与 native tool_calls 并存时，LLM 可能中途切换到输出 tool_calls，导致 envelope JSON 被截断。虽然已有 `try_partial_parse` 做尽力恢复，但 `step_status_update` 在嵌套深处，容易被丢失。

改为 tool 后：tool call arguments 由 LLM API 保证完整性，不存在截断问题，跨模型行为一致。

### 10. `current_steps` 注入策略

**改前**：每轮注入 `current_plan`（Plan 的结构化 steps 快照），无论是否变化。
**改后**：注入 `current_steps`，只在有变化时注入完整数据，无变化时压缩为一行。

```json
// steps 有变化时：注入完整状态
{
  "current_steps": [
    {"step_id": "1", "status": "completed"},
    {"step_id": "2", "status": "in_progress"},
    {"step_id": "3", "status": "pending"}
  ]
}

// steps 无变化时：一行搞定
{
  "current_steps": "no changes"
}
```

**压缩策略（三层）**：

| 场景 | 注入方式 |
|------|---------|
| compaction 前 + steps 有变化 | 一行摘要 `"Steps 1,2 done, Step 3 in_progress"` |
| compaction 后 + steps 有变化 | 完整结构化 steps |
| 任意场景 + steps 无变化 | `"no changes"` |

**判断方式**：服务端对比上一轮的 steps JSON 和这一轮的，相同就压缩。

### 11. Steps 停滞告警

连续 8 轮 steps 无变化时，在 `system_feedback` 中注入告警：

```json
{ "system_feedback": "Steps have not been updated for 8 consecutive iterations" }
```

**阈值**：默认 8 轮。不宜太小（Agent 可能在执行一个大的 step，中间有很多 tool call），也不宜太大（失去催促效果）。

### 12. 调用时序

两个 tool 没有因果关系，Agent 根据任务复杂度自行判断：

```
用户发任务
    │
    ├─ 简单任务 → 直接干，不调任何 tool
    │
    ├─ 复杂但明确 → task(create, [...steps]) → 执行 → task(update, ...)
    │
    └─ 复杂且有歧义 → plan(plan_text) → 用户审阅/编辑
                      → task(create, [...steps]) → 执行 → task(update, ...)
```

---

## 审批模式设计

### 事前审批（多轮对齐）

```
Agent 调 plan(plan_text="...")
    ↓
Engine 检测到 plan tool call，暂停 ReAct 循环
    ↓
SSE → 前端弹出 Plan Review 面板（只展示 Markdown，无 steps）
    ↓
用户操作（4 个选项）：

  ┌─────────────────────────────────────────────────────┐
  │                                                     │
  │  [✅ Approve]  批准 Plan，Agent 继续执行              │
  │     → Agent 调 task(create, steps=[...]) 建步骤      │
  │     → steps 基于（可能已编辑的）plan text 创建         │
  │                                                     │
  │  [✏️ Edit]  用户直接编辑 .md 文件                     │
  │     → 保存后 Engine 告知 Agent "plan modified,        │
  │       re-read .pivot/plans/{task_id}.md"             │
  │     → Approve 后 Agent 按编辑后的 plan 建 steps      │
  │                                                     │
  │  [❌ Reject]  打回重做                                │
  │     → Agent 收到 rejection + reason，重新规划          │
  │                                                     │
  │  [💬 Suggest]  在 Composer 中输入自然语言建议          │
  │     → 作为 role=user 注入 ReAct 循环                  │
  │     → Agent 修订后再次调 plan(plan_text=v2)           │
  │     → 触发下一轮 Review，可反复对齐直到 Approve        │
  │                                                     │
  └─────────────────────────────────────────────────────┘
```

**Suggest 模式的 message 流**：

```
[system] → [user: task]
  → [assistant: plan(plan_text=v1)]
  → [system: plan_review_pending]
  → [user: "Step 2 应该考虑 edge case X，Step 3 和 4 可以合并"]
  → [assistant: "好的，修改了 Plan..." + plan(plan_text=v2)]
  → [system: plan_review_pending]
  → [user: "LGTM"]  ← Approve
  → [assistant: task(create, steps=[...])]  ← 按 v2 plan 建 steps
  → [assistant: 继续执行... task(update, ...)]
```

**实现上**，Plan Review 暂停是 CLARIFY 的变体——Engine 暂停循环，等用户输入，用户输入后恢复。可复用同一个 Engine 暂停机制。

**可配置**：
- `"plan_approval": "always"` — 每次创建 Plan 都要审批（默认）
- `"plan_approval": "auto"` — 自动通过（适合自动化场景）

### 事后审计

- **`.md` 文件**中的 Decision Log / Risks / Surprises sections（叙述性审计）
- **Engine log**：每次 `plan` tool 调用记录 plan_event（task_id, step_id, old_status, new_status, recursion_id, timestamp）
- Plan 文件在工作区中持久保存，可随时查看历史 Plan

---

## 前端交互

### 复用现有 ComposerTaskPlan 进度条

现有的 step 级别进度追踪组件（pending → in_progress → completed → error + spinner/checkmark/error icon）直接复用。

**适配点**：

| 现在 | 改后 |
|------|------|
| 数据来源：DB `ReactPlanStep` 表 | 数据来源：API 读 `.json` 文件解析 |
| 无"查看完整 Plan"入口 | 加 **[📄 View Plan]** 按钮，展开渲染 `.md` 文件 |
| Plan 只在执行中显示 | Plan 在审批阶段也显示（Markdown 渲染，底部 Review 按钮） |

**不需要改的**：
- Step 级别的状态流转和渲染逻辑
- SSE 实时更新机制

### Plan Review 面板（审批阶段）

Agent 调 `plan(plan_text=...)` 后弹出。**只展示 Markdown，不展示 steps。** Steps 是 Approve 后 Agent 自己通过 `task` tool 创建的。

```
┌──────────────────────────────────────────────────────┐
│  📋 Plan Review                              [缩小]  │
├──────────────────────────────────────────────────────┤
│                                                      │
│  # Plan: 重构认证模块                                 │
│                                                      │
│  当前认证逻辑散落在 3 个文件中...                       │
│  主要风险：已发放的 JWT 不能失效                        │
│                                                      │
│  ## 验证                                              │
│  - pytest tests/test_auth.py                         │
│                                                      │
├──────────────────────────────────────────────────────┤
│  [✅ Approve]  [✏️ Edit]  [❌ Reject]  [💬 Suggest]   │
└──────────────────────────────────────────────────────┘
```

- **Approve**：Engine 恢复循环，Agent 继续执行
- **Edit**：打开 Markdown 编辑器，用户直接改 `.md`，保存后 Agent 被告知重新读取
- **Reject**：弹出输入框让用户写 rejection reason，Agent 重新规划
- **Suggest**：回到 Composer 输入自然语言建议，Agent 修订 Plan 后再次触发 Review

### Plan Execution 视图（执行中）

```
┌─ Plan Progress ───────────────────────── [📄 View Plan] ─┐
│  ✅ Step 1: 读取当前认证实现                     done      │
│  🔄 Step 2: 创建 AuthConfig model               running   │
│  ⬜ Step 3: 实现 AuthService                     pending   │
└───────────────────────────────────────────────────────────┘
```

点击 **View Plan** 展开完整 `.md` 文件渲染视图。

### Plan 文件在工作区浏览器

```
📁 .pivot/
  📁 plans/
    📄 abc123.md      ← task abc123 的 Plan（自由 Markdown）
    📄 abc123.json    ← task abc123 的 Steps（结构化追踪）
```

用户可直接打开查看/编辑。

---

## Compaction 恢复

**核心优势：Agent 主动读取，不依赖系统注入。**

```
Engine 注入 role=user:
  "plan_file": ".pivot/plans/{task_id}",
  "current_steps": "Steps 1,2 done, Step 3 in_progress, Steps 4,5 pending"
  // 或 steps 无变化时："current_steps": "no changes"

Agent 自主决定：
  - 需要 Plan 上下文？→ read_file(".pivot/plans/{task_id}.md")
  - 需要精确进度？→ read_file(".pivot/plans/{task_id}.json")
  - 都不需要？→ 继续，省 token
```

| 场景 | 注入方式 |
|------|---------|
| compaction 前 + steps 有变化 | `plan_file` 路径 + 一行 steps 摘要 ~20 tokens |
| compaction 后 + steps 有变化 | `plan_file` 路径 + 完整结构化 steps（Agent 可自行 read_file 获取最新） |
| 任意场景 + steps 无变化 | `"current_steps": "no changes"` |

---

## 格式规范

### `plan` Tool Description

```
Generate a markdown plan for the user to review before execution.
Pauses the task until the user approves, edits, or rejects the plan.

Use when: ambiguous requirements, multiple valid approaches, or high-impact
changes where getting sign-off first prevents rework.

Skip when: straightforward tasks, clear implementation path, or the user
gave specific detailed instructions.

After approval, use the `task` tool to create execution steps based on the
(possibly edited) plan.
```

### `task` Tool Description

```
Create or update structured execution steps to track progress.

Create: batch-create steps after plan approval, or directly for clear
multi-step tasks (3+ steps). Assign step_id in execution order.

Update: batch-update only the steps whose status changed this iteration.

Skip when: single straightforward task, or trivial 1-2 step work.
```

### System Prompt（建议，指导 Plan 质量）

```
## Planning Guidelines

When creating a plan:
1. Research first — read relevant files before planning. Do not plan blindly.
2. Be specific — name exact file paths, function names, and commands.
3. Explain why — include rationale for non-obvious choices.
4. State verification — describe how to confirm each step works.

When creating steps:
1. Keep steps atomic — each step should produce a verifiable result.
2. Limit step count — aim for 3-7 steps. Split further only when truly needed.
3. Assign step_id in execution order (1, 2, 3...).
4. Steps should reflect the (possibly edited) plan.
5. Only mark "completed" when fully done — if tests fail, keep "in_progress".
```

### 校验策略

| 数据 | 校验方式 |
|------|---------|
| `plan_text`（plan tool） | **不校验**。零格式要求，Agent 自由发挥 |
| `steps` 的 `step_id` + `subject`（task tool create） | Schema 校验（类型 + 非空） |
| `steps` 的 `step_id` + `status`（task tool update） | Schema 校验（类型 + 枚举值 + step 存在性） |
| `.md` 文件内容 | 不校验，不解析 |
| `.json` 文件内容 | `task` tool 写入时保证格式正确 |

---

## 已决问题

### Q1: 每个 iteration 在 plan 下必须关联 step 的意义大吗？

**结论：意义不大，移除 per-step recursion linking。**

`ReactRecursion.plan_step_id` 保留为调试字段，不再构建 per-step `recursion_history`，不再注入 prompt。

### Q2: Codex 的 Plan 用的是结构化 steps 还是自由 Markdown？

**结论：Codex 用富 Markdown（ExecPlan），UI 上的"结构化 step"背后是自由 Markdown。**

Codex 的 ExecPlan 是完整工程文档（10+ 必填章节），进度追踪用 Markdown 中的 checkbox。但 Codex 早期 4-tool 状态机已废弃，当前 plan mode 是 stream 原生 + read-only sandbox。

### Q3: Plan 和 Steps 应该耦合还是解耦？

**结论：解耦为两个独立 tool（`plan` + `task`）。**

参考 Claude Code 的设计：Plan（`EnterPlanMode` / `ExitPlanMode`）是纯 markdown 文件，Task（`TaskCreate` / `TaskUpdate` / `TaskList`）是独立的结构化 JSON 系统。两者没有因果关系。

Pivot 简化为两个 tool：
- `plan` — 只管生成 markdown 文档 + 触发用户审阅
- `task` — 只管创建/更新结构化 steps（合并 create + update 为一个 tool，参数用 action 区分）

解耦解决的核心问题：用户编辑 Plan 后 Steps 不会自动同步。解耦后 Plan 只是文档，Steps 是 Approve 后 Agent 根据最终 Plan 独立创建的。

### Q4: `current_plan` 应该注入 Plan text 还是 Steps 状态？

**结论：注入 Steps 状态，重命名为 `current_steps`。**

每轮 user message 中注入的是 steps 的执行状态，不是 plan 的 markdown text。Plan text Agent 需要时自行 `read_file`。无变化时压缩为 `"no changes"` 节省 token。

### Q5: Steps 长时间无更新怎么办？

**结论：连续 8 轮无变化时在 `system_feedback` 中告警。**

```json
{ "system_feedback": "Steps have not been updated for 8 consecutive iterations" }
```

---

## 五方 Plan 实现对比

### 竞品 Tool 设计

| | Claude Code | Codex | OpenCode | Pivot（改后） |
|---|---|---|---|---|
| **Plan tool** | 2（`EnterPlanMode` + `ExitPlanMode`，纯模式切换） | 0（stream 原生） | 1（`todowrite`） | **1（`plan`，生成 markdown + 触发审阅）** |
| **Task/Step tool** | 3（`TaskCreate` + `TaskUpdate` + `TaskList`） | 无（stream event） | 同 `todowrite`（合一） | **1（`task`，create + update 合一，action 区分）** |
| **Plan 内容格式** | 自由 Markdown | 自由 Markdown（ExecPlan） | 自由 Markdown | **自由 Markdown** |
| **Step 追踪方式** | 独立 JSON 文件（`~/.claude/tasks/`） | stream event | SQLite | **`.json` 文件（`step_id/subject/status`）** |
| **Plan 与 Step 关系** | 完全解耦（两套独立系统） | 混在一起（checkbox） | 混在一起（`todowrite` 全量替换） | **完全解耦（`plan` tool + `task` tool）** |
| **审批机制** | 强制（`ExitPlanMode` 弹对话框） | 有（plan mode review） | 有（`plan_exit` 弹确认） | **可配置（Approve/Edit/Reject/Suggest）** |

### 竞品格式规范方式

| | Claude Code | OpenCode | Codex |
|---|---|---|---|
| **格式规定在哪** | system-reminder 注入（每轮附带） | system-reminder 注入（每轮附带） | AGENTS.md + PLANS.md（prompt 工程） |
| **代码校验** | 无 | 无（`todowrite` 校验 todo schema，不校验 plan 文件） | 无 |
| **Claude Code A/B 测试** | 4 种长度变体：CONTROL（完整 Context）/ TRIM（一句话 Context）/ CUT（不要 Context，<40 行）/ CAP（不要 prose，硬限 40 行） | — | — |

### 架构总览

| 维度 | Claude Code | OpenCode | Pi Agent | Codex | Pivot（改后） |
|------|------------|----------|----------|-------|-------|
| **Plan 是什么** | 磁盘 Markdown 文件 | 磁盘 Markdown 文件 | Extension | 活文档（磁盘 Markdown） | **磁盘 Markdown 文件（`.md`）** |
| **Plan 内容格式** | 自由 Markdown | 自由 Markdown | 自由文本 | 富 Markdown（ExecPlan） | **自由 Markdown（零格式要求）** |
| **Step 追踪** | 独立 JSON 文件（`TaskCreate` / `TaskUpdate`） | `todowrite`（独立系统） | `[DONE:n]` 正则 | Markdown checkbox | **`.json` 文件（`task` tool 管理，Schema 校验）** |
| **Plan 与 Step** | 完全解耦 | 两套独立系统 | 混在一起 | 混在一起 | **完全解耦（`plan` tool + `task` tool）** |
| **设计哲学** | Plan 和 Task 各管各的 | Plan 是参考 + Todo 是仪表盘 | Plan 不是核心 | Plan 是活文档 | **Plan 是活文档，Steps 是执行追踪，各自独立** |
