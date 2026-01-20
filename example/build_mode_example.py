
import sys
import os
import time

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.llm.doubao_llm import DoubaoLLM
from core.agent.builder import AgentBuilder

def main():
    """
    Example of Build Mode: Creating and modifying agents using natural language.
    """
    # Read API key
    api_key = os.getenv("DOUBAO_SEED_API_KEY")
    if not api_key:
        print("Error: DOUBAO_SEED_API_KEY environment variable not set")
        return
    
    # Initialize LLM
    llm = DoubaoLLM(api_key=api_key, timeout=120) # Longer timeout for generation
    builder = AgentBuilder(llm)
    
    print("\n" + "="*50)
    print("TEST CASE 1: Build Agent from Scratch")
    print("="*50)
    
    requirement = """
    Create a 'Fitness Coach' agent. 
    It should help me plan my workout.
    Scenes:
    1. Assessment: Ask about my current fitness level and goals.
    2. Planning: Based on assessment, propose a plan (Cardio or Strength).
    3. Motivation: Give me a motivational quote and end the session.
    """
    
    print(f"Requirement:\n{requirement}")
    print("\nBuilding agent... (this may take a while)")
    
    try:
        result = builder.build(requirement)
        agent = result.agent
        agent.start()
        
        print(f"\nSuccessfully built agent: {agent.name}")
        print(f"Description: {agent.description}")
        print(f"Builder Response: {result.response}")
        print(f"Builder Reason: {result.reason}")
        print("\nPrinting Scene Graph:")
        agent.print_scene_graph()
        
        # Test chat
        print("\n--- Testing Chat ---")
        print("User: Hi, I want to workout.")
        output_message = agent.chat("Hi, I want to workout.")
        print(f"Agent: {output_message.response}")
        
    except Exception as e:
        print(f"Failed to build agent: {e}")
        return

    print("\n" + "="*50)
    print("TEST CASE 2: Modify Existing Agent (Multi-turn)")
    print("="*50)
    
    modification_req = """
    Add a 'Diet Advice' subscene to the 'Planning' scene.
    After proposing the workout plan, ask if I need diet advice.
    If yes, go to Diet Advice. If no, go to Motivation.
    From Diet Advice, go to Motivation.
    """
    
    print(f"Modification Requirement:\n{modification_req}")
    print("\nModifying agent...")
    
    try:
        # Pass the current agent back to the builder
        result = builder.build(modification_req, agent)
        new_agent = result.agent
        new_agent.start()
        
        print(f"\nSuccessfully modified agent: {new_agent.name}")
        print(f"Builder Response: {result.response}")
        print(f"Builder Reason: {result.reason}")
        print("\nPrinting New Scene Graph:")
        new_agent.print_scene_graph()
        
        # Test chat with new path
        print("\n--- Testing Chat with Modified Agent ---")
        print("User: I'm ready for the plan.")
        output_message = new_agent.chat("I'm ready for the plan.") 
        print(f"Agent: {output_message.response}")
        
    except Exception as e:
        print(f"Failed to modify agent: {e}")

if __name__ == "__main__":
    main()
