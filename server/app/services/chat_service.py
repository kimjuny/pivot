"""
Chat service module.

Provides business logic for agent chat operations, including
preview chat streaming directly with LLM.
"""

import logging
import re
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone

from app.llm_globals import get_default_llm, get_llm
from app.models.agent import Connection, Scene, Subscene
from app.schemas.schemas import (
    AgentDetailResponse,
    ConnectionResponse,
    SceneGraphResponse,
    StreamEvent,
    StreamEventType,
    SubsceneWithConnectionsResponse,
)

logger = logging.getLogger(__name__)


class ChatService:
    """
    Service class for chat operations.

    Handles agent streaming chat and response processing.
    """

    @staticmethod
    def build_scene_from_response(scene_resp: SceneGraphResponse) -> Scene:
        """Build a Scene with subscenes and connections from API response.

        Args:
            scene_resp: Scene response from API.

        Returns:
            Scene with subscenes and connections populated.
        """
        scene = Scene(
            name=scene_resp.name,
            description=scene_resp.description or "",
        )

        for sub_resp in scene_resp.subscenes:
            subscene = Subscene(
                name=sub_resp.name,
                type=sub_resp.type,
                state=sub_resp.state,
                mandatory=sub_resp.mandatory,
                objective=sub_resp.objective or "",
            )

            for conn_resp in sub_resp.connections:
                connection = Connection(
                    name=conn_resp.name,
                    condition=conn_resp.condition or "",
                    from_subscene=conn_resp.from_subscene,
                    to_subscene=conn_resp.to_subscene,
                )
                subscene.add_connection(connection)

            scene.subscenes.append(subscene)

        return scene

    @staticmethod
    def merge_graph_with_input(
        updated_scenes: list[Scene], input_agent_detail: AgentDetailResponse
    ) -> list[SceneGraphResponse]:
        """Merge updated scenes with input agent detail to preserve IDs.

        Takes scenes from LLM output and merges with original input
        to preserve database IDs and timestamps.

        Args:
            updated_scenes: List of Scene objects from LLM output.
            input_agent_detail: Original input agent detail with IDs.

        Returns:
            List of SceneGraphResponse with IDs and timestamps populated.
        """
        # Create lookup maps for input data
        input_scene_map = {s.name: s for s in input_agent_detail.scenes}
        input_subscene_map: dict[str, dict[str, SubsceneWithConnectionsResponse]] = {}
        input_connection_map: dict[str, dict[str, dict[str, ConnectionResponse]]] = {}

        for scene in input_agent_detail.scenes:
            input_subscene_map[scene.name] = {ss.name: ss for ss in scene.subscenes}
            input_connection_map[scene.name] = {}
            for ss in scene.subscenes:
                input_connection_map[scene.name][ss.name] = {}
                for conn in ss.connections:
                    conn_key = f"{conn.to_subscene}|{conn.name}"
                    input_connection_map[scene.name][ss.name][conn_key] = conn

        merged_scenes: list[SceneGraphResponse] = []
        current_time = datetime.now(timezone.utc)

        for scene in updated_scenes:
            input_scene = input_scene_map.get(scene.name)

            scene_id = input_scene.id if input_scene else f"new-{uuid.uuid4().hex[:8]}"
            created_at = input_scene.created_at if input_scene else current_time
            updated_at = current_time
            agent_id = input_scene.agent_id if input_scene else input_agent_detail.id

            merged_subscenes: list[SubsceneWithConnectionsResponse] = []

            # Safely access subscenes - Scene from LLM may not have SQLAlchemy instrumentation
            # Use __dict__ to bypass SQLAlchemy descriptors that trigger UnmappedInstanceError
            if hasattr(scene, "_sa_instance_state"):
                # This is a DB-backed Scene, safe to use normal attribute access
                subscenes_list = scene.subscenes
            else:
                # This is a runtime Scene from LLM, access __dict__ directly
                subscenes_list = scene.__dict__.get("subscenes", [])
            for subscene in subscenes_list:
                input_subscene = None
                if input_scene:
                    input_subscene = input_subscene_map.get(scene.name, {}).get(
                        subscene.name
                    )

                subscene_id = (
                    input_subscene.id
                    if input_subscene
                    else f"new-{uuid.uuid4().hex[:8]}"
                )
                sub_created_at = (
                    input_subscene.created_at if input_subscene else current_time
                )

                merged_connections: list[ConnectionResponse] = []
                for conn in subscene.connections:
                    input_conn = None
                    if input_scene and input_subscene:
                        conn_key = f"{conn.to_subscene}|{conn.name}"
                        input_conn = (
                            input_connection_map.get(scene.name, {})
                            .get(subscene.name, {})
                            .get(conn_key)
                        )
                        if not input_conn and not conn.name:
                            conns = input_connection_map.get(scene.name, {}).get(
                                subscene.name, {}
                            )
                            for _, v in conns.items():
                                if v.to_subscene == conn.to_subscene:
                                    input_conn = v
                                    break

                    conn_id = (
                        input_conn.id if input_conn else f"new-{uuid.uuid4().hex[:8]}"
                    )
                    conn_created_at = (
                        input_conn.created_at if input_conn else current_time
                    )

                    merged_connections.append(
                        ConnectionResponse(
                            id=conn_id,
                            name=conn.name,
                            condition=conn.condition,
                            from_subscene=conn.from_subscene,
                            to_subscene=conn.to_subscene,
                            from_subscene_id=(
                                input_conn.from_subscene_id if input_conn else None
                            ),
                            to_subscene_id=(
                                input_conn.to_subscene_id if input_conn else None
                            ),
                            scene_id=input_conn.scene_id if input_conn else scene_id,
                            created_at=conn_created_at,
                            updated_at=current_time,
                        )
                    )

                merged_subscenes.append(
                    SubsceneWithConnectionsResponse(
                        id=subscene_id,
                        name=subscene.name,
                        type=subscene.type,
                        state=subscene.state,
                        description=(
                            input_subscene.description if input_subscene else None
                        ),
                        mandatory=subscene.mandatory,
                        objective=subscene.objective,
                        scene_id=scene_id,
                        connections=merged_connections,
                        created_at=sub_created_at,
                        updated_at=current_time,
                    )
                )

            merged_scenes.append(
                SceneGraphResponse(
                    id=scene_id,
                    name=scene.name,
                    description=scene.identification_condition,
                    state=scene.state.value,
                    agent_id=agent_id,
                    subscenes=merged_subscenes,
                    created_at=created_at,
                    updated_at=updated_at,
                )
            )

        return merged_scenes

    @staticmethod
    def stream_preview_chat(
        agent_detail: AgentDetailResponse,
        message: str,
        current_scene_name: str | None = None,
        current_subscene_name: str | None = None,
    ) -> Iterator[StreamEvent]:
        """Stream chat responses for preview mode.

        Directly processes LLM streaming responses without using AgentRuntime.

        Args:
            agent_detail: Full agent definition.
            message: User message to process.
            current_scene_name: Optional active scene name.
            current_subscene_name: Optional active subscene name.

        Yields:
            StreamEvent objects for SSE streaming.
        """
        # Get LLM model
        model_name = agent_detail.model_name
        llm_model = get_llm(model_name) if model_name else get_default_llm()

        if not llm_model:
            yield StreamEvent(
                type=StreamEventType.ERROR,
                error="API Key not configured.",
                create_time=datetime.now(timezone.utc).isoformat(),
            )
            return

        # Build scenes for context
        scenes = [
            ChatService.build_scene_from_response(scene_resp)
            for scene_resp in agent_detail.scenes
        ]

        # Find current scene and subscene
        current_scene = None
        current_subscene = None

        if current_scene_name:
            for scene in scenes:
                if scene.name == current_scene_name:
                    current_scene = scene
                    break

        if current_subscene_name and current_scene:
            for subscene in current_scene.subscenes:
                if subscene.name == current_subscene_name:
                    current_subscene = subscene
                    break

        # Build input message
        from app.orchestration.base.input_message import InputMessage
        from app.orchestration.base.output_message import OutputMessage

        input_message = InputMessage(
            user_message=message,
            history=[],
            scenes=scenes,
            current_scene=current_scene,
            current_subscene=current_subscene,
        )

        # Stream LLM response and parse incrementally
        full_content = ""
        current_section = StreamEventType.REASON
        buffer = ""

        for chunk in llm_model.chat_stream(input_message.get_messages()):
            if not chunk.choices:
                continue

            choice = chunk.choices[0]
            delta = choice.message.content
            reasoning = choice.message.reasoning_content

            # Yield reasoning delta if available
            if reasoning:
                yield StreamEvent(
                    type=StreamEventType.REASONING,
                    delta=reasoning,
                    create_time=datetime.now(timezone.utc).isoformat(),
                )

            if delta:
                full_content += delta
                buffer += delta

                while True:
                    # Check for section transitions
                    split_match = re.search(
                        r"##\s*(Reason|Response|Update(?:d)? Scenes|Match(?:ed)? Connection)",
                        buffer,
                        re.IGNORECASE,
                    )

                    if split_match:
                        header_type = split_match.group(1).lower()
                        pre_header = buffer[: split_match.start()]

                        # Yield pre-header content
                        if pre_header and current_section != "parsing":
                            yield StreamEvent(
                                type=current_section,
                                delta=pre_header,
                                create_time=datetime.now(timezone.utc).isoformat(),
                            )

                        # Switch section
                        if "reason" in header_type:
                            current_section = StreamEventType.REASON
                        elif "response" in header_type:
                            current_section = StreamEventType.RESPONSE
                        else:
                            current_section = "parsing"  # type: ignore

                        buffer = buffer[split_match.end() :]
                    else:
                        break

                # Handle potential partial header at end of buffer
                safe_len = max(0, len(buffer) - 50)
                danger_zone = buffer[safe_len:]
                first_hash_in_danger = danger_zone.find("#")

                if first_hash_in_danger != -1:
                    split_idx = safe_len + first_hash_in_danger
                    to_yield = buffer[:split_idx]
                    buffer = buffer[split_idx:]

                    if to_yield and current_section != "parsing":
                        yield StreamEvent(
                            type=current_section,  # type: ignore
                            delta=to_yield,
                            create_time=datetime.now(timezone.utc).isoformat(),
                        )
                else:
                    if buffer and current_section != "parsing":
                        yield StreamEvent(
                            type=current_section,  # type: ignore
                            delta=buffer,
                            create_time=datetime.now(timezone.utc).isoformat(),
                        )
                    buffer = ""

        # Yield any remaining buffer
        if buffer and current_section != "parsing":
            yield StreamEvent(
                type=current_section,  # type: ignore
                delta=buffer,
                create_time=datetime.now(timezone.utc).isoformat(),
            )

        # Parse final output and yield scene updates
        try:
            output_message = OutputMessage.from_content(full_content)

            if output_message.updated_scenes:
                updated_graph = ChatService.merge_graph_with_input(
                    output_message.updated_scenes, agent_detail
                )

                yield StreamEvent(
                    type=StreamEventType.UPDATED_SCENES,
                    updated_scenes=updated_graph,
                    create_time=datetime.now(timezone.utc).isoformat(),
                )

            if output_message.match_connection:
                matched_connection = ConnectionResponse(
                    id=f"preview-{uuid.uuid4().hex[:8]}",
                    name=output_message.match_connection.name,
                    condition=output_message.match_connection.condition,
                    from_subscene=output_message.match_connection.from_subscene,
                    to_subscene=output_message.match_connection.to_subscene,
                    from_subscene_id=None,
                    to_subscene_id=None,
                    scene_id=None,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )

                yield StreamEvent(
                    type=StreamEventType.MATCH_CONNECTION,
                    matched_connection=matched_connection,
                    create_time=datetime.now(timezone.utc).isoformat(),
                )

        except Exception as e:
            logger.error(f"Error parsing stream output: {e}")
            import traceback

            logger.error(traceback.format_exc())

            yield StreamEvent(
                type=StreamEventType.ERROR,
                error=str(e),
                create_time=datetime.now(timezone.utc).isoformat(),
            )
