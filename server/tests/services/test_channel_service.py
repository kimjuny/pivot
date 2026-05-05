"""Tests for channel bindings and external identity linking."""

import asyncio
import sys
import unittest
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlmodel import Session, SQLModel, create_engine, select

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")

Agent = import_module("app.models.agent").Agent
User = import_module("app.models.user").User
ChannelInboundEvent = import_module("app.channels.types").ChannelInboundEvent
ChannelOutboundAction = import_module("app.channels.types").ChannelOutboundAction
ChannelPlanStepProgressView = import_module(
    "app.channels.types"
).ChannelPlanStepProgressView
ChannelProgressView = import_module("app.channels.types").ChannelProgressView
channel_service_module = import_module("app.services.channel_service")
ExternalIdentityBinding = import_module("app.models.channel").ExternalIdentityBinding
ChannelSession = import_module("app.models.channel").ChannelSession
SessionService = import_module("app.services.session_service").SessionService


class ChannelServiceTestCase(unittest.TestCase):
    """Validate binding creation and external identity link completion."""

    def setUp(self) -> None:
        """Create an isolated in-memory database for each test."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.service = channel_service_module.ChannelService(self.session)

        self.user = User(username="alice", password_hash="hash", role_id=1)
        self.agent = Agent(name="support-bot", is_active=True, max_iteration=5)
        self.session.add(self.user)
        self.session.add(self.agent)
        self.session.commit()
        self.session.refresh(self.user)
        self.session.refresh(self.agent)

    def tearDown(self) -> None:
        """Close the database session after each test."""
        self.session.close()

    def test_create_binding_and_complete_link_token(self) -> None:
        """External identities should be linkable through a short-lived token."""
        binding = self.service.create_binding(
            agent_id=self.agent.id or 0,
            channel_key="telegram",
            name="Telegram Support",
            enabled=True,
            auth_config={"bot_token": "123:abc"},
            runtime_config={"poll_timeout_seconds": 15},
        )

        self.assertEqual(binding.channel_key, "telegram")
        self.assertEqual(binding.name, "Telegram Support")
        self.assertEqual(binding.auth_config["bot_token"], "123:abc")

        token_payload = self.service.create_link_token(
            binding=self.session.get(
                import_module("app.models.channel").AgentChannelBinding,
                binding.id,
            ),
            provider_key="telegram",
            external_user_id="tg-42",
            external_conversation_id="chat-42",
        )

        self.assertIn("/channel-link/", token_payload.link_url)

        result = self.service.complete_link_token(token_payload.token, self.user)
        self.assertEqual(result.status, "linked")
        self.assertEqual(result.workspace_owner, "alice")

    def test_draft_connection_check_does_not_persist_a_binding(self) -> None:
        """Credential testing should work before saving a binding row."""
        result = self.service.test_binding_draft(
            channel_key="dingtalk",
            auth_config={
                "client_id": "client-id",
                "client_secret": "client-secret",
            },
            runtime_config={},
        )

        self.assertTrue(result["result"]["ok"])
        binding_rows = self.session.exec(
            select(import_module("app.models.channel").AgentChannelBinding)
        ).all()
        self.assertEqual(binding_rows, [])

    def test_unlinked_enter_event_returns_link_prompt(self) -> None:
        """Non-text entry events should still trigger the web linking flow."""
        binding = self.service.create_binding(
            agent_id=self.agent.id or 0,
            channel_key="work_wechat",
            name="Work WeChat Support",
            enabled=True,
            auth_config={
                "bot_id": "bot-123",
                "secret": "secret",
            },
            runtime_config={},
        )

        binding_row = self.session.get(
            import_module("app.models.channel").AgentChannelBinding,
            binding.id,
        )
        if binding_row is None:
            self.fail("Expected binding row to exist")

        reply = self.service._get_identity_binding(  # type: ignore[attr-defined]
            channel_binding_id=binding.id,
            external_user_id="user-a",
        )
        self.assertIsNone(reply)

        prompt = self.session.get(
            import_module("app.models.channel").AgentChannelBinding,
            binding.id,
        )
        if prompt is None:
            self.fail("Expected binding row to exist")

        result = self.service.create_link_token(
            binding=prompt,
            provider_key="work_wechat",
            external_user_id="user-a",
            external_conversation_id="user-a",
        )
        self.assertIn("/channel-link/", result.link_url)

    def test_route_unlinked_event_without_text_generates_link_reply(self) -> None:
        """Route logic should return a link prompt even when the event has no text."""
        binding = self.service.create_binding(
            agent_id=self.agent.id or 0,
            channel_key="work_wechat",
            name="Work WeChat Support",
            enabled=True,
            auth_config={
                "bot_id": "bot-123",
                "secret": "secret",
            },
            runtime_config={},
        )
        binding_row = self.session.get(
            import_module("app.models.channel").AgentChannelBinding,
            binding.id,
        )
        if binding_row is None:
            self.fail("Expected binding row to exist")

        reply = asyncio.run(
            self.service.route_inbound_event(
                binding=binding_row,
                event=ChannelInboundEvent(
                    external_event_id="evt-1",
                    external_user_id="user-a",
                    external_conversation_id="user-a",
                    message_type="event",
                    event_type="enter_chat",
                ),
            )
        )
        self.assertIsNotNone(reply)
        self.assertIn("Link your Pivot account", str(reply))

    def test_route_attachment_only_event_uses_fallback_text(self) -> None:
        """Attachment-only Work WeChat turns should still enter the ReAct flow."""
        binding = self.service.create_binding(
            agent_id=self.agent.id or 0,
            channel_key="work_wechat",
            name="Work WeChat Support",
            enabled=True,
            auth_config={
                "bot_id": "bot-123",
                "secret": "secret",
            },
            runtime_config={},
        )
        identity = ExternalIdentityBinding(
            channel_binding_id=binding.id,
            provider_key="work_wechat",
            external_user_id="user-a",
            external_conversation_id="user-a",
            pivot_user_id=self.user.id or 0,
            workspace_owner=self.user.username,
            status="linked",
            auth_method="link_page",
        )
        self.session.add(identity)
        self.session.commit()

        binding_row = self.session.get(
            import_module("app.models.channel").AgentChannelBinding,
            binding.id,
        )
        if binding_row is None:
            self.fail("Expected binding row to exist")

        captured_kwargs: dict[str, object] = {}

        async def fake_run_agent_turn(**kwargs: object):
            captured_kwargs.update(kwargs)
            yield ChannelOutboundAction(
                kind="answer",
                text="ok",
                delivery_hint="stream",
                is_terminal=True,
            )

        with (
            patch.object(
                self.service,
                "_prepare_channel_attachments",
                new=AsyncMock(return_value=["file-1"]),
            ),
            patch.object(
                self.service,
                "_run_agent_turn",
                new=fake_run_agent_turn,
            ),
        ):
            reply = asyncio.run(
                self.service.route_inbound_event(
                    binding=binding_row,
                    event=ChannelInboundEvent(
                        external_event_id="evt-2",
                        external_user_id="user-a",
                        external_conversation_id="user-a",
                        message_type="image",
                        attachments=[
                            {
                                "provider": "work_wechat",
                                "message_type": "image",
                                "url": "https://example.com/image",
                                "aes_key": "YWJj",
                            }
                        ],
                    ),
                )
            )

        self.assertEqual(reply, "ok")
        self.assertEqual(
            captured_kwargs["message"],
            "The user sent 1 attachment through the channel.",
        )
        self.assertEqual(captured_kwargs["channel_file_ids"], ["file-1"])

    def test_idle_channel_session_starts_a_new_pivot_session(self) -> None:
        """Idle channel conversations should reopen in a fresh Pivot session."""
        binding = self.service.create_binding(
            agent_id=self.agent.id or 0,
            channel_key="telegram",
            name="Telegram Support",
            enabled=True,
            auth_config={"bot_token": "123:abc"},
            runtime_config={"poll_timeout_seconds": 15},
        )
        identity = ExternalIdentityBinding(
            channel_binding_id=binding.id,
            provider_key="telegram",
            external_user_id="tg-user",
            external_conversation_id="tg-chat",
            pivot_user_id=self.user.id or 0,
            workspace_owner=self.user.username,
            status="linked",
            auth_method="link_page",
        )
        self.session.add(identity)
        self.session.commit()
        self.session.refresh(identity)

        session_service = SessionService(self.session)
        original_session = session_service.create_session(
            agent_id=self.agent.id or 0,
            user=self.user.username,
        )
        original_session.updated_at = datetime.now(UTC) - timedelta(minutes=16)
        self.session.add(original_session)
        self.session.commit()
        self.session.refresh(original_session)

        channel_session = ChannelSession(
            channel_binding_id=binding.id,
            external_conversation_id="tg-chat",
            external_user_id="tg-user",
            pivot_user_id=self.user.id or 0,
            pivot_session_id=original_session.session_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.session.add(channel_session)
        self.session.commit()

        binding_row = self.session.get(
            import_module("app.models.channel").AgentChannelBinding,
            binding.id,
        )
        if binding_row is None:
            self.fail("Expected binding row to exist")

        resolved_session = self.service._get_or_create_channel_session(
            binding=binding_row,
            identity=identity,
            external_conversation_id="tg-chat",
        )

        self.assertNotEqual(
            resolved_session.pivot_session_id,
            original_session.session_id,
        )
        self.assertIsNotNone(
            session_service.get_session(resolved_session.pivot_session_id)
        )

    def test_collect_outbound_actions_includes_summary_progress(self) -> None:
        """ReAct summaries should surface as structured channel progress actions."""
        self.agent.llm_id = 42
        self.session.add(self.agent)
        self.session.commit()

        binding = self.service.create_binding(
            agent_id=self.agent.id or 0,
            channel_key="work_wechat",
            name="Work WeChat Support",
            enabled=True,
            auth_config={
                "bot_id": "bot-123",
                "secret": "secret",
            },
            runtime_config={},
        )
        identity = ExternalIdentityBinding(
            channel_binding_id=binding.id,
            provider_key="work_wechat",
            external_user_id="user-a",
            external_conversation_id="user-a",
            pivot_user_id=self.user.id or 0,
            workspace_owner=self.user.username,
            status="linked",
            auth_method="link_page",
        )
        self.session.add(identity)
        self.session.commit()

        binding_row = self.session.get(
            import_module("app.models.channel").AgentChannelBinding,
            binding.id,
        )
        if binding_row is None:
            self.fail("Expected binding row to exist")

        task_events = [
            {
                "event_id": 1,
                "type": "summary",
                "task_id": "task-1",
                "iteration": 1,
                "timestamp": datetime.now(UTC).isoformat(),
                "delta": "Reading the linked files",
                "data": {
                    "current_plan": [
                        {
                            "step_id": "1",
                            "general_goal": "Inspect the linked files",
                            "specific_description": "",
                            "completion_criteria": "",
                            "status": "running",
                            "recursion_history": [
                                {
                                    "iteration": 1,
                                    "summary": "Reading the linked files",
                                }
                            ],
                        }
                    ]
                },
            },
            {
                "event_id": 2,
                "type": "answer",
                "task_id": "task-1",
                "iteration": 1,
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {"answer": "Done processing."},
            },
            {
                "event_id": 3,
                "type": "task_complete",
                "task_id": "task-1",
                "iteration": 1,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        ]

        class FakeSupervisor:
            """Minimal task supervisor stub for channel progress tests."""

            async def start_task(self, launch: object) -> SimpleNamespace:
                del launch
                return SimpleNamespace(
                    task_id="task-1",
                    session_id="pivot-session",
                    status="running",
                    cursor_before_start=0,
                )

            def list_events(
                self,
                *,
                session_id: str,
                after_id: int = 0,
                task_id: str | None = None,
            ) -> list[dict[str, object]]:
                del session_id, after_id, task_id
                return task_events

            async def subscribe(self, **kwargs: object) -> object:
                del kwargs
                raise AssertionError("subscribe should not be reached in this test")

            async def unsubscribe(self, **kwargs: object) -> None:
                del kwargs

        with patch.object(
            channel_service_module,
            "get_react_task_supervisor",
            return_value=FakeSupervisor(),
        ):
            actions = asyncio.run(
                self.service.collect_outbound_actions(
                    binding=binding_row,
                    event=ChannelInboundEvent(
                        external_event_id="evt-3",
                        external_user_id="user-a",
                        external_conversation_id="user-a",
                        message_type="text",
                        text="Please continue",
                    ),
                )
            )

        self.assertEqual(
            [action.kind for action in actions],
            ["progress", "progress", "answer"],
        )
        self.assertEqual(actions[0].text, "Received, starting the task...")
        self.assertIn("Inspect the linked files", actions[1].text)
        self.assertIn("Reading the linked files", actions[1].text)
        self.assertIsNotNone(actions[1].progress_view)
        self.assertEqual(actions[2].text, "Done processing.")
        self.assertTrue(actions[2].is_terminal)

    def test_collect_outbound_actions_emit_ack_then_summary_progress(self) -> None:
        """Channel turns should acknowledge receipt before normal progress events."""
        self.agent.llm_id = 42
        self.session.add(self.agent)
        self.session.commit()

        binding = self.service.create_binding(
            agent_id=self.agent.id or 0,
            channel_key="work_wechat",
            name="Work WeChat Support",
            enabled=True,
            auth_config={
                "bot_id": "bot-123",
                "secret": "secret",
            },
            runtime_config={},
        )
        identity = ExternalIdentityBinding(
            channel_binding_id=binding.id,
            provider_key="work_wechat",
            external_user_id="user-a",
            external_conversation_id="user-a",
            pivot_user_id=self.user.id or 0,
            workspace_owner=self.user.username,
            status="linked",
            auth_method="link_page",
        )
        self.session.add(identity)
        self.session.commit()

        binding_row = self.session.get(
            import_module("app.models.channel").AgentChannelBinding,
            binding.id,
        )
        if binding_row is None:
            self.fail("Expected binding row to exist")

        task_events = [
            {
                "event_id": 1,
                "type": "summary",
                "task_id": "task-1",
                "iteration": 1,
                "timestamp": datetime.now(UTC).isoformat(),
                "delta": "Drafting the first implementation plan",
                "data": {"current_plan": []},
            },
            {
                "event_id": 2,
                "type": "answer",
                "task_id": "task-1",
                "iteration": 1,
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {"answer": "All set."},
            },
            {
                "event_id": 3,
                "type": "task_complete",
                "task_id": "task-1",
                "iteration": 1,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        ]

        class FakeSupervisor:
            """Minimal task supervisor stub for channel event-order tests."""

            async def start_task(self, launch: object) -> SimpleNamespace:
                del launch
                return SimpleNamespace(
                    task_id="task-1",
                    session_id="pivot-session",
                    status="running",
                    cursor_before_start=0,
                )

            def list_events(
                self,
                *,
                session_id: str,
                after_id: int = 0,
                task_id: str | None = None,
            ) -> list[dict[str, object]]:
                del session_id, after_id, task_id
                return task_events

            async def subscribe(self, **kwargs: object) -> object:
                del kwargs
                raise AssertionError("subscribe should not be reached in this test")

            async def unsubscribe(self, **kwargs: object) -> None:
                del kwargs

        with patch.object(
            channel_service_module,
            "get_react_task_supervisor",
            return_value=FakeSupervisor(),
        ):
            actions = asyncio.run(
                self.service.collect_outbound_actions(
                    binding=binding_row,
                    event=ChannelInboundEvent(
                        external_event_id="evt-4",
                        external_user_id="user-a",
                        external_conversation_id="user-a",
                        message_type="text",
                        text="Please handle this request",
                    ),
                )
            )

        self.assertEqual(
            [action.text for action in actions],
            [
                "Received, starting the task...",
                "Drafting the first implementation plan",
                "All set.",
            ],
        )
        self.assertEqual(
            [action.kind for action in actions],
            ["progress", "progress", "answer"],
        )
        self.assertTrue(actions[-1].is_terminal)

    def test_render_channel_progress_view_uses_uniform_step_layout(self) -> None:
        """Plan projections should avoid mixed bullet formatting across channels."""
        progress_view = ChannelProgressView(
            mode="plan",
            summary="Using the design skill to prepare the design system",
            steps=[
                ChannelPlanStepProgressView(
                    step_id="1",
                    general_goal="Generate the Luckin Coffee design system",
                    status="running",
                    summaries=[
                        "Search the coffee retail design references and gather palette guidance."
                    ],
                ),
                ChannelPlanStepProgressView(
                    step_id="2",
                    general_goal="Create the project folder and initialize the structure",
                    status="pending",
                ),
                ChannelPlanStepProgressView(
                    step_id="3",
                    general_goal="Build the landing page HTML",
                    status="done",
                ),
            ],
        )

        rendered = self.service._render_channel_progress_view(
            progress_view=progress_view
        )

        self.assertEqual(
            rendered,
            "\n".join(
                [
                    "Using the design skill to prepare the design system",
                    "",
                    "[Running] Generate the Luckin Coffee design system",
                    "Progress: Search the coffee retail design references and gather palette guidance.",
                    "",
                    "[Pending] Create the project folder and initialize the structure",
                    "",
                    "[Done] Build the landing page HTML",
                ]
            ),
        )


if __name__ == "__main__":
    unittest.main()
