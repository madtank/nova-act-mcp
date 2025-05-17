"""
Browser session initialization for the Nova Act MCP Server.

This module provides functionality for starting new browser sessions.
"""

import time
import os
import traceback
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional
import sys  # For debug print to stderr
import anyio  # For from_thread
from anyio import from_thread

from ..config import (
    log,
    log_info, 
    log_debug, 
    log_error,
    log_warning,
    initialize_environment,
    get_nova_act_api_key,
    DEFAULT_PROFILE_IDENTITY,
    NOVA_ACT_AVAILABLE,
)
from ..session_manager import (
    active_sessions,
    session_lock,
    generate_session_id,
    log_session_info,
)
from ..utils import _normalize_logs_dir

# Import NovaAct if available
if NOVA_ACT_AVAILABLE:
    from nova_act import NovaAct


def initialize_browser_session( # This function now runs IN A THREAD via anyio.to_thread.run_sync
    url: str,
    identity: str = DEFAULT_PROFILE_IDENTITY,
    headless: bool = True,
    session_id: Optional[str] = None, 
    mcp_context: Optional[Any] = None 
) -> Dict[str, Any]:
    # This function's body IS the '_do_initialize_work'
    initialize_environment()
    effective_session_id = session_id or generate_session_id()
    log_debug(f"[{effective_session_id}] THREADED_INIT_SESSION: URL={url}, mcp_context_present={mcp_context is not None}")

    prog_total_steps = 5
    prog_current_step = 0

    async def _async_report_progress(step, total, msg): # Async helper
        if mcp_context and hasattr(mcp_context, 'report_progress'):
            log_info(f"[{effective_session_id}] Progress ({step}/{total}): {msg}")
            await mcp_context.report_progress(step, total, msg)

    def report_progress(step, msg): # Sync wrapper for thread
        if mcp_context:
            try:
                from_thread.run(_async_report_progress, step, prog_total_steps, msg)
            except Exception as e:
                log_error(f"[{effective_session_id}] Failed to send progress: {e}")
    
    def check_cancelled():
        if mcp_context and hasattr(mcp_context, 'cancelled') and mcp_context.cancelled.is_set():
            log_warning(f"[{effective_session_id}] Session initialization cancelled by client.")
            report_progress(prog_total_steps, "Initialization cancelled by client.")
            return True
        return False

    # Actual work starts
    if not NOVA_ACT_AVAILABLE: 
        return {"error": "Nova Act SDK not installed.", "error_code": "NOVA_ACT_NOT_AVAILABLE"}
    
    api_key = get_nova_act_api_key()
    if not api_key:
        return {
            "error": "Nova Act API key not found. Please set it in your MCP config or as an environment variable.",
            "error_code": "MISSING_API_KEY",
        }
    if not url:
        return {
            "error": "URL (starting_page) is required to start a session.",
            "error_code": "MISSING_PARAMETER",
        }

    log_info(f"[{effective_session_id}] Starting session for identity: {identity} at URL: {url}")
    nova: Optional[NovaAct] = None
    nova_sdk_session_id: Optional[str] = None
    logs_dir_path: Optional[str] = None # Renamed for clarity

    try:
        prog_current_step = 1
        report_progress(prog_current_step, "Initializing NovaAct SDK...")
        if check_cancelled(): 
            return {"error": "Cancelled", "success": False, "status": "cancelled"}

        # --- Explicitly create a unique logs_directory for the SDK ---
        base_log_path = Path(tempfile.gettempdir()) / f"{effective_session_id}_sdk_logs"
        base_log_path.mkdir(parents=True, exist_ok=True)
        explicit_sdk_logs_dir = str(base_log_path.resolve())
        log_info(f"[{effective_session_id}] Generated explicit logs_directory for NovaAct: {explicit_sdk_logs_dir}")
        
        os.environ["NOVA_ACT_API_KEY"] = api_key

        with session_lock:
            if effective_session_id in active_sessions and active_sessions[effective_session_id].get("nova_instance"):
                log(f"Session ID {effective_session_id} exists. Ensuring clean start by creating new NovaAct instance.")

        nova_kwargs = {
            "starting_page": url, 
            "headless": headless,
            "nova_act_api_key": api_key, 
            "logs_directory": explicit_sdk_logs_dir,
        }
        
        log_debug(f"[{effective_session_id}] Attempting NovaAct(**nova_kwargs)...")
        nova = NovaAct(**nova_kwargs)
        log_info(f"[{effective_session_id}] NovaAct instance created successfully. Type: {type(nova)}")
        if check_cancelled(): 
            return {"error": "Cancelled", "success": False, "status": "cancelled"}

        prog_current_step = 2
        report_progress(prog_current_step, "Starting browser (nova.start())...")
        
        # Always get SDK session_id after start
        if hasattr(nova, "start") and callable(nova.start):
            log_info(f"[{effective_session_id}] Calling nova.start()...")
            nova.start()
            log_info(f"[{effective_session_id}] nova.start() COMPLETED.")
        else:
            log_warning(f"[{effective_session_id}] No callable 'start' on NovaAct; assuming auto-start.")
        
        if check_cancelled(): 
            return {"error": "Cancelled", "success": False, "status": "cancelled"}

        # === DEBUG PRINTS FOR MAXIMUM VISIBILITY ===
        print(f"DEBUG_PRINT actions_start.py: [{effective_session_id}] JUST AFTER nova.start() completed.", file=sys.stderr, flush=True)
        try:
            print(f"DEBUG_PRINT actions_start.py: [{effective_session_id}] dir(nova) is: {dir(nova)}", file=sys.stderr, flush=True)
            if hasattr(nova, 'logs_directory'):
                print(f"DEBUG_PRINT actions_start.py: [{effective_session_id}] nova.logs_directory = {getattr(nova, 'logs_directory')}", file=sys.stderr, flush=True)
            else:
                print(f"DEBUG_PRINT actions_start.py: [{effective_session_id}] nova has NO 'logs_directory' attribute.", file=sys.stderr, flush=True)
            if hasattr(nova, 'logs_dir'):
                print(f"DEBUG_PRINT actions_start.py: [{effective_session_id}] nova.logs_dir = {getattr(nova, 'logs_dir')}", file=sys.stderr, flush=True)
            else:
                print(f"DEBUG_PRINT actions_start.py: [{effective_session_id}] nova has NO 'logs_dir' attribute.", file=sys.stderr, flush=True)
            if hasattr(nova, 'session_id'):
                print(f"DEBUG_PRINT actions_start.py: [{effective_session_id}] nova.session_id (SDK's) = {getattr(nova, 'session_id')}", file=sys.stderr, flush=True)
        except Exception as e_debug_inspect:
            print(f"DEBUG_PRINT actions_start.py: [{effective_session_id}] EXCEPTION during manual nova inspection: {e_debug_inspect}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)

        # === INTENSIVE NOVA INSTANCE INSPECTION ===
        log_debug(f"[{effective_session_id}] --- INTENSIVE NOVA INSTANCE INSPECTION ---")
        log_debug(f"[{effective_session_id}] type(nova): {type(nova)}")
        log_debug(f"[{effective_session_id}] dir(nova): {dir(nova)}")
        potential_logs_attrs = [
            "logs_dir", "logs_directory", "log_directory", "log_dir",
            "logs_path", "log_path", "output_dir", "output_directory"
        ]
        for attr in potential_logs_attrs:
            if hasattr(nova, attr):
                attr_val = getattr(nova, attr)
                log_debug(f"[{effective_session_id}] Attribute {attr} = {attr_val}")
                if attr in ("logs_dir", "logs_directory"):
                    if str(attr_val) == explicit_sdk_logs_dir:
                        log_info(f"[{effective_session_id}] {attr} matches explicit_sdk_logs_dir: {explicit_sdk_logs_dir}")

        # --- Additional checks for _logs_directory and _session_user_data_dir ---
        if hasattr(nova, '_logs_directory'):
            log_debug(f"[{effective_session_id}] Found: nova._logs_directory = {getattr(nova, '_logs_directory')}")
        if hasattr(nova, '_session_user_data_dir'):
            log_debug(f"[{effective_session_id}] Found: nova._session_user_data_dir = {getattr(nova, '_session_user_data_dir')}")

        log_debug(f"[{effective_session_id}] --- END INTENSIVE NOVA INSTANCE INSPECTION ---")

        prog_current_step = 3
        report_progress(prog_current_step, "Initial page observation (nova.act())...")
        if check_cancelled(): 
            return {"error": "Cancelled", "success": False, "status": "cancelled"}

        # --- Perform initial act() to get SDK session_id from result metadata ---
        initial_act_instruction = "Observe the current page and respond with the title."
        initial_result = None
        try:
            log_debug(f"[{effective_session_id}] Performing initial nova.act() to obtain SDK session_id from result metadata...")
            initial_result = nova.act(initial_act_instruction, timeout=45)
            log_debug(f"[{effective_session_id}] initial_result from nova.act(): {initial_result}")
        except Exception as e_initial_act:
            log_error(f"[{effective_session_id}] Exception during initial nova.act() for session_id discovery: {e_initial_act}")
            initial_result = None
        
        if (
            initial_result
            and hasattr(initial_result, "metadata")
            and hasattr(initial_result.metadata, "session_id")
            and initial_result.metadata.session_id
        ):
            nova_sdk_session_id = str(initial_result.metadata.session_id)
            log_info(f"[{effective_session_id}] Successfully CAPTURED SDK's internal session_id via initial act(): {nova_sdk_session_id}")
        elif hasattr(nova, 'session_id') and nova.session_id:
            nova_sdk_session_id = str(nova.session_id)
            log_info(f"[{effective_session_id}] Retrieved SDK session_id from nova.session_id: {nova_sdk_session_id}")
        else:
            log_error(f"[{effective_session_id}] CRITICAL: Failed to get SDK session_id.")
            nova_sdk_session_id = effective_session_id # Fallback
        
        if check_cancelled(): 
            return {"error": "Cancelled", "success": False, "status": "cancelled"}

        prog_current_step = 4
        report_progress(prog_current_step, "Finalizing setup (logs dir)...")
        
        # Use _normalize_logs_dir function to reliably get the logs directory path
        logs_dir_path = _normalize_logs_dir(nova, sdk_session_id_override=nova_sdk_session_id)
        log_info(f"[{effective_session_id}] Retrieved logs_dir using _normalize_logs_dir: {logs_dir_path}")

        if logs_dir_path:
            log_info(f"[{effective_session_id}] Successfully retrieved logs_dir: {logs_dir_path}")
        else:
            log_warning(f"[{effective_session_id}] Could not retrieve logs_dir via _normalize_logs_dir for session {effective_session_id}")
        
        if check_cancelled(): 
            return {"error": "Cancelled", "success": False, "status": "cancelled"}

        with session_lock:
            active_sessions[effective_session_id] = {
                "nova_instance": nova, 
                "identity": identity, 
                "status": "ready",
                "url": url, 
                "nova_session_id": nova_sdk_session_id, 
                "logs_dir": logs_dir_path,
                "last_updated": time.time(), 
                "progress": {
                    "current_step": prog_current_step, 
                    "total_steps": prog_total_steps, 
                    "current_action": "Session ready"
                }
            }
        
        prog_current_step = 5
        report_progress(prog_current_step, "Session initialized and ready.")
        
        return {
            "session_id": effective_session_id, 
            "nova_session_id": nova_sdk_session_id,
            "identity": identity, 
            "status": "ready", 
            "url": url,
            "logs_dir": logs_dir_path, 
            "retrieved_logs_dir": logs_dir_path,
            "logs_dir_found": logs_dir_path is not None,
            "success": True, 
            "timestamp": time.time(),
        }
    except Exception as e:
        error_details = traceback.format_exc()
        log_error(f"[{effective_session_id}] Error in initialize_browser_session: {str(e)}\n{error_details}")
        
        with session_lock: 
            active_sessions.pop(effective_session_id, None)
        
        if nova and hasattr(nova, "__exit__"):
            try: 
                nova.__exit__(None, None, None)
            except Exception as cleanup_error: 
                log_error(f"Error during Nova cleanup: {cleanup_error}")
        
        # Send failure progress if context is available
        report_progress(prog_total_steps, f"Session initialization failed: {str(e)[:100]}")

        return {
            "session_id": effective_session_id, 
            "nova_session_id": nova_sdk_session_id,
            "identity": identity, 
            "success": False, 
            "error": str(e),
            "error_details": error_details, 
            "status": "error", 
            "url": url,
            "logs_dir": logs_dir_path,
            "timestamp": time.time(),
        }