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
| **Agent-as-Tool (委托)** | Agent A 在 ReAct 循环中将 Agent B 当作一个 Tool 调用，等待返回结果 | Phase 1 ✅ |
| Handoff (转交) | 对话从 Agent A 转移到 Agent B，用户后续直接跟 B 聊 | Phase 3 |
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

### Workspace 共享

子 Agent 和主 Agent **共享同一个 workspace**。

```python
child_context = ToolExecutionContext(
    user_id=caller_context.user_id,
    agent_id=callee_agent_id,
    workspace_id=caller_context.workspace_id,              # 继承父 Agent 的 workspace
    workspace_backend_path=caller_context.workspace_backend_path,  # 同上
    ...
)
```

设计理由：用户发起任务 → 主 Agent 在用户 workspace 中工作 → 委托子 Agent 也需要在同一 workspace 中才能读到上下文文件、写入结果。当前委托是同步的（主 Agent 等子 Agent 完成才继续），所以并发冲突不存在。

### Session 类型：`delegation` ✅

现有 Session 类型 `client` 和 `studio_test` 分别服务于终端用户和管理员测试。子 Agent 调用需要第三种类型。

不建 Session 的代价：放弃整个现有 debug 基础设施（Debug Inspector、Operations 审计、Prompt Cache 链、Hook Replay 关联、上下文估算），需要重建一套平行机制。

```
Session Types:
  client       — 终端用户 ↔ Agent
  studio_test  — 管理员 ↔ Agent（测试）
  delegation   — Agent ↔ Agent（委托）    ← Phase 1 已实现
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
| **CLARIFY 动作** | 等待用户输入 | 同左 | Phase 1: 子 Agent 直接 ANSWER 或 CALL_TOOL。Phase 2: CLARIFY 冒泡至父 Agent（见下文） |
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

当没有配置委托时，system prompt 中整个 `## Delegation Agents` 段落被移除，不浪费 token。

### Agent 名称映射

通过 `AgentDelegation.callee_alias` 字段提供短标识符映射。用户在配置界面选中一个 Agent 后系统自动生成 alias（默认用 agent name 的 slugified 版本）。

### Agent Delegation Availability（Phase 2.5）✅

每个 Agent 通过两个新字段控制是否可被其他 Agent 委托调用：

```python
class Agent(SQLModel, table=True):
    # ... existing fields ...
    allow_delegation: bool = Field(
        default=False,
        description="Whether other agents can delegate tasks to this agent",
    )
    delegation_description: str | None = Field(
        default=None,
        description="Capability description surfaced to calling agents in the delegation tool catalog",
    )
```

设计要点：

- **Opt-in 模式**：`allow_delegation` 默认 False，Agent 创建者需主动开启
- **能力描述独立**：`delegation_description` 是专门给 LLM 看的能力描述，与 `agent.description`（面向用户的描述）完全独立，不 fallback
- **Prompt 生成**：`build_delegation_prompt_section()` 仅使用 `callee.delegation_description`，不再使用 `description_override` 或 `agent.description`
- **筛选条件**：只有同时满足 `allow_delegation=True` + `active_release_id IS NOT NULL`（已发布）的 Agent 才会：
  - 出现在 system prompt 的委托列表中
  - 出现在 DelegationSelectorDialog 的可选列表中
  - 被引擎运行时 `resolve_by_alias()` 后的二次校验通过
- **`description_override` 已移除**：之前的 `AgentDelegation.description_override` 字段已从模型、schemas、API、前端完全移除。子 Agent 的能力描述完全依赖其自身的 `delegation_description`

UI 变更：

- Agent Create/Edit Modal 的 General tab 新增 "Available for Delegation" Switch + 条件显示的 "Delegation Description" Textarea
- DelegationSelectorDialog 的可选 Agent 列表自动过滤，只显示 allow_delegation=True 且已发布的 Agent

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
  │         │         │    ├─ 2c. 解析 callee 的 AgentRuntimeConfig
  │         │         │    ├─ 2d. 通过 llm_crud.get() 获取 LLM 配置 → create_llm_from_config()
  │         │         │    ├─ 2e. 构建 callee 的 ToolManager + ToolExecutionContext（继承 workspace）
  │         │         │    ├─ 2f. 运行 ReactEngine.run_task() → 收集 ANSWER
  │         │         │    └─ 2g. 关闭 delegation Session，返回结果
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
- LLM 创建：通过 `llm_crud.get()` 获取 LLM 模型实例 → `create_llm_from_config(llm_config)` 单参数调用
- ANSWER 提取：从 `event_data["data"]["answer"]` 读取（引擎 yield 的 `type: "answer"` 事件的 data 字段）
- 迭代计数：在事件循环中统计 `type: "recursion_start"` 事件数量
- `stream_llm_responses=False`：子 Agent 使用非流式 LLM 调用

