# Tool Call Batch 与 Eager Execution 执行计划

本文面向后续实现者，尤其是 Agent 自己。目标是把我们已经达成的 tool call 设计共识落成可执行计划。

## 最新共识

1. `tool_call.batch` 是核心编排协议。
2. `batch` 越小越早执行，同一个 `batch` 内并发执行。
3. 是否并发主要由 Agent 判断。明显互相影响、存在前后依赖、或者需要前一个结果构造后一个参数的动作，Agent 应自行拆 batch 或拆 recursion。
4. Runtime 不做过度保姆式串行，只保留协议校验、取消、fatal error、pending user action 等底线保护。
5. Eager tool call 是目标能力：某个 tool 的参数 payload 完整且所在 batch 可执行后，应尽早启动，不必等整段 assistant response 完成。
6. Eager 不能突破 batch 顺序。payload ready 只代表参数可解析，不代表可以越过更早 batch 执行。

核心规则：

```text
Eager execution is readiness-gated by payload completeness,
but order-gated by the lowest unfinished batch.
```

中文：

```text
eager 只解决“能早跑就早跑”，但不能突破 batch 顺序。
```

## 协议目标形态

`CALL_TOOL` 的 `tool_calls` 中每个对象新增 `batch`：

```json
{
  "id": "call_read_component",
  "name": "read_file",
  "batch": 1,
  "arguments": {
    "path": {
      "$payload_ref": "payload_component_path"
    }
  }
}
```

约束：

- `id`: 非空字符串，全局唯一于本轮 `CALL_TOOL`。
- `name`: 非空字符串。
- `batch`: 正整数。建议从 1 开始。
- `arguments`: object，所有参数值继续使用 `{"$payload_ref":"..."}`。
- 没有 `batch` 时，Phase 3A 可以兼容为 `1`；如果希望更严格，也可以 parser retry 要求补齐。建议第一版兼容，system prompt 强要求。

执行语义：

```text
batch 1 内全部可并发
batch 1 全部结束后，batch 2 才能开始
batch 2 全部结束后，batch 3 才能开始
```

## System Prompt 改造

修改 `pivot/server/app/orchestration/react/system_prompt.md` 的 `action_type = CALL_TOOL` 章节。

需要新增说明：

- 每个 tool_call 必须包含 `batch`。
- 同 batch 表示可以并行。
- 更大的 batch 表示必须等更小 batch 完成后再执行。
- 如果动作之间有明显依赖，必须拆 batch。
- 如果后一个工具的参数依赖前一个工具的结果，不能放进同一个 `CALL_TOOL`，应进入下一轮 recursion。
- Agent 不应把可能互相覆盖的写操作放在同一个 batch。
- Agent 可以把多个独立 read/search/list 操作放在同一个 batch。

示例要更新为：

```json
{
  "action": {
    "action_type": "CALL_TOOL",
    "output": {
      "tool_calls": [
        {
          "id": "call_read_a",
          "name": "read_file",
          "batch": 1,
          "arguments": {
            "path": {
              "$payload_ref": "payload1"
            }
          }
        },
        {
          "id": "call_read_b",
          "name": "read_file",
          "batch": 1,
          "arguments": {
            "path": {
              "$payload_ref": "payload2"
            }
          }
        },
        {
          "id": "call_run_tests",
          "name": "run_bash",
          "batch": 2,
          "arguments": {
            "command": {
              "$payload_ref": "payload3"
            }
          }
        }
      ]
    }
  }
}
```

## Data Model 改造

文件：`pivot/server/app/orchestration/react/types.py`

`ToolCallRequest` 增加：

```python
batch: int = 1
```

`to_dict()` 输出 `batch`。

可以增加 helper：

```python
def group_tool_calls_by_batch(tool_calls: list[ToolCallRequest]) -> list[list[ToolCallRequest]]:
    ...
```

但第一版也可以在 engine 内部就地 group，避免过早抽象。

## Parser 改造

文件：`pivot/server/app/orchestration/react/parser.py`

在 `_parse_tool_calls()` 中解析并校验 `batch`：

- `batch` 缺省为 `1`。
- 如果提供，必须是 int，且 `>= 1`。
- Python 中要注意 bool 是 int 子类，`true` 不应被接受为 batch。
- 同一轮 `tool_call.id` 不能重复。

建议错误信息：

```text
action.output.tool_calls[0].batch must be a positive integer.
Duplicate tool_call id: call_xxx.
```

`parse_react_control_section()` 也走 `_parse_action()`，所以 preview 阶段会自然拿到 batch。

测试：

