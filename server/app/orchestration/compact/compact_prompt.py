接下来，你的任务是把一段较长的历史 messages 压缩成“高保真摘要 + 结构化记忆”，供后续轮次继续使用。

请重点保留：
- 用户稳定信息与偏好
- 当前任务目标与子目标
- 明确约束、限制、禁止项
- 已确认决定与最终结论
- 尚未解决的问题
- 待执行事项和承诺
- 重要实体（人名、项目名、文件名、接口名、术语、链接、ID）
- 用户对助手的纠正
- 若遗忘会导致后续回答错误、重复询问、任务中断的信息

规则：
- 忠于原始消息，不要编造
- 若有冲突，以更新、更明确、最终确认的信息为准
- 区分已确认内容与未解决事项
- 输出尽量简洁，但不能遗漏关键上下文
- 只输出 JSON，不要输出 markdown，不要解释

触发时机：
- 可能在task的开始时，发现当前已达到触发阈值，触发本次compact策略
    - 针对这种情况，执行压缩过后将保留system_prompt → compact_prompt → role = user message，基于这样的初始数据启动task iteration
- 可能在task中间的iteration中，由于达到上下文窗口阈值，紧急启动compact
    - 针对这种情况，执行压缩过后将保留system_prompt → compact_prompt → role = user message → [这一轮task的中间messages拼接...]

注意：
- 要忠于messages中用户的原语言进行摘要抽取，请不要翻译成其他语言存储

输出格式：
{
  "summary": "字符串",
  "facts": {
    "user_profile": ["字符串"],
    "preferences": ["字符串"],
    "constraints": ["字符串"],
    "decisions": ["字符串"],
    "open_loops": ["字符串"],
    "todo": ["字符串"],
    "important_entities": ["字符串"],
    "warnings": ["字符串"]
  }
}