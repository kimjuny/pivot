import json
from pathlib import Path
from typing import Any

from app.models.agent import Scene, Subscene


class SystemPrompt:
    _instance = None
    _chat_prompt_template: str = ""
    _build_prompt_template: str = ""

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_templates()
        return cls._instance

    def _load_templates(self):
        base_dir = Path(__file__).resolve().parent

        with (base_dir / "chat.md").open(encoding="utf-8") as f:
            self._chat_prompt_template = f.read()

        with (base_dir / "build.md").open(encoding="utf-8") as f:
            self._build_prompt_template = f.read()

    def get_chat_prompt(
        self,
        scenes: list[Scene],
        current_scene: Scene | None,
        current_subscene: Subscene | None,
    ) -> dict[str, str]:
        """
        Construct the system message containing instructions, rules, and state for Chat Mode.
        """
        # Build the scene graph JSON representation
        scene_graph = {"scenes": [scene.to_dict() for scene in scenes]}

        # Build current state information
        current_state_str = ""
        current_state = {}
        if current_scene:
            current_state["scene"] = current_scene.name
        if current_subscene:
            current_state["subscene"] = current_subscene.name

        if current_state:
            current_state_str = json.dumps(current_state, indent=2, ensure_ascii=False)

        scene_graph_str = json.dumps(scene_graph, indent=2, ensure_ascii=False)

        content = self._chat_prompt_template.replace("{{scene_graph}}", scene_graph_str)
        content = content.replace("{{current_state}}", current_state_str)

        return {"role": "system", "content": content}

    def get_build_prompt(
        self, existing_agent: dict[str, Any] | None = None
    ) -> dict[str, str]:
        """
        Construct the system message for Build Mode.

        Args:
            existing_agent (dict, optional): The dictionary representation of the existing agent.

        Returns:
            dict: The system message.
        """
        current_agent_config = ""

        if existing_agent:
            current_agent_config = json.dumps(
                existing_agent, indent=2, ensure_ascii=False
            )

        content = self._build_prompt_template.replace(
            "{{current_agent_config}}", current_agent_config
        )

        return {"role": "system", "content": content}


# Global instance accessor
_system_prompt = SystemPrompt()


def get_chat_prompt(
    scenes: list[Scene], current_scene: Scene | None, current_subscene: Subscene | None
) -> dict[str, str]:
    return _system_prompt.get_chat_prompt(scenes, current_scene, current_subscene)


def get_build_prompt(existing_agent: dict[str, Any] | None = None) -> dict[str, str]:
    return _system_prompt.get_build_prompt(existing_agent)
