# Thinking 能力重构设计

> 状态：已实现（2026-06-23）
> 目标：推翻独创的 auto 模式，对齐主流 Agent 的 CoT 设计——用户层只剩 `Thinking: Enabled / Disabled`，并把 `reasoning_content` 原样回灌进 messages 实现真正的多轮思维链延续。

---

## 一、为什么要重构

### 当前设计的两个根本错误

**错误 1：用户交互层过度复杂、自创概念**
- 现状：`auto / fast / thinking` 三态 + 20+ 个 per-LLM 的 `thinking_policy` 字符串（qwen-enable / doubao-response / claude-thinking-enabled / gemini-3x-level ...），前后端各镜像一份，新增 provider 要改 6+ 处。
- 问题：主流 Agent（Claude Code / Codex / Cursor）只有「thinking on/off」，我们却搞了一套独创的 auto 状态机，认知成本高、维护成本高，且 auto 实际几乎不生效（LLM 几乎从不主动申报 `thinking_next_turn=true`）。

**错误 2：为了省 context 主动丢弃思维链**
- 现状：`react_runtime_service.py:173 append_assistant_message` 只存 `{role, content, tool_calls}`，**完全丢弃 `reasoning_content`**。internal message 格式（`message_converter.py`）也没有 reasoning 字段。
- 后果：每一轮 recursion 的 LLM 都看不到上一轮自己的思考过程，等于**每一轮都从零开始推理**，长任务里思维链断裂、重复犯错、无法自我纠正。这是对 CoT 能力的根本性浪费。

### 重构后要达到的效果

| 维度 | 重构前 | 重构后 |
|------|--------|--------|
| 用户选项 | auto / fast / thinking（+ policy 丛林） | **Enabled / Disabled**（统一两个） |
| 配置层级 | per-LLM 三列 + per-request mode | **只在 per-request 层** |
| effort 调节 | 散落在 policy 字符串里 | 后期作为 model 的额外参数扩展（本轮不做） |
| reasoning 回灌 | **丢弃** | **原样回灌给 LLM**（所有 provider 一视同仁） |
| auto 旁路 | `thinking_next_turn` + `previous_iteration_failed` | **删除** |

---

## 二、已达成共识

### 决策 1：thinking 只在 per-request 层（方案 A）

LLM 表**彻底删除** `thinking_policy / thinking_effort / thinking_budget_tokens` 三列。用户在 chat composer 里 per-request 选 Enabled / Disabled。

- 理由：符合主流 Agent 语义；同一个 LLM 不需要预设「默认 thinking 行为」——thinking 本来就是用户按需触发的。
- 连带删除：`thinking_policy.py` 整个文件、`llm_factory.py` 里透传 thinking 配置的 4 处、各 LLM 实现类构造函数里的 thinking 参数。

### 决策 2：所有 provider 一视同仁回灌 reasoning

四个协议（OpenAI Completion / OpenAI Response / Anthropic / Gemini）**全部**把上一轮的 `reasoning_content` 原样塞回 messages 历史传给 LLM。

- 理由：CoT 多轮延续是这一轮的核心目标，按 provider 分别开关会让代码复杂化、且违背「主流 Agent 默认都回灌」的事实。
- 国产兼容端点的潜在报错：通过「reasoning 字段为空时不回灌」自然兜底，不做协议级开关。

### 决策 3：可以破坏性改 schema、删库重建

项目未上线、无存量数据。可以：
- 破坏性修改 `LLM` 表 schema（删列）。
- 破坏性修改 `react_llm_messages` JSON 结构（新增 reasoning 字段）。
- 删除 alembic 历史中相关的旧 migration，直接重建。

---

## 三、详细设计

### 3.1 用户交互层：Enabled / Disabled

**ChatComposer 改造**（`web/src/pages/chat/components/ChatComposer.tsx`）：

```
[ 💭 Thinking ▾ ]
        ├─ ✓ Enabled
        └─   Disabled
```

