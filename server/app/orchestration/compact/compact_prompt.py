# ruff: noqa: RUF001
"""Prompt template for session context compaction."""

COMPACT_PROMPT = """请对当前整个 session 的 messages 做一次完整的 context compact，并只输出一个新的 compact JSON。

你的任务不是复述原始对话，而是把整个 session 压缩成一份简洁、稳定、可继续迭代使用的结构化记忆。

重要要求：

1. 你要处理的是“整个 session”，不是只处理最近几条消息。
2. 如果历史消息中已经存在旧的 compact 结果（例如看起来像 compact memory 的结构化 JSON），请把它当作“旧压缩记忆”处理，而不是普通对话内容。
3. 若存在旧 compact 结果，你需要将它与其他普通对话消息一起整合、去重、消除冲突，然后生成一个新的完整 compact JSON。
4. 不要把旧 compact 原样嵌套到新结果里。
5. 不要把历史上用于触发 compact 的指令文本本身当作 session 事实写入结果。
6. 若信息冲突，以更新、更明确、用户显式表达的信息为准。
7. current_state 中只保留当前仍然有效的信息；已经被替换、取消、推翻、失效的旧状态不要继续保留。
8. interaction_digest 需要覆盖整个 session 的所有对话轮次。每一轮都要简要描述：
   - 用户这一轮主要表达了什么需求或问题
   - Agent 最终给用户输出了什么结果
   - 如果这一轮产生了文件、prompt、schema、代码、文档或其他产物，在 artifacts 中简要列出
9. change_log 只记录关键变化，不记录低价值重复来回。重点保留：
   - preference 的变化
   - constraint 的变化
   - decision 的变化
   - important_files 的新增、替换、失效
   - 用户对 Agent 的关键纠正
10. important_files 只保留重要文件、资源或产物，并尽量说明它们的用途。不要编造 path、文件名或文件用途。
11. history_summary 要高密度概括整个 session 的主要讨论内容、关键产出和演进过程。
12. 输出必须尽量使用简单、稳定、扁平的 JSON 结构。
13. 所有字段都必须输出；字符串没有值时填 ""；数组没有内容时填 []；不要省略键。
14. 只输出合法 JSON，不要输出 markdown，不要输出任何额外解释，不要输出代码块围栏。

注意：
- !!! 要忠于messages中用户的原语言进行摘要抽取，请不要翻译成其他语言 !!!

输出格式必须严格为如下的JSON：
```
{
  "current_state": {
    "user_profile": [
      {
        "key": "",
        "value": ""
      }
    ],
    "preferences": [
      {
        "key": "",
        "value": ""
      }
    ],
    "constraints": [
      {
        "key": "",
        "value": ""
      }
    ],
    "decisions": [""]
  },
  "important_files": [
    {
      "name": "",
      "path": "",
      "abstract": "",
      "role": "input|output|intermediate|reference",
      "status": "active|superseded|deprecated|unknown"
    }
  ],
  "interaction_digest": [
    {
      "turn": 1,
      "user": "",
      "assistant": "",
      "artifacts": [""]
    }
  ],
  "change_log": [
    {
      "turn": 1,
      "type": "preference|constraint|decision|file|correction|other",
      "key": "",
      "from": "",
      "to": "",
      "reason": ""
    }
  ],
  "history_summary": "",
  "meta": {
    "merge_strategy": "full_session_recompact",
    "conflict_policy": "latest_user_instruction_wins"
  }
}
```
"""
