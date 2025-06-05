"""
Browser control tools for the Nova Act MCP Server.

This module provides functionality for controlling web browsers,
including session management, page navigation, interaction, and inspection.
This is the main dispatcher that calls the appropriate action modules.
"""

import traceback # Added for error_details
from typing import Dict, Any, Optional
import anyio # CRITICAL IMPORT

from ..config import (
    initialize_environment, DEFAULT_TIMEOUT, DEFAULT_PROFILE_IDENTITY,
    get_nova_act_api_key, NOVA_ACT_AVAILABLE, log_info, log_error, log_warning, log_debug
)
from ..session_manager import active_sessions, session_lock # Still needed for session data

from .actions_start import initialize_browser_session
# execute_session_action_sync will be called by execute_instruction tool
from .actions_execute import execute_session_action_sync, MAX_RETRY_ATTEMPTS as EXECUTE_MAX_RETRY_ATTEMPTS
from .actions_end import end_session_action
from .actions_inspect import inspect_browser_action, _inspect_browser_async # The sync action function and async function

from .. import mcp # FastMCP instance

# REMOVE: session_executors, session_executors_lock, get_session_executor, cleanup_session_executor

@mcp.tool(
    name="start_session",
    description="Starts and initializes a new browser session controlled by Nova Act, navigating to the specified URL. Returns session details including a unique `session_id` required for other browser tools. This is a long-running operation (20-60s) and will send progress notifications."
)
async def start_session(
    url: str,
    headless: bool = True,
    identity: str = DEFAULT_PROFILE_IDENTITY,
    session_id: Optional[str] = None, 
    ctx: Optional[Any] = None 
) -> Dict[str, Any]:
    initialize_environment()
    if not NOVA_ACT_AVAILABLE: return {"error": "Nova Act SDK not installed.", "error_code": "NOVA_ACT_NOT_AVAILABLE"}
    api_key = get_nova_act_api_key()
    if not api_key: return {"error": "Nova Act API key not found.", "error_code": "MISSING_API_KEY"}
    if not url: return {"error": "URL is required.", "error_code": "MISSING_PARAMETER"}

    log_info(f"Tool 'start_session' called: url='{url}', headless={headless}, ctx_present={ctx is not None}")
    try:
        # initialize_browser_session is the synchronous function doing the blocking work
        start_result = await anyio.to_thread.run_sync(
            initialize_browser_session, # The synchronous function
            url, identity, headless, session_id, ctx, # Args for initialize_browser_session
            cancellable=True 
        )
    except anyio.get_cancelled_exc_class() as e_cancel:
        log_warning(f"start_session tool cancelled by client: {e_cancel}")
        return {"error": "Session start cancelled by client", "success": False, "status": "cancelled"}
    except Exception as e_exec: # Catch general Exception
        log_error(f"Exception from anyio.to_thread.run_sync for start_session: {str(e_exec)}\n{traceback.format_exc()}")
        return {"error": f"Failed to initialize session: {str(e_exec)}", "success": False, "status": "error", "error_details": traceback.format_exc()}
    return start_result

@mcp.tool(
    name="execute_instruction",
    description="Executes a natural language instruction in an active browser session. Use `task` for the main instruction. Returns action outcome, URL, and agent thinking. For complex goals, call multiple times, verifying each step."
)
async def execute_instruction(
    session_id: str,
    task: str,
    instructions: Optional[str] = None, # Supplemental details
    timeout: int = DEFAULT_TIMEOUT,
    retry_attempts: int = EXECUTE_MAX_RETRY_ATTEMPTS, 
    quiet: bool = False,
    ctx: Optional[Any] = None # For potential future progress reporting from execute
) -> Dict[str, Any]:
    initialize_environment()
    if not session_id: return {"error": "session_id is required.", "error_code": "MISSING_PARAMETER"}
    if not task: return {"error": "task (instruction) is required.", "error_code": "MISSING_PARAMETER"}
    
    with session_lock:
        if session_id not in active_sessions:
            return {"error": f"Session {session_id} not found.", "error_code": "SESSION_NOT_FOUND"}

    try:
        # execute_session_action_sync is the synchronous function from actions_execute.py
        result = await anyio.to_thread.run_sync(
            execute_session_action_sync,
            session_id, task, instructions, timeout, retry_attempts, quiet, ctx,
            cancellable=True
        )
    except anyio.get_cancelled_exc_class() as e_cancel:
        log_warning(f"execute_instruction for session {session_id} cancelled: {e_cancel}")
        return {"session_id": session_id, "error": "Execution cancelled", "success": False, "status": "cancelled"}
    except Exception as e_exec: # Catch general Exception
        log_error(f"Exception from anyio.to_thread.run_sync for execute_instruction (session {session_id}): {str(e_exec)}\n{traceback.format_exc()}")
        return {"session_id": session_id, "error": f"Failed to execute instruction: {str(e_exec)}", "success": False, "status": "error", "error_details": traceback.format_exc()}
    return result

