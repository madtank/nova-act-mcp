"""
Nova Act MCP Server Package

This package provides a FastMCP server exposing tools for controlling web browsers
using the Amazon Nova Act SDK. It allows AI assistants to perform browser automation
tasks through JSON-RPC calls.
"""

from fastmcp import FastMCP

# Initialize FastMCP server instance
# This 'mcp' instance will be used by the tool decorators
mcp = FastMCP("nova-browser")

# Import tools from the tools subpackage
# The tool functions themselves are decorated with @mcp.tool in their respective files
from .tools import (
    list_browser_sessions,
    start_session,
    execute_instruction,
    end_session,
    view_html_log,
    compress_logs,
    view_compressed_log,
    fetch_file,
    inspect_browser
)

# Import other necessary components that might be part of a public API
from .config import (
    initialize_environment, 
    NOVA_ACT_AVAILABLE, 
    get_nova_act_api_key,
    MAX_INLINE_IMAGE_BYTES,
    INLINE_IMAGE_QUALITY
)
from .session_manager import active_sessions, BrowserResult

# Package version
__version__ = "3.0.0"