- 解析带 batch 的 tool call。
- 缺省 batch 为 1。
- batch 为 0 / -1 / true / "1" 报错。
- 重复 id 报错。
- control section preview 保留 payload refs，同时包含 batch。

## Phase 3A: Batch Executor（已完成）

第一阶段先不做 eager。仍然等完整 LLM response parse 完，再按 batch 执行。

改造位置：

`pivot/server/app/orchestration/react/engine.py`

当前逻辑：

```python
for tool_call in action.tool_calls:
    result = await run_in_threadpool(...)
```

目标逻辑：

```python
for batch_number in sorted_batches:
    batch_calls = calls_by_batch[batch_number]
    if len(batch_calls) == 1:
        await execute_one(batch_calls[0])
    else:
        await execute_batch_parallel(batch_calls)
```

并发执行建议：

```python
tasks = [
    asyncio.create_task(execute_one(tool_call))
    for tool_call in batch_calls
]
for task in asyncio.as_completed(tasks):
    result_item = await task
    tool_results.append(result_item)
    emit tool_result
```

注意事项：

- `execute_one()` 内部继续使用 `run_in_threadpool(self.tool_manager.execute, ...)`。
- 每个 tool 完成后立刻通过 `token_meter_queue` emit `tool_result`。
- batch 内结果顺序可以按完成顺序流式发出。
- 最终持久化的 `tool_results` 建议按 `tool_calls` 原始顺序排序，方便历史稳定；如果保持完成顺序，也必须前后端都接受。建议最终 event_data 用原始 call 顺序，live SSE 用完成顺序。
- 如果某个 tool 失败，只记录该 tool 的 failed result，不默认取消同 batch 其他 tool。
- 当前 batch 全部结束后再进入下一 batch。
- 如果发现 pending user action，需要停止后续 batch。已完成工具结果保留。
- 如果 task cancelled，取消尚未完成的 asyncio task，并停止后续 batch。

事件：

- 完整 parse 后 emit resolved `tool_call`，包含所有 tool calls 和 batch。
- 每个 tool 完成 emit `tool_result`。
- 前端当前已经能合并 `tool_call` / `tool_result`，只需确认 batch 字段不会破坏展示。

测试：

- 同 batch 两个慢工具并发，总耗时小于串行。
- batch 2 等 batch 1 完成后才开始。
- batch 1 一个失败不阻止同 batch 另一个完成。
- pending user action 阻止后续 batch。
- live stream 中多个 result 能逐个发出。

## Phase 3B: 前端展示增强

第一版前端无需大改，现有 timeline 已经支持：

- Preparing
- Running
- Ran
- Failed badge
- 多工具聚合

可选增强：

- 展开 group 时按 batch 分组展示。
- 多 tool group 文案可以从 `n tools used` 升级为 `batch 1: n tools`，但不是必须。
- tooltip 或 detail 中展示 `Batch 1`。

保持克制：Phase 3A 不需要为了 batch 大改视觉层。

## Phase 3C: Eager Tool Call（基础闭环已完成）

这一阶段 blast radius 最大，应在 batch executor 稳定后再做。

当前已落地的最小闭环：

- `collect_complete_payload_blocks()` 可以从半截 assistant response 中收集已闭合 payload block。
- `resolve_tool_call_payloads()` 可以只解析单个 tool call 的 payload refs。
- `_stream_chat_response()` 在 JSON control section 可解析后初始化 eager state。
- payload 完整后，runtime 会在不突破 batch 顺序的前提下启动 ready tool。
- 最终完整 `parse_react_output()` 后，runtime 复用 eager 已完成结果，只补跑没有被 eager 启动的调用，避免重复执行。
- 单测已经覆盖：payload 在 stream 结束前闭合时，tool 会在后续 chunk 到达前启动。

仍待增强：

- 已完成：如果最终 parse failure 发生在 eager tool 已执行之后，当前实现会等待已启动任务结束，把本轮作为 failed `CALL_TOOL` 持久化，并把已发生 tool results 与 parse error 写入下一轮 `action_result`。
- 已完成：eager tool result pump。工具任务完成后会独立推送 `tool_result` 到 SSE 队列，不再依赖模型继续输出下一个 chunk。

### 前置条件

由于当前协议是“JSON control section 在前，payload blocks 在后”，scheduler 可以在第一个 payload begin 出现时拿到完整 tool call 列表：

```text
JSON control section complete
=> parse tool_calls + batch + payload refs
=> 初始化 scheduler
```

每个 tool 的启动条件：

1. tool_call JSON 已解析。
2. 该 tool 引用的所有 payload refs 都完整。
3. `tool_call.batch == active_batch`。
4. 没有 cancellation / fatal parse error / pending user action 阻断。

