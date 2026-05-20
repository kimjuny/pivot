# Multi-Agent Delegation Design

本文面向后续实现者，尤其是 Agent 自己。记录 Multi-Agent（Agent 间委托调用）的完整设计共识。

## 核心模型

### 模式选择：Agent-as-Tool

采用 **Agent-as-Tool**（委托调用）模式——把被调用的 Agent 注册为调用方 Agent 的一个 Tool。

选择理由：

- **契合现有架构**：复用 ToolManager、ReAct 循环、SSE 流式推送，几乎不改核心引擎
- **自然语义**：对 LLM 来说，调用另一个 Agent 和调用 `web_search` 是同一种决策
- **可组合**：如果 Agent B 也能调 Agent C，就自然形成了编排链
- **可降级**：如果 Agent B 不可用，LLM 可以自行处理或返回错误，和普通 Tool 失败一样

其他模式作为后续迭代方向：

| 模式 | 描述 | 阶段 |
|------|------|------|
| **Agent-as-Tool (委托)** | Agent A 在 ReAct 循环中将 Agent B 当作一个 Tool 调用，等待返回结果 | MVP ✅ |
| Handoff (转交) | 对话从 Agent A 转移到 Agent B，用户后续直接跟 B 聊 | Phase 2 |
| Orchestrator (编排) | 一个"路由 Agent"不做事，只分发任务给专业 Agent | Agent-as-Tool 的特例，无需额外设计 |

### 归因模型：原始用户始终是所有任务的最终发起者

委托链中所有 ReactTask 的 `user_id` 一致，都等于最初的那个用户。

```
用户 (user_id=42)
  │
  ├─ ReactTask #1 (agent_id=A, user_id=42)
  │    └─ iteration 3: LLM 决定委托 → delegate_to_agent("research", "分析市场数据")
  │         │
  │         └─ ReactTask #2 (agent_id=B, user_id=42, parent_task_id=task_1, parent_agent_id=A)
  │              │  user_id 仍然是 42，因为 Agent A 没有"身份"，它只是用户意图的执行代理
  │              │
  │              └─ ANSWER → 返回给 Task #1 的 recursion
  │
  └─ 用户最终拿到 Agent A 的回答
```

语义是：**用户**通过 Agent A 委托了 Agent B 来完成部分工作。

`user_id` 承载的五重职责都指向同一结论：

| 职责 | 为什么归因给原始用户 |
|------|---------------------|
| **权限边界** | 子 Agent 能访问什么由用户权限决定，Agent 没有独立权限 |
| **费用归属** | 用户发起的整条链的费用都归于用户 |
| **审计追溯** | 审计链始终可追溯到人 |
| **数据隔离** | 用户能看到的 = 整条链能看到的 |
| **可见性** | 按用户聚合时一条查询覆盖整条链 |

### Session 类型：新增 `delegation` ✅

现有 Session 类型 `client` 和 `studio_test` 分别服务于终端用户和管理员测试。子 Agent 调用需要第三种类型。

不建 Session 的代价：放弃整个现有 debug 基础设施（Debug Inspector、Operations 审计、Prompt Cache 链、Hook Replay 关联、上下文估算），需要重建一套平行机制。

```
Session Types:
  client       — 终端用户 ↔ Agent
  studio_test  — 管理员 ↔ Agent（测试）
  delegation   — Agent ↔ Agent（委托）    ← 已实现
```

## 数据模型 ✅

### AgentDelegation（已实现）

文件：`server/app/models/agent_delegation.py`

```python
class AgentDelegation(SQLModel, table=True):
    """Defines which agents this agent can delegate to and how."""

    id: int | None = Field(default=None, primary_key=True)
    caller_agent_id: int = Field(foreign_key="agent.id", index=True)
    callee_agent_id: int = Field(foreign_key="agent.id", index=True)
    callee_alias: str          # 短标识符，LLM 调用时使用
    description_override: str | None = Field(default=None)
    pass_mode: str = Field(default="instruction_only")
    max_timeout_seconds: int = Field(default=300)
    max_iterations_override: int | None = Field(default=None)
    enabled: bool = Field(default=True)
    priority: int = Field(default=100)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
```

### Session 扩展（已实现）

新增 `parent_task_id` 和 `parent_agent_id` 字段。

```python
class Session(SQLModel, table=True):
    # ... existing fields ...

    parent_task_id: str | None = Field(default=None, index=True)
    parent_agent_id: int | None = Field(default=None, foreign_key="agent.id", index=True)
```

各 Session 类型的字段值：

| Session Type | parent_task_id | parent_agent_id |
|--------------|---------------|-----------------|
| `client` | `None` | `None` |
| `studio_test` | `None` | `None` |
| `delegation` | 父 ReactTask 的 task_id | 父 Agent 的 id |

