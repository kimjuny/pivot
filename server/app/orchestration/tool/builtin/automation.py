"""Built-in tool for creating or proposing automations."""

from __future__ import annotations

from typing import Annotated

from app.orchestration.tool import Param, tool


@tool(
    description=(
        "Create or propose a new scheduled automation for the user. "
        "When skip_confirm is False (default), a pre-filled creation dialog is shown "
        "for the user to review. When skip_confirm is True, the automation is created "
        "directly without a dialog — use this in channel/messaging conversations where "
        "no UI dialog is available. Always confirm with the user via a clarify message "
        "before using skip_confirm=True."
    ),
)
def automation(
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
            "'30 8 * * *' (daily at 8:30), '0 10 1 * *' (monthly on the 1st). "
            "Times are interpreted in the system-configured timezone."
        ),
    ],
    skip_confirm: Annotated[
        bool,
        Param(
            "When True, create the automation directly without UI confirmation. "
            "Use in channel conversations after confirming with the user. "
            "When False (default), show a dialog for user review."
        ),
    ] = False,
) -> dict[str, object]:
    """Create or propose an automation.

    When ``skip_confirm=False`` (default), returns a ``pivot_action`` envelope
    that triggers a pre-filled creation dialog on the frontend.  The automation
    is only created when the user confirms through the UI.

    When ``skip_confirm=True``, creates the automation directly via the
    ``AutomationService``.  This is intended for Channel conversations where
    no UI dialog is available.  The session strategy is automatically set to
    ``"this_session"`` and bound to the current ChannelSession.

    Args:
        name: Short human-readable name.
        prompt_template: Message template with optional ``{{variables}}``.
        schedule: Five-field cron expression (system timezone).
        skip_confirm: If True, create directly without dialog.

    Returns:
        A dict containing the automation data and a ``pivot_action`` envelope.
    """
    if skip_confirm:
        return _create_directly(name, prompt_template, schedule)
    return _propose_via_dialog(name, prompt_template, schedule)


def _create_directly(
    name: str,
    prompt_template: str,
    schedule: str,
) -> dict[str, object]:
    """Create the automation directly (Channel flow)."""
    import json

    from app.db.session import managed_session
    from app.orchestration.tool.manager import get_current_tool_execution_context

    ctx = get_current_tool_execution_context()
    if ctx is None or ctx.session_id is None:
        return {
            "error": "Cannot create automation: no session context available.",
            "pivot_action": {
                "type": "automation_error",
                "category": "notify",
                "payload": {"error": "No session context available"},
            },
        }

    # Resolve ChannelSession from the current pivot session.
    channel_session_id: int | None = None
    agent_id: int | None = None
    with managed_session() as db:
        from app.models.channel import ChannelSession
        from sqlmodel import select

        cs = db.exec(
            select(ChannelSession).where(
                ChannelSession.pivot_session_id == ctx.session_id
            )
        ).first()
        if cs is not None:
            channel_session_id = cs.id

            from app.models.channel import AgentChannelBinding

            binding = db.get(AgentChannelBinding, cs.channel_binding_id)
            if binding is not None:
                agent_id = binding.agent_id

    if channel_session_id is None or agent_id is None:
        return {
            "error": "Not in a channel conversation — cannot auto-create automation.",
            "pivot_action": {
                "type": "automation_error",
                "category": "notify",
                "payload": {"error": "Not in a channel conversation"},
            },
        }

    trigger_config = json.dumps({"cron": schedule})

    with managed_session() as db:
        from app.services.automation_service import AutomationService

        svc = AutomationService(db)
        auto = svc.create_automation(
            owner_id=ctx.user_id,
            agent_id=agent_id,
            name=name,
            prompt_template=prompt_template,
            trigger_config=trigger_config,
            session_strategy="this_session",
            channel_session_id=channel_session_id,
        )

    return {
        "name": name,
        "prompt_template": prompt_template,
        "schedule": schedule,
        "session_strategy": "this_session",
        "automation_id": auto.automation_id,
        "status": auto.status,
        "message": f"Automation '{name}' created successfully.",
        "pivot_action": {
            "type": "automation_created",
            "category": "notify",
            "payload": {
                "automation_id": auto.automation_id,
                "name": name,
                "status": auto.status,
            },
        },
    }


def _propose_via_dialog(
    name: str,
    prompt_template: str,
    schedule: str,
) -> dict[str, object]:
    """Return a pivot_action to open the creation dialog (Web UI flow)."""
    return {
        "name": name,
        "prompt_template": prompt_template,
        "schedule": schedule,
        "session_strategy": "reuse",
        "pivot_action": {
            "type": "propose_automation",
            "category": "notify",
            "payload": {
                "name": name,
                "prompt_template": prompt_template,
                "cron": schedule,
                "session_strategy": "reuse",
            },
        },
    }
