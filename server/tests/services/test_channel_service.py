"""Tests for channel bindings and external identity linking."""

import asyncio
import sys
import unittest
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlmodel import Session, SQLModel, create_engine

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
SessionMemoryService = import_module(
    "app.services.session_memory_service"
).SessionMemoryService


class ChannelServiceTestCase(unittest.TestCase):
    """Validate binding creation and external identity link completion."""

    def setUp(self) -> None:
        """Create an isolated in-memory database for each test."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.service = channel_service_module.ChannelService(self.session)

        self.user = User(username="alice", password_hash="hash")
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

        session_service = SessionMemoryService(self.session)
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

        class FakeReactEngine:
            """Minimal async engine stub for channel progress tests."""

            def __init__(self, **kwargs: object) -> None:
                del kwargs

            async def run_task(
                self,
                **kwargs: object,
            ) -> AsyncIterator[dict[str, object]]:
                del kwargs
                yield {
                    "type": "summary",
                    "task_id": "task-1",
                    "iteration": 1,
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
                }
                yield {
                    "type": "answer",
                    "task_id": "task-1",
                    "iteration": 1,
                    "data": {"answer": "Done processing."},
                }

        with (
            patch.object(
                channel_service_module.llm_crud,
                "get",
                return_value=SimpleNamespace(streaming=False),
            ),
            patch.object(
                channel_service_module,
                "create_llm_from_config",
                return_value=object(),
            ),
            patch.object(
                self.service,
                "_build_request_tool_manager",
                return_value=MagicMock(),
            ),
            patch.object(
                self.service,
                "_resolve_skills_text",
                new=AsyncMock(return_value=""),
            ),
            patch.object(
                channel_service_module,
                "list_visible_skills",
                return_value=[],
            ),
            patch.object(
                channel_service_module,
                "build_skill_mounts",
                return_value=[],
            ),
            patch.object(
                channel_service_module,
                "ReactEngine",
                FakeReactEngine,
            ),
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

        self.assertEqual([action.kind for action in actions], ["progress", "answer"])
        self.assertIn("Inspect the linked files", actions[0].text)
        self.assertIn("Reading the linked files", actions[0].text)
        self.assertIsNotNone(actions[0].progress_view)
        self.assertEqual(actions[1].text, "Done processing.")
        self.assertTrue(actions[1].is_terminal)

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