### Supervisor 集成

文件：`server/app/services/react_task_supervisor.py` 的 `_run_task()`

1. 加载 `AgentDelegationService.list_enabled_by_caller(agent.id)`
2. 调用 `build_delegation_prompt_section()` 生成 system prompt 委托段
3. 将 `delegate_to_agent` 加入 filtered ToolManager
4. 传递 `delegation_agents` 给 `engine.run_task()`

### System Prompt 注入

文件：`server/app/orchestration/react/system_prompt.md` + `prompt_template.py`

`system_prompt.md` 中有 `## Delegation Agents` 段落 + `{{delegation_agents}}` 占位符。`prompt_template.py` 中：当 `delegation_agents` 为空时，整个段落（含标题）被移除；不为空时，替换占位符为实际内容。

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

### 引擎安全修复

已修复的引擎级问题：

| Bug | 根因 | 修复 |
|-----|------|------|
| `session_title` strip crash | `action_output.get("session_title", "")` 在值为 `null` 时返回 `None` 而非 `""` | 改为 `action_output.get("session_title") or ""` |
| `caller_task_id` 始终为空 | `_task_id` 从未被注入到 tool_call.arguments | 引擎在 `run_task()` 中存储 `self._current_task_id = task.task_id`，`_execute_delegation()` 中通过 `getattr(self, "_current_task_id", "")` 读取 |
| 子 Agent ANSWER 提取失败 | `event_data.get("content")` 路径错误，引擎实际 yield `{"type": "answer", "data": {"answer": "..."}}` | 改为从 `event_data["data"]["answer"]` 读取 |
| 子 Agent 迭代计数始终为 0 | `_run_sub_agent_loop()` 检查 `event_type == "recursion"`，但引擎实际 emit `"recursion_start"` | 改为检查 `"recursion_start"` |

## CLARIFY 冒泡策略（Phase 2）✅

### 设计共识

子 Agent 执行过程中遇到不明确的指令时，可以向父 Agent 发起 CLARIFY，而非被迫猜测或直接失败。

**核心原则**：主 Agent 在回应子 Agent 的 CLARIFY 时，**一定带着自己全部的 ReAct 上下文**来做出判断——包括原始用户对话历史、已有的工具执行结果、workspace 状态等。

### 为什么选择"暂停-返回-续接"模式

分析了两条实现路径后，选择 **CLARIFY 作为暂停点返回主 Agent 的 ReAct 循环**，而非在 tool 执行层内联调用主 Agent 的 LLM。

#### 方案对比

**方案 B（内联 LLM 调用）**——在 `_execute_delegation()` 内部直接调用主 Agent 的 LLM：

```
Main Agent iteration N:
  Tool execution: delegate_to_agent(...)
    Sub-agent → CLARIFY "哪个数据源？"
    → 需要在这里调用主 Agent 的 LLM
    → 需要持有主 Agent 的 LLM 实例 + 消息历史（跨层依赖）
    → 此 LLM 调用不在主 Agent 的 ReAct 循环内（审计链断裂）
    → 用户看不到这个交互（可观测性丢失）
    主 Agent LLM 回复
    → 注入子 Agent
    子 Agent 继续 → ANSWER
```

**方案 A（暂停-返回-续接）**——让 CLARIFY 作为 tool result 返回主 Agent 的 ReAct 循环：

```
Main Agent iteration N:
  LLM → CALL_TOOL: delegate_to_agent(agent="research", instruction="分析数据")
  DelegationExecutor 启动子 Agent
    子 Agent → CLARIFY "哪个数据源？"
    DelegationExecutor 暂停子 Agent（保持 session/task 活跃）
    返回 {"status": "clarify", "question": "哪个数据源？", "delegation_context_id": "xxx"}

Main Agent iteration N+1:
  主 Agent 的 LLM 看到 CLARIFY 结果 + 自己的全部上下文
  LLM 自然决定回复 → CALL_TOOL: delegate_to_agent(
    delegation_context_id="xxx",
    response="用 sales.db"
  )
  DelegationExecutor 找到暂停的子 Agent
    注入 response → 续接 ReAct 循环
    子 Agent 继续 → ANSWER
    返回最终结果
```

#### 选择方案 A 的理由

