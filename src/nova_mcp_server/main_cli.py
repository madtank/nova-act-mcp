"""
Command-line interface for the Nova Act MCP Server.
This module contains the main entry point for running the server directly.
"""

import argparse
import importlib.metadata
import os
import sys

from . import mcp, __version__
from .config import (
    initialize_environment, 
    get_nova_act_api_key, 
    NOVA_ACT_AVAILABLE,
    log
)

def main():
    """Main function to run the MCP server or display version information"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Nova Act MCP Server - FastMCP wrapper for Nova-Act"
    )
    parser.add_argument(
        "--version", action="store_true", help="Display version information"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument(
        "--stdio", action="store_true", help="Silence banners for MCP stdio clients"
    )
    parser.add_argument(
        "tool",
        nargs="?",
        default=None,
        help="Optional tool name (browser_session, list_browser_sessions, ...)",
    )
    args, unknown = parser.parse_known_args()

    # Set debug mode if requested
    if args.debug:
        os.environ["NOVA_MCP_DEBUG"] = "1"

    # Display version and exit if requested
    if args.version or "--version" in unknown:
        try:
            # Try to get version from package metadata first
            version = importlib.metadata.version("nova-act-mcp-server")
            print(f"nova-act-mcp-server version {version}", file=sys.stderr)
        except importlib.metadata.PackageNotFoundError:
            # Fall back to version defined in __init__.py
            print(f"nova-act-mcp-server version {__version__}", file=sys.stderr)
        return

    # Perform initialization and logging only when actually running the server
    initialize_environment()

    # Set stdio mode if requested
    if args.stdio:
        os.environ["NOVA_MCP_STDIO"] = "1"

    # === TEMPORARILY COMMENT OUT THESE LOGS ===
    # Print a welcome message with setup instructions
    # log("\n=== Nova Act MCP Server ===")
    # log("Status:")

    # if not NOVA_ACT_AVAILABLE:
    #     log("- Nova Act SDK: Not installed (required)")
    #     log("  Install with: pip install nova-act")
    # else:
    #     log("- Nova Act SDK: Installed ✓")

    # # Get the API key and update the status message
    # api_key = get_nova_act_api_key()
    # if api_key:
    #     log("- API Key: Found in configuration ✓")
    # else:
    #     log("- API Key: Not found ❌")
    #     log(
    #         "  Please add 'novaActApiKey' to your MCP config or set NOVA_ACT_API_KEY environment variable"
    #     )

    # log(
    #     "- Tool: list_browser_sessions - List all active and recent web browser sessions ✓"
    # )
    # log(
    #     "- Tool: browser_session - Manage and interact with web browser sessions via Nova Act agent ✓"
    # )
    # log("- Tool: view_html_log - View HTML logs from browser sessions ✓")
    # log("- Tool: inspect_browser - Get screenshots and current state of browser sessions ✓")

    # log("\nStarting MCP server...")
    # === END OF TEMPORARILY COMMENTED LOGS ===
    
    # Initialize and run the server
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()