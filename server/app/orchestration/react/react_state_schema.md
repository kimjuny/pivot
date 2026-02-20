## 5. 动态状态机Schema | 语义、结构说明

### 5.1. 顶层结构

{
  "global": {},
  "current_recursion": {},
  "context": {},
  "recursion_history": []
}

### 5.2. global

{
  "task_id": "string (uuid)",
  "iteration": 0,
  "max_iteration": 10,
  "status": "pending | running | completed | failed | waiting_input",
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}

- iteration：已执行的 recursion 次数
- max_iteration：达到后系统将强制终止
- status：
  - pending: 尚未启动
  - running: 本任务生命周期正在活跃，这是让你决定去发出 CALL_TOOL 还是 ANSWER 结束自己的标志，请勿把 running 当作“系统命令你必须继续盲目执行”的意思，只有你给出 ANSWER 才能让其结束！
  - completed: 已结束
  - failed: 失败
  - waiting_input: 等待用户输入答复

### 5.3. current_recursion

{
  "trace_id": "string (uuid)",
  "iteration_index": 3,
  "status": "running | done | error",
}

### 5.4. context

{
  "objective": "string",
  "constraints": ["string", "..."],
  "plan": [
    {
      "step_id": "string",
      "description": "string",
      "status": "pending | running | done | error",
      "recursion_history": [] // 外围程序将在这里维护每一个与step相关联的recursion的完整快照
    }
  ],

  "memory": {
    "short_term": [{"trace_id": "uuid", "memory": "指定uuid的recursion中写入进来的短期记忆"}] // 短期记忆，当你在每一轮recursion中返回
  }
}

**关键语义（非常重要）：**
  plan.step 是 strategy / policy：
- 每个step可以相对抽象由多步recursion来完成
  recursion_history 是 execution history：
- 一个 step 可以对应多个 recursion，一旦你看到其中已经有成功的结果，你要主动推进，不要看到状态是 running 而原地绕圈。
  status 含义：
- pending：尚未开始
- running：正在被探索（再次强调：如果是 running，代表的是由你决定是不是要让其结束，它依赖于你进行 ANSWER / 推进到下一阶段，不要误解为被动执行状态！）
- done：目标已达成
- error：多次失败或被判定不可行

### 5.5. recursion_history

[{
  "trace_id": "上一轮recursion的trace_id",
  "observe": "你对当前状态机和输入的客观观察",
  "thought": "你的分析与决策理由",
  "action": {
    "action_type": "CALL_TOOL | RE_PLAN | REFLECT | ANSWER | CLARIFY",
    "output": {}
  }
}]

**IMPORTANT:**
- 【外围程序】如果这一轮调用了工具（action_type=CALL_TOOL），那么应当在recursion_history[n].action.output.tool_calls[n]下增加result（str）、success（bool）两个字段，然后把计算结果注入进去。
- 【外围程序】recursion_history中只存储没有plan的step认领的recursion（避免重复存储），如果一个recursion有指定属于哪个step_id，那么就应当存储到关联的step_id中而不是这里。