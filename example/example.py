import sys
import os

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.llm.doubao_llm import DoubaoLLM
from core.agent.agent import Agent


def main():
    """
    Example demonstrating the Agent framework with DoubaoLLM.
    """
    # Read API key from environment variable
    api_key = os.getenv("DOUBAO_SEED_API_KEY")
    
    if not api_key:
        print("Error: DOUBAO_SEED_API_KEY environment variable not set")
        print("Please set the DOUBAO_SEED_API_KEY environment variable to your API key")
        return
    
    try:
        # Initialize the LLM with API key from environment variable
        llm = DoubaoLLM(api_key=api_key)
        
        # Create and configure agent using chainable methods
        agent = Agent().set_model(llm).start()
        
        # Chat with the agent
        print("=== Agent Chat Example ===")
        response = agent.chat("Hello, how are you?")
        first_choice = response.first()
        print(f"Assistant: {first_choice.message.content}")
        
        # Continue the conversation
        print("\n=== Continuing Conversation ===")
        response = agent.chat("What can you help me with?")
        first_choice = response.first()
        print(f"Assistant: {first_choice.message.content}")
        
        # Stop the agent
        agent.stop()
        print("\nAgent stopped.")
        
    except ValueError as e:
        print(f"Configuration Error: {e}")
    except Exception as e:
        print(f"Error occurred: {e}")


if __name__ == "__main__":
    main()