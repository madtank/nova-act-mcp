"""
Browser control tools for the Nova Act MCP Server.

This module provides functionality for controlling web browsers,
including session management, page navigation, interaction, and inspection.
This is the main dispatcher that calls the appropriate action modules.
"""

import asyncio
import re
import threading
import uuid
import time
from typing import Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor
import anyio  # Added import for anyio

from ..config import (
    initialize_environment,
    DEFAULT_TIMEOUT,
    DEFAULT_PROFILE_IDENTITY,
    PROGRESS_INTERVAL,
    get_nova_act_api_key,
    NOVA_ACT_AVAILABLE,
    log,
    log_debug,
    log_error,
    log_info,
    log_warning,
)

from ..session_manager import (
    active_sessions,
    session_lock,
)

# Import actions from their respective modules
from .actions_start import initialize_browser_session
from .actions_execute import execute_session_action, MAX_RETRY_ATTEMPTS as EXECUTE_MAX_RETRY_ATTEMPTS
from .actions_end import end_session_action
from .actions_inspect import inspect_browser_action

# Import FastMCP for tool decoration (if used in this file)
from .. import mcp

# Store thread-specific executors to maintain context for each session
# Key: session_id, Value: ThreadPoolExecutor with max_workers=1
session_executors = {}
session_executors_lock = threading.Lock()


def get_session_executor(session_id: str) -> ThreadPoolExecutor:
    """
    Get or create a dedicated ThreadPoolExecutor for a session.
    This ensures the same thread is used for all operations on a session.
    
    Args:
        session_id: The session ID
        
    Returns:
        ThreadPoolExecutor: A dedicated executor for the session
    """
    with session_executors_lock:
        if session_id not in session_executors:
            log_debug(f"Creating new executor for session {session_id}")
            session_executors[session_id] = ThreadPoolExecutor(max_workers=1)
        return session_executors[session_id]


def cleanup_session_executor(session_id: str):
    """
    Clean up the executor for a session when it's no longer needed.
    
    Args:
        session_id: The session ID
    """
    with session_executors_lock:
        if session_id in session_executors:
            log_debug(f"Shutting down executor for session {session_id}")
            executor = session_executors.pop(session_id)
            executor.shutdown(wait=False)


