# Native Tool Calling 迁移方案

> 从 prompt-based（sentinel marker）迁移到各 LLM provider 的原生 tool calling API。

## 1. 背景与目标

### 现状

Pivot 的 ReactEngine 采用 **prompt-based tool calling**：
- 工具通过 `ToolManager.to_text_catalog()` 以 JSON 数组注入 system prompt
- LLM 输出一个 JSON envelope，其中 `action_type: "CALL_TOOL"` 时附带 `$payload_ref` 引用
- 实际参数值放在 `<<<PIVOT_PAYLOAD:name:BEGIN/END_6F2D9C1A>>>` 哨兵标记之间
- `parser.py` 负责解析 JSON + 提取 payload 块 + 解析 `$payload_ref`
- Eager execution：payload 块完整后立即启动工具执行，不等整个 LLM 响应结束

### 目标

- 迁移到各 provider 的 **原生 tool calling API**（`tools` 参数 → `tool_calls` 响应 → `tool_result` 回传）
- 保留 Eager Execution 能力（基于 streaming tool call 完成检测）
- PLAN / REFLECT / CLARIFY / ANSWER 保持文本输出，只有 **CALL_TOOL** 走 native tool calling
- 干净切，无 fallback，删除所有旧 sentinel/parser 代码

---

## 2. 已达成的共识

| # | 决策 | 结论 |
|---|------|------|
| 1 | Custom Tools（Response API 独有） | **不做**。PLAN/REFLECT/CLARIFY/ANSWER 保持文本，只有 CALL_TOOL 走 native |
| 2 | Gemini call_id | Gemini 并行调用支持 `call_id` / `tool_use_id`，需从 API 响应中正确提取 |
| 3 | 消息持久化格式 | **方案 A**：DB 存统一内部格式，发送给 LLM 时按 provider 转换 |
| 4 | 是否保留 prompt-based 作为 fallback | **不保留**。干净切，旧代码全删 |
| 5 | Batch 编排 | **方案 A（隐式多轮）**：删除 batch 字段。并行调用由模型在一个响应中返回多个 tool_calls；顺序调用由模型自然分多轮。不再一次响应多批 |
| 6 | `strict` mode | 默认 `false`，前端 LLM Provider Create/Edit Dialog 中可选。三方兼容模型可能不支持此参数 |
| 7 | `tool_choice` | 保持默认 `auto`，不实现配置。模型需自由切换 tool calling 和文本输出 |
| 8 | Eager Tool Execution | **保留且更干净**。每个 provider 有明确的 tool call 完成信号（见第 5.4 节） |

### 路由逻辑

```
response 到达后:
├── 有 tool_calls? → 执行 CALL_TOOL 流程（优先）
│   文本部分作为 reasoning/thinking 展示给用户
├── 无 tool_calls? → 解析文本部分
│   ├── 含 PLAN/REFLECT/CLARIFY/ANSWER → 对应处理
│   └── 纯文本 → 当作 ANSWER 处理
```

每个轮次只有一种主 action，逻辑清晰。

---

## 3. 四大 Provider Native Tool Calling API 规范

### 3.1 OpenAI Chat Completion (`/chat/completions`)

**Tool 定义**：

```json
{
  "type": "function",
  "function": {
    "name": "read_file",
    "description": "...",
    "parameters": { "type": "object", ... },
    "strict": true
  }
}
```

**响应格式**（`message.tool_calls`）：

```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "I'll read that file.",
      "tool_calls": [{
        "id": "call_abc123",
        "type": "function",
        "function": { "name": "read_file", "arguments": "{\"path\":\"main.py\"}" }
      }]
    },
    "finish_reason": "tool_calls"
  }]
}
```

**Tool Result 回传**（专用 `tool` 角色）：

```json
{ "role": "tool", "tool_call_id": "call_abc123", "content": "file contents..." }
```

**流式事件**：
- `delta.tool_calls[i].function.arguments` 逐片段拼接
- `finish_reason: "tool_calls"` 表示所有 tool call 完成

---