- 默认值：`Disabled`（对齐主流 Agent 的「按需思考」）。
- 没有 hover 级联 effort——本轮不做。effort 后期作为 model 额外参数扩展（见第六节）。
- 该选择 per-request 传递，不持久化到 LLM 或 session 配置。

**前端类型变更**（`web/src/utils/llmThinking.ts`）：

整个文件**大幅瘦身**：
- 删除 `ThinkingProvider` / `ThinkingProviderOption` / `ThinkingEditorState` 及其所有派生函数（`getDefaultThinkingEditorState` / `getThinkingEditorStateFromPolicy` / `buildThinkingPolicyFromEditorState` / `formatThinkingPolicyLabel` / `llmHasThinkingSelector` / `getChatThinkingModes` / `getDefaultChatThinkingMode`）。
- 删除 `SUPPORTED_THINKING_POLICIES` / `DISABLED_THINKING_POLICIES` / `THINKING_PROVIDER_OPTIONS` 常量。
- 只保留一个最小定义：

```typescript
export type ChatThinkingMode = "enabled" | "disabled";
```

- `LLM` TS 类型（`web/src/types/index.ts`）删除 `thinking_policy / thinking_effort / thinking_budget_tokens` 字段。

**`ChatThinkingMode` 语义变更影响**：这是**破坏性类型变更**。当前 `ChatThinkingMode = "auto" | "fast" | "thinking"`，全仓引用点（ChatContainer 的 `selectedThinkingMode` state、ChatComposer 的 props、API 请求体）全部改为新的 `"enabled" | "disabled"`。不留任何 `"fast"` 这种过渡别名。

### 3.2 API 层

**Request schema**（`server/app/schemas/react.py`）：

```python
# 删除
thinking_mode: Literal["auto", "fast", "thinking"] | None = Field(default=None, ...)

# 替换为
thinking_enabled: bool = Field(
    default=False,
    description="Whether to enable provider thinking/reasoning for this task",
)
```

- 默认 `False`（Disabled）。
- 该字段是 per-task 的（一个 task 生命周期内保持一致），不做 per-recursion 切换。

**`ReactTaskLaunchRequest`**（`server/app/services/react_task_supervisor.py:57`）：

```python
@dataclass(slots=True)
class ReactTaskLaunchRequest:
    ...
    thinking_enabled: bool = False  # 替换原 thinking_mode: Literal[...] | None
```

**`thinking_runtime_config` 传递**（`react_task_supervisor.py:781`）：

```python
engine = ReactEngine(
    ...
    thinking_enabled=launch.thinking_enabled,  # 替换 thinking_runtime_config dict
)
```

不再传 dict，直接传一个 bool。`ReactEngine.__init__` 对应改为 `self.thinking_enabled: bool`。

### 3.3 Engine 层：删 auto、删旁路、改决策

**删除的方法**（`server/app/orchestration/react/engine.py`）：
- `_previous_recursion_failed`（约 147-201 行）——auto 失败恢复旁路。
- `_previous_recursion_requested_thinking`（约 237-284 行）——auto LLM 自申报旁路。
- `_build_iteration_llm_runtime_kwargs`（约 203-235 行）——基于旁路的复杂 kwargs 构建。

**新增的决策函数**（替代上面三个，极简）：

```python
def _build_thinking_kwargs(self) -> dict[str, Any]:
    """Translate the per-task thinking flag into provider request kwargs.

    Returns an empty dict when thinking is disabled (provider defaults apply).
    """
    if not self.thinking_enabled:
        return {}
    return build_thinking_kwargs(self.llm)
```

`build_thinking_kwargs` 的具体逻辑见 3.5（按 provider 协议翻译成各自的「开启 thinking」wire 参数）。

**调用点**：每个 recursion 开始发起 LLM 调用前，把 `self._build_thinking_kwargs()` merge 进 `llm_chat_kwargs`。逻辑扁平：**一个 bool，一次翻译，没有状态、没有旁路、没有跨轮信号**。

### 3.4 reasoning_content 回灌（核心改动）