@mcp.tool(
    name="start_session",
    description="Starts and initializes a new, isolated browser session controlled by Nova Act, navigating to the specified URL. Returns a dictionary containing session details including a unique `session_id`. This `session_id` is required for subsequent browser interaction tools like `execute_instruction` and `inspect_browser`. This operation can take 20-60 seconds due to browser and Nova Act SDK startup; MCP progress notifications will be sent to the client during this time if a `progressToken` was provided in the request metadata. The browser remains active until `end_session` is called with the returned `session_id`."
)
async def start_session( # This tool function remains async
    url: str,
    headless: bool = True,
    identity: str = DEFAULT_PROFILE_IDENTITY,
    session_id: Optional[str] = None, # This is the session_id for our MCP server, can be None
    ctx: Optional[Any] = None, # FastMCP injects this context
) -> Dict[str, Any]:
    """
    Starts and initializes a new browser session using Nova Act.

    This tool launches a new Chromium browser instance, navigates to the specified URL,
    and performs initial setup. It's designed to be the first step in a browser
    automation workflow. Progress notifications are sent during the potentially lengthy
    startup process if the MCP client supports them.

    Args:
        url: The initial URL the browser should navigate to upon starting.
        headless: If True (default), the browser runs in headless mode (no visible UI).
                  Set to False to see the browser window, useful for debugging.
        identity: An optional identifier for the user or profile associated with this session.
                  Defaults to "default".
        session_id: Optional. If provided, attempts to use this as the session ID. 
                    If None (default), a new unique session ID will be generated.
        ctx: (Injected by FastMCP) The MCP Context object, used internally for capabilities
             like progress reporting. Callers of the tool do not provide this.

    Returns:
        A dictionary containing:
        - session_id (str): The unique identifier for the newly created session.
        - nova_session_id (Optional[str]): The internal session ID from the Nova Act SDK.
        - identity (str): The identity used for the session.
        - status (str): Should be "ready" if successful.
        - url (str): The initial URL the session started with.
        - logs_dir (Optional[str]): The path to the directory where Nova Act SDK logs for this
                                   session are stored.
        - success (bool): True if the session was started successfully, False otherwise.
        - timestamp (float): The Unix timestamp of when the session was started.
        - error (Optional[str]): An error message if success is False.
        - error_code (Optional[str]): An error code if success is False.
    """
    initialize_environment()
    
    if not NOVA_ACT_AVAILABLE: 
        return {"error": "Nova Act SDK not installed.", "error_code": "NOVA_ACT_NOT_AVAILABLE"}
    api_key = get_nova_act_api_key()
    if not api_key: 
        return {"error": "Nova Act API key not found.", "error_code": "MISSING_API_KEY"}
    if not url: 
        return {"error": "URL is required.", "error_code": "MISSING_PARAMETER"}

    log_info(f"Tool 'start_session' called: url='{url}', headless={headless}, ctx_present={ctx is not None}")

    # initialize_browser_session is now a sync function that uses from_thread.run
    # We run it in an AnyIO managed thread.
    # The session_id passed to initialize_browser_session is the one potentially provided by the client
    # for this MCP session, NOT for the executor key yet.
    # initialize_browser_session will generate its own effective_session_id if this is None.
    
    try:
        start_result = await anyio.to_thread.run_sync(
            initialize_browser_session,
            url, # arg for initialize_browser_session
            identity, # arg
            headless, # arg
            session_id, # arg (session_id_param in initialize_browser_session)
            ctx, # arg (mcp_context in initialize_browser_session)
            cancellable=True # Allow cancellation if client cancels
        )
    except anyio.get_cancelled_exc_class() as e_cancel: # Catch AnyIO cancellation
        log_warning(f"start_session tool cancelled by client: {e_cancel}")
        return {"error": "Session start cancelled by client", "success": False, "status": "cancelled"}
    except Exception as e_exec:
        log_error(f"Exception from anyio.to_thread.run_sync for start_session: {e_exec}")
        return {"error": f"Failed to initialize session: {e_exec}", "success": False, "status": "error"}

    # Executor mapping:
    # initialize_browser_session returns its 'effective_session_id' as 'session_id' in its result.
    # We need to ensure an executor is set up for this session_id.
    # get_session_executor will create one if it doesn't exist.
    if start_result.get("success") and start_result.get("session_id"):
        actual_mcp_session_id = start_result["session_id"]
        get_session_executor(actual_mcp_session_id) # Ensures executor exists for this session
        log_debug(f"Ensured executor exists for session {actual_mcp_session_id} after successful start.")
    elif "session_id" in start_result and not start_result.get("success"): # Start failed but gave us an ID
        # If init failed but returned a session_id (e.g. its own generated one), try to clean up executor
        failed_session_id = start_result.get("session_id")
        if failed_session_id:
             cleanup_session_executor(failed_session_id)

    return start_result


