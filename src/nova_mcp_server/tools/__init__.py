"""
Tools module for the Nova Act MCP Server.

This module contains all the tool functions that are exposed via FastMCP.
"""

# Import and re-export tools
from .browser_control import browser_session, inspect_browser
from .file_transfer import fetch_file
from .log_management import view_html_log, compress_logs, view_compressed_log
from .session_listing import list_browser_sessions

# Define __all__ to control what gets imported with "from tools import *"
__all__ = [
    "browser_session",
    "inspect_browser",
    "fetch_file",
    "view_html_log",
    "compress_logs",
    "view_compressed_log",
    "list_browser_sessions",
]