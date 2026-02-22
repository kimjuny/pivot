"""Tool management service for file system operations.

This module provides services for managing user-created tool files,
including validation, file CRUD operations, and workspace management.
"""

import ast
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Workspace base directory relative to project root
WORKSPACE_BASE = Path(__file__).resolve().parent.parent.parent / "workspace"

# Builtin tools directory
BUILTIN_TOOLS_DIR = (
    Path(__file__).resolve().parent.parent / "orchestration" / "tool" / "builtin"
)


class ToolService:
    """Service for managing tool files and validation.

    Handles:
        - Tool file CRUD operations
        - Source code validation
        - Workspace directory management
    """

    def __init__(self) -> None:
        """Initialize tool service."""
        self._workspace_base = WORKSPACE_BASE
        self._builtin_dir = BUILTIN_TOOLS_DIR

    def get_user_tools_dir(self, username: str) -> Path:
        """Get the tools directory for a specific user.

        Args:
            username: The username to get tools directory for.

        Returns:
            Path to the user's tools directory.
        """
        return self._workspace_base / username / "tools"

    def ensure_user_workspace(self, username: str) -> Path:
        """Create user workspace directory if it doesn't exist.

        Args:
            username: The username to create workspace for.

        Returns:
            Path to the user's tools directory.
        """
        tools_dir = self.get_user_tools_dir(username)
        tools_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Ensured workspace directory exists: {tools_dir}")
        return tools_dir

    def validate_tool_name(self, name: str) -> tuple[bool, str | None]:
        """Validate tool name format.

        Tool names must be valid Python identifiers (alphanumeric and underscore).

        Args:
            name: The tool name to validate.

        Returns:
            Tuple of (is_valid, error_message).
        """
        if not name:
            return False, "Tool name cannot be empty"

        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name):
            return (
                False,
                "Tool name must start with a letter or underscore and contain only alphanumeric characters and underscores",
            )

        if len(name) > 100:
            return False, "Tool name must be 100 characters or less"

        return True, None

    def validate_tool_source(
        self, source_code: str, expected_name: str | None = None
    ) -> tuple[bool, str | None, dict[str, Any] | None]:
        """Validate tool source code.

        Validates that:
        1. Source code is valid Python syntax
        2. Contains exactly one @tool decorated function
        3. Tool name in decorator matches expected name (if provided)

        Args:
            source_code: The Python source code to validate.
            expected_name: Optional expected tool name to match.

        Returns:
            Tuple of (is_valid, error_message, extracted_metadata).
            metadata contains: name, description, parameters if valid.
        """
        # Step 1: Parse AST to check syntax
        try:
            tree = ast.parse(source_code)
        except SyntaxError as e:
            return False, f"Invalid Python syntax: {e}", None

        # Step 2: Find @tool decorated functions
        tool_functions = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    if self._is_tool_decorator(decorator):
                        # Extract metadata from decorator arguments
                        metadata = self._extract_decorator_metadata(decorator, node)
                        if metadata:
                            tool_functions.append(metadata)

        # Step 3: Validate exactly one @tool decorated function
        if len(tool_functions) == 0:
            return False, "Source code must contain a @tool decorated function", None

        if len(tool_functions) > 1:
            return (
                False,
                "Source code must contain exactly one @tool decorated function",
                None,
            )

        metadata = tool_functions[0]

        # Step 4: Validate tool name matches expected name
        if expected_name and metadata["name"] != expected_name:
            return (
                False,
                f"Tool name in decorator ({metadata['name']}) must match expected name ({expected_name})",
                None,
            )

        # Step 5: Validate function name matches tool name
        if metadata["function_name"] != metadata["name"]:
            return (
                False,
                f"Function name ({metadata['function_name']}) must match tool name ({metadata['name']})",
                None,
            )

        return True, None, metadata

    def _is_tool_decorator(self, decorator: ast.expr) -> bool:
        """Check if a decorator is the @tool decorator.

        Args:
            decorator: AST expression representing the decorator.

        Returns:
            True if this is a @tool decorator.
        """
        if isinstance(decorator, ast.Call):
            if isinstance(decorator.func, ast.Name):
                return decorator.func.id == "tool"
        elif isinstance(decorator, ast.Name):
            return decorator.id == "tool"
        return False

    def _extract_decorator_metadata(
        self, decorator: ast.expr, func_node: ast.FunctionDef
    ) -> dict[str, Any] | None:
        """Extract metadata from @tool decorator arguments.

        Args:
            decorator: AST expression representing the @tool(...) call.
            func_node: AST FunctionDef node for the decorated function.

        Returns:
            Dictionary with name, description, parameters, and function_name.
        """
        if not isinstance(decorator, ast.Call):
            return None

        metadata: dict[str, Any] = {"function_name": func_node.name}

        for keyword in decorator.keywords:
            if keyword.arg == "name":
                if isinstance(keyword.value, ast.Constant):
                    metadata["name"] = keyword.value.value
            elif keyword.arg == "description":
                if isinstance(keyword.value, ast.Constant):
                    metadata["description"] = keyword.value.value
            elif keyword.arg == "parameters" and isinstance(keyword.value, ast.Dict):
                metadata["parameters"] = self._ast_dict_to_dict(keyword.value)

        return metadata if "name" in metadata else None

    def _ast_dict_to_dict(self, node: ast.Dict) -> dict[str, Any]:
        """Convert AST Dict node to Python dict.

        Args:
            node: AST Dict node.

        Returns:
            Python dictionary.
        """
        result: dict[str, Any] = {}
        for key, value in zip(node.keys, node.values, strict=False):
            if isinstance(key, ast.Constant):
                result[key.value] = self._ast_value_to_python(value)
        return result

    def _ast_value_to_python(self, node: ast.expr) -> Any:
        """Convert AST expression to Python value.

        Args:
            node: AST expression node.

        Returns:
            Python value (str, int, float, bool, None, dict, or list).
        """
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.Dict):
            return self._ast_dict_to_dict(node)
        elif isinstance(node, ast.List):
            return [self._ast_value_to_python(elt) for elt in node.elts]
        elif isinstance(node, ast.Name):
            if node.id == "True":
                return True
            elif node.id == "False":
                return False
            elif node.id == "None":
                return None
            return node.id
        return None

    def create_tool_file(self, username: str, name: str, source_code: str) -> Path:
        """Create a new tool file in user's workspace.

        Args:
            username: The username who owns the tool.
            name: The tool name (used as filename).
            source_code: The Python source code.

        Returns:
            Path to the created file.

        Raises:
            FileExistsError: If the tool file already exists.
        """
        self.ensure_user_workspace(username)
        file_path = self.get_user_tools_dir(username) / f"{name}.py"

        if file_path.exists():
            raise FileExistsError(f"Tool file already exists: {name}")

        file_path.write_text(source_code, encoding="utf-8")
        logger.info(f"Created tool file: {file_path}")
        return file_path

    def update_tool_file(self, username: str, name: str, source_code: str) -> None:
        """Update an existing tool file.

        Args:
            username: The username who owns the tool.
            name: The tool name.
            source_code: The updated Python source code.

        Raises:
            FileNotFoundError: If the tool file doesn't exist.
        """
        file_path = self.get_user_tools_dir(username) / f"{name}.py"

        if not file_path.exists():
            raise FileNotFoundError(f"Tool file not found: {name}")

        file_path.write_text(source_code, encoding="utf-8")
        logger.info(f"Updated tool file: {file_path}")

    def delete_tool_file(self, username: str, name: str) -> bool:
        """Delete a tool file from user's workspace.

        Args:
            username: The username who owns the tool.
            name: The tool name.

        Returns:
            True if file was deleted, False if it didn't exist.
        """
        file_path = self.get_user_tools_dir(username) / f"{name}.py"

        if not file_path.exists():
            return False

        file_path.unlink()
        logger.info(f"Deleted tool file: {file_path}")
        return True

    def read_tool_file(self, username: str, name: str) -> str | None:
        """Read tool source code from user's workspace.

        Args:
            username: The username who owns the tool.
            name: The tool name.

        Returns:
            Source code string, or None if file doesn't exist.
        """
        file_path = self.get_user_tools_dir(username) / f"{name}.py"

        if not file_path.exists():
            return None

        return file_path.read_text(encoding="utf-8")

    def read_shared_tool_file(self, name: str) -> str | None:
        """Read shared tool source code from builtin directory.

        Args:
            name: The tool name.

        Returns:
            Source code string, or None if file doesn't exist.
        """
        file_path = self._builtin_dir / f"{name}.py"

        if not file_path.exists():
            return None

        return file_path.read_text(encoding="utf-8")

    def tool_exists_in_builtin(self, name: str) -> bool:
        """Check if a tool exists in the builtin directory.

        Args:
            name: The tool name.

        Returns:
            True if tool exists in builtin directory.
        """
        return (self._builtin_dir / f"{name}.py").exists()

    def tool_exists_in_workspace(self, username: str, name: str) -> bool:
        """Check if a tool exists in user's workspace.

        Args:
            username: The username.
            name: The tool name.

        Returns:
            True if tool exists in user's workspace.
        """
        return (self.get_user_tools_dir(username) / f"{name}.py").exists()

    def get_default_tool_template(self, name: str = "my_tool") -> str:
        """Get default tool template for new tools.

        Args:
            name: The tool name to use in template.

        Returns:
            Default Python source code template.
        """
        return f'''from app.orchestration.tool import tool


@tool(
    name="{name}",
    description="Description of what this tool does",
    parameters={{
        "type": "object",
        "properties": {{
            "input": {{
                "type": "string",
                "description": "Description of the input parameter"
            }}
        }},
        "required": ["input"],
        "additionalProperties": False
    }}
)
def {name}(input: str) -> str:
    """
    Tool function implementation.

    Args:
        input: Description of input parameter.

    Returns:
        Description of return value.
    """
    return f"Processed: {{input}}"
'''


# Singleton instance
_tool_service: ToolService | None = None


def get_tool_service() -> ToolService:
    """Get the ToolService singleton instance.

    Returns:
        ToolService instance.
    """
    global _tool_service
    if _tool_service is None:
        _tool_service = ToolService()
    return _tool_service