@mcp.tool(
    name="execute_instruction",
    description="Execute a natural language instruction in an existing browser session (e.g., 'Search for pizza', 'Click the login button', 'Fill out the form'). Returns step-by-step results of actions performed and any errors encountered."
)
async def execute_instruction(
    session_id: str,
    task: str,
    instructions: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
    retry_attempts: int = EXECUTE_MAX_RETRY_ATTEMPTS,
    quiet: bool = False,
) -> Dict[str, Any]:
    """
    Executes a given natural language instruction in the specified active browser session.

    This tool interfaces with Nova Act to perform web automation tasks based on
    natural language. It's designed for actions like clicking elements, typing text,
    navigating, and extracting simple information as directed by the instruction.

    Args:
        session_id: The unique identifier of an active browser session, previously
                    obtained from a successful call to `start_session`.
        task: The primary natural language instruction for the Nova Act agent to execute.
              This should be a clear, actionable command.
        instructions: Optional. Supplemental details or context for the `task`.
                      If `task` is comprehensive, this may not be needed.
        timeout: Optional. Maximum time (in seconds) to allow for the execution of this
                 instruction. Defaults to the server's DEFAULT_TIMEOUT.
        retry_attempts: Optional. Number of times to retry the instruction if the first
                        attempt is not deemed successful by the server. Defaults to the
                        server's EXECUTE_MAX_RETRY_ATTEMPTS.
        quiet: Optional. If True, suppresses some verbose logging during execution.

    Returns:
        A dictionary containing:
        - session_id (str): The session ID in which the instruction was executed.
        - success (bool): True if the instruction was processed by Nova Act without
                          raising an exception in our server, False otherwise. Note: Nova Act
                          itself might report success for an action that didn't achieve the
                          user's semantic goal; further verification by the caller may be needed.
        - task (str): The primary task that was executed.
        - instructions (Optional[str]): The supplemental instructions provided.
        - step_results (List[Dict]): Detailed results from Nova Act if it performs multiple
                                   sub-steps (structure may vary based on Nova Act output).
                                   Often contains the direct `response` from `nova.act()`.
        - content (List[Dict]): A structured representation of the primary textual response or
                                outcome from the agent.
        - agent_thinking (List[Dict]): Structured thinking steps extracted from Nova Act's logs
                                     or metadata, if available.
        - url (Optional[str]): The browser's current URL after the instruction was executed.
        - html_log_path (Optional[str]): Path to the HTML log file generated by Nova Act for
                                       this specific `act()` call, if available.
        - error (Optional[str]): An error message if success is False.
    """
    initialize_environment()
    
    if not session_id:
        return {
            "error": "Session ID is required for execute_instruction",
            "error_code": "MISSING_PARAMETER",
        }
    
    if not task:
        return {
            "error": "Task/instruction is required",
            "error_code": "MISSING_PARAMETER",
        }
    
    # Check if the session exists
    with session_lock:
        if session_id not in active_sessions:
            return {
                "error": f"Session {session_id} not found or no longer active",
                "error_code": "SESSION_NOT_FOUND",
            }
    
    try:
        executor = get_session_executor(session_id)
        
        # Store the executor in the session data
        with session_lock:
            if session_id in active_sessions:
                active_sessions[session_id]["executor"] = executor
                active_sessions[session_id]["last_updated"] = time.time()
        
        # Execute the task
        return await execute_session_action(
            session_id=session_id,
            task=task,
            instructions=instructions,
            timeout=timeout,
            retry_attempts=retry_attempts,
            quiet=quiet
        )
    
    except Exception as e:
        log_error(f"Error executing instruction in session {session_id}: {str(e)}")
        return {
            "session_id": session_id,
            "success": False,
            "error": f"Error executing instruction: {str(e)}",
            "timestamp": time.time(),
        }


@mcp.tool(
    name="end_session",
    description="End and clean up a browser session. This properly closes the browser and frees resources. Always call this when finished with a session to prevent memory leaks and zombie processes."
)
async def end_session(
    session_id: str,
) -> Dict[str, Any]:
    """
    End and clean up a browser session.
    
    This tool properly terminates a browser session that was previously started with
    `start_session`. It ensures that all browser resources, including the underlying
    Chromium process, are properly cleaned up, preventing memory leaks and zombie
    processes. Always call this tool when you're completely finished with a browser
    session to free system resources.
    
    Args:
        session_id: The unique identifier of the browser session to end, previously
                    obtained from a successful call to `start_session`.
        
    Returns:
        A dictionary containing:
        - session_id (str): The session ID that was ended.
        - success (bool): True if the session was ended successfully, False otherwise.
        - timestamp (float): The Unix timestamp of when the session was ended.
        - error (Optional[str]): An error message if success is False.
        - error_code (Optional[str]): An error code if success is False.
    """
    initialize_environment()
    loop = asyncio.get_event_loop()
    
    if not session_id:
        return {
            "error": "Session ID is required to end a session",
            "error_code": "MISSING_PARAMETER",
        }
    
    # Check if session exists
    with session_lock:
        if session_id not in active_sessions:
            log_warning(f"Attempting to end non-existent session: {session_id}")
            return {
                "session_id": session_id,
                "success": False,
                "error": f"Session {session_id} not found or already ended",
                "error_code": "SESSION_NOT_FOUND",
                "timestamp": time.time(),
            }
    
    try:
        executor = get_session_executor(session_id)
        
        # Run end_session_action in the session's dedicated executor
        end_result = await loop.run_in_executor(
            executor,
            lambda: end_session_action(session_id=session_id)
        )
        
        # Clean up the executor
        cleanup_session_executor(session_id)
        
        return end_result
    
    except Exception as e:
        log_error(f"Error ending session {session_id}: {str(e)}")
        # Try to clean up executor anyway
        cleanup_session_executor(session_id)
        return {
            "session_id": session_id,
            "success": False,
            "error": f"Error ending session: {str(e)}",
            "timestamp": time.time(),
        }