#### 3.4.1 internal message 格式新增字段

当前 internal assistant message：
```python
{"role": "assistant", "content": "...", "tool_calls": [...]}
```

改为：
```python
{"role": "assistant", "content": "...", "reasoning_content": "...", "tool_calls": [...]}
```

- `reasoning_content` 为可选字段，缺失或为空字符串时等价于「无思考内容」。
- 只有 `role == "assistant"` 的消息会有此字段。

#### 3.4.2 持久化层接收 reasoning

**`react_runtime_service.py:173 append_assistant_message`** 改造：

```python
def append_assistant_message(
    self,
    task: ReactTask,
    content: str,
    *,
    reasoning_content: str | None = None,   # 新增
    tool_calls: list[dict[str, Any]] | None = None,
) -> TaskRuntimeState:
    state = self.load(task)
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning_content:
        message["reasoning_content"] = reasoning_content   # 仅在非空时存
    if tool_calls:
        message["tool_calls"] = tool_calls
    state.messages.append(message)
    ...
```

**engine 调用点**（`engine.py:2994`）改造：

```python
runtime_state = self.runtime_service.append_assistant_message(
    task,
    assistant_message or "",
    reasoning_content=event_data.get("thinking"),  # 新增：回传 reasoning
    tool_calls=event_tool_calls if has_tool_calls else None,
)
```

`event_data["thinking"]` 已经在 `_execute_tool_action_recursion`（engine.py:2347）和 `_execute_text_action_recursion`（engine.py:2421）里塞好了原始 reasoning 文本，直接取用即可。

#### 3.4.3 message_converter 四个 provider 全部回灌

这是关键：**四个 provider 转换函数都要把 reasoning_content 翻译成各自的 wire format 塞回去**。

**OpenAI Completion**（`to_openai_completion_messages`）：

```python
elif role == "assistant":
    entry: dict[str, Any] = {
        "role": "assistant",
        "content": to_openai_completion_content(content),
    }
    reasoning = msg.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning:
        entry["reasoning_content"] = reasoning   # DeepSeek/Qwen/Kimi 等国产兼容标准字段
    if tool_calls:
        ...
```

> 国产 OpenAI 兼容端点（DeepSeek / Qwen / Kimi / GLM）普遍支持 assistant message 带 `reasoning_content` 字段回传。不支持时会自然忽略，不报错。

**OpenAI Response**（`to_openai_response_messages`）：

```python
elif role == "assistant":
    reasoning = msg.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning:
        # Responses API 用独立的 reasoning item 延续思维链
        out.append({
            "type": "reasoning",
            "content": [{"type": "reasoning_text", "text": reasoning}],
        })
    # 原有的 assistant message / function_call 输出逻辑不变
    ...
```

> OpenAI Responses API 官方支持把 `reasoning` item 放进 input 实现思维链延续，这是它的核心 CoT 机制。

**Anthropic**（`to_anthropic_messages`）：

```python
elif role == "assistant":
    reasoning = msg.get("reasoning_content")
    if tool_calls or reasoning:   # 只要有 reasoning 也必须用 block 格式
        blocks: list[dict[str, Any]] = []
        if isinstance(reasoning, str) and reasoning:
            blocks.append({"type": "thinking", "thinking": reasoning})
        converted = to_anthropic_content(content)
        ...   # 原有 text / tool_use block 逻辑
        formatted.append({"role": "assistant", "content": blocks})
    else:
        ...
```

> Anthropic 要求 thinking block 在 text/tool_use 之前，且必须原文回传。注意：Anthropic 对 thinking block 有签名校验（interleaved-thinking 模式），若报错可降级为不回灌——但本轮先按「回灌」实现，遇到具体 provider 兼容问题再单独处理。

**Gemini**（`to_gemini_messages`）：

```python
elif role in ("user", "assistant"):
    ...
    parts: list[dict[str, Any]] = []
    reasoning = msg.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning and role == "assistant":
        parts.append({"text": reasoning, "thought": True})   # thought part
    ...   # 原有 text / functionCall / functionResponse 逻辑
```