### 3.2 OpenAI Response (`/responses`)

**Tool 定义**（扁平格式，无 `function` 包裹）：

```json
{
  "type": "function",
  "name": "read_file",
  "description": "...",
  "parameters": { "type": "object", ... },
  "strict": true
}
```

**响应格式**（`output[]` 数组）：

```json
{
  "output": [
    { "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "..."}] },
    {
      "type": "function_call",
      "id": "fc_abc123",
      "call_id": "call_abc123",
      "name": "read_file",
      "arguments": "{\"path\":\"main.py\"}"
    }
  ]
}
```

**Tool Result 回传**（`function_call_output`，无角色概念）：

```json
{ "type": "function_call_output", "call_id": "call_abc123", "output": "file contents..." }
```

**流式事件**：
- `response.output_item.added` → 新 tool call 开始（含 `name`, `call_id`）
- `response.function_call_arguments.delta` → 逐步拼接 arguments
- `response.function_call_arguments.done` → 完整 arguments 可用 → **触发 eager execution**

---

### 3.3 Anthropic (`/v1/messages`)

**Tool 定义**（`input_schema` 替代 `parameters`）：

```json
{
  "name": "read_file",
  "description": "...",
  "input_schema": { "type": "object", ... }
}
```

**响应格式**（`content[]` 数组中的 `tool_use` block）：

```json
{
  "content": [
    { "type": "text", "text": "I'll read that file." },
    {
      "type": "tool_use",
      "id": "toolu_abc123",
      "name": "read_file",
      "input": { "path": "main.py" }
    }
  ],
  "stop_reason": "tool_use"
}
```

**Tool Result 回传**（`user` 角色 + `tool_result` content block）：

```json
{
  "role": "user",
  "content": [
    { "type": "tool_result", "tool_use_id": "toolu_abc123", "content": "file contents..." },
    { "type": "text", "text": "What should I do next?" }
  ]
}
```

⚠️ **Anthropic 硬性约束**：
- `tool_result` blocks 必须紧跟在 assistant 的 `tool_use` 消息之后
- 同一 user message 中，`tool_result` blocks 必须排在任何 `text` blocks 之前

**流式事件**：
- `content_block_start`（type=`tool_use`）→ 新 tool call 开始（含 `id`, `name`）
- `input_json_delta` → 逐步拼接 input JSON
- `content_block_stop` → tool call 完整 → **触发 eager execution**

---

### 3.4 Gemini (`generateContent`)

**Tool 定义**（包裹在 `functionDeclarations` 内）：

```json
{
  "tools": [{
    "functionDeclarations": [{
      "name": "read_file",
      "description": "...",
      "parameters": { "type": "object", ... }
    }]
  }]
}
```

**响应格式**（`candidates[0].content.parts[]` 中的 `functionCall`）：

```json
{
  "candidates": [{
    "content": {
      "role": "model",
      "parts": [
        { "text": "I'll read that file." },
        { "functionCall": { "name": "read_file", "args": { "path": "main.py" } } }
      ]
    }
  }]
}
```

**Tool Result 回传**（`user` 角色 + `functionResponse` part）：

```json
{
  "role": "user",
  "parts": [
    { "functionResponse": { "name": "read_file", "response": { "content": "file contents..." } } }
  ]
}
```

⚠️ **Gemini 注意事项**：
- 并行调用时使用 `tool_use_id`（匹配输出中的 `call_id`）来关联结果
- 需要保留 `thought_signature` 跨轮次（思考模型）
- `args` 是已解析的 dict，不是 JSON 字符串

---

## 4. Pivot 现有代码就绪度评估

基于源码探索的精确评估：

### 4.1 LLM Provider 层