### Scheduler 状态

建议内部状态：

```python
class EagerToolScheduler:
    calls_by_id: dict[str, ToolCallRequest]
    refs_by_call_id: dict[str, set[str]]
    payloads: dict[str, str]
    ready_call_ids: set[str]
    running_call_ids: set[str]
    completed_call_ids: set[str]
    failed_call_ids: set[str]
    active_batch: int
```

关键行为：

```text
on_json_control(parsed_action):
  初始化 calls_by_id / refs_by_call_id / batches

on_payload_complete(payload_name, payload_text):
  保存 payload
  找到因此 ready 的 calls
  尝试启动 active_batch 中 ready 且未启动的 calls

on_tool_complete(call_id):
  标记完成
  如果 active_batch 全部完成，推进到下一个 batch
  推进后立刻启动新 active_batch 中已经 ready 的 calls
```

### Payload 顺序特例

如果 Agent 先输出 batch 3 的 payload，再输出 batch 1 的 payload：

```text
batch 3 payload ready -> 只进入 ready queue，不执行
batch 1 payload ready -> batch 1 active，立即执行
batch 1 完成 -> active_batch 推进
batch 3 到达 active 后，如果已经 ready，立即执行
```

这就是“payload readiness 不突破 batch order”。

### 增量 Payload Parser

需要从 `_stream_chat_response()` 或更靠近 streaming content 的位置提取 payload block 完成事件。

可选实现：

- 增加一个 incremental parser，只识别 payload begin/end sentinel。
- JSON control section 仍使用现有 `parse_react_control_section()`。
- 当某个 payload end sentinel 到达时，emit 内部事件 `payload_complete`。

注意：

- payload 内容可能很大，不要无限复制字符串。
- sentinel 必须按行匹配，沿用 `PAYLOAD_SENTINEL_SUFFIX`。
- 重复 payload name 应 fatal。
- payload end 缺失时，最终 parse 会失败。

### Eager 后的 Final Parse

即使 eager 已执行，最终仍必须完整调用 `parse_react_output()` 做一次最终校验。

如果最终 parse 失败，但已有 tool 执行：

- 不要假装工具没执行。
- 本轮 recursion 应记录 parse failure 以及已发生的 tool results。
- 下一轮让 Agent 看见这些事实并恢复。

这是重要边界：eager execution 把工具调用提前了，也意味着 parse failure 不再是纯粹无副作用失败。

### Parse Failure Recovery 规则

核心不变量：

```text
Before first tool execution, parse failures are retryable and rollbackable.
After first tool execution, parse failures are durable facts and must be recovered in the next recursion.
```

实现语义：

1. JSON control section parse failed
   - 没有 tool list，也不会启动 tool。
   - 可以走现有 parse retry。
   - 最终失败时 rollback 本轮 user payload，不消耗 iteration。

2. JSON control section parse 成功，但任何 tool 启动前 payload 协议失败
   - 仍未越过副作用边界。
   - 可以 retry/rollback。

3. 任意 tool 已 started 后，后续 payload 或最终完整 parse 失败
   - 不允许 retry 成“这一轮没发生过”。
   - 等待已 started tool 完成。
   - 已完成结果写入 `tool_call_results`。
   - 未启动 tool 写入 skipped/failed 结果。
   - recursion 以 `status=error` 持久化，但 `action_type=CALL_TOOL` 保持本轮 tool 事实。
   - `rollback_messages=false`，assistant raw message 进入 runtime window。
   - 下一轮 `action_result` 包含：
     - 已执行 tool 的 result/error。
     - `{"source":"assistant_response_parse","error":"..."}`。

这样下一轮 Agent 会明确知道：哪些副作用已经发生，以及本轮响应哪里坏了。

## Phase 3D: Runtime 底线约束

我们已经达成共识：不要把“Agent 傻导致并发错”作为 runtime 默认强制串行的理由。

但底线约束仍可能需要：

- cancellation 停止未启动 call。
- pending user action 停止后续 batch。
- fatal parse error 停止后续 batch。
- 同一个 call id 只允许启动一次。

未来如果确实需要工具级互斥，可以设计：

```python
parallel_policy = {
    "exclusive": False,
    "concurrency_key": "workspace:{workspace_id}:path:{path}"
}
```

但不要在 Phase 3A 主动扩大范围。

## Phase 3E: Live Tool Payload Preview（新增共识）

目标：让前端不只是看到 `Preparing / Running / Ran`，还可以在模型生成 tool 参数 payload 的过程中实时展示参数内容。第一批重点支持 `write_file` 和 `edit_file`：