### ReactTask 扩展（已实现）

```python
class ReactTask(SQLModel, table=True):
    # ... existing fields ...

    parent_task_id: str | None = Field(default=None, index=True)
    parent_agent_id: int | None = Field(default=None, foreign_key="agent.id", index=True)
    delegation_depth: int = Field(default=0)
```

### Delegation Session 与其他 Session 类型的行为差异

| 维度 | Client | Studio Test | Delegation |
|------|--------|-------------|------------|
| **触发者** | 终端用户 | 管理员 | 父 Agent（程序化） |
| **Idle Timeout** | 15 min，到期新建 session | 同左 | 不需要——子任务是一次性的 |
| **用户重连** | 支持 SSE 断点续传 | 支持 | 不需要——消费者是父任务 |
| **迁移** | Agent 重新发布时迁移 | 同左 | 不需要——生命周期随父任务结束 |
| **CLARIFY 动作** | 等待用户输入 | 同左 | 禁止（MVP），子 Agent 没有"用户"可澄清 |
| **Chat History** | 用户可见对话 | 管理员可见 | 管理员可见（debug 用途） |
| **Session Title** | 用户可编辑 | 自动生成 | 自动标注："Delegation: {parent_id} → {callee_name}" |

## Tool 设计：单一 `delegate_to_agent` ✅

使用单一 `delegate_to_agent` 工具，而非为每个可委托 Agent 生成独立 tool。

### 为什么不用 Per-Agent Tool

假设一个 Agent 配置了 8 个可委托 Agent：

- **Token 浪费**：8 个 tool schema 的 parameters 部分完全相同（都是 `instruction: string`），冗余严重
- **不灵活**：Agent 名称变更时需要重新生成 tool schema
- **命名约束**：Agent 名称可能含中文、空格、特殊字符，需要 sanitization 映射

### 实现方式

注册为标准 `@tool` 用于 catalog 可见性，但实际执行由引擎拦截：

- **文件**：`server/app/orchestration/tool/builtin/delegate.py` — 注册 `delegate_to_agent` 为标准 tool
- **引擎拦截**：`server/app/orchestration/react/engine.py` 的 `_execute_tool_call_request()` 在标准 tool 执行路径之前拦截 `delegate_to_agent`，直接调用 `DelegationExecutor.execute_delegation()`
- **优势**：引擎已在 async 上下文中，无需 sync/async 桥接

```python
@tool(
    description="调用另一个Agent协助完成任务。根据任务需求选择最合适的Agent。"
)
def delegate_to_agent(
    agent: Annotated[str, Param("要调用的Agent标识符，必须从可用列表中选择")],
    instruction: Annotated[str, Param("传递给目标Agent的任务指令")],
) -> dict:
    ...
```

可用 Agent 列表通过 system prompt 注入，而非 tool schema：

```
You can call other agents via the `delegate_to_agent` tool.
Choose the most appropriate agent based on the task.

| Identifier | Name | Description |
|---|---|---|
| research | Research Agent | 擅长信息搜集与深度分析 |
| code | Code Agent | 擅长代码编写、调试 |

Example: delegate_to_agent(agent="research", instruction="Search for...")
```

### Agent 名称映射

通过 `AgentDelegation.callee_alias` 字段提供短标识符映射。用户在配置界面选中一个 Agent 后系统自动生成 alias（默认用 agent name 的 slugified 版本）。

## 核心执行流程 ✅

### 完整调用链路

```
用户 → ReactTask #1 (Agent A)
  │
  ├─ ReAct Loop iteration N
  │    └─ LLM 决定 CALL_TOOL: delegate_to_agent
  │         │
  │         ├─ Engine._execute_tool_call_request() 拦截
  │         │    └─ Engine._execute_delegation()
  │         │         │
  │         │         ├─ 1. AgentDelegationService.resolve_by_alias() 校验 alias
  │         │         ├─ 2. DelegationExecutor.execute_delegation()
  │         │         │    ├─ 2a. 创建 Session(type="delegation", user_id=原始用户)
  │         │         │    ├─ 2b. 创建 ReactTask(parent_task_id, delegation_depth+1)
  │         │         │    ├─ 2c. 解析 callee 的 AgentRuntimeConfig + LLM
  │         │         │    ├─ 2d. 构建 callee 的 ToolManager + ToolExecutionContext
  │         │         │    ├─ 2e. 运行 ReactEngine.run_task() → 收集 ANSWER
  │         │         │    └─ 2f. 关闭 delegation Session，返回结果
  │         │         │
  │         │         └─ 返回 {"delegated_agent", "answer", "iterations", "token_usage"}
  │         │
  │         └─ 作为标准 tool_result 返回给 ReAct 循环
  │
  └─ Agent A 拿到结果 → 继续推理或 ANSWER
```