@mcp.tool(
    name="inspect_browser",
    description="Retrieves the current state of an active browser session, including URL and page title. When include_screenshot=True, attempts to capture and include a base64-encoded JPEG screenshot (if under MAX_INLINE_IMAGE_BYTES size limit, default 1MB). Screenshots are omitted by default to conserve token usage. Use this tool to observe the current browser state after navigation or interaction, or to verify what the browser is currently displaying before executing further instructions. Always specify session_id from a previous start_session call."
)
async def inspect_browser(
    session_id: Optional[str] = None, # session_id is now truly optional at this level
    include_screenshot: bool = False  # New parameter to control screenshot inclusion
) -> Dict[str, Any]:
    """
    Gets detailed information about the current state of a browser session, including URL,
    page title, and optionally a screenshot.
    
    This tool is designed for AI agents to observe the browser's current state after executing
    navigation or interaction commands. It provides essential information for subsequent
    decision-making about what actions to take next. The optional screenshot feature is
    particularly valuable for visual verification of current page state, though it comes
    with a token usage cost.
    
    Args:
        session_id: The unique identifier of an active browser session, previously obtained 
                    from a successful call to `start_session`. Currently required, though
                    the parameter is typed as Optional for future extension where it might
                    default to a "current" or "most recent" session.
        include_screenshot: If True, attempts to capture and include a base64-encoded JPEG 
                            screenshot. Defaults to False to conserve token usage. Screenshots 
                            are only included if they are under the configured size limit 
                            (MAX_INLINE_IMAGE_BYTES, typically 1MB). Note that enabling 
                            screenshots can substantially increase LLM context/token usage.
        
    Returns:
        A dictionary containing:
        - session_id (str): The session ID that was inspected.
        - current_url (str): The current URL in the browser.
        - page_title (str): The title of the current page.
        - content (List[Dict]): A structured representation of information, including
                                text description of the current page. If include_screenshot
                                was True and successful, contains a base64-encoded image.
        - agent_thinking (List[Dict]): Information about the inspection process, including
                                      any warnings or errors encountered.
        - browser_state (Dict): Additional detailed information about the browser's state.
        - timestamp (float): The Unix timestamp when the inspection was performed.
        - success (bool): True if the inspection completed without errors, False otherwise.
        - error (Optional[str]): Error message if success is False.
        - error_code (Optional[str]): Error code if success is False.
    """
    initialize_environment()
    
    if not NOVA_ACT_AVAILABLE:
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

    if not session_id:
        log_error("inspect_browser called without a session_id, which is currently required.")
        return {
            "error": "session_id is currently required for inspect_browser",
            "error_code": "MISSING_PARAMETER",
        }

    try:
        executor = get_session_executor(session_id)
    except KeyError:
        log_error(f"No active executor found for session_id: {session_id}. Session might not be started or already ended.")
        return {
            "error": f"No active executor for session_id: {session_id}. Session may not exist or is not active.",
            "error_code": "SESSION_EXECUTOR_NOT_FOUND",
        }
        
    import traceback  # Ensure traceback is imported
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            executor,
            inspect_browser_action,
            session_id,
            include_screenshot  # Pass the include_screenshot parameter
        )
        return result
    except Exception as e:  # pylint: disable=broad-except
        log_error(f"Exception during inspect_browser execution for session {session_id}: {e}")
        return {
            "session_id": session_id,
            "error": f"An unexpected error occurred during inspection: {str(e)}",
            "error_details": traceback.format_exc(),
            "success": False,
        }