| 维度 | 方案 A | 方案 B |
|------|--------|--------|
| **Context 完整性** | ✅ 主 Agent 的 LLM 在 iteration N+1 自然拥有全部上下文 | ❌ 需要显式传递主 Agent 的 LLM 实例 + 消息历史 |
| **审计完整性** | ✅ CLARIFY 交互记录在主 Agent 的 recursion 历史中 | ❌ LLM 调用游离在 ReAct 循环之外 |
| **架构复杂度** | ✅ DelegationExecutor 不需要知道主 Agent 的 LLM | ❌ 跨层依赖，DelegationExecutor 需要持有主 Agent 的 LLM |
| **可观测性** | ✅ 前端可展示完整的 CLARIFY 交互 | ❌ 用户看不到交互过程 |
| **多次 CLARIFY** | ✅ 主 Agent 每次都能重新评估 | ❌ 需要循环调用主 Agent LLM |
| **代码冗余** | ✅ 复用现有 ReAct 循环，无需新增 LLM 调用机制 | ❌ 需要在 tool 执行层重建一套 LLM 调用机制 |

### 实现要点 ✅

#### DelegationExecutor 改造

文件：`server/app/services/delegation_executor.py`

1. **共享事件循环**：`_run_sub_agent_loop()` 处理 ANSWER / CLARIFY / error 三种终止条件
2. **CLARIFY 事件捕获**：在事件循环中捕获 `type: "clarify"` 事件，提取 `question`
3. **Session 保持**：当子 Agent CLARIFY 时，设置 `runtime_status = "idle"` 并 commit，不关闭 delegation session 和 ReactTask
4. **返回特殊结果**：返回 `{"status": "clarify", "question": "...", "delegation_context_id": "..."}`
5. **续接机制**：`resume_delegation()` 通过 `session_id` 找到暂停的 session/task，重建 LLM + Engine + ToolManager，调用 `_patch_clarify_reply()` 将父 Agent 的 response 注入到 pending action_result 中，续接 ReAct 循环
6. **action_result 修补**：`_patch_clarify_reply()` 将 CLARIFY 输出中的 placeholder reply 替换为父 Agent 的实际 response，通过 `ReactRuntimeService.set_next_action_result()` 持久化

#### `delegate_to_agent` Tool 参数扩展 ✅

文件：`server/app/orchestration/tool/builtin/delegate.py`

```python
@tool(...)
def delegate_to_agent(
    agent: Annotated[str | None, Param("要调用的Agent标识符")] = None,
    instruction: Annotated[str | None, Param("传递给目标Agent的任务指令")] = None,
    delegation_context_id: Annotated[str | None, Param("续接先前暂停的委托")] = None,
    response: Annotated[str | None, Param("对子Agent CLARIFY 的回复")] = None,
) -> dict:
    ...
```

所有参数均为可选，由两种使用模式决定必填项：
- **新建委托**：`agent` + `instruction` 必填
- **恢复委托**：`delegation_context_id` + `response` 必填

#### 引擎路由 ✅

文件：`server/app/orchestration/react/engine.py` 的 `_execute_delegation()`

方法内部根据参数路由到两种模式：
1. 检测 `delegation_context_id` → 调用 `DelegationExecutor.resume_delegation()`
2. 检测 `agent` + `instruction` → 调用 `DelegationExecutor.execute_delegation()`

#### System Prompt 引导 ✅

子 Agent 的 system prompt 尾部追加 `_CLARIFY_PROMPT_SECTION`：

```
## Delegation Clarify

You are a delegated sub-agent working on behalf of another agent.
If the instruction is ambiguous or you need more information to proceed,
use the CLARIFY action to ask a question. Your question will be forwarded
to the agent that delegated to you, and you will receive a response to
continue working.
```

该 section 仅在 `execute_delegation()` 中追加，用户正常的 CLARIFY 语义不受影响。

### 交互流程图

```
Main Agent ReAct Loop
  │
  ├─ Iteration N:
  │    LLM → delegate_to_agent(agent="research", instruction="分析市场数据")
  │    │
  │    └─ DelegationExecutor
  │         ├─ 创建 delegation session + task
  │         ├─ 运行子 Agent ReAct loop
  │         │    └─ 子 Agent → CLARIFY "需要哪个季度的数据？"
  │         ├─ 暂停子 Agent（保持 session/task）
  │         └─ 返回 tool result:
  │              {"status": "clarify",
  │               "question": "需要哪个季度的数据？",
  │               "delegation_context_id": "ctx_abc123"}
  │
  ├─ Iteration N+1:
  │    LLM 看到 CLARIFY + 全部上下文 → 决定回复
  │    LLM → delegate_to_agent(
  │      delegation_context_id="ctx_abc123",
  │      response="Q3 2024 数据，重点关注亚太区域"
  │    )
  │    │
  │    └─ DelegationExecutor
  │         ├─ 找到暂停的 session/task
  │         ├─ 注入 response 作为 user message
  │         ├─ 续接子 Agent ReAct loop
  │         │    └─ 子 Agent → ANSWER
  │         ├─ 关闭 delegation session
  │         └─ 返回 tool result:
  │              {"status": "completed", "answer": "...", ...}
  │
  └─ Iteration N+2:
       LLM 拿到最终结果 → 继续推理或 ANSWER 给用户
```

