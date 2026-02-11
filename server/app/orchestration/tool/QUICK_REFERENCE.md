# Tool System Quick Reference

## Creating a New Tool

```python
from app.orchestration.tool import tool

@tool(
    name="your_tool_name",
    description="Brief description of what the tool does",
    input_schema="{'param1': type, 'param2': type}",
    output_schema="return_type"
)
def your_tool_function(param1: type, param2: type) -> return_type:
    """
    Docstring following Google style.
    
    Args:
        param1: Description.
        param2: Description.
    
    Returns:
        Description of return value.
    """
    # Implementation
    return result
```

## Using Tools

```python
from app.orchestration.tool import get_tool_manager

# Get manager instance
tm = get_tool_manager()

# List all tools
tools = tm.list_tools()

# Execute a tool
result = tm.execute("tool_name", param1=value1, param2=value2)

# Get tool catalog for LLM
catalog = tm.to_text_catalog()

# Get specific tool
tool = tm.get_tool("tool_name")
if tool:
    print(tool.to_text())
```

## Runtime Management

```python
from pathlib import Path
from app.orchestration.tool import get_tool_manager, ToolMetadata

tm = get_tool_manager()

# Add a tool manually
metadata = ToolMetadata(
    name="custom_tool",
    description="Description",
    input_schema="{'x': int}",
    output_schema="int",
    func=my_function
)
tm.add_entry(metadata)

# Remove a tool
tm.remove_entry("tool_name")

# Refresh from directory
tm.refresh(Path("/path/to/tools"))
```

## Tool Catalog Format (for LLM)

```
Tool: tool_name
Description: What the tool does
Input: {'param': type}
Output: return_type
```

## File Locations

- **Core System**: `server/app/orchestration/tool/`
- **Built-in Tools**: `server/app/orchestration/tool/builtin/`
- **Documentation**: `server/app/orchestration/tool/README.md`
- **Demo Script**: `server/app/examples/tool_demo.py`

## Running the Demo

```bash
cd server
poetry run python -m app.examples.tool_demo
```
