"""
Session listing tool for the Nova Act MCP Server.

This module provides functionality for listing browser sessions.
"""

import json
import time
from typing import Dict, List, Any, Optional

from .. import mcp
from ..config import log, initialize_environment
from ..session_manager import get_session_status, cleanup_old_sessions

@mcp.tool(
    name="list_browser_sessions",
    description="List all active and recent web browser sessions"
)
async def list_browser_sessions() -> Dict[str, Any]:
    """
    List all active and recent browser sessions.
    
    Returns:
        dict: A dictionary containing information about active browser sessions
    """
    initialize_environment()
    log("Listing browser sessions...")

    # Clean up old completed sessions
    cleanup_old_sessions()
    
    # Get the status of all active sessions
    sessions = get_session_status()
    
    # Prepare result in a consistent format
    result = {
        "sessions": sessions,
        "total_count": len(sessions),
        "timestamp": time.time(),
    }
    
    log(f"Found {len(sessions)} active browser sessions")
    return result