| 组件 | 文件 | 状态 | Gap |
|------|------|------|-----|
| **Tool 定义转换** | | | |
| Completion tools 透传 | `openai_completion_llm.py:370-408` | ✅ 已支持 | 需要从 OpenAI Completion 格式传入 |
| Response tools 透传 | `openai_response_llm.py:336-350` | ✅ 已支持 | 需要 Response 扁平格式（不是嵌套 `function`） |
| Anthropic 格式转换 | `anthropic_llm.py:125-150` | ✅ 已实现 | `parameters` → `input_schema` |
| Gemini 格式转换 | `gemini_llm.py:136-157` | ✅ 已实现 | → `functionDeclarations` |
| **非流式 Response 解析** | | | |
| Completion | `openai_completion_llm.py:204-218` | ✅ 已解析 `tool_calls` | 无 |
| Response | `openai_response_llm.py:133-177` | ✅ 已解析 `function_call` | 无 |
| Anthropic | `anthropic_llm.py:346-372` | ✅ 已解析 `tool_use` | 无 |
| Gemini | `gemini_llm.py:234-306` | ✅ 已解析 `functionCall` | 需要提取真实 call_id 而非合成 UUID |
| **流式 Tool Call 解析** | | | |
| Completion | `openai_completion_llm.py:488-632` | ⚠️ 片段已 yield | 需要上层积累（当前已如此） |
| Response | `openai_response_llm.py:387-543` | ❌ 完全缺失 | 需要新增 `response.output_item.added` / `response.function_call_arguments.delta` / `response.function_call_arguments.done` 事件处理 |
| Anthropic | `anthropic_llm.py:422-484` | ❌ 被丢弃 | `content_block_start`(L441) 和 `input_json_delta`(L478) 都 return None，需要改为正确 yield |
| Gemini | `gemini_llm.py:363-428` | ⚠️ 可用但有缺陷 | 每个 chunk 生成新 UUID，需要去重或使用 provider 返回的 id |
| **Tool Role 消息处理** | | | |
| Completion | `openai_completion_llm.py` 无转换 | ✅ 原样透传 | 无 |
| Response | `openai_response_llm.py:86-131` | ❌ 被丢弃 | `_build_input_messages()` 需要处理 `function_call_output` 类型 |
| Anthropic | `anthropic_llm.py:95-123` | ❌ 被丢弃 | `_convert_messages()` 需要生成 `tool_use`/`tool_result` 格式 |
| Gemini | `gemini_llm.py:95-130` | ❌ 被丢弃 | `_convert_messages()` 需要生成 `functionCall`/`functionResponse` 格式 |
| **死代码** | | | |
| `AbstractLLM._convert_response()` | `abstract_llm.py:254-351` | 死代码 | 迁移完成后删除 |

### 4.2 ReactEngine 层

| 组件 | 文件:行号 | 当前行为 | 迁移后 |
|------|-----------|----------|--------|
| LLM 调用 | `engine.py:2009-2012` | 不传 `tools` 参数 | 传入 `tools=tool_manager.to_openai_tools()` |
| 输出解析 | `engine.py:2053-2057` | `parse_react_output(content)` | 从 response 的 `tool_calls` 提取 + 文本部分解析 PLAN/REFLECT/CLARIFY/ANSWER |
| Eager 触发 | `engine.py:643-887` | 哨兵标记检测 → payload 块完成 | provider-native 流式 tool call 完成检测 |
| Eager 执行 | `engine.py:1856-1951` | payload refs 解析后启动 | tool call arguments 完整后启动 |
| 工具结果回传 | `engine.py:3106-3122` | 文本形式嵌入下一轮 user message | provider-native tool result 格式 |
| Assistant 消息追加 | `engine.py:3077-3091` | 原始文本（含 sentinel） | 含 `tool_calls` 的消息 |

### 4.3 Parser 层

| 组件 | 文件:行号 | 迁移后处理 |
|------|-----------|-----------|
| `parse_react_output()` | `parser.py:265-308` | 大幅简化：只解析 JSON envelope 中的 PLAN/REFLECT/CLARIFY/ANSWER |
| `split_json_and_payload_sections()` | `parser.py:66-93` | **删除**：不再有 payload section |
| `parse_payload_blocks()` | `parser.py:110-161` | **删除** |
| `collect_complete_payload_blocks()` | `parser.py:164-213` | **删除** |
| `$payload_ref` 解析 | `parser.py:705-798` | **删除** |
| `PAYLOAD_BEGIN_RE` / 哨兵相关常量 | `parser.py:9-27` | **删除** |

