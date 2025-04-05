from typing import Any, Dict, List, Optional
import os
import asyncio
import concurrent.futures
import json
import time
import traceback
import threading
import atexit
import sys
from pydantic import BaseModel
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server with config (no output here)
mcp = FastMCP("nova-browser")

# Constants for timeouts and progress reporting
DEFAULT_TIMEOUT = 180  # 3 minutes per step
PROGRESS_INTERVAL = 5  # Send progress updates every 5 seconds
MAX_RETRY_ATTEMPTS = 2  # Maximum retry attempts for failed steps

# User profiles directory
PROFILES_DIR = "./profiles"
DEFAULT_PROFILE = "default"  # Default profile name to use

# Global browser session registry
active_sessions = {}
session_lock = threading.Lock()

# Global variable to track if logging is initialized
_logging_initialized = False

# Global API key variable
NOVA_ACT_API_KEY = None

# Flag to check for NovaAct availability - initialize without logging
NOVA_ACT_AVAILABLE = False
try:
    from nova_act import NovaAct
    NOVA_ACT_AVAILABLE = True
except ImportError:
    pass

# Utility function to log to stderr instead of stdout
# This prevents log messages from interfering with JSON-RPC communication
def log(message):
    """Log messages to stderr instead of stdout to prevent interference with JSON-RPC"""
    print(message, file=sys.stderr, flush=True)

# Clean up function to ensure all browser sessions are closed on exit
def cleanup_browser_sessions():
    log("Cleaning up browser sessions...")
    with session_lock:
        for session_id, session_data in list(active_sessions.items()):
            try:
                nova = session_data.get("nova")
                if nova and hasattr(nova, 'close') and not getattr(nova, '_closed', True):
                    log(f"Closing browser session {session_id}")
                    nova.close()
            except Exception as e:
                log(f"Error closing browser session {session_id}: {str(e)}")
        active_sessions.clear()

# Register the cleanup function to run on exit
atexit.register(cleanup_browser_sessions)

class BrowserResult(BaseModel):
    text: str
    success: bool
    details: Optional[Dict[str, Any]] = None

class SessionStatus(BaseModel):
    """Represents the current status of a browser session"""
    session_id: str
    identity: str
    status: str
    current_step: int
    total_steps: int
    last_updated: float
    current_action: str
    url: Optional[str] = None
    error: Optional[str] = None

# Create a session management system
def generate_session_id():
    """Generate a unique session ID"""
    import uuid
    return str(uuid.uuid4())

def get_session_status():
    """Get status of all active browser sessions"""
    with session_lock:
        return [
            SessionStatus(
                session_id=session_id,
                identity=data.get("identity", "unknown"),
                status=data.get("status", "unknown"),
                current_step=data.get("progress", {}).get("current_step", 0),
                total_steps=data.get("progress", {}).get("total_steps", 0),
                last_updated=data.get("last_updated", 0),
                current_action=data.get("progress", {}).get("current_action", ""),
                url=data.get("url", None),
                error=data.get("progress", {}).get("error", None)
            ).model_dump() 
            for session_id, data in active_sessions.items()
        ]

def get_nova_act_api_key():
    """Read the API key from the MCP server config or environment variables"""
    global NOVA_ACT_API_KEY
    try:
        # Check for an environment variable first (highest priority)
        api_key = os.environ.get("NOVA_ACT_API_KEY")
        if (api_key):
            NOVA_ACT_API_KEY = api_key
            log(f"✅ Found API key in environment variable NOVA_ACT_API_KEY")
            return NOVA_ACT_API_KEY
            
        # Try to get it from MCP server config
        if hasattr(mcp, 'config') and mcp.config is not None:
            config_data = mcp.config
            
            # Try direct access first
            if isinstance(config_data, dict) and 'novaActApiKey' in config_data:
                NOVA_ACT_API_KEY = config_data['novaActApiKey']
                log(f"✅ Found API key in MCP config (direct)")
                return NOVA_ACT_API_KEY
                
            # Try nested config access
            if isinstance(config_data, dict) and 'config' in config_data and isinstance(config_data['config'], dict):
                if 'novaActApiKey' in config_data['config']:
                    NOVA_ACT_API_KEY = config_data['config']['novaActApiKey']
                    log(f"✅ Found API key in MCP config (nested)")
                    return NOVA_ACT_API_KEY
        
        log("⚠️ Warning: Nova Act API key not found in environment variables or MCP config.")
        log("Please set the NOVA_ACT_API_KEY environment variable or add 'novaActApiKey' to your MCP configuration.")
        return None
    except Exception as e:
        log(f"⚠️ Error accessing config: {str(e)}")
        return os.environ.get("NOVA_ACT_API_KEY")