> Gemini 通过 `part.thought = true` 标记 thought parts，回传后 Gemini 2.5/3.x 会将其作为思维链历史。

#### 3.4.4 兼容兜底规则（统一）

四个转换函数里，reasoning 字段**统一遵循「空值不回灌」**：

```python
reasoning = msg.get("reasoning_content")
if not (isinstance(reasoning, str) and reasoning):
    # 视为无思考内容，跳过回灌
```

这样：
- Disabled 模式下，LLM 不返回 reasoning → 不回灌（自然）。
- 旧存量 session 数据（无 reasoning_content 字段）→ 不回灌（自然兼容）。
- 某些 provider 不返回 reasoning → 不回灌（自然兜底）。

不需要协议级开关，靠「字段为空即跳过」这一条规则统一处理。

### 3.5 LLM 实现层：删 thinking 构造参数

**`thinking_policy.py` 整个文件删除**，替换为一个极简的纯函数（放在 `app/llm/thinking.py`）：

```python
"""Translate the per-task thinking flag into provider request kwargs."""

from typing import Any


def build_thinking_kwargs(llm: Any) -> dict[str, Any]:
    """Return provider-specific kwargs that turn on thinking/reasoning.

    Called by the engine when thinking_enabled is True. Returns an empty
    dict for providers/protocols that have no explicit "enable" knob
    (the provider's own default will then apply).

    Args:
        llm: The LLM instance. Uses its protocol/transport class name to
            decide the wire format.

    Returns:
        Provider request kwargs to merge into the LLM call.
    """
    protocol = getattr(llm, "protocol", None) or type(llm).__name__

    # OpenAI Responses API
    if protocol == "openai_response_llm":
        return {"reasoning": {}}   # 让 provider 用默认 effort

    # Anthropic-compatible (Claude extended thinking)
    if protocol == "anthropic_compatible":
        return {"thinking": {"type": "enabled", "budget_tokens": 10000}}

    # OpenAI Completion (国产兼容: DeepSeek/Qwen/Kimi/GLM via extra field)
    if protocol == "openai_completion_llm":
        return {}   # 这些模型由 extra_body 控制，无需顶层 kwargs

    # Gemini
    if protocol == "gemini_compatible":
        return {"generationConfig": {"thinkingConfig": {"includeThoughts": True}}}

    return {}
```

> 关键简化：本轮**不暴露 effort 调节**。effort 后期作为 model 的额外可配参数（见第六节）。这里每个 protocol 只给一个「合理的开启默认值」。
>
> `protocol` 字段：当前各 LLM 实现类没有统一的 `protocol` 属性，需要在每个实现类的 `__init__` 里加一个 `self.protocol = "openai_completion_llm"`（或对应值）。这是本轮顺带的小重构——让 protocol 可内省，取代当前从 `LLM` 表读字符串的方式。

**各 LLM 实现类构造函数瘦身**（`anthropic_llm.py` / `openai_response_llm.py` / `openai_completion_llm.py` / `gemini_llm.py`）：

删除以下入参：
- `thinking_policy`
- `thinking_effort`
- `thinking_budget_tokens`
- 构造函数里的 `validate_thinking_policy(...)` 调用

新增：
- `self.protocol = "<协议名>"`

**`llm_factory.py`**：删除透传 thinking 三参数的 4 处。

### 3.6 Model 层（DB schema）

**`server/app/models/llm.py` 的 `LLM` 表删除三列**：

```python
# 删除
thinking_policy: str = Field(default="auto", ...)
thinking_effort: str | None = Field(default=None, ...)
thinking_budget_tokens: int | None = Field(default=None, ...)
```

**Migration 处理**（决策 3：破坏性重建）：
- 不写 alembic downgrade，直接在 `server/app/db/session.py` 的初始化逻辑或 startup 钩子里 drop & recreate 相关表。
- 或更简单：用户删库重启（按 AGENTS.md 约定，这是允许的）。
- **不保留任何 LEGACY alias 兼容代码**。

