### Session-Memory Schema | 语义、说明

```json
{
    "session_id": "session_id",
    "subject": {
        "content": "对于这段对话的主题 / 话题是什么?",
        "source": "user | agent",
        "confidence": 0.8
    },
    "object": {
        "content": "对于这段对话用户的目的究竟是什么?",
        "source": "user | agent",
        "confidence": 0.7
    },
    "status": "active | waiting_input | closed",
    "artifacts_metadata": {
        "workspace_root": "/dev",
        "sandbox_id": "podman-session-xxx"
    },
    "conversations": [
        {
            "task_index": 1,
            "task_id": "每一轮对话都是一个task_id(uuid)",
            "user_input": "用户在这一轮对话的输入信息",
            "angent_answer": "Agent在这一轮的最终answer",
            "status": "running | done | error",
            "error": "（选填）错误原因",
            "summary": {
                "content": "简要描述下你在整个多轮recursion完成的整个task过程中，你都有哪些发现、思考，最终怎样解决的问题，给用户呈现的最终回答都包含什么关键信息。这里不需要太冗长，而是在简洁凝练的前提下对后续的持续对话产生关键信息的参考作用。",
                "key_findings": ["...", "..."],
                "final_decisions": ["...", "..."]
            }
        }
    ],
    "session_memory": [
        {
            "type": "preference",       // 写入时机：1. 用户明确说，2. 多次行为一致
            "content": "用户在表达方式 / 输出形式 / 风格上的偏好，如用户偏好工程化、系统级、结构化的回答",
            "confidence": 0.8
        },
        {
            "type": "constraint",        // 写入时机：1. 用户明确声明，2. 任务依赖环境
            "content": "对任务执行形成硬限制，如方案必须基于 Python + FastAPI + React",
            "confidence": 0.8
        },
        {
            "type": "background",        // 写入时机：1. 用户声明，2. 多轮对话中逐渐显现
            "content": "关于用户 / 项目的长期背景信息，我们默认应该知道的事实，如用户正在构建一个 Agent Runtime 系统",
            "confidence": 0.7
        },
        {
            "type": "capability_assumption",        // 写入时机：1. 用户展现出能力
            "content": "关于用户能做什么 / 系统能做什么的假设，这类假设可有效减少CLARIFY次数，例如用户具备 Python / 后端工程能力",
            "confidence": 0.8
        },
        {
            "type": "decision",          // 写入时机：共同决策、Agent默认决策、或用户的提出
            "source": "user | joint | agent",
            "decision": "例如采用 Agent Runtime 视角来讨论问题",
            "rationale": "例如用户多次讨论状态机与调度机制",
            "confidence": 0.85,
            "reversible": true    // 是否可re-clarify
        }
    ],
    "created_at": "",
    "updated_at": ""
}
```