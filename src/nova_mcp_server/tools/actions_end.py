"""
Browser session cleanup for the Nova Act MCP Server.

This module provides functionality for ending browser sessions.
"""

import time
import traceback
from typing import Dict, Any

from ..config import (
    log_info,
    log_debug,
    log_error,
    log_warning,
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
    
    if not NOVA_ACT_AVAILABLE:
        return {
            "error": "Nova Act SDK is not installed. Please install it with: pip install nova-act",
            "error_code": "NOVA_ACT_NOT_AVAILABLE",
        }
    
    nova = None
    session_data = None
    identity = None # Define identity here to ensure it's available for the result

    with session_lock:
        if session_id not in active_sessions:
            return {
                "error": f"Session not found: {session_id}",
                "error_code": "SESSION_NOT_FOUND",
            }
        
        session_data = active_sessions[session_id]
        nova = session_data.get("nova_instance")
        identity = session_data.get("identity") # Get identity before potential pop

    try:
        log_info(f"Attempting to end browser session: {session_id}")
        
        if nova:
            try:
                log_info(f"Calling nova.__exit__ for session: {session_id}")
                nova.__exit__(None, None, None) # Primary cleanup method
                log_debug(f"Nova instance __exit__ called successfully for session: {session_id}")
            except Exception as e_exit:
                log_error(f"Error calling __exit__ on Nova instance for session {session_id}: {e_exit}")
                if hasattr(nova, "close") and callable(getattr(nova, "close")):
                    try:
                        log_debug(f"Attempting fallback nova.close() for session: {session_id}")
                        nova.close()
                        log_debug(f"Fallback nova.close() called for session: {session_id}")
                    except Exception as e_close:
                        log_error(f"Fallback nova.close() also failed for session {session_id}: {e_close}")
        else:
            log_warning(f"No Nova instance found for session {session_id} during end_session_action, but will clean up registry.")

        # Remove from active sessions registry and cleanup executor
        # This part must happen regardless of whether nova instance existed or closed cleanly.
        with session_lock:
            active_sessions.pop(session_id, None) 
        
        # It's better if cleanup_session_executor is robust to session_id not being in its dict
        # from ..tools.browser_control import cleanup_session_executor # Assuming this path
        # cleanup_session_executor(session_id) # REMOVED as anyio handles thread pool
        log_info(f"Session {session_id} registry cleaned.")
        
        return {
            "session_id": session_id,
            "identity": identity,
            "success": True,
            "message": "Session closed successfully and resources cleaned up.",
            "timestamp": time.time(),
        }
    
    except Exception as e:
        error_details = traceback.format_exc()
        log_error(f"Unexpected error closing browser session {session_id}: {str(e)}\n{error_details}")
        
        # Ensure cleanup attempts even if an unexpected error occurs
        with session_lock:
            active_sessions.pop(session_id, None)
        
        # try:
        #     from ..tools.browser_control import cleanup_session_executor
        #     cleanup_session_executor(session_id)
        # except Exception as e_cleanup_fail:
        #     log_error(f"Failed to cleanup executor for session {session_id} during error handling: {e_cleanup_fail}")
            
        return {
            "session_id": session_id,
            "identity": identity, # identity might be None if error occurred before it was fetched
            "success": False,
            "error": str(e),
            "error_details": error_details,
            "message": "Error during session closure, registry cleaned up.",
            "timestamp": time.time(),
        }