- 折叠态只显示文件名和实时变更统计。
- 展开态不再把这两个工具渲染成传统 `Arguments:` JSON，而是渲染成类代码编辑器 / diff viewer。
- 统计和预览都随 payload stream 实时增长。

### 用户侧目标形态

折叠态：

```text
Running write_file index.html +37
Running edit_file index.html +12 -5
```

展开态：

```text
write_file index.html
+ 1  <!doctype html>
+ 2  <html>
+ 3    <head>
...
```

```diff
edit_file index.html
@@ -56,6 +56,6 @@
  .hero {
-   background: old;
+   background: new;
  }
```

### 后端 SSE 事件

新增一种 live payload event：

```json
{
  "type": "tool_payload_delta",
  "task_id": "...",
  "trace_id": "...",
  "iteration": 1,
  "data": {
    "tool_call_id": "call_1",
    "tool_name": "edit_file",
    "argument_name": "diff",
    "payload_name": "diff_payload",
    "delta": "...",
    "is_final": false
  },
  "timestamp": "..."
}
```

字段语义：

- `tool_call_id`: 所属 tool call。
- `tool_name`: 工具名，例如 `write_file` / `edit_file`。
- `argument_name`: 参数名，例如 `content` / `diff` / `path`。
- `payload_name`: payload block 名称。
- `delta`: 本次新增 payload 文本。
- `is_final`: 该 payload 是否已经看到 END sentinel。

### 映射来源

后端需要先从 JSON control section 得到：

```text
payload_name -> tool_call_id + tool_name + argument_name
```

来源示例：

```json
{
  "id": "call_1",
  "name": "edit_file",
  "arguments": {
    "path": {"$payload_ref": "path_payload"},
    "diff": {"$payload_ref": "diff_payload"}
  }
}
```

如果 payload begin 先于映射可用（极端 streaming 时序），可以先按 `payload_name` 暂存 delta；映射可用后再补发或补绑定。正常协议里 JSON control section 在前，payload blocks 在后，因此大多数情况下映射应已存在。

### 后端增量解析

后端 streaming parser 已经能明确感知 payload begin / end：

```text
<<<PIVOT_PAYLOAD:name:BEGIN_6F2D9C1A>>>
...
<<<PIVOT_PAYLOAD:name:END_6F2D9C1A>>>
```

新增能力：

- 当某个 payload begin 出现后，后端开始把 payload 内容作为 delta 推给前端。
- END sentinel 不进入 delta 内容。
- begin/end sentinel 只用于协议，不展示给用户。
- payload 完整后仍走现有 final parse / resolved tool_call / eager execution 逻辑。

边界：

- tool 仍不能在 payload 未完整前执行。
- payload 协议失败时，沿用 Phase 3C 的 parse failure recovery 规则。
- 不要为了预览改变最终 tool arguments 的解析语义。

### 前端状态设计

不要把实时 payload delta 直接塞进主 `messages` 状态。否则每个 delta 都会重渲染整条 Chat timeline，容易卡顿。

推荐新增一个轻量 live payload store：

```ts
type LiveToolPayloadState = {
  toolCallId: string;
  toolName: string;
  argumentName: string;
  payloadName: string;
  filename?: string;
  addedLines: number;
  removedLines: number;
  isFinal: boolean;
  previewLines: string[];
};
```

设计原则：

- 用 `Map<toolCallId, LiveToolPayloadState>` 存在独立 store/ref 中。
- SSE 收到 delta 后先 append 到 buffer/ref。
- 用 `requestAnimationFrame` 或 100ms throttle 批量通知订阅组件。
- 只有相关 tool row / expanded preview 订阅自己的 `toolCallId`。
- 未展开时只渲染 filename 和 counters。
- 展开时才渲染代码 / diff 预览。
- 大 payload 不要全量渲染，优先渲染窗口，例如最近 300-500 行。

这样能复用 Chat 列表当前的 memo 分层，同时避免高频 payload 更新牵动整个 `messages` tree。

### `write_file` 展示规则

摘要：

```text
Running write_file filename +N
```

文件名：

- `write_file` 和 `edit_file` 的摘要只显示 basename。
- 完整 path 放到 `title`，hover 时可看。

计数：

- `write_file.content` 按当前 payload 内容统计写入行数。
- 折叠态实时显示 `+N`，绿色。
- content 完整后以最终 resolved arguments 为准校正一次。

展开态：

- 用等宽字体 + 行号。
- 每一行按新增行展示为绿色。
- 可以显示为：

```text
+ 1  first line
+ 2  second line
```

性能：