def initialize_environment():
    """Initialize the environment and do setup that might produce output"""
    global _logging_initialized
    
    # Set the logging flag to prevent duplicate initialization
    if _logging_initialized:
        return
    _logging_initialized = True
    
    # Log NovaAct availability
    if NOVA_ACT_AVAILABLE:
        log("✅ Nova Act SDK is available.")
    else:
        log("❌ Nova Act SDK is not installed.")
        log("Please install it with: pip install nova-act")
    
    # Create the profiles directory if it doesn't exist
    os.makedirs(os.path.join(PROFILES_DIR, DEFAULT_PROFILE), exist_ok=True)

# Fix for issue with string formatting in results
def count_success_failures(step_results):
    """Count the number of successful and failed steps"""
    success_count = sum(1 for s in step_results if s.get('success', False))
    failure_count = sum(1 for s in step_results if not s.get('success', False))
    return success_count, failure_count

# Add logging for session tracking to debug session ID issues
def log_session_info(prefix, session_id, nova_session_id=None):
    """Log information about the session to help debug session ID discrepancies"""
    if nova_session_id and nova_session_id != session_id:
        log(f"⚠️ {prefix}: Session ID mismatch - MCP: {session_id}, Nova: {nova_session_id}")
    else:
        log(f"{prefix}: {session_id}")

