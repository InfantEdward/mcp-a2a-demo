from datetime import datetime
from fastmcp import FastMCP

mcp = FastMCP("MathTools")


@mcp.tool()
async def add(a: float, b: float) -> str:
    """Add two numbers."""
    return str(a + b)


@mcp.tool()
async def subtract(a: float, b: float) -> str:
    """Subtract two numbers."""
    return str(a - b)


@mcp.tool()
async def multiply(a: float, b: float) -> str:
    """Multiply two numbers."""
    return str(a * b)


@mcp.tool()
async def divide(a: float, b: float) -> str:
    """Divide two numbers."""
    return str(a / b) if b != 0 else "Error: Division by zero"


@mcp.tool()
async def get_current_time() -> str:
    """Get the current time."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    mcp.run()
