"""
Example script demonstrating the tool system usage.

This script shows how to:
1. Get the tool manager instance
2. List all registered tools
3. Execute tools by name
4. Get the tool catalog for LLM consumption
"""

from pathlib import Path

from app.orchestration.tool import get_tool_manager


def main():
    """Demonstrate the tool system functionality."""
    # Get the tool manager instance
    tool_manager = get_tool_manager()

    # Discover and register built-in tools
    builtin_tools_dir = (
        Path(__file__).parent.parent / "orchestration" / "tool" / "builtin"
    )
    tool_manager.refresh(builtin_tools_dir)

    print("=" * 60)
    print("Tool System Demo")
    print("=" * 60)

    # List all registered tools
    tools = tool_manager.list_tools()
    print(f"\n✓ Discovered {len(tools)} tools\n")

    # Display tool catalog (for LLM consumption)
    print("Tool Catalog:")
    print("-" * 60)
    print(tool_manager.to_text_catalog())
    print("-" * 60)

    # Execute some example tools
    print("\n\nTool Execution Examples:")
    print("-" * 60)

    # Math tools
    result = tool_manager.execute("add", a=5, b=3)
    print(f"add(5, 3) = {result}")

    result = tool_manager.execute("multiply", a=4, b=7)
    print(f"multiply(4, 7) = {result}")

    result = tool_manager.execute("power", base=2, exponent=8)
    print(f"power(2, 8) = {result}")

    # Text tools
    result = tool_manager.execute("uppercase", text="hello world")
    print(f'uppercase("hello world") = "{result}"')

    result = tool_manager.execute("lowercase", text="HELLO WORLD")
    print(f'lowercase("HELLO WORLD") = "{result}"')

    result = tool_manager.execute("word_count", text="The quick brown fox jumps")
    print(f'word_count("The quick brown fox jumps") = {result}')

    print("-" * 60)

    # Get individual tool metadata
    print("\n\nIndividual Tool Details:")
    print("-" * 60)
    add_tool = tool_manager.get_tool("add")
    if add_tool:
        print(add_tool.to_text())
        print(f"\nMetadata as dict: {add_tool.to_dict()}")
    print("-" * 60)

    print("\n✓ Tool system demo complete!\n")


if __name__ == "__main__":
    main()
