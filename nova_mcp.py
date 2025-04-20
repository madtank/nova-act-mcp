import asyncio
import atexit
import base64
import concurrent.futures
import json
import os
import re
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal

# Third-party imports
from pydantic import BaseModel

# Local application/library specific imports
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

# Global browser session registry - add type hint for clarity
active_sessions: Dict[str, Dict[str, Any]] = {}
session_lock = threading.Lock()

# Global variable to track if logging is initialized
_logging_initialized = False

# Global API key variable
NOVA_ACT_API_KEY = None

# Flag to check for NovaAct availability - initialize without logging
NOVA_ACT_AVAILABLE = False
try:
    from nova_act import NovaAct
    # Import error classes for specific error handling
    try:
        from nova_act import ActError
        from nova_act.types.act_errors import ActGuardrailsError
    except ImportError:
        # Define dummy exceptions if SDK not installed with these classes
        class ActError(Exception): pass
        class ActGuardrailsError(Exception): pass
    NOVA_ACT_AVAILABLE = True
except ImportError:
    # Define dummy exceptions if SDK not installed
    class ActError(Exception): pass
    class ActGuardrailsError(Exception): pass
    pass

# Utility function to log to stderr instead of stdout
# This prevents log messages from interfering with JSON-RPC communication
def log(message):
    """Log messages to stderr instead of stdout to prevent interference with JSON-RPC"""
    print(f"[NOVA_LOG] {message}", file=sys.stderr, flush=True)

# Clean up function to ensure all browser sessions are closed on exit
def cleanup_browser_sessions():
    log("Cleaning up browser sessions...")
    with session_lock:
        sessions_to_close = list(active_sessions.items())
    
    for session_id, session_data in sessions_to_close:
        nova_instance = session_data.get("nova_instance")
        executor = session_data.get("executor")
        
        if (nova_instance):
            log(f"Attempting to close lingering session: {session_id}")
            try:
                # Try to properly close the NovaAct instance
                if hasattr(nova_instance, 'close') and callable(nova_instance.close):
                    nova_instance.close()
                    log(f"Closed instance for session {session_id}")
                elif hasattr(nova_instance, '__exit__') and callable(nova_instance.__exit__):
                    # Fallback to context manager exit if no close method
                    nova_instance.__exit__(None, None, None)
                    log(f"Called __exit__ for session {session_id}")
                else:
                    log(f"Warning: No close() or __exit__ method found on NovaAct instance for session {session_id}. Browser might remain open.")
            except Exception as e:
                log(f"Error closing session {session_id} during cleanup: {e}")
        
        # Shutdown the executor if it exists
        if executor:
            try:
                executor.shutdown(wait=False)
                log(f"Shutdown executor for session {session_id}")
            except Exception:
                pass
                
        # Remove from registry after attempting close
        with session_lock:
            active_sessions.pop(session_id, None)

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

# Helper function to create proper JSON-RPC 2.0 response
def create_jsonrpc_response(id, result=None, error=None):
    """Create a properly formatted JSON-RPC 2.0 response"""
    response = {
        "jsonrpc": "2.0",
        "id": id
    }
    
    if error is not None:
        response["error"] = error
    else:
        response["result"] = result
        
    # Return as Python dict, not as JSON string - let the MCP framework handle serialization
    return response

# Flag to enable debug mode - false by default, can be enabled with env var
DEBUG_MODE = os.environ.get("NOVA_MCP_DEBUG", "0") == "1"

