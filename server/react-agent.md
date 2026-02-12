## 总览
我们要实现的是一套递归智能体ReAct机制：用户输入需求，智能体基于手中现有的tools / functions，通过递归，自行去plan到执行，甚至可以自行纠错，直到任务完成。

## ReAct机制状态机
```mermaid
stateDiagram-v2
%% Recursive Agent ReAct Diagram
%% 递归智能体ReAct状态机
state RESULT_TYPE <<choice>>

[*] --> INIT
INIT --> RECURSION
RECURSION --> RESULT_TYPE

RESULT_TYPE --> [*]: if result_type == answer or result_type == error(比如reach max iteration)
RESULT_TYPE --> RECURSION: if result_type != answer

state RECURSION {
  state REACH_MAX_ITERATION <<choice>>

  [*] --> INPUT : 整理输入
  note right of INPUT
    duty: 将上一轮结果(如果有)拼接到context中,并为本轮recursion生成唯一trace_id用于后续追踪
    input: {
      "result": "上一轮recursion运行成功的结果",
      "error_log": "上一轮recursion运行失败的输出",
      "context": "prompt上下文"
    }
    output: {
      "trace_id": "生成全局唯一的uuid,用于代表本轮唯一recursion",
      "context": "即把上一轮的error_log 或 result拼接整合到context后的最新context"
    }
  end note

  INPUT --> REACH_MAX_ITERATION

  REACH_MAX_ITERATION --> [*]: if iteration_times > MAX_ITERATION_TIMES
  REACH_MAX_ITERATION --> CALL_LLM: if iteration_times <= MAX_ITERATION_TIMES

  note right of CALL_LLM
    duty: 调用大模型,让大模型在本轮recursion中执行一次,分别让LLM输出执行观察(observe)结果、思考(thought)结果、行动(action)结果
    input: {
      "trace_id": "",
      "context": "最新context",
      "tools": "智能体所有这一轮可调用tools的specification",
      "model": "传入要调用的model",
      "stream": "是否流式返回"
    }
    output: {
      "observe": "[我观察到上一轮的result或error_log怎样怎样 / 我观察到这是第一轮执行]",
      "thought": "[我分析XX,综合以上我决定接下来XX]",
      "action": {
        "result": {
          "action_type": "CALL_TOOL / PLAN / REMEND / ANSWER",
          "output": {
            ...
          }
        }
      }
    }
  end note
  
  state CALL_LLM {
    state ACTION_TYPE <<choice>>

    [*] --> OBSERVE(LLM)
    OBSERVE(LLM) --> THOUGHT(LLM) : "[我观察到上一轮的result或error_log怎样怎样 / 我观察到这是第一轮执行]"
    THOUGHT(LLM) --> ACTION_TYPE : "[我分析出XX、XX、XX,综合以上我决定接下来采取action_type = XX的action,并且XXX]"
    
    ACTION_TYPE --> CALL_TOOL: if action_type == CALL_TOOL
    note left of CALL_TOOL
      duty: 如果是action_type == CALL_TOOL,那么LLM应当返回了tool_calls(包含了tool_call.function.name和tool_call.function.arguments),依次调用functions
      input: {
        "tool_calls": [{
          "function": {
            "name": "take_memo / search / calculate ...",
            "arguments": "arguments"
          }
        }]
      }
      output: [{
        "function": {
          "name": "function name",
          "arguments": "arguments",
          "result": {
            "success": "如果调用成功,就应当有success结果",
            "error": "如果有异常,就应当返回error异常栈,便于下一轮REMEND"
          }
        }
      }]
    end note

    ACTION_TYPE --> RE_PLAN(LLM): if action_type == PLAN
    note left of RE_PLAN(LLM)
      duty: 
      (plan)基于observe和thought,对任务进行一次plan. plan最终会在下一轮的recursion中的INPUT环节,被植入到context的plan章节中,用于指导后续整个任务流程的执行
      (replan)当然,如果有error_log,给出修复过的plan.下一轮recursion的llm应当能看懂上下文和断点,继续执行.
      output: {
        "plan": "1. XXXXX.\n2. XXXXX.\n3. XXXXX.\n",
        ...其他断点信息(如果有)
      }
    end note

    ACTION_TYPE --> ANSWER(LLM): if action_type == ANSWER
    note left of ANSWER(LLM)
      duty: 基于上面的observe、thought,执行完成或达到可输出结论的地步,那么可直接给出answer.
      output: {
        "answer": "最终结论"
      }
    end note

    CALL_TOOL --> [*]
    RE_PLAN(LLM) --> [*]
    ANSWER(LLM) --> [*]
  }
}
```

## 系统特性要求

- recursion要有可回溯性（有task_id、step_id、trace_id），前端到时候有地方可以读取一个基于task_id的完整回溯查询能力，甚至有机遇agent_id的每轮task_id（其实每轮task可能就是一轮对话）的查询能力。
- 不用去管旧的preview chat接口，重新写个新的chat stream接口，应当实时向前端暴露出plan了什么、recursion在执行什么、plan的step消灭了哪些等实时必要信息。
- agent的定义应当增加max_iteration字段配置，默认值是30。agent已经定义了大模型选型，那么面向这个agent去chat的时候整个ReAct状态机（包括recursion）都应当用这个大模型作为执行底座。
- 切记为了避免message / context / prompt递归爆炸，所以应当是message[0]是role = user的用户原始输入需求，message[1]是role = system的system prompt（模板我已经提前写好了你可以读取进来），其中的`{{current_state}}`就是每轮recursion变化过后的实时状态快照，而message[2 - n]是role = assistant的ReAct每轮recursion返回的result（或error），这样就能避免随着recursion的递归增加整个messages重复出现大量system prompt导致信息爆炸。
