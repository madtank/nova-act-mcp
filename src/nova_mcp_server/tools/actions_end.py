"""
Browser session cleanup for the Nova Act MCP Server.

This module provides functionality for ending browser sessions.
"""

import time
import traceback
from typing import Dict, Any

from ..config import (
    log,
    log_info,
    log_debug,
    log_error,
    initialize_environment,
    NOVA_ACT_AVAILABLE,
)
from ..session_manager import (
    active_sessions,
    session_lock,
)


def end_session_action(session_id: str) -> Dict[str, Any]:
    """
    End a browser session.
    
    Args:
        session_id: The session ID to end
        
    Returns:
        dict: A dictionary containing the result of the session cleanup
    """
    initialize_environment()
    
    if not session_id:
        return {
            "error": "Missing required parameter: session_id",
            "error_code": "MISSING_PARAMETER",
        }
    
    # Check if NovaAct is available
    if not NOVA_ACT_AVAILABLE:
        return {
            "error": "Nova Act SDK is not installed. Please install it with: pip install nova-act",
            "error_code": "NOVA_ACT_NOT_AVAILABLE",
        }
    
    # Check if the session exists
    nova = None
    with session_lock:
        if session_id not in active_sessions:
            return {
                "error": f"Session not found: {session_id}",
                "error_code": "SESSION_NOT_FOUND",
            }
        
        # Get the Nova instance
        session_data = active_sessions[session_id]
        nova = session_data.get("nova_instance")
        if not nova:
            # If no instance but the session exists, we can still clean up the registry
            active_sessions.pop(session_id, None)
            return {
                "session_id": session_id,
                "success": True,
                "message": "Session registry cleaned up (no browser instance found)",
                "timestamp": time.time(),
            }
    
    try:
        # Close the browser session
        log(f"Closing browser session: {session_id}")
        
        # Get session details before closing
        identity = None
        with session_lock:
            if session_id in active_sessions:
                identity = active_sessions[session_id].get("identity")
        
        # Close the browser
        if nova:
            try:
                # Use __exit__ method to properly clean up the NovaAct instance
                # as it's designed to be used as a context manager
                nova.__exit__(None, None, None)
                log_debug(f"Nova instance __exit__ called for session: {session_id}")
            except Exception as e:
                log_error(f"Error calling __exit__ on Nova instance: {e}")
                # Fall back to other cleanup methods if __exit__ fails
                try:
                    # Try close method as fallback if available
                    if hasattr(nova, "close") and callable(getattr(nova, "close")):
                        nova.close()
                        log_debug(f"Nova instance close() called for session: {session_id}")
                except Exception as e2:
                    log_error(f"Fallback close also failed: {e2}")
        
        # Remove from session registry
        with session_lock:
            if session_id in active_sessions:
                # Try to stop any running executors
                executor = active_sessions[session_id].get("executor")
                if executor:
                    try:
                        executor.shutdown(wait=False)
                    except Exception as e:
                        log_error(f"Error shutting down executor: {e}")
                
                # Remove the session
                active_sessions.pop(session_id, None)
        
        log(f"Closed browser session: {session_id}")
        
        # Prepare success result
        result = {
            "session_id": session_id,
            "identity": identity,
            "success": True,
            "message": "Session closed successfully",
            "timestamp": time.time(),
        }
        
        return result
    
    except Exception as e:
        # Handle any exceptions
        error_details = traceback.format_exc()
        log_error(f"Error closing browser session: {str(e)}\n{error_details}")
        
        # Try to clean up the registry even if closing failed
        with session_lock:
            if session_id in active_sessions:
                active_sessions.pop(session_id, None)
        
        # Prepare error result
        error_result = {
            "session_id": session_id,
            "success": False,
            "error": str(e),
            "error_details": error_details,
            "message": "Error closing session, registry cleaned up",
            "timestamp": time.time(),
        }
        
        return error_result