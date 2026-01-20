import json
from typing import Any

from .plan.scene import Scene
from .plan.subscene import Subscene


def get_chat_prompt(scenes: list[Scene], 
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
    current_state = {}
    if current_scene:
        current_state["scene"] = current_scene.name
    if current_subscene:
        current_state["subscene"] = current_subscene.name
        
    # Construct the system prompt content
    prompt_parts = []
    
    prompt_parts.append("You are an intelligent agent with the following scene graph:")
    prompt_parts.append(json.dumps(scene_graph, indent=2, ensure_ascii=False))
    
    if current_state:
        prompt_parts.append("\nCurrent state:")
        prompt_parts.append(json.dumps(current_state, indent=2, ensure_ascii=False))
        
    prompt_parts.append("\nInstructions:")
    prompt_parts.append("\n- Scene property explanation:"
                        "name represents the name, globally unique, you can use name to refer to a scene."
                        "identification_condition represents the identification condition for entering this scene."
                        "state has two states: ACTIVE and INACTIVE. Only one scene can be in active state globally."
                        "subscenes are all the subscenes under this scene.")
    prompt_parts.append("\n- Subscene property explanation:"
                        "name represents the name, globally unique, you can use name to refer to a subscene."
                        "objective represents the goal of this subscene. When the agent enters this subscene, the conversation should be organized according to this objective."
                        "type has three types: START, END, and NORMAL, representing that this subscene is a start scene, end scene, or normal scene respectively."
                        "state has two states: ACTIVE and INACTIVE. Only one subscene can be in active state globally."
                        "mandatory indicates whether this subscene must be performed. Mandatory subscenes cannot be skipped."
                        "connections are all the connections under this subscene. Each connection has a target subscene and a transition condition.")
    prompt_parts.append("\n- Connection property explanation:"
                        "name represents the name, globally unique, you can use name to refer to a connection."
                        "from_subscene represents the source subscene of this connection"
                        "to_subscene represents the target subscene of this connection"
                        "condition represents the transition condition of this connection. When the conversation meets this condition description, the agent will jump from from_subscene to to_subscene.")
    prompt_parts.append("\n- OutputMessage property explanation:"
                        "response represents the agent's reply. After processing the user message, the agent will organize a reply based on the current state and user input."
                        "updated_scenes represents the updated list of scenes. After processing the user message, the agent may update the scene states."
                        "match_connection represents the connection matched by the agent. When the agent matches a connection, it will return this connection."
                        "reason represents the explanatory reason for returning this response, updated_scenes, and match_connection after processing according to requirements and rules.")
    prompt_parts.append("\n- Rules:")
    prompt_parts.append("\n- At most one scene and corresponding subscene can be selected globally at any moment")
    prompt_parts.append("\n- Requirements:")
    prompt_parts.append("\n- Input: user message, conversation history, scene_graph. Output: OutputMessage (json format)")
    prompt_parts.append("\n- After user input, the agent has two states: one is that no scene and subscene are currently selected, and the other is that a scene and subscene are currently selected."
                        "1. When the agent currently has no selected scene and subscene, you should first determine which scene in the scene_graph matches the user's conversation intent based on the user's input and each scene's identification_condition."
                        "If there is a matching scene, you should set this scene to active state, set the first subscene with type=start under this scene to active state, then organize your reply according to the objective description of this selected subscene, output the updated scene to OutputMessage's updated_scenes, output the reply to OutputMessage's response, and put your analysis reason into OutputMessage's reason."
                        "If there is no matching scene, you should organize your speech according to the information of all scenes (name and identification_condition description) to guide the user into one of your defined scenes, play a guiding role for the function, output the reply to OutputMessage's response, put your analysis reason into OutputMessage's reason, and do not fill in other content that is not updated."
                        "2. When the agent currently has selected scene and subscene, you should first iterate through all connections in the current subscene based on the user message to see if any connection's condition description is met."
                        "If a connection's condition description is met, the agent should jump from this connection's from_subscene to the specified to_subscene. The from_subscene's state should be set to INACTIVE, and the to_subscene's state should be set to ACTIVE. Based on this principle, the updated_scenes in OutputMessage should be updated by you. You should organize your reply according to the to_subscene's objective and put it into OutputMessage's response. OutputMessage's match_connection should be filled with the connection you just matched, and your analysis reason should be put into OutputMessage's reason. In particular, if the to_subscene you arrive at is a node with type=end, then all scene and subscene states in OutputMessage's updated_scenes should be reset to inactive, and your analysis reason should be put into OutputMessage's reason."
                        "If no connection is met, you should continue to organize your guiding speech according to the current subscene's objective and put it into OutputMessage's response, put your analysis reason into OutputMessage's reason, and do not fill in other content that is not updated in OutputMessage")
    prompt_parts.append("\n- Specifically, when you discover that the user is deliberately avoiding the choices you provide, you need to re-formulate your strategy based on understanding the original graph, especially what your ultimate goal is, and plan and create a new path that can eventually lead to the End node (including subscene and connection), and update your new strategy to the updated_scenes of OutputMessage.")
    
    return {
        "role": "system",
        "content": "\n".join(prompt_parts)
    }


def get_build_prompt(existing_agent: dict[str, Any] | None = None) -> dict[str, str]:
    """
    Construct the system message for Build Mode.
    
    Args:
        existing_agent (dict, optional): The dictionary representation of the existing agent.
        
    Returns:
        dict: The system message.
    """
    prompt_parts = []
    
    prompt_parts.append("You are an expert Agent Architect. Your goal is to design or modify an intelligent agent's configuration based on user requirements.")
    prompt_parts.append("You must output ONLY a valid JSON object representing the Agent configuration. Do not include any markdown formatting or explanations outside the JSON.")
    
    prompt_parts.append("\n### Output Schema Format")
    prompt_parts.append("""
{
  "response": "Your friendly reply to the user explaining what you did or asking for clarification",
  "reason": "Your internal reasoning process for the changes (or why you need clarification)",
  "agent": {
    "name": "Agent Name",
    "description": "Agent Description",
    "scenes": [
      {
        "name": "Scene Name",
        "identification_condition": "Condition to enter this scene",
        "state": "inactive",
        "subscenes": [
          {
            "name": "Subscene Name",
            "type": "start|normal|end",
            "mandatory": true|false,
            "objective": "Goal of this subscene",
            "state": "inactive",
            "connections": [
              {
                "name": "Connection Name",
                "from_subscene": "Source Subscene Name",
                "to_subscene": "Target Subscene Name",
                "condition": "Transition condition"
              }
            ]
          }
        ]
      }
    ]
  }
}
""")
    
    prompt_parts.append("\n### Example")
    prompt_parts.append("Here is an example of a valid output (Sleep Companion):")
    
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
    
    prompt_parts.append(json.dumps(example_output, indent=2, ensure_ascii=False))
    
    if existing_agent:
        prompt_parts.append("\n### Current Agent Configuration")
        prompt_parts.append("You need to modify the following agent based on the user's request:")
        prompt_parts.append(json.dumps(existing_agent, indent=2, ensure_ascii=False))
        prompt_parts.append("Please output the FULL updated JSON configuration.")
    else:
        prompt_parts.append("\n### Task")
        prompt_parts.append("Create a NEW agent configuration based on the user's request, or modify the configuration provided in the conversation history.")

    return {
        "role": "system",
        "content": "\n".join(prompt_parts)
    }