**`ReactRecursion.thinking` 列保留**：继续存原始 reasoning 文本，用于：
1. 前端历史回放展示（`chatData.ts:475` 已经在用）。
2. 流式断线后的 reasoning 重建（`engine.py:3050` 非流式补发）。

> 注意区分：`ReactRecursion.thinking` 是**展示与回放用的持久化**，`message.reasoning_content` 是**给下一轮 LLM 的回灌**。两者数据源相同（都是本轮的 reasoning_content），但用途不同，都需要保留。

### 3.7 prompt 层

**`system_prompt.md` 删除 `thinking_next_turn` 字段**（第 20 行附近）：

```diff
  {
    "iteration": 3,
    "message": "...",
-   "thinking_next_turn": false,       // Set `true` only when ...
    "action": {
      "action_type": "CALL_TOOL | CLARIFY | ANSWER",
      "output": {}
    }
  }
```

**`parser.py` 删除 `thinking_next_turn` 解析**：
- `ParsedReactDecision.thinking_next_turn` 字段（`types.py:76`）删除。
- `parse_react_output` 里 `_expect_optional_bool(raw_payload.get("thinking_next_turn"), ...)` 删除。

> LLM 偶尔还是会输出 `thinking_next_turn`（旧习惯），parser 严格模式会报错。处理：parser 对**未知字段一律忽略**（不报错），只在必填字段缺失/类型错误时报错。这点需要在 parser 里确认行为（当前 `safe_load_json` 只校验顶层是 dict，额外字段被 `dict(raw_payload)` 自然保留但不校验——所以已经是忽略态度，无需改动）。

### 3.8 流式 reasoning 传输（保持不变）

当前 `engine.py` 的 `_stream_chat_response`（约 738 行）已经正确处理：
- `reasoning_content` delta → `reasoning_parts` 累积 → `EmitBuffer.add_reasoning_delta` → SSE `reasoning` 事件。
- 最终组装进 `Response.choices[0].message.reasoning_content`。

**这部分逻辑不动**。本轮只改「持久化回灌」（3.4）和「决策」（3.3），流式传输链路保持现状。

---

## 四、文件改动清单

### 删除
| 文件 | 内容 |
|------|------|
| `server/app/llm/thinking_policy.py` | 整个文件（约 378 行） |
| `web/src/utils/llmThinking.test.ts` | 整个文件（测试旧逻辑） |

### 服务端改动
| 文件 | 改动 |
|------|------|
| `server/app/models/llm.py` | 删 `thinking_policy/effort/budget_tokens` 三列 |
| `server/app/llm/abstract_llm.py` | 无（`reasoning_content` 字段已存在） |
| `server/app/llm/message_converter.py` | **核心**：4 个 provider 转换函数全部加 reasoning 回灌 |
| `server/app/llm/llm_factory.py` | 删透传 thinking 参数的 4 处 |
| `server/app/llm/anthropic_llm.py` | 删 thinking 构造参数，加 `self.protocol` |
| `server/app/llm/openai_response_llm.py` | 同上 |
| `server/app/llm/openai_completion_llm.py` | 同上 |
| `server/app/llm/gemini_llm.py` | 同上 |
| `server/app/llm/thinking.py` | **新建**：`build_thinking_kwargs(llm)` 纯函数 |
| `server/app/services/react_runtime_service.py` | `append_assistant_message` 加 `reasoning_content` 参数 |
| `server/app/services/react_task_supervisor.py` | `ReactTaskLaunchRequest` 改 `thinking_enabled: bool`，传 engine |
| `server/app/orchestration/react/engine.py` | 删 3 个 auto 方法，加 `_build_thinking_kwargs`，append 调用传 reasoning |
| `server/app/orchestration/react/types.py` | `ParsedReactDecision` 删 `thinking_next_turn` |
| `server/app/orchestration/react/parser.py` | 删 `thinking_next_turn` 解析 |
| `server/app/orchestration/react/system_prompt.md` | 删 `thinking_next_turn` 字段说明 |
| `server/app/schemas/react.py` | `ReactChatRequest.thinking_mode` → `thinking_enabled: bool` |
| `server/app/api/react.py` | 传 `thinking_enabled`（2 处调用点） |
| `server/app/services/llm_service.py` | 删 thinking policy 校验相关代码 |
| `server/app/services/session_service.py` | 删 thinking 相关引用（如有） |

