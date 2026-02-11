"""
Example mathematical tools for demonstration.
"""

from app.orchestration.tool import tool


@tool(
    name="add",
    description="Add two numbers together",
    input_schema="{'a': number, 'b': number}",
    output_schema="number",
)
def add(a: float, b: float) -> float:
    """
    Add two numbers.

    Args:
        a: First number.
        b: Second number.

    Returns:
        The sum of a and b.
    """
    return a + b


@tool(
    name="multiply",
    description="Multiply two numbers together",
    input_schema="{'a': number, 'b': number}",
    output_schema="number",
)
def multiply(a: float, b: float) -> float:
    """
    Multiply two numbers.

    Args:
        a: First number.
        b: Second number.

    Returns:
        The product of a and b.
    """
    return a * b


@tool(
    name="power",
    description="Raise a number to a power",
    input_schema="{'base': number, 'exponent': number}",
    output_schema="number",
)
def power(base: float, exponent: float) -> float:
    """
    Raise a number to a power.

    Args:
        base: The base number.
        exponent: The exponent.

    Returns:
        base raised to the power of exponent.
    """
    return base**exponent