@mcp.tool(
    name="inspect_browser",
    description="Retrieves current state (URL, title) of an active browser session. Screenshot is omitted by default. Set include_screenshot=True to get a base64 JPEG (can be large)."
)
async def inspect_browser( # Removed unused ctx parameter
    session_id: str, 
    include_screenshot: bool = False
) -> Dict[str, Any]:
    initialize_environment()
    if not session_id: return {"error": "session_id is required.", "error_code": "MISSING_PARAMETER"}

    with session_lock:
        if session_id not in active_sessions:
            return {"error": f"Session {session_id} not found.", "error_code": "SESSION_NOT_FOUND"}

    try:
        # Call the async inspect function directly to avoid double-threading
        from .actions_inspect import _inspect_browser_async
        result = await _inspect_browser_async(session_id, include_screenshot)
        
        # Handle logs directory processing separately (synchronous part)
        from .actions_start import active_sessions
        from ..utils import _normalize_logs_dir
        
        # Get the nova instance for logs processing
        try:
            session_data = active_sessions[session_id]
            nova = session_data.get("nova_instance")
            
            # Extract values from async result
            browser_state = result.get("browser_state", {})
            
            # Logs directory processing (synchronous part)
            logs_dir_from_session = active_sessions.get(session_id, {}).get("logs_dir")
            if logs_dir_from_session:
                logs_dir = logs_dir_from_session
                log_debug(f"[{session_id}] Using logs_dir from active session: {logs_dir}")
            else:
                sdk_session_id_for_logs = active_sessions.get(session_id, {}).get("nova_session_id")
                logs_dir = _normalize_logs_dir(nova, sdk_session_id_override=sdk_session_id_for_logs)
                log_debug(f"[{session_id}] Normalizing logs_dir again (override: {sdk_session_id_for_logs}): {logs_dir}")

            if logs_dir:
                import glob
                import os
                browser_state["logs_directory"] = logs_dir
                log_files = []
                for ext in [".html", ".htm", ".json", ".log", "trace.zip"]:
                    log_files.extend(glob.glob(os.path.join(logs_dir, f"*{ext}")))
                log_files.sort(key=lambda x: os.path.getmtime(x) if os.path.exists(x) else 0, reverse=True)
                browser_state["log_files"] = [
                    {
                        "path": str(f), "name": os.path.basename(f),
                        "size": os.path.getsize(f) if os.path.exists(f) else 0,
                        "mtime": os.path.getmtime(f) if os.path.exists(f) else 0,
                    } for f in log_files[:10]
                ]
                
                # Update the result with logs information
                result["browser_state"] = browser_state
        except Exception as e_logs:
            log_warning(f"Could not process logs directory for session {session_id}: {e_logs}")
            
    except anyio.get_cancelled_exc_class() as e_cancel:
        log_warning(f"inspect_browser for session {session_id} cancelled: {e_cancel}")
        return {"session_id": session_id, "error": "Inspection cancelled", "success": False, "status": "cancelled"}
    except Exception as e_exec: # Catch general Exception
        log_error(f"Exception in inspect_browser (session {session_id}): {str(e_exec)}\n{traceback.format_exc()}")
        return {"session_id": session_id, "error": f"Failed to inspect browser: {str(e_exec)}", "success": False, "status": "error", "error_details": traceback.format_exc()}
    return result

@mcp.tool(
    name="end_session",
    description="Closes the specified browser session and cleans up resources. Call this when done with a session."
)
async def end_session( # Removed unused ctx parameter
    session_id: str
) -> Dict[str, Any]:
    initialize_environment()
    if not session_id: return {"error": "session_id is required.", "error_code": "MISSING_PARAMETER"}

    # Check if session exists before attempting to run in thread, to provide immediate feedback
    with session_lock:
        if session_id not in active_sessions:
            log_warning(f"Attempting to end non-existent session via tool: {session_id}")
            return {"session_id": session_id, "success": False, "error": f"Session {session_id} not found or already ended.", "error_code": "SESSION_NOT_FOUND"}
    try:
        # end_session_action is the synchronous function from actions_end.py
        end_result = await anyio.to_thread.run_sync(
            end_session_action,
            session_id,
            cancellable=True # Though cancellation might be tricky for cleanup
        )
    except anyio.get_cancelled_exc_class() as e_cancel:
        log_warning(f"end_session for session {session_id} cancelled: {e_cancel}")
        # Still attempt to return a status indicating what might have happened if possible
        return {"session_id": session_id, "error": "Session end cancelled", "success": False, "status": "cancelled_cleanup_attempted"}
    except Exception as e_exec: # Catch general Exception
        log_error(f"Exception from anyio.to_thread.run_sync for end_session (session {session_id}): {str(e_exec)}\n{traceback.format_exc()}")
        return {"session_id": session_id, "error": f"Failed to end session: {str(e_exec)}", "success": False, "status": "error", "error_details": traceback.format_exc()}
    
    # Note: cleanup_session_executor is now handled by anyio's thread management
    return end_result