### 前端改动
| 文件 | 改动 |
|------|------|
| `web/src/utils/llmThinking.ts` | 大幅瘦身，只留 `ChatThinkingMode = "enabled" \| "disabled"` |
| `web/src/types/index.ts` | `LLM` 类型删 thinking 三字段 |
| `web/src/pages/chat/ChatContainer.tsx` | `selectedThinkingMode` 类型改、默认值改 `disabled`、对齐 effect 改 |
| `web/src/pages/chat/components/ChatComposer.tsx` | Thinking 下拉改为 Enabled/Disabled 两项 |
| `web/src/pages/chat/components/LLMModal.tsx` | 删 thinking policy 编辑器 |
| `web/src/components/LLMList.tsx` | 删 thinking badge 显示 |
| `web/src/utils/api/react.ts` | 请求体 `thinking_mode` → `thinking_enabled` |
| `web/src/utils/api/llms.ts` | 删 thinking 字段 |
| 相关 `.test.tsx` | 同步更新 |

### 测试改动
| 文件 | 改动 |
|------|------|
| `server/tests/orchestration/react/test_engine_thinking_mode.py` | 删除（测试已废弃的 auto 逻辑） |
| `server/tests/services/test_llm_thinking_policy.py` | 删除 |
| `server/tests/services/test_llm_reasoning_support.py` | 重写或删除 |
| 新增 `server/tests/orchestration/react/test_reasoning_replay.py` | 验证 reasoning 回灌到下一轮 messages |
| 新增 `server/tests/llm/test_message_converter_reasoning.py` | 验证 4 个 provider 的 reasoning wire format |

---

## 五、验证目标（Success Criteria）

### 5.1 功能验证

| # | 验证点 | 验证方式 |
|---|--------|----------|
| 1 | 用户在 chat 选 Enabled，LLM 返回 reasoning，前端 Thinking 区块显示 | 手动：Claude/GPT-5 thinking 模型跑一轮 |
| 2 | 第二轮 recursion 的 prompt 里包含上一轮 reasoning | 看 `app.log` 的 `LLM messages delta` 日志 |
| 3 | 用户选 Disabled，LLM 不返回 reasoning，prompt 里也不回灌 | 手动 + 日志 |
| 4 | 四个 provider 各跑一轮 thinking，均不报错 | 各 protocol 单测 + 至少 1 个 provider 手动验证 |
| 5 | 历史回放仍能看到每轮 reasoning | 刷新页面，历史 recursion 的 Thinking 区块正常显示 |
| 6 | `thinking_next_turn` 字段被 LLM 输出时不报错 | 单测：parser 忽略未知字段 |

### 5.2 代码质量验证

| # | 验证点 | 命令 |
|---|--------|------|
| 1 | 后端 lint/type 通过 | `podman compose exec backend poetry run ruff check server --fix && poetry run ruff format server && poetry run pyright server` |
| 2 | 前端 lint/type 通过 | `podman compose exec frontend npm run lint && npm run type-check` |
| 3 | 新增单测全过 | `podman compose exec backend poetry run pytest server/tests/orchestration/react/test_reasoning_replay.py server/tests/llm/test_message_converter_reasoning.py` |
| 4 | 全量后端测试不回归 | `podman compose exec backend poetry run pytest server/tests/` |

### 5.3 简洁性验证（AGENTS.md 原则）

