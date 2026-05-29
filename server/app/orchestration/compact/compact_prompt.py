"""Prompt template helpers for session context compaction."""

from typing import Literal

CompactPromptMode = Literal["session", "in_task"]

_COMPACT_PROMPT_PREFIX = """Compress the provided messages into a single compact JSON.

Your task is not to retell the conversation, but to distill the messages into a concise, stable, structured memory that can be iterated upon.
"""

_SESSION_COMPACT_REQUIREMENTS = """Requirements:

1. Process the ENTIRE session, not just the most recent messages.
2. If the history already contains a prior compact result (a structured JSON that looks like compact memory), treat it as "old compressed memory" rather than regular conversation content.
3. If an old compact exists, merge it with the remaining conversation messages — deduplicate and resolve conflicts — into one new complete compact JSON.
4. Do NOT nest the old compact verbatim inside the new result.
5. Do NOT treat the compact instruction text itself as session facts.
6. When information conflicts, prefer newer, more explicit, user-expressed information.
7. `current_state` must only contain currently valid information. Drop superseded, cancelled, or invalidated entries.
8. `task_digest` summarizes at the TASK level. Each entry represents one complete task cycle: the user's original request through to the agent's final ANSWER. Do NOT create one entry per recursion/iteration within a task. For each task, briefly describe:
   - What the user asked or needed
   - What the agent ultimately delivered in its ANSWER
   - Any artifacts produced (files, schemas, code, documents, etc.)
9. `change_log` records only notable changes, not low-value back-and-forth. Focus on: preference shifts, constraint changes, decision changes, important_files additions/replacements/deprecations, and key user corrections.
10. `important_files` lists only significant files, resources, or artifacts with a short description of their purpose. Do NOT fabricate paths, filenames, or file purposes.
11. `history_summary` provides a high-density summary of the session's main discussions, key outputs, and evolution.
12. Use simple, stable, flat JSON structure.
13. All fields must be present. Use "" for empty strings and [] for empty arrays. Do not omit keys.
14. Output ONLY valid JSON — no markdown, no extra explanations, no code fences.

Note:
- Preserve the user's original language when extracting summaries; do NOT translate to another language.

Output must strictly follow this JSON schema:
```
{
  "current_state": {
    "user_profile": [{"key": "", "value": ""}],
    "preferences": [{"key": "", "value": ""}],
    "constraints": [{"key": "", "value": ""}],
    "decisions": [""]
  },
  "task_digest": [
    {
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
  "important_files": [
    {
      "path": "",
      "description": ""
    }
  ],
  "history_summary": ""
}
```
"""

_IN_TASK_COMPACT_REQUIREMENTS = """Requirements:

1. Process the ENTIRE in-flight task context provided to you.
2. The task is not complete yet. Preserve enough state for the agent to continue from the next step without repeating finished work.
3. If the history already contains a prior compact result, treat it as old compressed memory and merge it with the newer task messages.
4. Do NOT nest an old compact result verbatim inside the new result.
5. Do NOT treat the compact instruction text itself as task facts.
6. When information conflicts, prefer newer, more explicit, user-expressed information.
7. `current_state` must only contain currently valid information. Drop superseded, cancelled, or invalidated entries.
8. `task_digest` may include an unfinished task entry. For unfinished work, describe what the user asked for and what has been produced so far.
9. `in_task_memory.purpose` must preserve the user's original request and success criteria in the user's original language.
10. `in_task_memory.progress` must summarize what the agent already did before compaction, including important decisions and artifacts.
11. `in_task_memory.next_steps` must list concrete next actions the agent should take after compaction.
12. `in_task_memory.open_questions` must list unresolved user questions, clarify requests, or missing inputs.
13. `in_task_memory.important_intermediate_results` must preserve important partial analysis, generated drafts, file paths, tool outputs, or constraints needed to continue.
14. `in_task_memory.do_not_repeat` must list completed work the agent should avoid redoing unless the user asks.
15. `important_files` lists only significant files, resources, or artifacts with a short description of their purpose. Do NOT fabricate paths, filenames, or file purposes.
16. Use simple, stable JSON structure.
17. All fields must be present. Use "" for empty strings and [] for empty arrays. Do not omit keys.
18. Output ONLY valid JSON — no markdown, no extra explanations, no code fences.

Note:
- Preserve the user's original language when extracting summaries; do NOT translate to another language.

Output must strictly follow this JSON schema:
```
{
  "current_state": {
    "user_profile": [{"key": "", "value": ""}],
    "preferences": [{"key": "", "value": ""}],
    "constraints": [{"key": "", "value": ""}],
    "decisions": [""]
  },
  "task_digest": [
    {
      "user": "",
      "assistant": "",
      "artifacts": [""]
    }
  ],
  "in_task_memory": {
    "purpose": "",
    "progress": "",
    "next_steps": [""],
    "open_questions": [""],
    "important_intermediate_results": [""],
    "do_not_repeat": [""]
  },
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
  "important_files": [
    {
      "path": "",
      "description": ""
    }
  ],
  "history_summary": ""
}
```
"""


def build_compact_prompt(
    user_instruction: str | None = None,
    *,
    mode: CompactPromptMode = "session",
) -> str:
    """Build the compaction prompt with optional one-off user guidance."""
    instruction = (user_instruction or "").strip()
    requirements = (
        _IN_TASK_COMPACT_REQUIREMENTS
        if mode == "in_task"
        else _SESSION_COMPACT_REQUIREMENTS
    )
    if not instruction:
        return f"{_COMPACT_PROMPT_PREFIX}\n{requirements}"

    manual_requirements = f"""Additional user requirements for this compact only. These have high priority — follow them explicitly:

<user_compact_requirements>
{instruction}
</user_compact_requirements>

When processing these extra requirements:
- If they conflict with the output JSON schema, the schema takes precedence.
- If they conflict with higher-priority system or safety requirements, the higher priority wins.
- Do NOT write the extra-requirements text verbatim into the compact result unless it describes actual session facts.
"""
    return f"{_COMPACT_PROMPT_PREFIX}\n" f"{manual_requirements}\n" f"{requirements}"


COMPACT_PROMPT = build_compact_prompt()
