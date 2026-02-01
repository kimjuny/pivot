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

    def get_chat_prompt(self, scenes: list[Scene], 
                       current_scene: Scene | None, 
                       current_subscene: Subscene | None) -> dict[str, str]:
        """
        Construct the system message containing instructions, rules, and state for Chat Mode.
        """
        # Build the scene graph JSON representation
        scene_graph = {
            "scenes": [scene.to_dict() for scene in scenes]
        }
        
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
        
        return {
            "role": "system",
            "content": content
        }

    def get_build_prompt(self, existing_agent: dict[str, Any] | None = None) -> dict[str, str]:
        """
        Construct the system message for Build Mode.
        
        Args:
            existing_agent (dict, optional): The dictionary representation of the existing agent.
            
        Returns:
            dict: The system message.
        """
        example_agent_json = {
          "name": "Sleep Companion",
          "description": "A virtual girlfriend who helps with sleep",
          "scenes": [
            {
              "name": "哄睡陪伴",
              "identification_condition": "用户表示想要休息、睡觉或需要放松陪伴",
              "state": "inactive",
              "subscenes": [
                {
                  "name": "睡前问候",
                  "type": "start",
                  "mandatory": True,
                  "objective": "温馨地问候用户，询问今天的情况，营造舒适的氛围。根据用户的回应，可以进入轻松的故事时间或者进行深度放松练习。",  # noqa: RUF001
                  "state": "inactive",
                  "connections": [
                    {
                      "name": "进入故事时间",
                      "from_subscene": "睡前问候",
                      "to_subscene": "轻柔故事",
                      "condition": "用户表示想听故事或者显得很有兴趣"
                    },
                    {
                      "name": "进入放松练习",
                      "from_subscene": "睡前问候",
                      "to_subscene": "呼吸练习",
                      "condition": "用户表示感到紧张或需要放松"
                    }
                  ]
                },
                {
                  "name": "轻柔故事",
                  "type": "normal",
                  "mandatory": False,
                  "objective": "讲述轻松柔和的故事帮助用户放松心情准备入睡。在故事结束后，可以根据用户的感受决定是否需要进一步的放松练习，或者直接准备入睡。",  # noqa: RUF001
                  "state": "inactive",
                  "connections": [
                    {
                      "name": "需要进一步放松",
                      "from_subscene": "轻柔故事",
                      "to_subscene": "呼吸练习",
                      "condition": "用户表示还想继续放松或者还没完全放松下来"
                    },
                    {
                      "name": "准备入睡",
                      "from_subscene": "轻柔故事",
                      "to_subscene": "晚安道别",
                      "condition": "用户表示已经很放松了，准备睡觉"  # noqa: RUF001
                    }
                  ]
                },
                {
                  "name": "呼吸练习",
                  "type": "normal",
                  "mandatory": False,
                  "objective": "引导用户进行深呼吸练习，帮助身体放松。通过舒缓的呼吸节奏，让用户逐渐平静下来，为最终的入睡做好准备。",  # noqa: RUF001
                  "state": "inactive",
                  "connections": [
                    {
                      "name": "完成放松",
                      "from_subscene": "呼吸练习",
                      "to_subscene": "晚安道别",
                      "condition": "用户表示已经放松下来，准备睡觉"  # noqa: RUF001
                    }
                  ]
                },
                {
                  "name": "晚安道别",
                  "type": "end",
                  "mandatory": True,
                  "objective": "温柔地道晚安，祝愿用户有个好梦",  # noqa: RUF001
                  "state": "inactive",
                  "connections": []
                }
              ]
            }
          ]
        }
        
        example_output = {
            "response": "I've created a sleep companion agent for you.",
            "reason": "The user requested a sleep aid agent, so I designed a scene graph with greeting, storytelling, and breathing exercises leading to a goodnight conclusion.",
            "agent": example_agent_json
        }
        
        example_output_str = json.dumps(example_output, indent=2, ensure_ascii=False)
        
        current_agent_config = ""
        task_description = ""
        
        if existing_agent:
            current_agent_config = "You need to modify the following agent based on the user's request:\n" + \
                                 json.dumps(existing_agent, indent=2, ensure_ascii=False) + \
                                 "\nPlease output the FULL updated JSON configuration."
        else:
            task_description = "Create a NEW agent configuration based on the user's request, or modify the configuration provided in the conversation history."

        content = self._build_prompt_template.replace("{{example_output}}", example_output_str)
        content = content.replace("{{current_agent_config}}", current_agent_config)
        content = content.replace("{{task_description}}", task_description)

        return {
            "role": "system",
            "content": content
        }

# Global instance accessor
_system_prompt = SystemPrompt()

def get_chat_prompt(scenes: list[Scene], 
                   current_scene: Scene | None, 
                   current_subscene: Subscene | None) -> dict[str, str]:
    return _system_prompt.get_chat_prompt(scenes, current_scene, current_subscene)

def get_build_prompt(existing_agent: dict[str, Any] | None = None) -> dict[str, str]:
    return _system_prompt.get_build_prompt(existing_agent)