### 4.4 System Prompt

| 组件 | 文件:行号 | 变化 |
|------|-----------|------|
| `{{tools_description}}` 占位符 | `system_prompt.md:133-139` | **删除**：工具通过 API 传入，不再注入 prompt |
| CALL_TOOL 格式说明 | `system_prompt.md:32-71` | **大幅简化**：不再需要 `$payload_ref` 和哨兵格式说明 |
| 工具使用指导 | `system_prompt.md:133-139` | **简化**：只保留何时使用工具的高层指导 |

### 4.5 Frontend（预计零或极小改动）

SSE 事件类型不变（`tool_call`, `tool_payload_delta`, `tool_result` 等），因为：
- 这些事件由 ReactEngine 发射，格式由我们控制
- 后端从 sentinel-based 改为 native-tool-based 后，发射的事件数据结构保持兼容
- `RecursionCard.tsx` 渲染逻辑不变

可能的微小变化：
- `tool_payload_delta` 事件的 arguments 内容来源从 "sentinel payload 文本" 变为 "native tool call arguments JSON"，前端需要验证兼容性

---

## 5. 架构设计

### 5.1 统一内部消息格式

DB 中存储的消息使用统一格式（不依赖任何 provider）：

```python
# 消息角色
INTERNAL_ROLE_USER = "user"
INTERNAL_ROLE_ASSISTANT = "assistant"
INTERNAL_ROLE_SYSTEM = "system"

# 一条消息的内部表示
{
    "role": "assistant",
    "content": "I'll read that file for you.",
    "tool_calls": [                          # 可选，仅 assistant 消息
        {
            "id": "call_abc123",
            "name": "read_file",
            "arguments": "{\"path\":\"main.py\"}"
        }
    ]
}

{
    "role": "user",
    "content": "Here are the results...",     # 可选
    "tool_results": [                         # 可选，仅 user 消息
        {
            "tool_call_id": "call_abc123",
            "name": "read_file",
            "result": "file contents...",
            "is_error": false
        }
    ]
}
```

### 5.2 Provider 消息转换层

新增 `server/app/llm/message_converter.py`，将内部格式转换为各 provider 的 API 格式：

```
内部格式 → OpenAI Completion: content + tool_calls → message.tool_calls, role=tool
内部格式 → OpenAI Response: content + tool_calls → output items, function_call_output
内部格式 → Anthropic: content + tool_calls → content blocks (text + tool_use / tool_result)
内部格式 → Gemini: content + tool_calls → parts (text + functionCall / functionResponse)
```

### 5.3 Provider Tool Result Formatter

每个 provider 需要将自己的 tool call 结果格式化为该 provider 能理解的消息：

| Provider | Tool Call 消息 | Tool Result 消息 |
|----------|---------------|-----------------|
| Completion | `message.tool_calls` 保留原样 | `{role: "tool", tool_call_id, content}` |
| Response | `output[]` 中的 `function_call` item | `{type: "function_call_output", call_id, output}` |
| Anthropic | `content[]` 中的 `tool_use` block | `{role: "user", content: [{type: "tool_result", tool_use_id, content}]}` |
| Gemini | `parts[]` 中的 `functionCall` part | `{role: "user", parts: [{functionResponse: {name, response}}]}` |

### 5.4 Eager Execution 新触发机制

| Provider | 流式中的 tool call 完成信号 | Eager 触发点 |
|----------|--------------------------|-------------|
| Completion | `delta.tool_calls[i]` arguments 拼接完整 | 检测到完整 JSON arguments |
| Response | `response.function_call_arguments.done` 事件 | 该事件到达即触发 |
| Anthropic | `content_block_stop`（当前 block 是 `tool_use`） | 该事件到达即触发 |
| Gemini | `functionCall` part 出现（含完整 args） | part 出现即触发 |

---

## 6. 需要修改的文件清单

### 新增文件

