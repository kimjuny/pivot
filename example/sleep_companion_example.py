import json
import sys
import os

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.llm.doubao_llm import DoubaoLLM
from core.agent.agent import Agent
from core.agent.base.stream import AgentResponseChunkType
from core.agent.plan.scene import Scene
from core.agent.plan.subscene import Subscene, SubsceneType
from core.agent.plan.connection import Connection


def create_sleep_companion_scenario() -> Scene:
    """
    Create a sleep companion scenario for a virtual girlfriend agent.
    This scenario aims to help the user fall asleep through conversation.
    """
    # Create the main scene
    sleep_scene = Scene(
        name="哄睡陪伴",
        identification_condition="用户表示想要休息、睡觉或需要放松陪伴"
    )
    
    # Create subscenes
    greeting = Subscene(
        name="睡前问候",
        subscene_type=SubsceneType.START,
        mandatory=True,
        objective="温馨地问候用户，询问今天的情况，营造舒适的氛围。根据用户的回应，可以进入轻松的故事时间或者进行深度放松练习。"
    )
    
    storytelling = Subscene(
        name="轻柔故事",
        subscene_type=SubsceneType.NORMAL,
        mandatory=False,
        objective="讲述轻松柔和的故事帮助用户放松心情准备入睡。在故事结束后，可以根据用户的感受决定是否需要进一步的放松练习，或者直接准备入睡。"
    )
    
    breathing_exercise = Subscene(
        name="呼吸练习",
        subscene_type=SubsceneType.NORMAL,
        mandatory=False,
        objective="引导用户进行深呼吸练习，帮助身体放松。通过舒缓的呼吸节奏，让用户逐渐平静下来，为最终的入睡做好准备。"
    )
    
    goodnight = Subscene(
        name="晚安道别",
        subscene_type=SubsceneType.END,
        mandatory=True,
        objective="温柔地道晚安，祝愿用户有个好梦"
    )
    
    # Add subscenes to the scene
    sleep_scene.add_subscene(greeting)
    sleep_scene.add_subscene(storytelling)
    sleep_scene.add_subscene(breathing_exercise)
    sleep_scene.add_subscene(goodnight)
    
    # Create connections between subscenes
    # From greeting, user can go to storytelling or breathing exercise
    conn1 = Connection(
        name="进入故事时间",
        from_subscene=greeting.name,
        to_subscene=storytelling.name,
        condition="用户表示想听故事或者显得很有兴趣"
    )
    
    conn2 = Connection(
        name="进入放松练习",
        from_subscene=greeting.name,
        to_subscene=breathing_exercise.name,
        condition="用户表示感到紧张或需要放松"
    )
    
    # From storytelling, user can go to breathing exercise or goodnight
    conn3 = Connection(
        name="需要进一步放松",
        from_subscene=storytelling.name,
        to_subscene=breathing_exercise.name,
        condition="用户表示还想继续放松或者还没完全放松下来"
    )
    
    conn4 = Connection(
        name="准备入睡",
        from_subscene=storytelling.name,
        to_subscene=goodnight.name,
        condition="用户表示已经很放松了，准备睡觉"
    )
    
    # From breathing exercise, user can go to goodnight
    conn5 = Connection(
        name="完成放松",
        from_subscene=breathing_exercise.name,
        to_subscene=goodnight.name,
        condition="用户表示已经放松下来，准备睡觉"
    )
    
    # Add connections to subscenes
    greeting.add_connection(conn1)
    greeting.add_connection(conn2)
    storytelling.add_connection(conn3)
    storytelling.add_connection(conn4)
    breathing_exercise.add_connection(conn5)
    
    return sleep_scene


def main():
    """
    Example demonstrating the Agent framework with a virtual girlfriend who helps with sleep.
    """
    # Read API key from environment variable
    api_key = os.getenv("DOUBAO_SEED_API_KEY")
    
    if not api_key:
        print("Error: DOUBAO_SEED_API_KEY environment variable not set")
        print("Please set the DOUBAO_SEED_API_KEY environment variable to your API key")
        return
    
    try:
        # Initialize the LLM with API key from environment variable and increased timeout
        llm = DoubaoLLM(api_key=api_key, timeout=60)
        
        # Create the sleep companion scenario
        sleep_scene = create_sleep_companion_scenario()
        
        # Create and configure agent using chainable methods
        agent = Agent().add_plan(sleep_scene).set_model(llm).start()
        
        # Chat with the agent
        print("=== Virtual Girlfriend Sleep Companion ===")
        print("虚拟女友哄睡场景示例")
        print("你可以尝试说：我想睡觉了 / 我今天很累 / 给我讲个故事吧")
        print("-" * 50)
        
        conversation_count = 0
        while True:
            user_input = input("你: ").strip()
            if user_input.lower() in ['退出', 'exit', 'quit']:
                break
                
            # Use chat_stream to get response
            print("女友 (Streaming): ", end="", flush=True)
            reasoning_printed = False
            reason_printed = False
            response_printed = False
            updated_scenes_printed = False
            match_connection_printed = False
            
            for chunk in agent.chat_stream(user_input):
                if chunk.type == AgentResponseChunkType.REASONING:
                    if not reasoning_printed and (reasoning_printed := True):
                        print("\n[Reasoning]: ", end="", flush=True)
                    print(chunk.delta, end="", flush=True)
                elif chunk.type == AgentResponseChunkType.REASON:
                    if not reason_printed and (reason_printed := True):
                        print("\n[Reason]: ", end="", flush=True)
                    print(chunk.delta, end="", flush=True)
                elif chunk.type == AgentResponseChunkType.RESPONSE:
                    if not response_printed and (response_printed := True):
                        print("\n[Response]: ", end="", flush=True)
                    print(chunk.delta, end="", flush=True)
                elif chunk.type == AgentResponseChunkType.UPDATED_SCENES:
                    if not updated_scenes_printed and (updated_scenes_printed := True):
                        print("\n[Updated Scenes]: ", end="", flush=True)
                    print(json.dumps([s.to_dict() for s in chunk.updated_scenes], ensure_ascii=False, indent=2), end="", flush=True)
                elif chunk.type == AgentResponseChunkType.MATCH_CONNECTION:
                    if not match_connection_printed and (match_connection_printed := True):
                        print("\n[Match Connection]: ", end="", flush=True)
                    print(json.dumps([s.to_dict() for s in chunk.matched_connection], ensure_ascii=False, indent=2), end="", flush=True)
                elif chunk.type == AgentResponseChunkType.ERROR:
                    print(f"\nError: {chunk.delta}")

            # Print scene graph state
            conversation_count += 1
        
        # Stop the agent
        agent.stop()
        print("\n晚安，好梦！")
        
    except ValueError as e:
        print(f"Configuration Error: {e}")
    except Exception as e:
        print(f"Error occurred: {e}")


if __name__ == "__main__":
    main()