@mcp.tool()
async def execute_browser_workflow(starting_url: str, steps: List[str], identity: Optional[str] = DEFAULT_PROFILE) -> str:
    """Execute a multi-step browser workflow from start to finish.
    
    This tool allows you to run a sequence of browser actions in a single workflow,
    similar to the NovaAct script mode example. Each step is executed in sequence,
    and the browser session persists across all steps. The browser session is
    automatically closed when the workflow completes.
    
    Args:
        starting_url: The URL to begin the workflow (must be a valid web address)
        steps: List of specific browser actions to perform in sequence. Each step should be
               a clear, direct instruction (e.g., "search for coffee makers", "select the first result")
        identity: Optional profile name to use for the browser session (defaults to "default")
                 This determines which user data directory is used for the browser session.
    
    Returns:
        A JSON string containing the results of the workflow execution with details about each step
    """
    # Ensure environment is initialized
    initialize_environment()
    
    if not NOVA_ACT_AVAILABLE:
        return BrowserResult(
            success=False,
            text="Error: Nova Act package is not installed. Please install with: pip install nova-act"
        ).model_dump_json()
    
    # Get API key at runtime (it might not be available at import time)
    api_key = get_nova_act_api_key()
    if not api_key:
        return BrowserResult(
            success=False,
            text="Error: Nova Act API key not found. Please check your MCP config or set the NOVA_ACT_API_KEY environment variable."
        ).model_dump_json()
    
    # Generate a new session ID for this workflow
    session_id = generate_session_id()
    log(f"Starting new browser workflow with session ID: {session_id}")
    
    # Create a progress context
    progress_context = {
        "current_step": 0,
        "total_steps": len(steps),
        "current_action": "initializing",
        "is_complete": False,
        "last_update": time.time(),
        "error": None
    }
    
    # Register this session in the global registry
    with session_lock:
        active_sessions[session_id] = {
            "session_id": session_id,
            "identity": identity,
            "status": "initializing",
            "progress": progress_context,
            "url": starting_url,
            "steps": steps,
            "results": [],
            "last_updated": time.time(),
            "nova": None,
            "complete": False
        }
    
    # Setup progress reporting task (keeps connection alive)
    async def report_progress():
        """Send periodic progress updates to keep the connection alive"""
        while not progress_context["is_complete"]:
            # Only send updates if more than PROGRESS_INTERVAL seconds have passed
            current_time = time.time()
            if current_time - progress_context["last_update"] >= PROGRESS_INTERVAL:
                progress_context["last_update"] = current_time
                current_step = progress_context["current_step"]
                total_steps = progress_context["total_steps"]
                action = progress_context["current_action"]
                
                # Log progress to keep the client connection alive
                progress_pct = int((current_step / total_steps) * 100) if total_steps > 0 else 0
                log(f"Progress [{session_id}]: {progress_pct}% - Step {current_step}/{total_steps}: {action}")
                
                # Update session registry
                with session_lock:
                    if session_id in active_sessions:
                        active_sessions[session_id]["last_updated"] = current_time
                        active_sessions[session_id]["status"] = "running" if not progress_context["is_complete"] else "complete"
                        if progress_context["error"]:
                            active_sessions[session_id]["status"] = "error"
                            log(f"Error in session {session_id}: {progress_context['error']}")
            
            # Yield control back to the event loop to prevent blocking
            await asyncio.sleep(0.5)
    
    try:
        # Main workflow function that runs in a ThreadPoolExecutor
        def run_workflow():
            # Ensure the profile directory exists
            profile_dir = os.path.join(PROFILES_DIR, identity)
            os.makedirs(profile_dir, exist_ok=True)
            
            step_results = []
            nova = None
            browser_closed_properly = False
            nova_session_id = None
            
            # Update session registry with status
            with session_lock:
                if session_id in active_sessions:
                    active_sessions[session_id]["status"] = "starting_browser"
            
            try:
                # Update progress context
                progress_context["current_action"] = f"Opening browser to {starting_url}"
                log(f"start session {session_id} on {starting_url}")
                
                # Using the with statement ensures the browser will be properly closed
                # even if an error occurs during execution
                with NovaAct(
                    starting_page=starting_url, 
                    nova_act_api_key=api_key,
                    user_data_dir=profile_dir,
                    headless=False  # Set to False to watch the browser in action
                ) as nova:
                    # Store NovaAct's own session ID for debugging
                    if hasattr(nova, 'session_id'):
                        nova_session_id = nova.session_id
                        log_session_info("NovaAct session started", session_id, nova_session_id)
                    
                    # Register the browser instance in the session registry
                    with session_lock:
                        if session_id in active_sessions:
                            active_sessions[session_id]["nova"] = nova
                            active_sessions[session_id]["status"] = "browser_open"
                            if nova_session_id:
                                active_sessions[session_id]["nova_session_id"] = nova_session_id
                    
                    # Execute each step in sequence
                    for i, step in enumerate(steps):
                        # Update progress context for the current step
                        progress_context["current_step"] = i + 1
                        progress_context["current_action"] = f"Executing: {step}"
                        progress_context["last_update"] = time.time()
                        
                        # Update session registry
                        with session_lock:
                            if session_id in active_sessions:
                                active_sessions[session_id]["status"] = "executing_step"
                                active_sessions[session_id]["last_updated"] = time.time()
                        
                        retry_count = 0
                        step_success = False
                        last_error = None
                        
                        # Try the step with retries if it fails
                        while not step_success and retry_count <= MAX_RETRY_ATTEMPTS:
                            try:
                                # First wait for any page navigation to complete if it's not the first step
                                if i > 0:
                                    progress_context["current_action"] = f"Waiting for page to load before: {step}"
                                    log(f"Waiting for page to load before step {i+1}: {step}")
                                    nova.act("Wait for the page to fully load", timeout=30)
                                
                                # Execute the requested action with timeout
                                log(f"Executing step {i+1}: {step} (attempt {retry_count + 1})")
                                progress_context["current_action"] = f"Executing: {step} (attempt {retry_count + 1})"
                                result = nova.act(step, timeout=DEFAULT_TIMEOUT)
                                log(f"Step {i+1} completed with result type: {type(result)}")
                                
                                # Get the current URL after the action
                                try:
                                    current_url = nova.page.url
                                    with session_lock:
                                        if session_id in active_sessions:
                                            active_sessions[session_id]["url"] = current_url
                                except Exception as e:
                                    log(f"Error getting current URL: {str(e)}")
                                
                                # Print detailed result info for debugging
                                if hasattr(result, 'metadata') and result.metadata:
                                    log(f"Metadata: steps={result.metadata.num_steps_executed}, session={result.metadata.session_id}, act={result.metadata.act_id}")
                                
                                # Extract the response properly - IMPROVED TO HANDLE MORE CASES
                                response_content = None
                                if hasattr(result, 'response') and result.response is not None:
                                    log(f"Response type: {type(result.response)}, value: {result.response}")
                                    
                                    # If it's a string, use it directly
                                    if isinstance(result.response, str):
                                        response_content = result.response
                                    # If it's a dict or has a serializable representation
                                    elif isinstance(result.response, dict):
                                        response_content = result.response
                                    # If it has __dict__ but isn't directly serializable
                                    elif hasattr(result.response, '__dict__'):
                                        try:
                                            response_content = result.response.__dict__
                                        except:
                                            response_content = str(result.response)
                                    # If it has any other JSON-serializable format
                                    else:
                                        try:
                                            # Try to serialize as JSON to check if it's serializable
                                            json.dumps(result.response)
                                            response_content = result.response
                                        except:
                                            # Otherwise convert to string
                                            response_content = str(result.response)
                                else:
                                    # If no response content, add page content for context
                                    try:
                                        page_title = nova.page.title()
                                        current_url = nova.page.url
                                        response_content = f"Page title: {page_title}, URL: {current_url}"
                                        log(f"No response content, using page info: {response_content}")
                                    except Exception as e:
                                        log(f"Error getting page info: {str(e)}")
                                
                                # The step completed successfully
                                step_success = True
                                
                                # Force a small delay to ensure page stabilizes between actions
                                try:
                                    progress_context["current_action"] = f"Waiting for page to stabilize after: {step}"
                                    log(f"Waiting for page to stabilize after step {i+1}")
                                    if i < len(steps) - 1:  # Don't wait after the last step
                                        nova.page.wait_for_timeout(1000)  # 1 second wait
                                except Exception as e:
                                    log(f"Error waiting: {str(e)}")
                                
                                # Record successful step result
                                step_result = {
                                    "step_number": i+1,
                                    "action": step,
                                    "success": True,
                                    "response": response_content,
                                    "steps_taken": result.metadata.num_steps_executed if hasattr(result, 'metadata') and result.metadata else 0,
                                    "session_id": result.metadata.session_id if hasattr(result, 'metadata') and result.metadata else None,
                                    "act_id": result.metadata.act_id if hasattr(result, 'metadata') and result.metadata else None,
                                    "retry_count": retry_count
                                }
                                
                                step_results.append(step_result)
                                
                                # Update session registry with results
                                with session_lock:
                                    if session_id in active_sessions:
                                        active_sessions[session_id]["results"] = step_results
                                
                                # Update session with current NovaAct session ID
                                if hasattr(result, 'metadata') and hasattr(result.metadata, 'session_id'):
                                    act_session_id = result.metadata.session_id
                                    if nova_session_id != act_session_id:
                                        log_session_info("NovaAct session ID changed", session_id, act_session_id)
                                        nova_session_id = act_session_id
                                        with session_lock:
                                            if session_id in active_sessions:
                                                active_sessions[session_id]["nova_session_id"] = nova_session_id
                                
                            except Exception as e:
                                retry_count += 1
                                last_error = str(e)
                                error_tb = traceback.format_exc()
                                log(f"Error in step {i+1} (attempt {retry_count}): {last_error}")
                                log(f"Traceback: {error_tb}")
                                
                                progress_context["current_action"] = f"Error in: {step} - {last_error[:100]}..."
                                progress_context["error"] = last_error
                                
                                # Update session registry with error
                                with session_lock:
                                    if session_id in active_sessions:
                                        active_sessions[session_id]["status"] = "error"
                                
                                # Retry logic for specific errors
                                if "timeout" in last_error.lower() or "navigation" in last_error.lower():
                                    try:
                                        log(f"Trying to refresh page and retry...")
                                        progress_context["current_action"] = f"Refreshing page after error in: {step}"
                                        nova.page.reload()
                                        nova.page.wait_for_timeout(2000)  # 2 second wait after refresh
                                    except Exception as refresh_error:
                                        log(f"Error refreshing page: {str(refresh_error)}")
                                
                                # If we've hit max retries or this isn't a retriable error, break out
                                if retry_count > MAX_RETRY_ATTEMPTS:
                                    log(f"Exceeded maximum retry attempts for step {i+1}")
                                    break
                        
                        # If we've tried all attempts and still failed, record the failure
                        if not step_success:
                            step_result = {
                                "step_number": i+1,
                                "action": step,
                                "success": False,
                                "error": last_error,
                                "retry_count": retry_count
                            }
                            step_results.append(step_result)
                            
                            # Update session registry with results
                            with session_lock:
                                if session_id in active_sessions:
                                    active_sessions[session_id]["results"] = step_results
                
                # Mark that we properly closed the browser
                browser_closed_properly = True
                
                # Update session registry as complete
                with session_lock:
                    if session_id in active_sessions:
                        active_sessions[session_id]["status"] = "complete"
                        active_sessions[session_id]["complete"] = True
                
            except Exception as e:
                # If we have an error during setup, make sure we capture it
                error_message = str(e)
                error_tb = traceback.format_exc()
                log(f"Error in browser workflow: {error_message}")
                log(f"Traceback: {error_tb}")
                
                # Update progress context with the error
                progress_context["error"] = error_message
                progress_context["current_action"] = f"Error: {error_message[:100]}..."
                
                # Update session registry with error
                with session_lock:
                    if session_id in active_sessions:
                        active_sessions[session_id]["status"] = "error"
                        active_sessions[session_id]["error"] = error_message
                
                return BrowserResult(
                    success=False,
                    text=f"Error executing workflow: {error_message}",
                    details={
                        "error": error_message,
                        "traceback": error_tb,
                        "steps_completed": step_results,
                        "session_id": session_id
                    }
                ).model_dump_json()
            finally:
                # This is redundant with the 'with' statement but ensures closure
                # in case something unusual happens
                if nova and hasattr(nova, 'close') and hasattr(nova, '_closed') and not nova._closed:
                    try:
                        log(f"Explicitly closing browser for session {session_id}...")
                        nova.close()
                        browser_closed_properly = True
                    except Exception as close_error:
                        log(f"Error while closing browser: {str(close_error)}")
                
                # Set completion flag for progress reporting
                progress_context["is_complete"] = True
                
                # Update session registry as complete and remove the browser instance reference
                with session_lock:
                    if session_id in active_sessions:
                        active_sessions[session_id]["nova"] = None  # Remove reference to allow GC
                        active_sessions[session_id]["complete"] = True
                        active_sessions[session_id]["status"] = "complete"
            
            # Count successes and failures for the result summary
            success_count, failure_count = count_success_failures(step_results)
            
            # Return structured result with fixed string formatting
            return BrowserResult(
                success=any(step.get("success", False) for step in step_results),
                text=f"Executed {len(steps)} steps in workflow starting at {starting_url}" + 
                     (f" ({success_count} succeeded, {failure_count} failed)"
                      if step_results else ""),
                details={
                    "session_id": session_id,
                    "nova_session_id": nova_session_id,  # Include NovaAct's session ID
                    "starting_url": starting_url,
                    "num_steps": len(steps),
                    "steps": step_results,
                    "browser_closed": browser_closed_properly,
                    "identity": identity
                }
            ).model_dump_json()
        
        # Start the progress reporting task
        progress_task = asyncio.create_task(report_progress())
        
        # Update session registry with task reference
        with session_lock:
            if session_id in active_sessions:
                active_sessions[session_id]["progress_task"] = progress_task
        
        # Run the synchronous workflow code in a thread pool
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(run_workflow)
            
            try:
                # Run the workflow and get the result
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: future.result()
                )
                
                # Mark the progress task as complete
                progress_context["is_complete"] = True
                
                # Wait for the progress task to finish
                try:
                    await asyncio.wait_for(progress_task, timeout=2.0)
                except asyncio.TimeoutError:
                    # If it doesn't finish in time, cancel it
                    progress_task.cancel()
                
                # Return the final result
                return result
                
            except Exception as e:
                # Cancel the future if it's still running
                if not future.done():
                    future.cancel()
                    
                # Mark the progress task as complete with an error
                progress_context["is_complete"] = True
                progress_context["error"] = str(e)
                
                # Wait for the progress task to finish
                try:
                    await asyncio.wait_for(progress_task, timeout=2.0)
                except asyncio.TimeoutError:
                    # If it doesn't finish in time, cancel it
                    progress_task.cancel()
                
                # Re-raise the exception
                raise
                
    except Exception as e:
        error_tb = traceback.format_exc()
        
        # Update session registry with error
        with session_lock:
            if session_id in active_sessions:
                active_sessions[session_id]["status"] = "error"
                active_sessions[session_id]["error"] = str(e)
                active_sessions[session_id]["complete"] = True
        
        return BrowserResult(
            success=False,
            text=f"Error executing workflow starting at {starting_url}: {str(e)}",
            details={
                "error": str(e),
                "traceback": error_tb,
                "session_id": session_id
            }
        ).model_dump_json()