| 文件 | 用途 |
|------|------|
| `server/app/llm/message_converter.py` | 内部消息格式 → 各 provider API 格式的转换 |

### 修改文件

| 文件 | 改动范围 |
|------|----------|
| **LLM Provider 层** | |
| `server/app/llm/openai_completion_llm.py` | 小：`_build_messages()` 处理 `tool_results` 角色 |
| `server/app/llm/openai_response_llm.py` | **中**：`_build_input_messages()` 处理 tool result + **补全流式 tool call 事件** |
| `server/app/llm/anthropic_llm.py` | **中**：`_convert_messages()` 处理 tool_use/tool_result + 修改 `_parse_stream_event()` 中的 `content_block_start` / `input_json_delta` |
| `server/app/llm/gemini_llm.py` | **中**：`_convert_messages()` 处理 functionCall/functionResponse + `_parse_response()` 提取真实 call_id + `_parse_stream_chunk()` 去重 |
| **ReactEngine 层** | |
| `server/app/orchestration/react/engine.py` | **大**：`execute_recursion()` 传入 tools、解析 tool_calls、tool result 回传、eager execution 重构 |
| **Parser 层** | |
| `server/app/orchestration/react/parser.py` | **大**：删除 sentinel/payload/ref 相关代码，只保留 PLAN/REFLECT/CLARIFY/ANSWER 文本解析 |
| **System Prompt** | |
| `server/app/orchestration/react/system_prompt.md` | **中**：删除 `{{tools_description}}` 占位符和 CALL_TOOL 格式说明 |
| `server/app/orchestration/react/prompt_template.py` | **小**：删除 `tools_description` 模板替换逻辑 |
| **Tool 层** | |
| `server/app/orchestration/tool/manager.py` | **小**：删除 `to_text_catalog()`，保留 `to_openai_tools()` |

### 删除文件

无（代码删除在现有文件中完成）。

### 删除的代码

| 代码 | 位置 | 原因 |
|------|------|------|
| `AbstractLLM._convert_response()` | `abstract_llm.py:254-351` | 死代码，从未被调用 |
| `to_text_catalog()` | `manager.py:148-162` | 不再需要文本目录注入 prompt |
| 哨兵相关常量 | `parser.py:9-27` | 不再使用 sentinel markers |
| `split_json_and_payload_sections()` | `parser.py:66-93` | 不再有 payload section |
| `parse_payload_blocks()` | `parser.py:110-161` | 不再有 payload blocks |
| `collect_complete_payload_blocks()` | `parser.py:164-213` | 不再需要流式 payload 检测 |
| `_resolve_payload_references()` | `parser.py:705-798` | 不再使用 `$payload_ref` |
| `_resolve_answer_payload_reference()` | `parser.py:801-829` | ANSWER 不再需要 payload ref |
| Eager execution 中的 sentinel 检测逻辑 | `engine.py` 中的 `PAYLOAD_BEGIN_RE` 使用 | 改为 native tool call 完成检测 |

---

## 7. 实施阶段

### Phase 0: 基础抽象（2 天）

1. 创建 `message_converter.py`，实现内部消息格式 → 四种 provider 格式的转换
2. 修改四个 provider 的 `_convert_messages()` / `_build_input_messages()` / `_build_messages()`，使其能处理 tool result 消息
3. 单元测试：给定内部格式消息 → 验证各 provider 输出正确的 API 格式

**验证**：每个 provider 的消息转换有独立的单元测试通过

### Phase 1: ReactEngine 核心改造（3 天）

1. 修改 `execute_recursion()`：传入 `tools=tool_manager.to_openai_tools()`
2. 新增 `_extract_tool_calls_and_text()` 方法：从 LLM response 中分离 tool_calls 和文本
3. 修改路由逻辑：有 tool_calls → CALL_TOOL；无 → 解析文本
4. 修改工具结果回传：使用内部统一格式存储，通过 message_converter 转换后发送
5. 简化 `parser.py`：只保留文本 action（PLAN/REFLECT/CLARIFY/ANSWER）的解析

