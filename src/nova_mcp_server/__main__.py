"""
Primary entry point for running the Nova Act MCP Server directly as a package.
Example: python -m nova_mcp_server
"""

from .main_cli import main

if __name__ == "__main__":
    main()