@mcp.tool()
async def get_browser_sessions() -> str:
    """Get the status of all active browser sessions.
    
    This tool returns information about all currently active or recently completed
    browser sessions, including their current status, step progress, and any errors.
    
    Returns:
        A JSON string containing information about all browser sessions
    """
    # Ensure environment is initialized
    initialize_environment()
    
    sessions = get_session_status()
    
    # Clean up old completed sessions that are more than 10 minutes old
    current_time = time.time()
    with session_lock:
        for session_id, session_data in list(active_sessions.items()):
            # Only clean up sessions that are marked complete and are old
            if session_data.get("complete", False) and (current_time - session_data.get("last_updated", 0) > 600):
                log(f"Cleaning up old completed session {session_id}")
                active_sessions.pop(session_id, None)
    
    return json.dumps({
        "success": True,
        "sessions": sessions,
        "active_count": len([s for s in sessions if s.get("status") not in ("complete", "error")]),
        "total_count": len(sessions)
    })

@mcp.tool()
async def test_browser_connection() -> str:
    """Run a quick test to verify browser automation is working correctly.
    
    This tool opens a browser to Google, performs a simple search, and closes the browser.
    It's useful for quickly testing that the NovaAct integration is working properly.
    
    Returns:
        A JSON string containing the test result details
    """
    # Ensure environment is initialized
    initialize_environment()
    
    if not NOVA_ACT_AVAILABLE:
        return BrowserResult(
            success=False,
            text="Error: Nova Act package is not installed. Please install with: pip install nova-act"
        ).model_dump_json()
    
    # Get API key at runtime
    api_key = get_nova_act_api_key()
    if not api_key:
        return BrowserResult(
            success=False,
            text="Error: Nova Act API key not found. Please check your MCP config or set the NOVA_ACT_API_KEY environment variable."
        ).model_dump_json()
    
    # Generate a test session ID
    session_id = generate_session_id()
    log(f"Starting quick browser test with session ID: {session_id}")
    
    test_url = "https://www.google.com"
    test_action = "Search for 'Nova Act test'"
    
    # Define details for result
    start_time = time.time()
    result_details = {
        "session_id": session_id,
        "test_url": test_url,
        "test_action": test_action,
        "start_time": start_time,
        "elapsed_time": None,
        "success": False,
        "error": None,
        "steps_executed": 0
    }
    
    # Define a synchronous function to run in a separate thread
    def run_browser_test():
        try:
            # Create the default profile directory if it doesn't exist
            profile_dir = os.path.join(PROFILES_DIR, DEFAULT_PROFILE)
            os.makedirs(profile_dir, exist_ok=True)
            
            log(f"Opening browser to {test_url} for quick test")
            
            # Open the browser and perform the test action
            with NovaAct(
                starting_page=test_url,
                nova_act_api_key=api_key,
                user_data_dir=profile_dir,
                headless=False
            ) as nova:
                log(f"Browser opened successfully. Executing test action: {test_action}")
                
                # Perform the test action
                result = nova.act(test_action, timeout=60)
                
                # Extract metadata
                if hasattr(result, 'metadata') and result.metadata:
                    result_details["steps_executed"] = result.metadata.num_steps_executed
                    
                    # Store the session ID as a string explicitly
                    if hasattr(result.metadata, 'session_id'):
                        result_details["nova_session_id"] = str(result.metadata.session_id)
                    
                    # Store the act ID as a string explicitly
                    if hasattr(result.metadata, 'act_id'):
                        result_details["act_id"] = str(result.metadata.act_id)
                    
                    log(f"Test completed with {result.metadata.num_steps_executed} steps")
                
                # Get current URL as verification
                try:
                    result_details["final_url"] = nova.page.url
                except Exception as e:
                    log(f"Error getting URL: {str(e)}")
                    result_details["final_url"] = "unknown"
                
                # Test succeeded
                result_details["success"] = True
                
                log("Browser test completed successfully")
                
            return True
        except Exception as e:
            error_message = str(e)
            error_tb = traceback.format_exc()
            log(f"Error in browser test: {error_message}")
            log(f"Traceback: {error_tb}")
            
            # Update result details with error information
            result_details["error"] = error_message
            result_details["traceback"] = error_tb
            return False
    
    try:
        # Run the synchronous code in a thread pool
        with concurrent.futures.ThreadPoolExecutor() as executor:
            # Use run_in_executor to run the synchronous code in a separate thread
            success = await asyncio.get_event_loop().run_in_executor(
                executor, run_browser_test
            )
            
            # Calculate elapsed time
            result_details["elapsed_time"] = time.time() - start_time
            
            # Ensure serializable - convert non-serializable values to strings
            for key, value in list(result_details.items()):
                try:
                    # Test if the value is JSON serializable
                    json.dumps({key: value})
                except (TypeError, OverflowError):
                    # If not serializable, convert to string
                    log(f"Converting non-serializable value for {key} to string")
                    result_details[key] = str(value)
    except Exception as e:
        # Handle any exception that occurs in the thread execution
        log(f"Exception running browser test in thread: {str(e)}")
        result_details["error"] = str(e)
        result_details["traceback"] = traceback.format_exc()
        result_details["elapsed_time"] = time.time() - start_time
    
    # Create the result object
    result = BrowserResult(
        success=result_details.get("success", False),
        text=f"Browser test {'successful' if result_details.get("success", False) else 'failed'} " +
             f"in {result_details.get("elapsed_time", 0):.2f} seconds" +
             (f" ({result_details.get("steps_executed", 0)} steps executed)" 
              if result_details.get("success", False) else ""),
        details=result_details
    )
    
    # Ensure the returned JSON is valid by trying to parse it first
    try:
        result_json = result.model_dump_json()
        # Validate the JSON by parsing it
        json.loads(result_json)
        return result_json
    except Exception as e:
        # If JSON serialization fails, return a simpler error response
        log(f"Error serializing result to JSON: {str(e)}")
        return json.dumps({
            "success": False, 
            "text": f"Browser test completed but response serialization failed: {str(e)}",
            "details": {
                "error": str(e),
                "session_id": session_id,
                "elapsed_time": time.time() - start_time
            }
        })