def extract_agent_thinking(result, nova=None, logs_dir=None, instruction=None):
    """
    Extract agent thinking from Nova Act results using multiple methods.
    """
    agent_messages = []
    extraction_methods_tried = []
    debug_info = {}
    
    # Method 1: Direct attributes (unchanged)
    
    # Method 2: Parse HTML output file - Updated regex pattern!
    extraction_methods_tried.append("html_file")
    if hasattr(result, 'metadata') and result.metadata:
        nova_session_id = result.metadata.session_id
        nova_act_id = result.metadata.act_id
        debug_info["nova_session_id"] = nova_session_id
        debug_info["nova_act_id"] = nova_act_id
        
        # Get logs directory
        if not logs_dir and nova and hasattr(nova, 'logs_directory'):
            logs_dir = nova.logs_directory
            
        # Try both direct path and searching through temp directories
        html_paths = []
        
        # Direct path attempt
        if logs_dir and nova_session_id and nova_act_id:
            direct_path = os.path.join(logs_dir, nova_session_id, f"act_{nova_act_id}_output.html")
            if os.path.exists(direct_path):
                html_paths.append(direct_path)
        
        # Search in temp directories
        temp_dir = tempfile.gettempdir()
        for root, dirs, files in os.walk(temp_dir):
            if nova_session_id in root:
                for file in files:
                    if file.startswith(f"act_{nova_act_id}") and file.endswith("_output.html"):
                        html_paths.append(os.path.join(root, file))
        
        debug_info["html_paths_found"] = html_paths
        
        # Process all found HTML files
        for html_path in html_paths:
            log(f"Parsing HTML file: {html_path}")
            try:
                with open(html_path, 'r') as f:
                    html_content = f.read()
                
                # Log a snippet for debugging
                log(f"HTML snippet (first 100 chars): {html_content[:100]}")
                
                # Updated pattern to match both formats
                think_patterns = re.findall(r'(?:\w+> )?think\("([^"]*)"\);?', html_content, re.DOTALL)
                
                # Also try a more direct approach looking for pre tags
                if not think_patterns:
                    # This is a simple pattern that might work with the HTML structure
                    think_patterns = re.findall(r'<pre[^>]*>(?:\w+> )?think\("([^"]*?)"\);?</pre>', html_content, re.DOTALL)
                
                # Process extracted patterns
                for pattern in think_patterns:
                    # Clean up the content
                    cleaned = pattern.replace('\\n', '\n').replace('\\\"', '"')
                    agent_messages.append(cleaned)
                
                log(f"Extracted {len(think_patterns)} thinking patterns from HTML")
                debug_info["html_patterns_found"] = think_patterns
                debug_info["source"] = "html_file"
                
                # If we found thinking, break out of the loop
                if think_patterns:
                    break
                    
            except Exception as e:
                log(f"Error parsing HTML file: {str(e)}")
                debug_info["html_error"] = str(e)
    
    # Method 3: Parse logs directly (updated pattern)
    extraction_methods_tried.append("direct_logs")
    if not agent_messages and nova and hasattr(nova, 'get_logs') and callable(getattr(nova, 'get_logs', None)):
        try:
            logs = nova.get_logs()
            debug_info["log_count"] = len(logs)
            
            think_count = 0
            for log_line in logs:
                if 'think("' in log_line:
                    # Updated pattern to handle session prefixes
                    thinking_match = re.search(r'(?:\w+> )?think\("([^"]*)"\)', log_line)
                    if thinking_match:
                        thought = thinking_match.group(1).replace('\\n', '\n').replace('\\\"', '"')
                        if thought not in agent_messages:
                            agent_messages.append(thought)
                            think_count += 1
                            
            if think_count > 0:
                debug_info["source"] = "direct_logs"
                debug_info["think_patterns_found"] = think_count
        except Exception as e:
            log(f"Error parsing logs: {str(e)}")
            debug_info["logs_error"] = str(e)
    
    # Method 4 (unchanged)
    
    # Fallback method (unchanged)
    
    debug_info["extraction_methods"] = extraction_methods_tried
    debug_info["message_count"] = len(agent_messages)
    
    return agent_messages, debug_info

@mcp.tool(name="list_browser_sessions", description="List all active and recent web browser sessions managed by Nova Act agent")
async def list_browser_sessions() -> str:
    """List all active and recent web browser sessions managed by Nova Act agent.

     Returns a JSON string with session IDs, status, progress, and error details for each session."""
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
                
                # Close NovaAct instance if present
                nova_instance = session_data.get("nova_instance")
                if nova_instance:
                    try:
                        if hasattr(nova_instance, 'close') and callable(nova_instance.close):
                            nova_instance.close()
                        elif hasattr(nova_instance, '__exit__') and callable(nova_instance.__exit__):
                            nova_instance.__exit__(None, None, None)
                    except Exception as e:
                        log(f"Error closing NovaAct during cleanup: {e}")
                
                # Shutdown the executor if it exists
                executor = session_data.get("executor")
                if executor:
                    try:
                        executor.shutdown(wait=False)
                        log(f"Shutdown executor for old session {session_id}")
                    except Exception:
                        pass
                
                active_sessions.pop(session_id, None)
    
    result = {
        "sessions": sessions,
        "active_count": len([s for s in sessions if s.get("status") not in ("complete", "error")]),
        "total_count": len(sessions)
    }
    
    # Get the request ID from the MCP context if available
    request_id = getattr(mcp, 'request_id', 1)
    
    return create_jsonrpc_response(request_id, result)


