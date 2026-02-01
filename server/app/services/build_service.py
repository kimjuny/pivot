"""
Build service module.

Provides business logic for agent building/modification operations,
including session management and LLM-based agent creation.
"""

import json
import logging
from typing import Any

from app.crud import build as build_crud
from app.crud.agent import agent as agent_crud
from app.crud.connection import connection as connection_crud
from app.crud.scene import scene as scene_crud
from app.crud.subscene import subscene as subscene_crud
from app.llm_globals import get_default_llm, get_llm
from app.orchestration.base.system_prompt import get_build_prompt
from app.orchestration.builder import AgentBuilder, BuildResult
from sqlmodel import Session

logger = logging.getLogger(__name__)


class BuildServiceError(Exception):
    """Exception raised for build service errors."""

    pass


class BuildService:
    """
    Service class for agent building operations.

    Handles agent creation/modification via LLM, session management,
    and history tracking.
    """

    @staticmethod
    def get_agent_builder() -> AgentBuilder:
        """Initialize AgentBuilder with LLM.

        Returns:
            Configured AgentBuilder instance.

        Raises:
            BuildServiceError: If no LLM is available.
        """
        # Prefer GLM-4 for building if available, else Doubao, else default
        llm = get_llm("glm-4") or get_llm("doubao") or get_default_llm()

        if not llm:
            logger.error("No LLM available for AgentBuilder")
            raise BuildServiceError("No LLM configured for Builder")

        return AgentBuilder(llm)

    @staticmethod
    def reconstruct_builder_history(
        builder: AgentBuilder,
        history_items: list[Any],
        initial_agent_dict: dict[str, Any] | None = None,
    ) -> None:
        """Reconstruct conversation history for AgentBuilder.

        Args:
            builder: The AgentBuilder instance.
            history_items: List of BuildHistory items from DB.
            initial_agent_dict: Initial agent state for system prompt.
        """
        builder.clear_history()

        # Inject System Prompt
        system_msg = get_build_prompt(existing_agent=initial_agent_dict)
        builder.history.append(system_msg)

        for item in history_items:
            msg = {"role": item.role, "content": item.content}
            builder.history.append(msg)

    @staticmethod
    def load_agent_as_dict(agent_id: int, db: Session) -> dict[str, Any] | None:
        """Load agent from database and convert to dictionary.

        Args:
            agent_id: The agent ID to load.
            db: Database session.

        Returns:
            Agent as dictionary, or None if not found.
        """
        try:
            db_agent = agent_crud.get(agent_id, db)
            if not db_agent:
                return None

            db_scenes = scene_crud.get_by_agent_id(agent_id, db)
            scenes_list = []

            for db_scene in db_scenes:
                db_subscenes = subscene_crud.get_by_scene_id(db_scene.id, db)
                subscenes_list = []

                for db_sub in db_subscenes:
                    conns = connection_crud.get_by_from_subscene(db_sub.name, db)
                    connections_list = [
                        {
                            "name": c.name,
                            "condition": c.condition or "",
                            "from_subscene": c.from_subscene,
                            "to_subscene": c.to_subscene,
                        }
                        for c in conns
                    ]
                    subscenes_list.append(
                        {
                            "name": db_sub.name,
                            "type": db_sub.type,
                            "mandatory": db_sub.mandatory,
                            "objective": db_sub.objective or "",
                            "state": db_sub.state,
                            "connections": connections_list,
                        }
                    )

                scenes_list.append(
                    {
                        "name": db_scene.name,
                        "identification_condition": db_scene.description or "",
                        "subscenes": subscenes_list,
                    }
                )

            return {
                "name": db_agent.name,
                "description": db_agent.description or "",
                "scenes": scenes_list,
            }

        except Exception as e:
            logger.error(f"Failed to load agent {agent_id}: {e}")
            return None

    @staticmethod
    def get_current_agent_from_history(
        history_items: list[Any],
    ) -> dict[str, Any] | None:
        """Extract current agent from history snapshot.

        Args:
            history_items: List of BuildHistory items.

        Returns:
            Last agent snapshot as dict, or None.
        """
        for item in reversed(history_items):
            if item.role == "assistant" and item.agent_snapshot:
                try:
                    return json.loads(item.agent_snapshot)
                except Exception:
                    pass
        return None

    @staticmethod
    def build_agent(
        db: Session,
        content: str,
        session_id: str | None = None,
        agent_id: str | None = None,
    ) -> tuple[str, BuildResult]:
        """Build or modify an agent based on content.

        Args:
            db: Database session.
            content: The build/modification requirement.
            session_id: Optional existing session ID.
            agent_id: Optional agent ID to modify.

        Returns:
            Tuple of (session_id, BuildResult).

        Raises:
            BuildServiceError: If building fails.
        """
        # 1. Handle Session
        if session_id:
            session = build_crud.get_session(db, session_id)
            if not session:
                logger.info(f"Session {session_id} not found, creating new.")
                session = build_crud.create_session(db)
        else:
            session = build_crud.create_session(db)

        actual_session_id = session.id

        # 2. Load History
        history_items = build_crud.get_session_history(db, actual_session_id)

        # 3. Determine Context Agent
        initial_agent_dict: dict[str, Any] | None = None
        if not history_items and agent_id:
            try:
                initial_agent_dict = BuildService.load_agent_as_dict(
                    int(agent_id), db
                )
            except Exception as e:
                logger.error(f"Failed to load initial agent {agent_id}: {e}")

        # 4. Initialize Builder & Restore State
        builder = BuildService.get_agent_builder()

        if history_items:
            BuildService.reconstruct_builder_history(
                builder, history_items, initial_agent_dict=None
            )

        # 5. Determine current agent context
        current_agent_dict = initial_agent_dict
        if history_items:
            current_agent_dict = (
                BuildService.get_current_agent_from_history(history_items)
                or initial_agent_dict
            )

        # 6. Execute Build
        result = builder.build(content, agent_dict=current_agent_dict)

        # 7. Save History
        build_crud.add_history(db, actual_session_id, "user", content)

        assistant_raw_content = builder.history[-1]["content"]
        agent_snapshot_json = json.dumps(result.agent_dict, ensure_ascii=False)

        build_crud.add_history(
            db,
            actual_session_id,
            "assistant",
            assistant_raw_content,
            agent_snapshot=agent_snapshot_json,
        )

        return actual_session_id, result