- 未展开时不渲染正文。
- 展开时渲染可视窗口，不一次性渲染超大文件全文。
- 可以在完成后提供 “show full” 行为，但初版不必做复杂编辑器。

### `edit_file` 展示规则

摘要：

```text
Running edit_file filename +N -M
```

计数：

- 统计 `edit_file.diff` payload 中真正的 diff body 行。
- `+` 开头计入 added，绿色。
- `-` 开头计入 removed，红色。
- 忽略 `+++` / `---` file header。
- 忽略 `@@` hunk header 和 context 行。
- diff payload 完整后以最终 resolved arguments 为准校正一次。

展开态：

- 渲染轻量 diff viewer：
  - hunk header 灰色。
  - added 行绿色。
  - removed 行红色。
  - context 行正常。
- 不展示 `Arguments:` JSON。
- `Result:` 仍可在底部保留，或折叠在 “Tool result” 区域。

### 渲染性能约束

核心原则：

```text
Payload delta can be high-frequency; React state updates must be low-frequency and local.
```

约束：

- 不允许每个 token / chunk 都 set 主消息状态。
- 不允许每个 delta 都重新 split 全量 payload。
- 统计用增量算法。
- previewLines 只保留窗口，或者保留完整 buffer 在 ref 中、渲染只取尾部。
- 使用 `requestAnimationFrame` 合并 UI 更新。
- 展开态组件卸载后要取消订阅，避免后台继续重渲染。
- auto scroll 只响应已启用 follow mode 的可见高度变化，不因每个 payload token 抖动锚点。

### 与现有 tool_result 的关系

live payload preview 是“参数正在生成”的 UI，不替代最终 tool lifecycle。

完整 lifecycle：

```text
JSON control parsed
=> tool_call preview: Preparing
=> payload begin
=> tool_payload_delta: live content / diff preview
=> payload end
=> resolved tool_call: Running
=> tool_result: Ran / Failed
```

如果最终 parse failure 发生在 tool 执行前：

- live preview 可以消失或标记为 parse failed。
- 不应显示为已执行。

如果 eager tool 已经执行后最终 parse failure：

- 沿用 Phase 3C：已执行结果作为事实保留。
- live preview 可保留为本轮失败诊断的一部分。

### 实施顺序建议

1. 前端先把 `write_file` / `edit_file` 摘要从完整 path 改为 basename，并在 resolved arguments 后显示最终 `+N` / `+N -M`。
2. 后端新增 `tool_payload_delta` SSE event。
3. 前端新增 live payload store，折叠态实时 counters。
4. 前端给 `write_file` 做展开态 code preview。
5. 前端给 `edit_file` 做展开态 diff preview。
6. 大 payload 下做窗口化 / show full 优化。

## 推荐执行顺序（当前进度）

1. 已完成：更新 `system_prompt.md`，加入 `batch` 规范与示例。
2. 已完成：更新 `types.py`，`ToolCallRequest` 增加 `batch`。
3. 已完成：更新 `parser.py`，校验 batch 与重复 id。
4. 已完成：更新 parser tests。
5. 已完成：更新 `engine.py`，实现非 eager batch executor。
6. 已完成：更新 engine tests，覆盖 batch 并发、串行、最终结果顺序。
7. 已完成：确认现有前端 timeline 可消费 `pending_arguments`、resolved `tool_call`、`tool_result`。
8. 已完成：Phase 3C 最小 eager scheduler。
9. 已完成：补 parse failure recovery。
10. 已完成：补 eager result pump，确保 tool 完成后立即进入 SSE 队列。
11. 下一步：真实 session 联调观察端到端 UI 时序。

## 暂不做

- 暂不做 `$result_ref`。
- 暂不做任意 DAG。
- 暂不做复杂工具安全推断。
- 暂不大改前端 batch 分组视觉。
- 暂不让后端替 Agent 判断哪些写操作“应该串行”。

## 成功标准

Phase 3A 完成时：

- Agent 可以在一轮 `CALL_TOOL` 中声明多个 batch。
- 同 batch 工具实际并发执行。
- 后续 batch 严格等待前序 batch 完成。
- live tool_result 仍能逐个到达前端。
- 历史 session 仍能正确展示 tool calls 和 results。
- 旧的不带 batch 的 tool call 不会立刻崩溃。

Phase 3C 完成时：

- JSON control section 完成后前端能看到 Preparing。
- 单个 tool 的 payload 完整后，只要所在 batch active，就能进入 Running。
- batch 顺序不被 payload 输出顺序破坏。
- 已 eager 执行的结果在 parse failure 下仍作为事实保留。