@mcp.tool(name="control_browser", description="Control a web browser session via Nova Act agent in multiple steps: start, execute, and end sessions. Screenshot embedding is currently disabled due to token limitations.")
async def browser_session(
    action: Literal["start", "execute", "end"] = "execute",
    session_id: Optional[str] = None,
    url: Optional[str] = None,
    instruction: Optional[str] = None,
    headless: bool = False,  # Changed default to False
    username: Optional[str] = None,
    password: Optional[str] = None,
    # embedScreenshot: Optional[bool] = False,  # Removed parameter
    schema: Optional[dict] = None,
    debug: Optional[bool] = False
) -> str:
    """Control a web browser session via Nova Act agent.

    Perform actions in multiple steps: start a session, execute navigation or agent instructions, and end a session.

    If action == "execute" and no session_id is supplied, a new session is started automatically (defaulting to non-headless).

    NOTE: Screenshot embedding ('embedScreenshot' parameter) has been temporarily disabled
          in the function signature due to excessive token usage with current LLMs.
          The underlying screenshot code remains for potential future use or debugging.
          The path to Nova Act's HTML execution log will be provided in the result if found.

    Args:
        action: One of "start", "execute", or "end".
        session_id: Session identifier (not needed for "start").
        url: Initial or navigation URL.
        instruction: Instruction text for navigation actions ("execute").
        headless: Run browser in headless mode when starting (default is False).
        username: Username text typed directly with Playwright (optional).
        password: Password text typed directly with Playwright (optional).
        schema:      Optional JSON schema forwarded to nova.act().
        debug:       If true, include extra debug keys in the result.

    Returns:
        JSON string with action result and session status.
    """
    # Ensure environment is initialized
    initialize_environment()
    
    # Get the request ID from the MCP context if available
    request_id = getattr(mcp, 'request_id', 1)
    
    if not NOVA_ACT_AVAILABLE:
        error = {
            "code": -32603,
            "message": "Nova Act package is not installed. Please install with: pip install nova-act",
            "data": None
        }
        return create_jsonrpc_response(request_id, error=error)
    
    # Get API key at runtime
    api_key = get_nova_act_api_key()
    if not api_key:
        error = {
            "code": -32603,
            "message": "Nova Act API key not found. Please check your MCP config or set the NOVA_ACT_API_KEY environment variable.",
            "data": None
        }
        return create_jsonrpc_response(request_id, error=error)
    
    # Handle the "start" action
    if action == "start":
        if not url:
            error = {
                "code": -32602, 
                "message": "URL is required for 'start' action.",
                "data": None
            }
            return create_jsonrpc_response(request_id, error=error)
        
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
                "complete": False,
                "nova_instance": None,  # Will store the NovaAct instance
                "executor": None        # Single-thread executor for this session
            }
        
        # Create a dedicated single-thread executor – NovaAct is not thread-safe.
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        with session_lock:
            active_sessions[session_id]["executor"] = executor
        
        # Define a synchronous function to run in a separate thread
        def start_browser_session():
            nova_instance = None
            try:
                profile_dir = os.path.join(PROFILES_DIR, DEFAULT_PROFILE)
                os.makedirs(profile_dir, exist_ok=True)
                
                log(f"[{session_id}] Opening browser to {url}")
                
                # Create NovaAct instance directly (not using context manager)
                nova_instance = NovaAct(
                    starting_page=url,
                    nova_act_api_key=api_key,
                    user_data_dir=profile_dir,
                    headless=headless
                )
                
                # --- Explicitly start the client - THIS FIXES THE ERROR ---
                log(f"[{session_id}] Calling nova_instance.start()...")
                if hasattr(nova_instance, 'start') and callable(nova_instance.start):
                    nova_instance.start()
                    log(f"[{session_id}] nova_instance.start() completed.")
                else:
                    # This case should ideally not happen based on docs/error
                    log(f"[{session_id}] Warning: nova_instance does not have a callable start() method!")
                
                # Now it should be safe to access nova_instance.page
                log(f"[{session_id}] Accessing page properties...")
                
                # Wait for initial page to load
                try:
                    nova_instance.page.wait_for_load_state('domcontentloaded', timeout=15000)
                except Exception as wait_e:
                    log(f"[{session_id}] Info: Initial page wait timed out or errored: {wait_e}")
                
                # Store NovaAct's own session ID for debugging
                nova_session_id = None
                if hasattr(nova_instance, 'session_id'):
                    nova_session_id = nova_instance.session_id
                    log_session_info("NovaAct session started", session_id, nova_session_id)
                
                # Take a screenshot
                screenshot_data = None
                try:
                    screenshot_bytes = nova_instance.page.screenshot()
                    screenshot_data = base64.b64encode(screenshot_bytes).decode('utf-8')
                except Exception as e:
                    log(f"Error taking screenshot: {str(e)}")
                
                # Get initial page info
                current_url = nova_instance.page.url
                page_title = nova_instance.page.title()
                log(f"[{session_id}] Browser ready at URL: {current_url}")
                
                # Update session registry with results and store the nova instance
                with session_lock:
                    if session_id in active_sessions:
                        active_sessions[session_id]["status"] = "browser_ready"
                        active_sessions[session_id]["url"] = current_url
                        active_sessions[session_id]["nova_instance"] = nova_instance
                        active_sessions[session_id]["last_updated"] = time.time()
                        active_sessions[session_id]["error"] = None  # Clear previous error
                        if nova_session_id:
                            active_sessions[session_id]["nova_session_id"] = nova_session_id
                    else:
                        # Session might have been cancelled/ended externally
                        log(f"[{session_id}] Warning: Session disappeared before instance could be stored.")
                        # Need to clean up the instance we just created
                        if nova_instance:
                            try:
                                if hasattr(nova_instance, 'close') and callable(nova_instance.close): 
                                    nova_instance.close()
                                elif hasattr(nova_instance, '__exit__'): 
                                    nova_instance.__exit__(None, None, None)
                            except Exception:
                                pass  # Avoid errors during cleanup
                        return None  # Indicate failure to store
                
                # Create result formatted for JSON-RPC
                result = {
                    "session_id": session_id,
                    "url": current_url,
                    "title": page_title,
                    "status": "ready"
                }
                
                return result
                
            except Exception as e:
                error_message = str(e)
                error_tb = traceback.format_exc()
                log(f"[{session_id}] Error during start_browser_session: {error_message}")
                log(f"Traceback: {error_tb}")
                
                # Clean up the instance if it was partially created
                if nova_instance:
                    try:
                        log(f"[{session_id}] Attempting cleanup after error...")
                        if hasattr(nova_instance, 'close') and callable(nova_instance.close):
                            nova_instance.close()
                        elif hasattr(nova_instance, '__exit__'):
                            nova_instance.__exit__(None, None, None)
                    except Exception as cleanup_e:
                        log(f"[{session_id}] Error during cleanup after failed start: {cleanup_e}")
                
                # Update session registry with error
                with session_lock:
                    if session_id in active_sessions:
                        active_sessions[session_id]["status"] = "error"
                        active_sessions[session_id]["error"] = error_message
                        active_sessions[session_id]["nova_instance"] = None  # Ensure no broken instance is stored
                        active_sessions[session_id]["last_updated"] = time.time()
                
                # Return the error in JSON-RPC format
                raise Exception(f"Error starting browser session: {error_message}")
        
        # Run the synchronous code in the session's dedicated thread
        try:
            # Use run_in_executor to run the synchronous code in the session's thread
            result = await asyncio.get_event_loop().run_in_executor(
                executor, start_browser_session
            )
            
            # Return the result as a proper JSON-RPC response
            return create_jsonrpc_response(request_id, result)
                
        except Exception as e:
            error_message = str(e)
            error_tb = traceback.format_exc()
            log(f"Error in thread execution: {error_message}")
            log(f"Traceback: {error_tb}")
            
            error = {
                "code": -32603,
                "message": f"Error starting browser session: {error_message}",
                "data": {
                    "traceback": error_tb,
                    "session_id": session_id
                }
            }
            
            return create_jsonrpc_response(request_id, error=error)

    # Handle the "execute" action
    elif action == "execute":
        # Require session_id for execute (no longer auto-starting)
        if not session_id:
            error = {"code": -32602, "message": "session_id is required for 'execute' action. Please 'start' a session first.", "data": None}
            return create_jsonrpc_response(request_id, error=error)
            
        # Require instruction or credentials for execution
        if not instruction and not (username or password or schema):
            error = {"code": -32602, "message": "instruction, schema, or credentials are required for 'execute' action.", "data": None}
            return create_jsonrpc_response(request_id, error=error)
        
        # Get the session data and the NovaAct instance
        with session_lock:
            session_data = active_sessions.get(session_id)
        
        if not session_data or session_data.get("status") == "ended":
            error = {
                "code": -32602,
                "message": f"No active session found or session ended: {session_id}",
                "data": None
            }
            return create_jsonrpc_response(request_id, error=error)
        
        # Get the NovaAct instance and session's dedicated executor
        nova_instance = session_data.get("nova_instance")
        executor = session_data.get("executor")
        
        if not nova_instance:
            error = {
                "code": -32603, 
                "message": f"NovaAct instance missing for session: {session_id}",
                "data": None
            }
            return create_jsonrpc_response(request_id, error=error)
            
        if executor is None:
            error = {
                "code": -32603,
                "message": "Internal error – executor missing for session.",
                "data": {"session_id": session_id},
            }
            return create_jsonrpc_response(request_id, error=error)
        
        # Define a synchronous function to run in a separate thread
        def execute_instruction():
            original_instruction = instruction  # Keep original for logging/reporting
            instruction_to_execute = instruction  # This one might be modified
            output_html_paths = []  # Keep track of HTML output paths
            action_handled_directly = False  # Flag to track if we used Playwright directly
        
            try:
                # If a URL is provided for execute, navigate first
                current_url = session_data.get("url")
                if url and nova_instance.page.url != url:
                    log(f"[{session_id}] Navigating to execute URL: {url}")
                    try:
                        # Use the SDK's navigation if available, otherwise use page.goto
                        if hasattr(nova_instance, 'go_to_url'):
                            nova_instance.go_to_url(url)  # Use SDK's method per docs
                        else:
                            nova_instance.page.goto(url, wait_until='domcontentloaded', timeout=60000)
                        current_url = url
                        log(f"[{session_id}] Navigation complete.")
                    except Exception as nav_e:
                        raise Exception(f"Failed to navigate to execute URL {url}: {nav_e}")
                
                # Optional credential typing
                if username or password:
                    try:
                        log(f"[{session_id}] Handling credentials...")
                        # Prefer explicit selectors
                        if username:
                            nova_instance.page.fill(
                                "input#username, input[name='username'], input[type='text'], input[name*='user']",
                                username,
                                timeout=5000
                            )
                        if password:
                            nova_instance.page.fill(
                                "input#password, input[name='password'], input[type='password']",
                                password,
                                timeout=5000
                            )
                    except Exception:
                        log(f"[{session_id}] Falling back to focus/type for credentials")
                        # Fallback: focus + type
                        if username:
                            nova_instance.act("focus the username field")
                            nova_instance.page.keyboard.type(username)
                        if password:
                            nova_instance.act("focus the password field")
                            nova_instance.page.keyboard.type(password)

                    if not original_instruction:  # Auto-click Login if no other instruction
                        log(f"[{session_id}] Auto-clicking login after credentials.")
                        instruction_to_execute = "click the Login button"  # Set instruction
                        original_instruction = "[Auto-Login]"  # For reporting
                    else:
                        # Sanitize the instruction that WILL be executed
                        log(f"[{session_id}] Sanitizing instruction after credential input.")
                        safe_instruction = original_instruction
                        if username:
                            safe_instruction = safe_instruction.replace(username, "«username»")
                        if password:
                            safe_instruction = safe_instruction.replace(password, "«password»")
                        safe_instruction = re.sub(r"(?i)password", "••••••", safe_instruction)
                        instruction_to_execute = safe_instruction
                
                # --- Direct Playwright Action Interpretation ---
                # Example: Look for "Type 'text' into 'selector'" pattern
                type_match = re.match(r"^\s*Type\s+['\"](.*)['\"]\s+into\s+element\s+['\"](.*)['\"]\s*$",
                                      original_instruction or "", re.IGNORECASE)

                if type_match:
                    text_to_type = type_match.group(1)
                    element_selector = type_match.group(2)
                    log(f"[{session_id}] Handling instruction directly: Typing '{text_to_type}' into '{element_selector}'")
                    try:
                        # Use page.fill which is often better for inputs
                        nova_instance.page.fill(element_selector, text_to_type, timeout=10000)
                        # Alternatively, use type:
                        # nova_instance.page.locator(element_selector).type(text_to_type, delay=50, timeout=10000)
                        log(f"[{session_id}] Direct fill successful.")
                        action_handled_directly = True
                        result = None  # No result object from nova.act needed
                        response_content = f"Successfully typed text into '{element_selector}' using direct Playwright call."

                    except Exception as direct_e:
                        log(f"[{session_id}] Error during direct Playwright fill/type: {direct_e}")
                        raise Exception(f"Failed direct Playwright action: {direct_e}")  # Propagate error
                
                # --- Look for "Click element 'selector'" pattern ---
                elif re.match(r"^\s*Click\s+element\s+['\"](.*)['\"]\s*$", original_instruction or "", re.IGNORECASE):
                    element_selector = re.match(r"^\s*Click\s+element\s+['\"](.*)['\"]\s*$", original_instruction, re.IGNORECASE).group(1)
                    log(f"[{session_id}] Handling click directly: Clicking element '{element_selector}'")
                    try:
                        nova_instance.page.click(element_selector, timeout=10000)
                        log(f"[{session_id}] Direct click successful.")
                        action_handled_directly = True
                        result = None
                        response_content = f"Successfully clicked element '{element_selector}' using direct Playwright call."
                    except Exception as direct_e:
                        log(f"[{session_id}] Error during direct Playwright click: {direct_e}")
                        raise Exception(f"Failed direct Playwright click: {direct_e}")
                
                # --- If not handled directly, try using nova.act (as fallback/default) ---
                elif instruction_to_execute or schema:
                    log(f"[{session_id}] Passing instruction to nova.act: {instruction_to_execute}")
                    result = nova_instance.act(
                        instruction_to_execute or "Observe the page and respond based on the schema.",
                        timeout=DEFAULT_TIMEOUT,
                        schema=schema  # Pass schema if provided
                    )
                    
                    # Extract the response properly
                    if result and hasattr(result, 'response') and result.response is not None:
                        # Handle different response types (string, dict, object)
                        if isinstance(result.response, (str, dict, list, int, float, bool)):
                            response_content = result.response
                        elif hasattr(result.response, '__dict__'):
                            try: 
                                response_content = result.response.__dict__
                            except: 
                                response_content = str(result.response)
                        else:
                            try:  # Check if serializable
                                json.dumps(result.response)
                                response_content = result.response
                            except: 
                                response_content = str(result.response)
                    elif result and hasattr(result, 'matches_schema') and result.matches_schema and hasattr(result, 'parsed_response'):
                        # Prioritize parsed schema response if available
                        response_content = result.parsed_response
                    else:
                        # Get the updated URL after the action
                        updated_url = nova_instance.page.url
                        page_title = nova_instance.page.title()
                        # Fallback if no specific response
                        response_content = f"Action executed. Page title: {page_title}, URL: {updated_url}"
                else:
                    # No instruction provided, and not handled directly (e.g., just credentials entered)
                    log(f"[{session_id}] No specific instruction to execute via nova.act.")
                    result = None
                    # Get the current page state
                    updated_url = nova_instance.page.url
                    page_title = nova_instance.page.title()
                    response_content = f"No explicit instruction executed. Current state - URL: {updated_url}, Title: {page_title}"
                
                # --- Post-Action Steps (State Update, Screenshot, etc.) ---
                # Get updated page state AFTER the action
                updated_url = nova_instance.page.url
                page_title = nova_instance.page.title()
                log(f"[{session_id}] Action completed. Current URL: {updated_url}")
                
                # Look for the output HTML file in the logs (only if we used nova.act)
                html_output_path = None
                if result and hasattr(result, 'metadata') and result.metadata:
                    # ... existing HTML path extraction code ...
                    nova_session_id = result.metadata.session_id
                    nova_act_id = result.metadata.act_id
                    
                    # Try to get the HTML output path
                    logs_dir = nova_instance.logs_directory if hasattr(nova_instance, 'logs_directory') else None
                    
                    if logs_dir and nova_session_id and nova_act_id:
                        possible_html_path = os.path.join(
                            logs_dir, 
                            nova_session_id, 
                            f"act_{nova_act_id}_output.html"
                        )
                        if os.path.exists(possible_html_path):
                            html_output_path = possible_html_path
                            output_html_paths.append(html_output_path)
                            log(f"Found HTML output path: {html_output_path}")
                    
                    # If logs_directory is not set, try to find HTML in temp directory
                    if not logs_dir or not html_output_path:
                        # ... existing temp directory search code ...
                        temp_dir = tempfile.gettempdir()
                        for root, dirs, files in os.walk(temp_dir):
                            if nova_session_id in root:
                                for file in files:
                                    if file.startswith(f"act_{nova_act_id}") and file.endswith("_output.html"):
                                        html_output_path = os.path.join(root, file)
                                        output_html_paths.append(html_output_path)
                                        log(f"Found HTML output path in temp dir: {html_output_path}")
                                        break
            
                # Extract agent thinking (only if we used nova.act)
                agent_messages = []
                debug_info = {}
                if result:
                    agent_messages, debug_info = extract_agent_thinking(
                        result, 
                        nova_instance, 
                        logs_dir if 'logs_dir' in locals() else None,
                        instruction_to_execute
                    )
                elif action_handled_directly:
                    debug_info = {"direct_action": True, "action_type": "playwright_direct"}
            
                # Take a screenshot if requested - DISABLED FOR NOW
                screenshot_data = None
                # if embedScreenshot:  # Original condition
                if False:  # CHANGED: Disable screenshot embedding due to token limits
                    # Keep the code below for future reference or manual debugging
                    try:
                        log(f"[{session_id}] Capturing screenshot (Currently Disabled)...")
                        # screenshot_bytes = nova_instance.page.screenshot()
                        # screenshot_data = base64.b64encode(screenshot_bytes).decode('utf-8')
                        # log(f"[{session_id}] Captured screenshot successfully ({len(screenshot_data)} bytes encoded)")
                    except Exception as e:
                        log(f"[{session_id}] Error taking screenshot: {str(e)}")
                
                # Update session registry with results
                with session_lock:
                    if session_id in active_sessions:
                        active_sessions[session_id]["url"] = updated_url
                        active_sessions[session_id]["results"].append({
                            "action": original_instruction,  # Log the original requested action
                            "executed": instruction_to_execute if not action_handled_directly else "direct_playwright",
                            "response": response_content,
                            "agent_messages": agent_messages,
                            "output_html_paths": output_html_paths,
                            "screenshot_included": bool(screenshot_data),
                            "direct_action": action_handled_directly
                        })
                        active_sessions[session_id]["last_updated"] = time.time()
                        active_sessions[session_id]["status"] = "browser_ready"  # Ready for next action
                        active_sessions[session_id]["error"] = None  # Clear previous error on success
                
                # Find the first valid HTML log path, if any
                html_log_path = None
                if output_html_paths:
                    # Find the first existing path (in case multiple were found somehow)
                    for path in output_html_paths:
                        # Check existence again just to be sure
                        if path and os.path.exists(path): 
                            html_log_path = path
                            break  # Use the first valid one
                
                # Format agent thinking for MCP response
                agent_thinking = []
                for message in agent_messages:
                    agent_thinking.append({
                        "type": "reasoning",
                        "content": message,
                        "source": "nova_act"
                    })
            
                # Create result properly formatted for JSON-RPC
                action_type = "direct Playwright" if action_handled_directly else "Nova Act SDK"
                
                # Assemble the main text, adding the HTML log path if found
                main_text = f"Successfully executed via {action_type}: {original_instruction or 'Schema Observation'}\n\nCurrent URL: {updated_url}\nPage Title: {page_title}\nResponse: {json.dumps(response_content)[:500]}..."
                if html_log_path:
                    main_text += f"\nNova Act HTML Log Path: {html_log_path}"  # ADDED HTML PATH
                
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": main_text
                        }
                    ],
                    "agent_thinking": agent_thinking,
                    "isError": False,
                    "session_id": session_id,  # Include session ID in result
                    "direct_action": action_handled_directly
                }
                
                # Include debug info if in debug mode
                if DEBUG_MODE or debug:
                    mcp_result["debug"] = {
                        "html_paths": output_html_paths,  # Still useful for debug
                        "html_log_path_selected": html_log_path,  # Show which one we added
                        "extraction_info": debug_info,
                        "response_object": response_content,  # Include raw response for debug
                        "action_handled_directly": action_handled_directly
                    }
            
                return mcp_result
                
            # Refined Error Handling
            except ActGuardrailsError as e:
                error_message = f"Guardrail triggered: {str(e)}"
                error_type = "Guardrails"
                error_tb = traceback.format_exc()
            except ActError as e:
                error_message = f"Nova Act execution error: {str(e)}"
                error_type = "NovaAct" 
                error_tb = traceback.format_exc()
            except Exception as e:
                error_message = f"General execution error: {str(e)}"
                error_type = "General"
                error_tb = traceback.format_exc()
            
            # Common Error Logging and Update - unchanged
            log(f"[{session_id}] Error ({error_type}): {error_message}")
            log(f"Traceback: {error_tb}")
            with session_lock:
                if session_id in active_sessions:
                    active_sessions[session_id]["status"] = "error"
                    active_sessions[session_id]["error"] = error_message
                    active_sessions[session_id]["last_updated"] = time.time()
            # Propagate error message to be caught by the main handler
            raise Exception(f"({error_type}) {error_message}")
        
        # Run the synchronous code in the session's dedicated thread
        try:
            # Use run_in_executor to run the synchronous code in the session's thread
            result = await asyncio.get_event_loop().run_in_executor(
                executor, execute_instruction
            )
            
            # Return the result as a proper JSON-RPC response
            return create_jsonrpc_response(request_id, result)
                
        except Exception as e:
            # ... existing error handling code ...
            error_message = str(e)
            error_tb = traceback.format_exc()
            log(f"Error in thread execution: {error_message}")
            log(f"Traceback: {error_tb}")
            
            error = {
                "code": -32603,
                "message": f"Error executing instruction: {error_message}",
                "data": {
                    "session_id": session_id
                }
            }
            
            return create_jsonrpc_response(request_id, error=error)
    
    # Handle the "end" action
    elif action == "end":
        if not session_id:
            error = {
                "code": -32602,
                "message": "session_id is required for 'end' action.",
                "data": None
            }
            return create_jsonrpc_response(request_id, error=error)
        
        # Define a synchronous function to end the session
        def end_browser_session():
            try:
                # Get the session data and NovaAct instance
                with session_lock:
                    session_data = active_sessions.get(session_id)
                    if not session_data:
                        raise Exception(f"No active session found to end: {session_id}")
                    nova_instance = session_data.get("nova_instance")
                    executor = session_data.get("executor")
                
                log(f"[{session_id}] Ending session...")
                if nova_instance:
                    try:
                        # Close the NovaAct instance
                        log(f"[{session_id}] Attempting to close NovaAct instance...")
                        if hasattr(nova_instance, 'close') and callable(nova_instance.close):
                            nova_instance.close()
                            log(f"[{session_id}] NovaAct instance closed.")
                        elif hasattr(nova_instance, '__exit__') and callable(nova_instance.__exit__):
                            nova_instance.__exit__(None, None, None)  # Try context manager exit
                            log(f"[{session_id}] NovaAct instance exited via __exit__.")
                        else:
                            log(f"[{session_id}] Warning: No close() or __exit__ method found. Browser might remain.")
                    except Exception as e:
                        # Log error but continue to remove from registry
                        log(f"[{session_id}] Error closing NovaAct instance: {e}")
                
                # Shutdown the executor if it exists
                if executor:
                    try:
                        executor.shutdown(wait=False)
                        log(f"[{session_id}] Executor shutdown.")
                    except Exception as e:
                        log(f"[{session_id}] Error shutting down executor: {e}")
                
                # Update session registry or remove from registry
                with session_lock:
                    if session_id in active_sessions:
                        active_sessions[session_id]["status"] = "ended"
                        active_sessions[session_id]["complete"] = True
                        active_sessions[session_id]["nova_instance"] = None  # Clear the instance
                        active_sessions[session_id]["executor"] = None  # Clear the executor
                
                return {
                    "session_id": session_id,
                    "status": "ended",
                    "success": True
                }
            except Exception as e:
                error_message = str(e)
                error_tb = traceback.format_exc()
                log(f"Error ending browser session: {error_message}")
                log(f"Traceback: {error_tb}")
                raise Exception(error_message)
        
        # Get the session's executor
        with session_lock:
            session_data = active_sessions.get(session_id)
            if not session_data:
                error = {
                    "code": -32602,
                    "message": f"No active session found to end: {session_id}",
                    "data": None
                }
                return create_jsonrpc_response(request_id, error=error)
            executor = session_data.get("executor")
        
        # Run the synchronous code in the session's dedicated thread
        try:
            # Use run_in_executor to run the synchronous code in the session's thread
            result = await asyncio.get_event_loop().run_in_executor(
                executor if executor else None, end_browser_session
            )
            
            # Return the result as a proper JSON-RPC response
            return create_jsonrpc_response(request_id, result)
                
        except Exception as e:
            error_message = str(e)
            error_tb = traceback.format_exc()
            log(f"Error in thread execution: {error_message}")
            log(f"Traceback: {error_tb}")
            
            error = {
                "code": -32603,
                "message": f"Error ending browser session: {error_message}",
                "data": {
                    "session_id": session_id
                }
            }
            
            return create_jsonrpc_response(request_id, error=error)
    
    else:
        error = {
            "code": -32601,
            "message": f"Unknown action '{action}'. Valid actions are 'start', 'execute', 'end'.",
            "data": None
        }
        return create_jsonrpc_response(request_id, error=error)

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
    
    log("- Tool: list_browser_sessions - List all active and recent web browser sessions ✓")
    log("- Tool: control_browser - Manage and interact with web browser sessions via Nova Act agent ✓")
    
    log("\nStarting MCP server...")
    # Initialize and run the server
    mcp.run(transport='stdio')

if __name__ == "__main__":
    main()