**验证**：用 OpenAI Completion protocol 端到端验证（非流式）

### Phase 2: Eager Execution 适配（2 天）

1. 重构 `_stream_chat_response()`：移除 sentinel 检测，改为 tool call 完成检测
2. 每个 provider 的流式 tool call 处理：
   - Completion：积累 `delta.tool_calls[i].function.arguments`
   - Response：处理 `response.function_call_arguments.done`
   - Anthropic：处理 `content_block_start`(tool_use) + `input_json_delta` + `content_block_stop`
   - Gemini：检测 `functionCall` part 出现
3. `_advance_eager_tool_execution()` 改为基于 tool call arguments 完整性触发

**验证**：用 OpenAI Completion protocol 端到端验证（流式 + eager execution）

### Phase 3: 补全其他 Provider（2-3 天）

1. **OpenAI Response**：补全 `chat_stream()` 中的 `response.output_item.added` / `response.function_call_arguments.delta` / `response.function_call_arguments.done` 事件处理
2. **Anthropic**：修改 `_parse_stream_event()` 让 `content_block_start`(tool_use) 和 `input_json_delta` 正确 yield
3. **Gemini**：`_parse_response()` 提取真实 call_id、`_parse_stream_chunk()` 去重、添加 FinishReason.TOOL_CALLS 映射

**验证**：每个 provider 独立端到端测试

### Phase 4: 清理与 System Prompt 优化（1 天）

1. 删除所有 sentinel/parser 相关的死代码
2. 精简 `system_prompt.md`：移除 `{{tools_description}}` 和 CALL_TOOL 格式说明
3. 修改 `prompt_template.py`：移除 `tools_description` 模板变量
4. 删除 `to_text_catalog()`
5. 删除 `AbstractLLM._convert_response()` 死代码
6. 全量回归测试

**验证**：四个 provider 全部通过，前端显示正常

---

## 8. System Prompt 变化

### 现有 system_prompt.md 关键部分

```
## Output Format
Output a bare JSON object. When `action_type` is `CALL_TOOL` or `ANSWER`,
append payload blocks immediately after the JSON.

## CALL_TOOL Format
(30+ 行关于 $payload_ref、sentinel markers、batch 编排的说明)

## Available Tools
```json
{{tools_description}}
```
```

### 迁移后

```
## Output Format
Output a bare JSON object with your reasoning and next action decision.

When you need to execute tools, use the tool calling interface.
When you want to plan, reflect, clarify, or answer, output the JSON action directly.

## Action Types
- PLAN: ...
- REFLECT: ...
- CLARIFY: ...
- ANSWER: ...

## Available Tools
(不再列出。工具通过 API tools 参数传入，模型自动感知)
```

关键变化：
- **不再在 prompt 中描述工具列表**（通过 API 传入）
- **不再描述 CALL_TOOL 格式**（模型通过 native tool calling 自动处理）
- **不再描述 sentinel/payload 协议**（完全删除）
- **保留** PLAN/REFLECT/CLARIFY/ANSWER 的文本格式说明

---

## 9. 前端影响评估

### SSE 事件类型（不变）

| 事件 | 来源变化 | 数据结构变化 |
|------|----------|-------------|
| `tool_call` | 从 sentinel 解析变为从 native tool_calls 提取 | `tool_calls[].arguments` 从 payload ref 变为直接 JSON |
| `tool_payload_delta` | 从 payload 文本流变为 tool call arguments 流 | 可能从纯文本变为 JSON 片段 |
| `tool_result` | 不变 | 不变 |
| `answer_delta` | 不变 | 不变 |
| `reasoning` / `message` / `action` | 不变 | 不变 |

### RecursionCard.tsx

- `ToolTimeline` 组件处理 `tool_call` / `tool_payload_delta` / `tool_result` 事件
- 需要验证 `tool_payload_delta` 的 arguments 流内容是否兼容现有的 live payload 累积逻辑
- 如果 native tool calling 的 arguments 是 JSON 字符串而非自由文本，可能需要微调

### 预计改动