## 前端实现 ✅

### 配置入口：Agent Detail Sidebar

在 `AgentDetailSidebar` 的 "Capabilities" 分组下的 **"Agents"** section：

```
Capabilities:
  Tools     [9/10]  ⚙️
  Skills    [0/0]   ⚙️
  Agents    [2/11]  ⚙️    ← 选中数/可委托Agent总数
Connections:
  Extensions ...
```

### DelegationSelectorDialog

文件：`web/src/components/DelegationSelectorDialog.tsx`

复用 `ToolSelectorDialog` 交互模式：DraggableDialog + checkbox table + search + select-all

- 内部加载 agent 列表和现有 delegations
- 排除自身 Agent（`excludeAgentId`）
- 选中后自动生成 `callee_alias`（slugified agent name）
- Save 时调用 `replaceAgentDelegations()` API 批量替换
- Save 成功后通过 `onSaved` 回调刷新 sidebar stats 和 delegations 列表

### 聊天渲染

`delegate_to_agent` 的调用在 `RecursionCard` 中渲染，与其他 tool 保持一致的展示方式：

1. **摘要行**（折叠状态）：
   - 新建委托：显示 agent alias（紫色 `text-violet-400`）+ instruction 预览（截断到 60 字符）
   - 恢复委托：显示 "Resume"（琥珀色 `text-amber-400`）+ response 预览
2. **详情展开**：标准 `Arguments` + `Result` 布局，与其他 tool 一致
   - `Arguments`：显示 agent / instruction / delegation_context_id / response 参数
   - `Result`：完整 JSON 结果（包含 status / answer / iterations / token_usage）

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
| `server/app/orchestration/react/system_prompt.md` | 新增 `## Delegation Agents` + `{{delegation_agents}}` 占位 |
| `server/app/orchestration/react/prompt_template.py` | `build_runtime_system_prompt()` 接受 delegation_agents 参数，空时移除整个段落 |
| `server/app/orchestration/react/engine.py` | `_execute_delegation()` 拦截 + `run_task()` 存储 `_current_task_id` 和 `_current_task_delegation_depth` + `_delegation_event_queue` + meter pump drain + `_make_delegation_event_callback()` |
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
| `web/src/pages/chat/components/RecursionCard.tsx` | delegate_to_agent 摘要渲染 + 标准 Arguments/Result 详情展示 |
| `web/src/studio/operations/api.ts` | 类型加入 "delegation" + parent 字段 |
| `web/src/studio/operations/SessionHistoryPage.tsx` | Delegation 类型筛选 |
| `web/src/studio/operations/SessionDetailPage.tsx` | 父 Agent 信息展示 |
| `web/src/studio/operations/SessionDetailPage.test.tsx` | 更新 fixture |

## 分阶段路线

### Phase 1（MVP）— ✅ 已完成

- [x] 数据模型：AgentDelegation 表 + Session/ReactTask 扩展字段
- [x] 服务层：AgentDelegationService（CRUD + 环检测 + prompt 生成）+ DelegationExecutor
- [x] API 层：delegations CRUD + batch replace
- [x] Tool 注册：`delegate_to_agent` 注册 + 引擎拦截
- [x] System Prompt：委托列表注入（空时移除整个段落）
- [x] Supervisor 集成：加载 delegations + 构建 prompt + 注册 tool
- [x] 前端配置 UI：DelegationSelectorDialog + AgentDetailSidebar section
- [x] 前端聊天渲染：RecursionCard 中的 delegate_to_agent 专门渲染
- [x] Operations 页面：Delegation 类型筛选 + 父 Agent 信息
- [x] Sidebar 统计：delegations 计数
- [x] E2E 委托执行验证：Gemini Agent → Claude Agent / DeepSeek Agent 委托成功
- [x] 引擎安全修复：session_title null guard, caller_task_id 追踪, ANSWER 提取, 迭代计数

