"""Built-in tool for proposing an automation to the user via the chat UI."""

from __future__ import annotations

from typing import Annotated

from app.orchestration.tool import Param, tool


@tool(
    description=(
        "Propose a new automation to the user. "
        "The system will show a pre-filled creation dialog so the user can review "
        "and confirm. Use this when the user asks to set up a recurring task or "
        "scheduled automation."
    ),
)
def propose_automation(
    name: Annotated[
        str,
        Param("Short human-readable name for the automation (e.g. 'Daily Report')."),
    ],
    prompt_template: Annotated[
        str,
        Param(
            "Message template sent to the agent each run. "
            "Supports {{date}}, {{time}}, {{datetime}}, {{weekday}} variables."
        ),
    ],
    schedule: Annotated[
        str,
        Param(
            "Cron expression for the schedule. "
            "Examples: '0 9 * * 1-5' (weekdays at 9), "
            "'30 8 * * *' (daily at 8:30), '0 10 1 * *' (monthly on the 1st)."
        ),
    ],
    description: Annotated[
        str,
        Param("Optional description of what this automation does."),
    ] = "",
    timezone: Annotated[
        str,
        Param("IANA timezone for the schedule (e.g. 'UTC', 'Asia/Shanghai')."),
    ] = "UTC",
    session_strategy: Annotated[
        str,
        Param(
            "'reuse' to keep one session across runs (agent remembers previous results), "
            "or 'isolate' for a fresh session each run."
        ),
    ] = "reuse",
) -> dict[str, object]:
    """Propose an automation that the user can review and confirm.

    The tool does **not** create the automation directly.  Instead it returns
    a ``pivot_action`` envelope that triggers a pre-filled creation dialog on
    the frontend.  The actual automation is only created when the user
    confirms through the UI.

    Args:
        name: Short human-readable name.
        prompt_template: Message template with optional ``{{variables}}``.
        schedule: Five-field cron expression.
        description: Optional description.
        timezone: IANA timezone string.
        session_strategy: ``"reuse"`` or ``"isolate"``.

    Returns:
        A dict containing the proposal data and a ``pivot_action`` envelope.
    """
    return {
        "name": name,
        "description": description,
        "prompt_template": prompt_template,
        "schedule": schedule,
        "timezone": timezone,
        "session_strategy": session_strategy,
        "pivot_action": {
            "type": "propose_automation",
            "category": "notify",
            "payload": {
                "name": name,
                "description": description,
                "prompt_template": prompt_template,
                "cron": schedule,
                "timezone": timezone,
                "session_strategy": session_strategy,
            },
        },
    }
