"""
Tools module for the Nova Act MCP Server.

This module contains all the tool functions that are exposed via FastMCP.
"""

# Import and re-export tools
from .browser_control import (
    start_session, 
    execute_instruction, 
    end_session,
    inspect_browser # Keeping inspect_browser defined as a tool in browser_control.py
)
from .file_transfer import fetch_file
from .log_management import view_html_log, compress_logs, view_compressed_log
from .session_listing import list_browser_sessions

# Define __all__ to control what gets imported with "from tools import *"
__all__ = [
    "start_session", 
    "execute_instruction", 
    "end_session", 
    "inspect_browser",
    "fetch_file", 
    "view_html_log", 
    "compress_logs", 
    "view_compressed_log",
    "list_browser_sessions",
]