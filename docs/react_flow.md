## ReAct机制

以下为一种兼容目前所有主流LLM厂商缓存机制的messages结构。在task开始时构建，在task结束时清空。

**提前准备**
照常运行原来的skill寻找步骤，寻找合适的skill

**第一轮 recursion：**
【prepare】
- 说明0：如果是task的第一轮，准备tools_description、session_memory、skills等数据，同时准备一个task_id（uuid）；
- 说明1：查询基于task_id有没有持久化过的state信息，并准备注入到role = user的信息中；
- 说明2：更新iteration轮次；

【role = system】向LLM输入message
content = `system_prompt.md`中的内容（其中`{{tools_description}}`、`{{session_memory}}`、`{{skills}}`提前注入过）

【role = user】向LLM输入message
```json
content = {
    "trace_id": "uuid",
    "iteration": 1,
    "user_intent": "", // 用户在本一轮task启动时的原话
    "current_plan": [], // plan（如果有）
    "action_result": [] // tool执行结果（如果有）
}
```

【role = assitant】等待LLM返回结果
- 说明1：content = action_type中的一种（CALL_TOOL、CLARIFY、REFLECT、ANSWER、RE_PLAN等）固定JSON返回格式（如`system_prompt.md`中提前规定的那样）。我们假设这一轮LLM返回了action_type = RE_PLAN。
```json
content = {
    // ...
    "action_type": "RE_PLAN",
    "output": {
        "plan": [
            {
                "step_id": "1",
                "general_goal": "该步骤的整体目标",
                "specific_description": "详细的说明，例如预计要用什么tools什么样的参数",
                "completion_criteria": "该步骤完成的验收标准或标志性事件",
                "status": "pending"
            }
        ]
    },
    // ...
}
```

【execute & conclude】
- 说明0：execute指，如果assistant要求执行tool，那么首先要开始在沙箱中执行tool
- 说明1：conclude指，execute结束后针对本轮recursion的数据收尾工作。
- 说明2：背后的程序需要维护最新state：最新iteration轮次信息、当前最新的plan状态、tool执行结果
- 说明3：conclude工作包括但不限于
    - 收集LLM的返回结果；
    - 根据`action.step_status_update`信息更新最新的plan状态；
    - 持久化当前task的state，支持前端查询的同时为下一轮role = user准备好输入内容；
    - 持久化更新task的最新messages，便于下一次调用LLM时把历史messages都带上（且能精准集中LLM厂商的缓存）；
- 说明4：如果是action_type = ANSWER，那么收集好`session_subject`、`session_object`、`task_summary`、`session_memory_delta`等信息，修改好session-memory，并进行持久化，准备下一次task注入使用。ANSWER意味着给用户返回结果后，结束本轮task。

**第二轮 recursion：**
【prepare】
...

【role = user】
```json
content = {
    "trace_id": "uuid",
    "iteration": 2,
    "user_intent": "",
    "current_plan": [
        {
            "step_id": "1",
            "general_goal": "该步骤的整体目标",
            "specific_description": "详细的说明，例如预计要用什么tools什么样的参数",
            "completion_criteria": "该步骤完成的验收标准或标志性事件",
            "status": "pending"
        }
    ]
}
```

【role = assitant】
返回action_type中的一种固定JSON返回格式。假设这一轮LLM返回了action_type = CALL_TOOL(read_file, filename)。
```json
content = {
  // ...
  "action": {
    "action_type": "CALL_TOOL",
    "output": {
      "tool_calls": [
        {
          "id": "id of this call",
          "name": "read_file",
          "arguments": {
            "path": "file_path"
          }
        }
      ]
    }
  },
  // ...
}
```

【execute & conclude】
...

**第三轮 recursion：**
【prepare】
...

【role = user】
```json
content = {
    "trace_id": "uuid",
    "iteration": 3,
    "user_intent": "",
    "current_plan": [
        {
            "step_id": "1",
            "general_goal": "该步骤的整体目标",
            "specific_description": "详细的说明，例如预计要用什么tools什么样的参数",
            "completion_criteria": "该步骤完成的验收标准或标志性事件",
            "status": "pending"
        }
    ],
    "action_result": [ // 只有当上一轮是action_type = CALL_TOOL的时候，这里就应当返回出来
        {
            "id": "id of this call",
            "result": "xxxxxx",
            "error": "if any"
        }
    ]
}
```

【role = assistant】
```json
content = {
    // ...
}
```

【execute & conclude】
...

以此类推，直到action_type = ANSWER。