**极小或零**。主要风险在 `tool_payload_delta` 的内容格式兼容性，需要实测确认。

---

## 10. Batch 编排（已确认：方案 A 隐式多轮）

### 决策

**删除 batch 字段**，采用隐式多轮方案。

### 现有方式
LLM 在 JSON envelope 中指定每个 tool call 的 `batch` 编号，parser 提取后按 batch 顺序执行。一次 LLM 调用可以编排多批工具。

### 迁移后

Native tool calling API 的 `tool_calls` 是扁平列表，没有地方挂 batch 元数据。

**方案 A（隐式多轮）**：
- 并行调用 → 模型在一个响应中返回多个 tool_calls → 全部并发执行
- 顺序调用 → 模型分多轮：先返回第一批 tool_calls → 收到结果 → 再返回第二批
- 这就是 Claude Code、OpenAI Agents SDK 等所有主流 agent 的标准做法

### 影响

| 维度 | 现在 | 迁移后 |
|------|------|--------|
| 编排方式 | 显式 batch 编号 | 隐式多轮 |
| 串行执行 | 1 次 LLM 调用内完成 | N 次 LLM 调用 |
| 并行执行 | 同 batch 内并发 | 同一响应内多个 tool_calls 并发 |
| 协议复杂度 | 需要 batch 字段 + 顺序保证 | 零额外协议 |
| 延迟 | 较低（少一次 LLM 往返） | 略高（多一次 LLM 往返） |

### 代码变化

- **删除** `parser.py` 中 `tool_calls[].batch` 的解析逻辑
- **删除** `engine.py` 中按 batch 分组的执行逻辑
- **简化** `execute_recursion()`：所有 tool_calls 并发执行，无 batch 排序
- **简化** `system_prompt.md`：不再需要 batch 编排指导

---

## 11. 已确认方案：`tool_payload_delta` Streaming 渲染

### 决策：方案 B — Batched Partial Parse（500ms 纯时间驱动）

**核心思路**：LLM streaming 时，native tool call 的 arguments 以 JSON 字符串片段到达。后端每 500ms 用 Pydantic `allow_partial` 做一次 partial parse，发现新完成的参数后发射兼容现有前端格式的事件。工具调用完成时立即做最终 parse（不等 500ms）。

**为什么选 B 不选 A（Claude Code 做法）**：
- 方案 B 能让前端按参数名逐个展示（和现在一致），用户体验无变化
- 方案 A 在 streaming 阶段只能显示 raw JSON 增长，完成后才切换结构化——有体验降级
- jiter (Rust) partial parse 开销极小（~µs 级），500ms 间隔下每秒仅 2 次 parse

**为什么是 500ms 纯时间驱动**：
- 500ms 内主流模型约产出 20-150 字符（取决于模型速度），足够包含 1-2 个完整参数
- 用户在 streaming 中看到的是连续 token 流，结构化参数延迟 500ms 完全无感知
- 不用 delta 计数或字符数阈值，因为这些值与 JSON 结构无关且跨 provider 不可比
- 配置项在 `config.py: REACT_TOOL_CALL_PARTIAL_PARSE_INTERVAL_MS = 500`

### 四 provider 的流式 tool call 能力

| Provider | Tool Call 流式？ | 机制 |
|----------|-----------------|------|
| OpenAI Completion | ✅ 增量 delta | `delta.tool_calls[i].function.arguments` 逐片段 |
| OpenAI Response | ✅ 增量 delta | `response.function_call_arguments.delta` |
| Anthropic | ✅ 增量 delta | `input_json_delta` 逐字符 |
| Gemini | ❌ 完整单元 | `functionCall` 一个 chunk 完整到达（天然适合，无需 partial parse） |

### 后端实现