- `thinking_policy.py` 378 行 → `thinking.py` ~30 行（**减少 ~92%**）。
- `llmThinking.ts` ~526 行 → ~10 行（**减少 ~98%**）。
- engine 删除 3 个 auto 相关方法（~140 行）。
- 前后端不再有 policy 字符串镜像，真相源唯一。

---

## 六、本轮明确不做的事

1. **effort 级联选择**（max / xhigh / medium / low / minimal）：后期作为 model 的额外可配参数扩展。本轮 `build_thinking_kwargs` 每个 protocol 只给一个合理默认值。
2. **reasoning 压缩/摘要**：reasoning 原样回灌，不做压缩。context 压力由现有的 compact 机制兜底（compact 流程后续可单独优化如何处理 reasoning）。
3. **per-recursion 动态开关**：thinking 是 per-task 的，一旦开启整个 task 生命周期保持。不做「某些轮 thinking、某些轮不 thinking」的动态切换。
4. **provider 级回灌开关**：所有 provider 一视同仁回灌（决策 2），不做协议级开关。如遇具体 provider 报错，单独处理该 provider 的兼容，不引入通用开关机制。
5. **migration 兼容**：破坏性改 schema，用户删库重建。不写 downgrade，不留 LEGACY alias。

---

## 七、风险与已知不确定项

### 风险 1：Anthropic thinking block 签名校验
Anthropic 对回传的 thinking block 有签名/完整性校验（尤其 interleaved-thinking 模式）。回灌原文理论可行，但若某些 Claude 版本/端点报签名错，需要降级。

**缓解**：先按「回灌」实现。若手动验证时 Claude 报错，单独在 `to_anthropic_messages` 里加 try-skip 逻辑（不引入通用开关）。

### 风险 2：context 体积膨胀
开启 thinking 后，每轮 reasoning（Claude extended 可达 10k+ tokens）全部累积进 messages，context 消耗显著增加。

**缓解**：本轮接受这个代价（对齐主流 Agent 行为）。compact 机制会触发，后续可单独优化「compact 时如何处理 reasoning 历史」（如压缩或丢弃早期 reasoning）。

### 风险 3：国产 OpenAI 兼容端点的 reasoning_content 字段兼容性
DeepSeek / Qwen / Kimi 等对 assistant message 回传 `reasoning_content` 的支持程度不一。多数支持，少数可能忽略或报错。

**缓解**：「字段为空不回灌」兜底了「LLM 没返回 reasoning」的情况。若具体端点报错，按风险 1 的方式单独处理。

### 不确定项：`build_thinking_kwargs` 各 protocol 的默认值
文档里给的默认值（如 Claude `budget_tokens: 10000`、Gemini `includeThoughts: True`）是基于当前代码的合理继承。实现时如果某个 provider 的默认值需要调整，可在 `thinking.py` 里直接改，不影响整体架构。

---

## 八、实现顺序（建议）

1. **DB schema + model** → 删 `LLM` 三列，删库重建。验证：服务能起来。
2. **`thinking.py` 新建 + 各 LLM 类瘦身** → 删 `thinking_policy.py`，加 `self.protocol`。验证：LLM 能实例化。
3. **`message_converter.py` 四函数回灌** → 核心改动。验证：单测 4 个 provider wire format。
4. **`react_runtime_service.append_assistant_message` + engine** → 回灌链路打通。验证：单测 reasoning 进 messages。
5. **engine 删 auto、加 `_build_thinking_kwargs`** → 决策简化。验证：thinking_enabled 生效。
6. **parser/types/system_prompt 删 `thinking_next_turn`** → 协议清理。验证：parser 单测过。
7. **API schema + supervisor** → `thinking_enabled` 贯通。验证：API 能接收。
8. **前端** → ChatThinkingMode 改、ChatComposer 改、LLM 编辑器删 thinking。验证：lint/type 过。
9. **手动端到端验证** → 跑一轮 Claude/GPT thinking 模型，看 reasoning 回灌。验证 5.1 全部。
10. **删旧测试、加新测试** → 验证 5.2/5.3。

每步完成后可独立 commit，便于回滚。
