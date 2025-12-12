import sys
import os
import json

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.llm.doubao_llm import DoubaoLLM
from core.llm.abstract_llm import Response


def main():
    """
    Simple test example for the DoubaoLLM implementation.
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
        
        # Prepare a simple conversation
        messages = [
            {"role": "user", "content": "Hello, how are you?"}
        ]
        
        # Get response from the model
        response: Response = llm.chat(messages)
        
        # Pretty print the response
        response.pretty_print_full()
        
    except ValueError as e:
        print(f"Configuration Error: {e}")
    except Exception as e:
        print(f"Error occurred: {e}")


if __name__ == "__main__":
    main()