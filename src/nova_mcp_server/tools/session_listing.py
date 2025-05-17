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
    description="Lists all active Nova Act browser sessions managed by this MCP server. Returns details about each session including their IDs, status, creation timestamps, and associated URLs. Use this to discover existing sessions before attempting to perform operations on them with other browser tools. Sessions that have ended or timed out will be automatically cleaned up."
)
async def list_browser_sessions() -> Dict[str, Any]:
    """
    Lists all active and recent browser sessions managed by this MCP server.
    
    This tool retrieves information about all currently active browser sessions
    and performs cleanup of old/inactive sessions. It's useful for discovering
    what sessions are available for interaction before using tools like 
    execute_instruction or inspect_browser.
    
    Returns:
        A dictionary containing:
        - sessions (List[Dict]): Array of session objects, each containing:
          - session_id (str): The unique identifier for the session
          - status (str): Current status of the session (e.g., "active", "ready")
          - created_at (float): Unix timestamp when the session was created
          - last_updated (float): Unix timestamp when the session was last used
          - url (Optional[str]): The URL the session was last known to be on
          - identity (Optional[str]): The profile identity associated with the session
          - nova_session_id (Optional[str]): The Nova Act SDK's internal session ID
        - total_count (int): The total number of active sessions
        - timestamp (float): Unix timestamp when this listing was generated
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