### Phase 2 — CLARIFY 冒泡 ✅ 已完成

子 Agent 可以向父 Agent 发起 CLARIFY，父 Agent 带着全部 ReAct 上下文做出判断后回复。

- [x] DelegationExecutor 改造：共享 `_run_sub_agent_loop()` + `resume_delegation()` + `_patch_clarify_reply()`
- [x] `delegate_to_agent` 参数扩展：新增可选 `delegation_context_id` + `response` 参数
- [x] 引擎路由：`_execute_delegation()` 根据 `delegation_context_id` 参数路由到 resume/new 模式
- [x] 子 Agent System Prompt：追加 `_CLARIFY_PROMPT_SECTION` 告知可以使用 CLARIFY
- [x] 前端渲染：CLARIFY 交互可视化（amber 色卡片 + "Clarification requested" 标题 + 恢复模式 "Resume" 标签）
- [x] E2E 验证：Gemini → Claude Agent 委托，Claude Agent 发起 CLARIFY，Gemini 回复后续接成功
- [x] Bug 修复：`resume_delegation()` 中使用 `select(Session).where(Session.session_id == ...)` 替代 `self.db.get()` 按 session_id 查询（主键是整数 id，不是 UUID session_id）

### Phase 2 剩余待办

- [x] ~~Token 用量聚合~~：经验证，当前 Analytics 统计已是准确的——每个 ReactTask 各自记录 LLM 真实消耗，不存在重复统计问题，无需额外处理

### SSE 委托事件 ✅

通过父 Agent 的 SSE 流实时推送委托状态变化：

- [x] 事件类型：`delegation_start`（开始）、`delegation_result`（完成）、`delegation_clarify`（暂停）、`delegation_error`（失败）
- [x] 后端 enum：`ReactStreamEventType` 新增 `DELEGATION_START/RESULT/CLARIFY/ERROR`
- [x] 引擎队列：`ReactEngine._delegation_event_queue` 接收 DelegationExecutor 发出的事件，由 meter pump 循环 drain 并 yield 到父任务 SSE 流
- [x] 回调接入：`_execute_delegation()` 通过 `_make_delegation_event_callback()` 传递 `on_event` 给 executor
- [x] Bug 修复：`_run_sub_agent_loop()` 中 `event_type == "recursion"` → `"recursion_start"`（修复迭代计数始终为 0）
- [x] 前端类型：`ReactStreamEventType` union 新增 `"delegation_clarify"`（其余 3 个已存在）
- [x] 后端 lint/pyright + 前端 type-check/lint 全部通过

### 细粒度配置 UI ✅

在 `DelegationSelectorDialog` 中为每个已勾选的委托行添加可展开的配置区域：

- [x] 状态管理：`Set<number>` → `Map<number, DelegationRowState>`，包含 `checked`、`config`、`configExpanded`
- [x] 配置字段：Alias（`callee_alias`）、Timeout（`max_timeout_seconds`）、Max Iterations（`max_iterations_override`）。Description override 已移除，改用 Agent 自身的 `delegation_description`
- [x] UI 交互：已勾选行显示齿轮图标，点击展开/折叠配置区域
- [x] 保存逻辑：批量替换时包含每行的配置参数
- [x] Sidebar 展示：委托列表显示 alias 而非 agent name，tooltip 显示 agent name
- [x] E2E 验证：配置保存、持久化、重载均已通过

### Phase 3 — 高级功能

- [ ] Handoff 模式（对话转交，用户直接跟 B 聊）
- [x] 并行委托（Agent A 同时调用 B 和 C）— 已有 eager tool execution + batch orchestration 支持，E2E 验证通过（Gemini Agent 同时并行委托 Claude Agent + DeepSeek Agent）
- [ ] Agent 编排模板（预设的 Agent 团队配置）
- [ ] Workspace 隔离策略（子 Agent 是否使用独立 workspace）

### 并行委托验证 ✅

已通过 E2E 验证：Gemini Agent 在一个 CALL_TOOL action 中同时委托 Claude Agent 和 DeepSeek Agent。

- LLM 根据 `system_prompt.md` 中的 batch orchestration 说明，自然生成多个同 batch 的 `delegate_to_agent` tool_call
- 引擎的 eager execution 为每个 tool_call 创建独立 `asyncio.Task`，通过 `_execute_tool_call_request()` → `_execute_delegation()` 并行执行
- 两个子 Agent 的 ReAct 循环并发运行，结果汇总到同一 `action_result` 中
- 前端正确展示 "2 tools used" + 各自的 Arguments/Result 详情
