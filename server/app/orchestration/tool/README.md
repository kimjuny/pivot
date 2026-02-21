# Tool System

The tool system provides function calling capabilities for agents, allowing them to discover, register, and execute tools dynamically.

## Architecture

The tool system consists of four main components:

1. **`@tool` Decorator** (`decorator.py`) - Annotates functions with metadata
2. **ToolMetadata** (`metadata.py`) - Stores tool information
3. **ToolManager** (`manager.py`) - Manages tool discovery, registration, and execution
4. **Built-in Tools** (`builtin/`) - System-provided tools

## Quick Start

### Creating a Tool

Use the `@tool` decorator to register a function as a tool:

```python
from app.orchestration.tool import tool

@tool(
    name="calculate_sum",
    description="Calculates the sum of two numbers",
    input_schema="{'a': number, 'b': number}",
    output_schema="number"
)
def calculate_sum(a: float, b: float) -> float:
    """
    Add two numbers together.
    
    Args:
        a: First number.
        b: Second number.
    
    Returns:
        The sum of a and b.
    """
    return a + b
```

### Using the Tool Manager

```python
from app.orchestration.tool import get_tool_manager

# Get the global tool manager instance
tool_manager = get_tool_manager()

# List all registered tools
tools = tool_manager.list_tools()
for tool_meta in tools:
    print(tool_meta.to_text())

# Execute a tool by name
result = tool_manager.execute("calculate_sum", a=5, b=3)
print(result)  # Output: 8

# Get tool catalog for LLM consumption
catalog = tool_manager.to_text_catalog()
print(catalog)
```

## Tool Metadata

Each tool has the following metadata:

- **name**: Unique identifier for the tool
- **description**: Brief description of what the tool does
- **input_schema**: Description of expected input parameters (string format)
- **output_schema**: Description of the output/return value (string format)

### Text Serialization

Tools can be serialized to text format for LLM consumption:

```python
tool_meta = tool_manager.get_tool("calculate_sum")
print(tool_meta.to_text())
```

Output:
```
Tool: calculate_sum
Description: Calculates the sum of two numbers
Input: {'a': number, 'b': number}
Output: number
```

## Tool Discovery

### Built-in Tools

Built-in tools are automatically discovered at application startup from the `server/app/orchestration/tool/builtin/` directory.

The system:
1. Scans all `.py` files in the `builtin/` directory
2. Imports each module
3. Registers any functions decorated with `@tool`

### Runtime Tool Management

You can dynamically add or remove tools at runtime:

```python
from app.orchestration.tool import get_tool_manager, ToolMetadata

tool_manager = get_tool_manager()

# Add a tool manually
def my_custom_tool(x: int) -> int:
    return x * 2

metadata = ToolMetadata(
    name="double",
    description="Double a number",
    input_schema="{'x': number}",
    output_schema="number",
    func=my_custom_tool
)
tool_manager.add_entry(metadata)

# Remove a tool
tool_manager.remove_entry("double")

# Refresh tools from a directory
from pathlib import Path
tool_manager.refresh(Path("/path/to/tools"))
```

## Built-in Tools

The system comes with example tools in two categories:

### Math Tools (`math_tools.py`)
- `add` - Add two numbers
- `multiply` - Multiply two numbers
- `power` - Raise a number to a power

### Text Tools (`text_tools.py`)
- `uppercase` - Convert text to uppercase
- `lowercase` - Convert text to lowercase
- `word_count` - Count words in text

## Future Extensions

### User-Specific Tools

In the future, users will be able to create custom tools in their isolated directories:

1. User creates a Python file with `@tool` decorated functions
2. System dynamically loads the file at runtime
3. Tools are registered without server restart
4. Tools are isolated per user/session

### Example Future Usage

```python
# Load user-specific tools from their directory
user_tools_dir = Path(f"/user_data/{user_id}/tools")
tool_manager.refresh(user_tools_dir)
```

## API Integration

The tool system is initialized during application startup in `main.py`:

```python
@app.on_event("startup")
async def startup_event():
    # ... other initialization ...
    
    # Initialize tool system
    logger.info("Initializing tool system...")
    tool_manager = get_tool_manager()
    builtin_tools_dir = Path(__file__).parent / "orchestration" / "tool" / "builtin"
    tool_manager.refresh(builtin_tools_dir)
    logger.info(f"Tool system initialized with {len(tool_manager.list_tools())} built-in tools")
```

## Error Handling

The tool system includes comprehensive error handling:

- **Duplicate Registration**: Raises `ValueError` if a tool with the same name already exists
- **Tool Not Found**: Raises `KeyError` when trying to execute or remove a non-existent tool
- **Import Errors**: Silently skips modules that fail to import during discovery

## Best Practices

1. **Unique Names**: Ensure each tool has a unique name across the system
2. **Clear Descriptions**: Write clear, concise descriptions for LLM understanding
3. **Schema Documentation**: Use consistent schema format (JSON-like string representation)
4. **Type Hints**: Always include proper type hints in tool functions
5. **Docstrings**: Follow Google-style docstrings for all tool functions
6. **Error Handling**: Handle errors gracefully within tool functions

## Testing

Example test for a tool:

```python
from app.orchestration.tool import get_tool_manager

def test_calculate_sum():
    tool_manager = get_tool_manager()
    result = tool_manager.execute("add", a=5, b=3)
    assert result == 8

def test_tool_discovery():
    tool_manager = get_tool_manager()
    tools = tool_manager.list_tools()
    assert len(tools) > 0
    assert any(t.name == "add" for t in tools)
```