### DelegationExecutor 实现

文件：`server/app/services/delegation_executor.py`

关键设计决策：
- 引擎在 async 上下文中直接 `await DelegationExecutor.execute_delegation()`，不走 `run_in_threadpool`
- 子 Agent 的 system prompt 中**不注入委托列表**（避免子 Agent 继续委托造成混淆）
- `MAX_DELEGATION_DEPTH = 3`，超过拒绝创建子任务

### Supervisor 集成

文件：`server/app/services/react_task_supervisor.py` 的 `_run_task()`

1. 加载 `AgentDelegationService.list_enabled_by_caller(agent.id)`
2. 调用 `build_delegation_prompt_section()` 生成 system prompt 委托段
3. 将 `delegate_to_agent` 加入 filtered ToolManager
4. 传递 `delegation_agents` 给 `engine.run_task()`

### System Prompt 注入

文件：`server/app/orchestration/react/system_prompt.md` + `prompt_template.py`

在 `## Skills Index` 之后插入：

```markdown
## Delegation Agents
{{delegation_agents}}
```

`build_runtime_system_prompt()` 新增 `delegation_agents: str = ""` 参数。

## 安全与约束 ✅

### 防循环

| 约束 | 实现 |
|------|------|
| **禁止自调用** | `AgentDelegationService.create()` 校验 `caller_id != callee_id` |
| **禁止循环链** | 保存 AgentDelegation 时 BFS 检查有向图是否有环（`validate_no_cycle`） |
| **最大深度** | `MAX_DELEGATION_DEPTH = 3`，超过拒绝创建子任务 |
| **超时保护** | 子任务总执行时间受 `AgentDelegation.max_timeout_seconds` 限制 |

### 权限模型

子 Agent 的 `ToolExecutionContext` 继承原始用户的权限：

```python
child_context = ToolExecutionContext(
    user_id=parent_context.user_id,    # 原始用户权限边界
    agent_id=callee.id,                 # 子 Agent 自身身份
    ...
)
```

子 Agent 调用 `read_file` 等工具时，权限检查基于原始用户的访问范围。

### CLARIFY 处理

**MVP 策略：禁止 CLARIFY** — 子 Agent 的 system prompt 中不包含委托列表，自然无法触发委托链。

## 前端实现 ✅

### 配置入口：Agent Detail Sidebar

在 `AgentDetailSidebar` 的 "Capabilities" 分组下新增 **"Agents"** section：

```
Capabilities:
  Tools     [9/10]  ⚙️
  Skills    [0/0]   ⚙️
  Agents    [2/11]  ⚙️    ← 新增（选中数/可委托Agent总数）
Connections:
  Extensions ...
  ...
```

### DelegationSelectorDialog

文件：`web/src/components/DelegationSelectorDialog.tsx`

复用 `ToolSelectorDialog` 交互模式：DraggableDialog + checkbox table + search + select-all

- 内部加载 agent 列表和现有 delegations
- 排除自身 Agent（`excludeAgentId`）
- 选中后自动生成 `callee_alias`（slugified agent name）
- Save 时调用 `replaceAgentDelegations()` API 批量替换

### 聊天渲染

`delegate_to_agent` 的调用在 `RecursionCard` 中获得专门渲染：

1. **摘要行**：显示 agent alias（紫色）+ instruction 预览（截断到60字符）
2. **详情展开**：显示子 Agent 返回的 answer + iterations + token usage + 完整 result JSON

### Operations 页面

- `SessionHistoryPage`：新增 "Delegation" 类型筛选器
- `SessionDetailPage`：delegation session 显示 "Delegated from agent #X (task xxxxxxxx...)"
- 后端 operations API 返回 `parent_task_id` 和 `parent_agent_id`

## 已实现文件清单

### 后端新增

| 文件 | 说明 |
|------|------|
| `server/app/models/agent_delegation.py` | AgentDelegation SQLModel 表 |
| `server/app/services/agent_delegation_service.py` | 委托配置 CRUD + BFS 环检测 + prompt 生成 |
| `server/app/services/delegation_executor.py` | 子 Agent 执行器（创建 session/task，运行 ReAct 循环） |
| `server/app/api/delegations.py` | REST API endpoints（CRUD + batch replace） |
| `server/app/schemas/delegation.py` | 请求/响应 Pydantic schemas |
| `server/app/orchestration/tool/builtin/delegate.py` | `delegate_to_agent` tool 注册 |

### 后端修改