@mcp.tool()
async def browser_session(action: str, session_id: Optional[str] = None, url: Optional[str] = None, instruction: Optional[str] = None, extraction_query: Optional[str] = None, headless: Optional[bool] = True) -> str:
    """Manage and interact with browser sessions.
    
    This tool allows you to create, manage, and interact with browser sessions.
    
    Args:
        action: The operation to perform ("start", "execute", "extract", "end")
        session_id: Required for all actions except "start"
        url: Starting URL when action is "start" or navigation URL
        instruction: Natural language instruction for "execute" action
        extraction_query: What to extract for "extract" action
        headless: Whether to run in headless mode (for "start")
    
    Returns:
        A JSON string containing the results of the action
    """
    # Ensure environment is initialized
    initialize_environment()
    
    if not NOVA_ACT_AVAILABLE:
        return BrowserResult(
            success=False,
            text="Error: Nova Act package is not installed. Please install with: pip install nova-act"
        ).model_dump_json()
    
    # Get API key at runtime
    api_key = get_nova_act_api_key()
    if not api_key:
        return BrowserResult(
            success=False,
            text="Error: Nova Act API key not found. Please check your MCP config or set the NOVA_ACT_API_KEY environment variable."
        ).model_dump_json()
    
    # Handle the "start" action
    if action == "start":
        if not url:
            return BrowserResult(
                success=False,
                text="Error: URL is required for 'start' action."
            ).model_dump_json()
        
        # Generate a new session ID
        session_id = generate_session_id()
        log(f"Starting new browser session with session ID: {session_id}")
        
        # Create a progress context
        progress_context = {
            "current_step": 0,
            "total_steps": 1,
            "current_action": "initializing",
            "is_complete": False,
            "last_update": time.time(),
            "error": None
        }
        
        # Register this session in the global registry
        with session_lock:
            active_sessions[session_id] = {
                "session_id": session_id,
                "identity": DEFAULT_PROFILE,
                "status": "initializing",
                "progress": progress_context,
                "url": url,
                "steps": [],
                "results": [],
                "last_updated": time.time(),
                "nova": None,
                "complete": False
            }
        
        # Start the browser session
        try:
            profile_dir = os.path.join(PROFILES_DIR, DEFAULT_PROFILE)
            os.makedirs(profile_dir, exist_ok=True)
            
            with NovaAct(
                starting_page=url,
                nova_act_api_key=api_key,
                user_data_dir=profile_dir,
                headless=headless
            ) as nova:
                # Store NovaAct's own session ID for debugging
                if hasattr(nova, 'session_id'):
                    nova_session_id = nova.session_id
                    log_session_info("NovaAct session started", session_id, nova_session_id)
                
                # Register the browser instance in the session registry
                with session_lock:
                    if session_id in active_sessions:
                        active_sessions[session_id]["nova"] = nova
                        active_sessions[session_id]["status"] = "browser_open"
                        if nova_session_id:
                            active_sessions[session_id]["nova_session_id"] = nova_session_id
                
                # Return the session ID and initial status
                return json.dumps({
                    "session_id": session_id,
                    "status": "browser_open",
                    "current_url": nova.page.url,
                    "page_title": nova.page.title(),
                    "action_taken": "Browser session started",
                    "visible_elements_summary": "N/A",
                    "extracted_data": None,
                    "errors": None,
                    "screenshot_base64": None
                })
        
        except Exception as e:
            error_message = str(e)
            error_tb = traceback.format_exc()
            log(f"Error starting browser session: {error_message}")
            log(f"Traceback: {error_tb}")
            
            # Update progress context with the error
            progress_context["error"] = error_message
            progress_context["current_action"] = f"Error: {error_message[:100]}..."
            
            # Update session registry with error
            with session_lock:
                if session_id in active_sessions:
                    active_sessions[session_id]["status"] = "error"
                    active_sessions[session_id]["error"] = error_message
            
            return BrowserResult(
                success=False,
                text=f"Error starting browser session: {error_message}",
                details={
                    "error": error_message,
                    "traceback": error_tb,
                    "session_id": session_id
                }
            ).model_dump_json()
    
    # Handle the "execute" action
    elif action == "execute":
        if not session_id or not instruction:
            return BrowserResult(
                success=False,
                text="Error: session_id and instruction are required for 'execute' action."
            ).model_dump_json()
        
        # Get the session data
        with session_lock:
            session_data = active_sessions.get(session_id)
        
        if not session_data:
            return BrowserResult(
                success=False,
                text=f"Error: No active session found with session_id: {session_id}"
            ).model_dump_json()
        
        # Execute the instruction
        try:
            nova = session_data.get("nova")
            if not nova:
                return BrowserResult(
                    success=False,
                    text=f"Error: No active browser instance found for session_id: {session_id}"
                ).model_dump_json()
            
            result = nova.act(instruction, timeout=DEFAULT_TIMEOUT)
            
            # Get the current URL after the action
            current_url = nova.page.url
            page_title = nova.page.title()
            
            # Extract the response properly
            response_content = None
            if hasattr(result, 'response') and result.response is not None:
                if isinstance(result.response, str):
                    response_content = result.response
                elif isinstance(result.response, dict):
                    response_content = result.response
                elif hasattr(result.response, '__dict__'):
                    try:
                        response_content = result.response.__dict__
                    except:
                        response_content = str(result.response)
                else:
                    try:
                        json.dumps(result.response)
                        response_content = result.response
                    except:
                        response_content = str(result.response)
            else:
                response_content = f"Page title: {page_title}, URL: {current_url}"
            
            # Update session registry with results
            with session_lock:
                if session_id in active_sessions:
                    active_sessions[session_id]["url"] = current_url
                    active_sessions[session_id]["results"].append({
                        "action": instruction,
                        "response": response_content
                    })
            
            return json.dumps({
                "session_id": session_id,
                "status": "action_executed",
                "current_url": current_url,
                "page_title": page_title,
                "action_taken": instruction,
                "visible_elements_summary": "N/A",
                "extracted_data": None,
                "errors": None,
                "screenshot_base64": None
            })
        
        except Exception as e:
            error_message = str(e)
            error_tb = traceback.format_exc()
            log(f"Error executing instruction: {error_message}")
            log(f"Traceback: {error_tb}")
            
            return BrowserResult(
                success=False,
                text=f"Error executing instruction: {error_message}",
                details={
                    "error": error_message,
                    "traceback": error_tb,
                    "session_id": session_id
                }
            ).model_dump_json()
    
    # Handle the "extract" action
    elif action == "extract":
        if not session_id or not extraction_query:
            return BrowserResult(
                success=False,
                text="Error: session_id and extraction_query are required for 'extract' action."
            ).model_dump_json()
        
        # Get the session data
        with session_lock:
            session_data = active_sessions.get(session_id)
        
        if not session_data:
            return BrowserResult(
                success=False,
                text=f"Error: No active session found with session_id: {session_id}"
            ).model_dump_json()
        
        # Execute the extraction query
        try:
            nova = session_data.get("nova")
            if not nova:
                return BrowserResult(
                    success=False,
                    text=f"Error: No active browser instance found for session_id: {session_id}"
                ).model_dump_json()
            
            result = nova.extract(extraction_query, timeout=DEFAULT_TIMEOUT)
            
            # Get the current URL after the action
            current_url = nova.page.url
            page_title = nova.page.title()
            
            # Extract the response properly
            response_content = None
            if hasattr(result, 'response') and result.response is not None:
                if isinstance(result.response, str):
                    response_content = result.response
                elif isinstance(result.response, dict):
                    response_content = result.response
                elif hasattr(result.response, '__dict__'):
                    try:
                        response_content = result.response.__dict__
                    except:
                        response_content = str(result.response)
                else:
                    try:
                        json.dumps(result.response)
                        response_content = result.response
                    except:
                        response_content = str(result.response)
            else:
                response_content = f"Page title: {page_title}, URL: {current_url}"
            
            # Update session registry with results
            with session_lock:
                if session_id in active_sessions:
                    active_sessions[session_id]["url"] = current_url
                    active_sessions[session_id]["results"].append({
                        "action": extraction_query,
                        "response": response_content
                    })
            
            return json.dumps({
                "session_id": session_id,
                "status": "data_extracted",
                "current_url": current_url,
                "page_title": page_title,
                "action_taken": extraction_query,
                "visible_elements_summary": "N/A",
                "extracted_data": response_content,
                "errors": None,
                "screenshot_base64": None
            })
        
        except Exception as e:
            error_message = str(e)
            error_tb = traceback.format_exc()
            log(f"Error extracting data: {error_message}")
            log(f"Traceback: {error_tb}")
            
            return BrowserResult(
                success=False,
                text=f"Error extracting data: {error_message}",
                details={
                    "error": error_message,
                    "traceback": error_tb,
                    "session_id": session_id
                }
            ).model_dump_json()
    
    # Handle the "end" action
    elif action == "end":
        if not session_id:
            return BrowserResult(
                success=False,
                text="Error: session_id is required for 'end' action."
            ).model_dump_json()
        
        # Get the session data
        with session_lock:
            session_data = active_sessions.get(session_id)
        
        if not session_data:
            return BrowserResult(
                success=False,
                text=f"Error: No active session found with session_id: {session_id}"
            ).model_dump_json()
        
        # End the browser session
        try:
            nova = session_data.get("nova")
            if nova and hasattr(nova, 'close') and not getattr(nova, '_closed', True):
                nova.close()
            
            # Update session registry
            with session_lock:
                if session_id in active_sessions:
                    active_sessions[session_id]["status"] = "ended"
                    active_sessions[session_id]["complete"] = True
            
            return json.dumps({
                "session_id": session_id,
                "status": "ended",
                "current_url": None,
                "page_title": None,
                "action_taken": "Browser session ended",
                "visible_elements_summary": "N/A",
                "extracted_data": None,
                "errors": None,
                "screenshot_base64": None
            })
        
        except Exception as e:
            error_message = str(e)
            error_tb = traceback.format_exc()
            log(f"Error ending browser session: {error_message}")
            log(f"Traceback: {error_tb}")
            
            return BrowserResult(
                success=False,
                text=f"Error ending browser session: {error_message}",
                details={
                    "error": error_message,
                    "traceback": error_tb,
                    "session_id": session_id
                }
            ).model_dump_json()
    
    else:
        return BrowserResult(
            success=False,
            text=f"Error: Unknown action '{action}'. Valid actions are 'start', 'execute', 'extract', 'end'."
        ).model_dump_json()

def main():
    """Main function to run the MCP server"""
    # Perform initialization and logging only when actually running the server
    initialize_environment()
    
    # Print a welcome message with setup instructions
    log("\n=== Nova Act MCP Server ===")
    log("Status:")
    
    if not NOVA_ACT_AVAILABLE:
        log("- Nova Act SDK: Not installed (required)")
        log("  Install with: pip install nova-act")
    else:
        log("- Nova Act SDK: Installed ✓")
    
    # Get the API key and update the status message
    api_key = get_nova_act_api_key()
    if (api_key):
        log("- API Key: Found in configuration ✓")
    else:
        log("- API Key: Not found ❌")
        log("  Please add 'novaActApiKey' to your MCP config or set NOVA_ACT_API_KEY environment variable")
    
    log("- Tool: execute_browser_workflow - Run multi-step browser actions ✓")
    log("- Tool: test_browser_connection - Quick browser test ✓")
    log("- Tool: get_browser_sessions - Get active browser sessions ✓")
    log("- Tool: browser_session - Manage and interact with browser sessions ✓")
    
    log("\nStarting MCP server...")
    # Initialize and run the server
    mcp.run(transport='stdio')

if __name__ == "__main__":
    main()
