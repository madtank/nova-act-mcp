"""
Session manager for the Nova Act MCP Server.

This module provides functionality for managing browser sessions,
including tracking active sessions, generating session IDs, and
retrieving session information.
"""

import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Any, Optional, Set, Tuple, Union

from .config import log, log_error, log_debug, SESSION_CLEANUP_AGE


# Global lock for thread safety
session_lock = threading.RLock()

# Global active sessions registry
active_sessions: Dict[str, Dict[str, Any]] = {}


@dataclass
class BrowserResult:
    """Data class for storing browser action results."""
    success: bool
    session_id: str
    action: str
    response: Optional[str] = None
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


def generate_session_id() -> str:
    """
    Generate a unique session ID.
    
    Returns:
        str: A unique session ID
    """
    # Generate a UUID and take the first 8 characters
    session_id = str(uuid.uuid4()).replace("-", "")[:8].lower()
    return session_id


def list_active_sessions() -> Dict[str, Dict[str, Any]]:
    """
    List all active sessions with their status.
    
    Returns:
        dict: A dictionary of active sessions and their metadata
    """
    with session_lock:
        # Create a copy of the session data without the Nova instance
        cleaned_sessions = {}
        for session_id, session_data in active_sessions.items():
            # Exclude the Nova instance and executor from the session data
            # because they can't be serialized to JSON
            cleaned_data = {
                key: value
                for key, value in session_data.items()
                if key not in ["nova_instance", "executor"]
            }
            cleaned_sessions[session_id] = cleaned_data
        
        # Clean up old sessions while we're here
        cleanup_old_sessions()
        
        return cleaned_sessions


def get_session_status(session_id: Optional[str] = None) -> Union[Dict[str, Any], List[Dict[str, Any]], None]:
    """
    Get the status of a specific session or all sessions.
    
    Args:
        session_id: The ID of the session to check, or None to get all sessions
        
    Returns:
        dict, list or None: The session status data, list of all sessions, or None if not found
    """
    with session_lock:
        # If no session_id provided, return all sessions
        if session_id is None:
            results = []
            for s_id, session_data in active_sessions.items():
                # Create a clean version for return (no Nova instance or executor)
                cleaned_data = {
                    key: value
                    for key, value in session_data.items()
                    if key not in ["nova_instance", "executor"]
                }
                # Add the session_id to the cleaned data
                cleaned_data["session_id"] = s_id
                results.append(cleaned_data)
            return results
            
        # Otherwise, return status for the specific session
        if session_id in active_sessions:
            session_data = active_sessions[session_id]
            
            # Create a clean version for return (no Nova instance or executor)
            cleaned_data = {
                key: value
                for key, value in session_data.items()
                if key not in ["nova_instance", "executor"]
            }
            # Add the session_id to the cleaned data
            cleaned_data["session_id"] = session_id
            
            return cleaned_data
        
        return None


def cleanup_old_sessions(max_age: int = SESSION_CLEANUP_AGE) -> None:
    """
    Clean up old sessions that haven't been accessed recently.
    
    Args:
        max_age: Maximum age in seconds before a session is considered stale
    """
    current_time = time.time()
    sessions_to_remove = []
    
    with session_lock:
        for session_id, session_data in active_sessions.items():
            last_updated = session_data.get("last_updated", 0)
            if current_time - last_updated > max_age:
                # Session is stale, mark for removal
                sessions_to_remove.append(session_id)
                
                # Try to close the browser if possible
                nova_instance = session_data.get("nova_instance")
                if nova_instance:
                    try:
                        nova_instance.close()
                        log(f"Closed stale browser session: {session_id}")
                    except Exception as e:
                        log_error(f"Error closing stale browser session {session_id}: {str(e)}")
        
        # Remove the stale sessions
        for session_id in sessions_to_remove:
            active_sessions.pop(session_id, None)
            log_debug(f"Removed stale session: {session_id}")


def close_session(session_id: str) -> bool:
    """
    Close a specific browser session.
    
    Args:
        session_id: The ID of the session to close
        
    Returns:
        bool: True if the session was closed successfully, False otherwise
    """
    with session_lock:
        if session_id in active_sessions:
            session_data = active_sessions[session_id]
            nova_instance = session_data.get("nova_instance")
            
            # Try to close the browser if possible
            if nova_instance:
                try:
                    nova_instance.close()
                    log(f"Closed browser session: {session_id}")
                except Exception as e:
                    log_error(f"Error closing browser session {session_id}: {str(e)}")
            
            # Remove from active sessions
            active_sessions.pop(session_id, None)
            return True
        
        return False


def log_session_info(action: str, session_id: str, detail: str = "") -> None:
    """
    Log information about a session.
    
    Args:
        action: The action being performed
        session_id: The session ID
        detail: Additional details to log
    """
    if detail:
        log(f"{action}: {session_id} ({detail})")
    else:
        log(f"{action}: {session_id}")