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


def initialize_browser_session(
    url: str,
    identity: str = DEFAULT_PROFILE_IDENTITY,
    headless: bool = True,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Initialize a new browser session or validate an existing one.
    """
    initialize_environment()
    log_debug(f"INIT DEBUG: Starting initialize_browser_session with URL={url}, headless={headless}")

    if not NOVA_ACT_AVAILABLE:
        log_error("NovaAct SDK not available, returning error")
        return {
            "error": "Nova Act SDK is not installed. Please install it with: pip install nova-act",
            "error_code": "NOVA_ACT_NOT_AVAILABLE",
        }
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
    if not session_id:
        session_id = generate_session_id()
        log(f"Creating new browser session: {session_id} for identity: {identity} at URL: {url}")
    else:
        log(f"Starting new browser session with provided ID: {session_id} for identity: {identity} at URL: {url}")

    nova: Optional[NovaAct] = None
    nova_session_id: Optional[str] = None
    logs_dir: Optional[str] = None

    try:
        # --- Explicitly create a unique logs_directory for the SDK ---
        base_log_path = Path(tempfile.gettempdir()) / f"{session_id}_sdk_logs"
        base_log_path.mkdir(parents=True, exist_ok=True)
        explicit_sdk_logs_dir = str(base_log_path.resolve())
        log_info(f"[{session_id}] Generated explicit logs_directory for NovaAct: {explicit_sdk_logs_dir}")

        with session_lock:
            if session_id in active_sessions and active_sessions[session_id].get("nova_instance"):
                log(f"Session ID {session_id} exists. Ensuring clean start by creating new NovaAct instance.")

        log(f"Creating new NovaAct browser instance for session {session_id} with starting_page: {url}")

        os.environ["NOVA_ACT_API_KEY"] = api_key

        nova_kwargs = {
            "starting_page": url,
            "headless": headless,
            "nova_act_api_key": api_key,
            "logs_directory": explicit_sdk_logs_dir,
        }

        log_debug(f"[{session_id}] Attempting NovaAct(**nova_kwargs)...")
        nova = NovaAct(**nova_kwargs)
        log_info(f"[{session_id}] NovaAct instance CREATED successfully. Type: {type(nova)}")

        # Always get SDK session_id after start
        if hasattr(nova, "start") and callable(nova.start):
            log_info(f"[{session_id}] Calling nova.start()...")
            nova.start()
            log_info(f"[{session_id}] nova.start() COMPLETED.")
        else:
            log_warning(f"[{session_id}] No callable 'start' on NovaAct; assuming auto-start.")

        # === DEBUG PRINTS FOR MAXIMUM VISIBILITY ===
        print(f"DEBUG_PRINT actions_start.py: [{session_id}] JUST AFTER nova.start() completed.", file=sys.stderr, flush=True)
        try:
            print(f"DEBUG_PRINT actions_start.py: [{session_id}] dir(nova) is: {dir(nova)}", file=sys.stderr, flush=True)
            if hasattr(nova, 'logs_directory'):
                print(f"DEBUG_PRINT actions_start.py: [{session_id}] nova.logs_directory = {getattr(nova, 'logs_directory')}", file=sys.stderr, flush=True)
            else:
                print(f"DEBUG_PRINT actions_start.py: [{session_id}] nova has NO 'logs_directory' attribute.", file=sys.stderr, flush=True)
            if hasattr(nova, 'logs_dir'):
                print(f"DEBUG_PRINT actions_start.py: [{session_id}] nova.logs_dir = {getattr(nova, 'logs_dir')}", file=sys.stderr, flush=True)
            else:
                print(f"DEBUG_PRINT actions_start.py: [{session_id}] nova has NO 'logs_dir' attribute.", file=sys.stderr, flush=True)
            if hasattr(nova, 'session_id'):
                print(f"DEBUG_PRINT actions_start.py: [{session_id}] nova.session_id (SDK's) = {getattr(nova, 'session_id')}", file=sys.stderr, flush=True)
        except Exception as e_debug_inspect:
            print(f"DEBUG_PRINT actions_start.py: [{session_id}] EXCEPTION during manual nova inspection: {e_debug_inspect}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)

        # === INTENSIVE NOVA INSTANCE INSPECTION ===
        log_debug(f"[{session_id}] --- INTENSIVE NOVA INSTANCE INSPECTION ---")
        log_debug(f"[{session_id}] type(nova): {type(nova)}")
        log_debug(f"[{session_id}] dir(nova): {dir(nova)}")
        potential_logs_attrs = [
            "logs_dir", "logs_directory", "log_directory", "log_dir",
            "logs_path", "log_path", "output_dir", "output_directory"
        ]
        for attr in potential_logs_attrs:
            if hasattr(nova, attr):
                attr_val = getattr(nova, attr)
                log_debug(f"[{session_id}] Attribute {attr} = {attr_val}")
                if attr in ("logs_dir", "logs_directory"):
                    if str(attr_val) == explicit_sdk_logs_dir:
                        log_info(f"[{session_id}] {attr} matches explicit_sdk_logs_dir: {explicit_sdk_logs_dir}")

        # --- Additional checks for _logs_directory and _session_user_data_dir ---
        if hasattr(nova, '_logs_directory'):
            log_debug(f"[{session_id}] Found: nova._logs_directory = {getattr(nova, '_logs_directory')}")
        if hasattr(nova, '_session_user_data_dir'):
            log_debug(f"[{session_id}] Found: nova._session_user_data_dir = {getattr(nova, '_session_user_data_dir')}")

        log_debug(f"[{session_id}] --- END INTENSIVE NOVA INSTANCE INSPECTION ---")

        # --- Perform initial act() to get SDK session_id from result metadata ---
        initial_act_instruction = "Observe the current page and respond with the title."
        initial_result = None
        try:
            log_debug(f"[{session_id}] Performing initial nova.act() to obtain SDK session_id from result metadata...")
            initial_result = nova.act(initial_act_instruction, timeout=30)
            log_debug(f"[{session_id}] initial_result from nova.act(): {initial_result}")
        except Exception as e_initial_act:
            log_error(f"[{session_id}] Exception during initial nova.act() for session_id discovery: {e_initial_act}")
            initial_result = None

        nova_session_id = None
        if (
            initial_result
            and hasattr(initial_result, "metadata")
            and hasattr(initial_result.metadata, "session_id")
            and initial_result.metadata.session_id
        ):
            nova_session_id = str(initial_result.metadata.session_id)
            log_info(f"[{session_id}] Successfully CAPTURED SDK's internal session_id via initial act(): {nova_session_id}")
        else:
            log_error(f"[{session_id}] Could not extract SDK session_id from initial act() result metadata. initial_result: {initial_result}")
            nova_session_id = None

        # Use _normalize_logs_dir function to reliably get the logs directory path
        # Created by the NovaAct SDK after nova.start() has been called
        logs_dir = _normalize_logs_dir(nova, sdk_session_id_override=nova_session_id)

        if logs_dir:
            log_info(f"[{session_id}] Successfully retrieved logs_dir: {logs_dir}")
        else:
            log_warning(f"[{session_id}] Could not retrieve logs_dir via _normalize_logs_dir for session {session_id}")

        with session_lock:
            active_sessions[session_id] = {
                "nova_instance": nova,
                "identity": identity,
                "status": "ready",
                "url": url,
                "nova_session_id": nova_session_id,
                "logs_dir": logs_dir,
                "last_updated": time.time(),
            }

        return {
            "session_id": session_id,
            "nova_session_id": nova_session_id,
            "identity": identity,
            "status": "ready",
            "url": url,
            "logs_dir": logs_dir,
            "retrieved_logs_dir": logs_dir,
            "logs_dir_found": logs_dir is not None,
            "success": True,
            "timestamp": time.time(),
        }

    except Exception as e:
        error_details = traceback.format_exc()
        log_error(f"Error initializing browser session {session_id}: {str(e)}\n{error_details}")

        with session_lock:
            if session_id in active_sessions:
                active_sessions.pop(session_id, None)

        return {
            "session_id": session_id,
            "nova_session_id": nova_session_id,
            "identity": identity,
            "success": False,
            "error": str(e),
            "error_details": error_details,
            "status": "error",
            "url": url,
            "timestamp": time.time(),
        }