```python
# config.py
REACT_TOOL_CALL_PARTIAL_PARSE_INTERVAL_MS: int = 500

# engine.py — StreamingToolCallState
class StreamingToolCallState:
    """跟踪流式 tool call 的累积状态"""
    call_id: str
    name: str
    accumulated_json: str = ""
    last_parse_time: float = 0.0
    last_parsed_result: dict = {}  # 上次 parse 结果，用于 diff

# _stream_chat_response() 中的核心逻辑
streaming_tools: dict[str, StreamingToolCallState] = {}
parse_interval = get_settings().REACT_TOOL_CALL_PARTIAL_PARSE_INTERVAL_MS / 1000

for chunk in self.llm.chat_stream(messages=messages, tools=tools, **kwargs):
    # 1. 文本 delta（reasoning / message）→ 和现在一样处理
    ...

    # 2. Tool call delta（provider-specific extraction）
    tool_call_delta = extract_tool_call_delta(chunk)

    if tool_call_delta.type == "tool_call_start":
        # 工具名立即可见
        streaming_tools[call_id] = StreamingToolCallState(call_id=..., name=...)
        yield {"type": "tool_call", "data": {
            "tool_calls": [{"id": call_id, "name": name, "arguments": {},
                            "pending_arguments": True}]
        }}

    elif tool_call_delta.type == "arguments_delta":
        state = streaming_tools[call_id]
        state.accumulated_json += delta

        # 每 500ms 做一次 partial parse
        now = time.monotonic()
        if now - state.last_parse_time >= parse_interval:
            state.last_parse_time = now
            parsed = try_partial_parse(state.accumulated_json)
            if parsed is not None:
                # Diff → 发射新完成参数的事件（前端零改动）
                for key in parsed:
                    if key not in state.last_parsed_result:
                        yield {
                            "type": "tool_payload_delta",
                            "data": {
                                "tool_call_id": call_id,
                                "argument_name": key,
                                "delta": str(parsed[key]),
                                "is_final": True,
                            },
                        }
                state.last_parsed_result = parsed

    elif tool_call_delta.type == "arguments_done":
        # 工具调用完成 → 最终 parse → eager execution
        state = streaming_tools.pop(call_id)
        final_args = json.loads(state.accumulated_json)

        # 发射剩余未通过 partial parse 捕获的参数
        for key, value in final_args.items():
            if key not in state.last_parsed_result:
                yield {"type": "tool_payload_delta", "data": {
                    "tool_call_id": call_id,
                    "argument_name": key,
                    "delta": str(value),
                    "is_final": True,
                }}

        yield {"type": "tool_call", "data": {
            "tool_calls": [{"id": call_id, "name": name,
                            "arguments": final_args,
                            "pending_arguments": False}]
        }}

        # Eager execution
        asyncio.create_task(self._execute_tool_call_request(...))


def try_partial_parse(accumulated_json: str) -> dict | None:
    """Pydantic allow_partial 解析不完整 JSON"""
    try:
        return TypeAdapter(dict).validate_json(
            accumulated_json, allow_partial=True,
        )
    except Exception:
        return None
```

### 前端影响

**零改动**。后端发射的 `tool_payload_delta` 事件格式和现在完全一致：
```json
{"type": "tool_payload_delta", "data": {"tool_call_id": "...", "argument_name": "path", "delta": "main.py", "is_final": true}}
```

前端 `livePayload.arguments[argument_name] += delta` 逻辑无需任何变化。

### 实施前需验证

1. **Pydantic `allow_partial` 行为**：确认 `{"path": "main.py", "con` → 返回 `{"path": "main.py"}`
2. **嵌套对象处理**：`{"path": "main.py", "options": {"enc` 的 partial parse 结果
3. **空值/null 参数**：`{"path": null, "enc` 的 partial parse 结果

---

## 12. 工作量估算

| Phase | 内容 | 天数 | 风险 |
|-------|------|------|------|
| Phase 0 | 基础抽象 + 消息转换 | 2 | 低 |
| Phase 1 | ReactEngine 核心改造 | 3 | 中 |
| Phase 2 | Eager Execution + Streaming Partial Parse | 2 | 中 |
| Phase 3 | 补全其他 Provider | 2-3 | 中（Response 流式补全、Anthropic 顺序约束） |
| Phase 4 | 清理与优化 | 1 | 低 |
| **总计** | | **10-11 天** | |