| 文件 | 说明 |
|------|------|
| `server/app/models/__init__.py` | 导入 AgentDelegation |
| `server/app/models/session.py` | 新增 parent_task_id, parent_agent_id |
| `server/app/models/react.py` | 新增 parent_task_id, parent_agent_id, delegation_depth |
| `server/app/db/session.py` | `_REQUIRED_TABLES` 加入 `"agentdelegation"` + ALTER TABLE 新列 |
| `server/app/orchestration/react/system_prompt.md` | 新增 `{{delegation_agents}}` 占位 |
| `server/app/orchestration/react/prompt_template.py` | `build_runtime_system_prompt()` 接受 delegation_agents 参数 |
| `server/app/orchestration/react/engine.py` | `_execute_delegation()` + `run_task()` delegation_agents 参数 |
| `server/app/services/react_task_supervisor.py` | 加载 delegations + 注入 prompt + 注册 tool |
| `server/app/services/agent_sidebar_service.py` | sidebar stats 加入 delegations 计数 |
| `server/app/schemas/schemas.py` | `AgentSidebarStatsResponse` 加入 delegations 字段 |
| `server/app/api/operations.py` | 返回 parent_task_id, parent_agent_id |
| `server/app/main.py` | 注册 delegations_router |

### 前端新增

| 文件 | 说明 |
|------|------|
| `web/src/components/DelegationSelectorDialog.tsx` | Agent 委托选择对话框 |

### 前端修改

| 文件 | 说明 |
|------|------|
| `web/src/types/index.ts` | 新增 AgentDelegation 接口 |
| `web/src/utils/api.ts` | 委托 API 函数 + AgentSidebarStats 类型 |
| `web/src/pages/chat/types.ts` | 新增 delegation SSE 事件类型 |
| `web/src/components/AgentDetailSidebar.tsx` | 新增 Agents section + DelegationSelectorDialog |
| `web/src/components/AgentDetailSidebar.test.tsx` | 更新 baseSidebarStats fixture |
| `web/src/pages/chat/components/RecursionCard.tsx` | delegate_to_agent 专门渲染 |
| `web/src/studio/operations/api.ts` | 类型加入 "delegation" + parent 字段 |
| `web/src/studio/operations/SessionHistoryPage.tsx` | Delegation 类型筛选 |
| `web/src/studio/operations/SessionDetailPage.tsx` | 父 Agent 信息展示 |
| `web/src/studio/operations/SessionDetailPage.test.tsx` | 更新 fixture |

## 待完成（Phase 1 剩余）

以下功能在当前实现基础上仍需补充：

- [ ] **E2E 委托执行验证**：配置 Agent A 委托给 Agent B → 与 A 聊天 → 触发委托 → 验证结果正确
- [ ] **细粒度配置对话框**：单个委托的 Alias、描述覆写、超时、迭代覆写等参数配置 UI
- [ ] **SSE delegation 事件**：在引擎中显式 emit `delegation_start` / `delegation_result` / `delegation_error` 事件（当前委托结果作为普通 tool_result 返回）
- [ ] **CLARIFY 禁止策略**：子 Agent 的 system prompt 中明确禁止 CLARIFY 动作

## 分阶段路线

### Phase 1 (MVP) — 当前阶段，大部分已完成

- [x] 数据模型：AgentDelegation 表 + Session/ReactTask 扩展字段
- [x] 服务层：AgentDelegationService（CRUD + 环检测 + prompt 生成）+ DelegationExecutor
- [x] API 层：delegations CRUD + batch replace
- [x] Tool 注册：`delegate_to_agent` 注册 + 引擎拦截
- [x] System Prompt：委托列表注入
- [x] Supervisor 集成：加载 delegations + 构建 prompt + 注册 tool
- [x] 前端配置 UI：DelegationSelectorDialog + AgentDetailSidebar section
- [x] 前端聊天渲染：RecursionCard 中的 delegate_to_agent 专门渲染
- [x] Operations 页面：Delegation 类型筛选 + 父 Agent 信息
- [x] Sidebar 统计：delegations 计数
- [ ] E2E 委托执行验证
- [ ] 细粒度配置 UI
- [ ] 显式 delegation SSE 事件

### Phase 2

多层嵌套 + 上下文传递。

- `with_context` 模式（传递对话摘要）
- 子任务详情展开面板（前端可折叠卡片）
- Token 用量聚合（全链路汇总）
- CLARIFY 冒泡策略（子 Agent → 父 Agent → 用户）

### Phase 3

高级功能。

- Handoff 模式（对话转交，用户直接跟 B 聊）
- 并行委托（Agent A 同时调用 B 和 C）
- Agent 编排模板（预设的 Agent 团队配置）
- Workspace 共享策略（子 Agent 是否共享父 Agent 的 workspace）
