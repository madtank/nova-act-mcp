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
from typing import Any, Dict, List, Optional

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
    print(f"[NOVA_LOG] {message}", file=sys.stderr, flush=True)

# Clean up function to ensure all browser sessions are closed on exit
def cleanup_browser_sessions():
    log("Cleaning up browser sessions...")
    # No need to manually close NovaAct instances - they should be handled by context managers

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
                active_sessions.pop(session_id, None)
    
    result = {
        "sessions": sessions,
        "active_count": len([s for s in sessions if s.get("status") not in ("complete", "error")]),
        "total_count": len(sessions)
    }
    
    # Get the request ID from the MCP context if available
    request_id = getattr(mcp, 'request_id', 1)
    
    return create_jsonrpc_response(request_id, result)


@mcp.tool(name="control_browser", description="Control a web browser session via Nova Act agent in multiple steps: start, execute, and end sessions.")
async def browser_session(action: str, session_id: Optional[str] = None, url: Optional[str] = None, instruction: Optional[str] = None, headless: Optional[bool] = True) -> str:
    """Control a web browser session via Nova Act agent.

    Perform actions in multiple steps: start a session, execute navigation or agent instructions, and end a session.

    Args:
        action: One of "start", "execute", or "end".
        session_id: Session identifier (not needed for "start").
        url: Initial or navigation URL.
        instruction: Instruction text for navigation actions ("execute").
        headless: Run browser in headless mode when starting.

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
                "complete": False
            }
        
        # Define a synchronous function to run in a separate thread
        def start_browser_session():
            try:
                profile_dir = os.path.join(PROFILES_DIR, DEFAULT_PROFILE)
                os.makedirs(profile_dir, exist_ok=True)
                
                log(f"Opening browser to {url}")
                
                # Create NovaAct instance with context manager to ensure proper closure
                with NovaAct(
                    starting_page=url,
                    nova_act_api_key=api_key,
                    user_data_dir=profile_dir,
                    headless=headless
                ) as nova:
                    # Store NovaAct's own session ID for debugging
                    nova_session_id = None
                    if hasattr(nova, 'session_id'):
                        nova_session_id = nova.session_id
                        log_session_info("NovaAct session started", session_id, nova_session_id)
                    
                    # Take a screenshot
                    screenshot_data = None
                    try:
                        screenshot_bytes = nova.page.screenshot()
                        screenshot_data = base64.b64encode(screenshot_bytes).decode('utf-8')
                    except Exception as e:
                        log(f"Error taking screenshot: {str(e)}")
                    
                    # Get initial page info
                    current_url = nova.page.url
                    page_title = nova.page.title()
                
                # Update session registry with results
                with session_lock:
                    if session_id in active_sessions:
                        active_sessions[session_id]["status"] = "browser_ready"
                        active_sessions[session_id]["url"] = current_url
                        if nova_session_id:
                            active_sessions[session_id]["nova_session_id"] = nova_session_id
                
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
                
                # Return the error in JSON-RPC format
                raise Exception(error_message)
        
        # Run the synchronous code in a thread pool
        try:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                # Use run_in_executor to run the synchronous code in a separate thread
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
        if not session_id or not instruction:
            error = {
                "code": -32602,
                "message": "session_id and instruction are required for 'execute' action.",
                "data": None
            }
            return create_jsonrpc_response(request_id, error=error)
        
        # Get the session data
        with session_lock:
            session_data = active_sessions.get(session_id)
        
        if not session_data:
            error = {
                "code": -32602,
                "message": f"No active session found with session_id: {session_id}",
                "data": None
            }
            return create_jsonrpc_response(request_id, error=error)
        
        # Get the URL from the session or use the provided URL
        current_url = url if url else session_data.get("url")
        if not current_url:
            error = {
                "code": -32602,
                "message": f"No URL found for session. Please provide a URL.",
                "data": None
            }
            return create_jsonrpc_response(request_id, error=error)
            
        # Define a synchronous function to run in a separate thread
        def execute_instruction():
            try:
                # Create a new instance each time for execute
                profile_dir = os.path.join(PROFILES_DIR, DEFAULT_PROFILE)
                log(f"Creating new NovaAct instance for execute with URL: {current_url}")
                
                # Track HTML output paths
                output_html_paths = []
                
                # Create and initialize NovaAct for this specific action
                with NovaAct(
                    starting_page=current_url,
                    nova_act_api_key=api_key,
                    user_data_dir=profile_dir,
                    headless=False  # Show the browser for execute commands
                ) as nova:
                    # Wait for the page to load
                    log(f"Executing instruction: Wait for the page to fully load")
                    load_result = nova.act("Wait for the page to fully load", timeout=30)
                    
                    # Capture HTML output path from load action if available
                    if hasattr(load_result, 'metadata') and load_result.metadata:
                        # Look for HTML output path in logs
                        nova_session_id = load_result.metadata.session_id
                        nova_act_id = load_result.metadata.act_id
                        logs_dir = nova.logs_directory if hasattr(nova, 'logs_directory') else None
                        
                        # Check for standard Nova Act output path pattern
                        if logs_dir and nova_session_id and nova_act_id:
                            possible_html_path = os.path.join(
                                logs_dir, 
                                nova_session_id, 
                                f"act_{nova_act_id}_output.html"
                            )
                            if os.path.exists(possible_html_path):
                                output_html_paths.append(possible_html_path)
                    
                    # Execute the instruction
                    log(f"Executing instruction: {instruction}")
                    result = nova.act(instruction, timeout=DEFAULT_TIMEOUT)
                    
                    # Get the updated URL after the action
                    updated_url = nova.page.url
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
                        response_content = f"Page title: {page_title}, URL: {updated_url}"
                    
                    # Look for the output HTML file in the logs
                    # Extract logs from Nova Act and find the HTML output path
                    html_output_path = None
                    if hasattr(result, 'metadata') and result.metadata:
                        nova_session_id = result.metadata.session_id
                        nova_act_id = result.metadata.act_id
                        
                        # Try to get the HTML output path
                        # First check if nova has logs_directory attribute
                        logs_dir = nova.logs_directory if hasattr(nova, 'logs_directory') else None
                        
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
                            # Check in temp directory using session ID and act ID
                            temp_dir = tempfile.gettempdir()
                            log(f"Searching for HTML output in temp directory: {temp_dir}")
                            
                            for root, dirs, files in os.walk(temp_dir):
                                if nova_session_id in root:
                                    for file in files:
                                        if file.startswith(f"act_{nova_act_id}") and file.endswith("_output.html"):
                                            html_output_path = os.path.join(root, file)
                                            output_html_paths.append(html_output_path)
                                            log(f"Found HTML output path in temp dir: {html_output_path}")
                                            break
                    
                    # Use the new extraction function to get agent thinking
                    agent_messages, debug_info = extract_agent_thinking(
                        result, 
                        nova, 
                        logs_dir if 'logs_dir' in locals() else None,
                        instruction
                    )
                    
                    # Take a screenshot
                    screenshot_data = None
                    try:
                        screenshot_bytes = nova.page.screenshot()
                        screenshot_data = base64.b64encode(screenshot_bytes).decode('utf-8')
                        log("Captured screenshot successfully")
                    except Exception as e:
                        log(f"Error taking screenshot: {str(e)}")
                
                # Update session registry with results
                with session_lock:
                    if session_id in active_sessions:
                        active_sessions[session_id]["url"] = updated_url
                        active_sessions[session_id]["results"].append({
                            "action": instruction,
                            "response": response_content,
                            "agent_messages": agent_messages,
                            "output_html_paths": output_html_paths
                        })
                
                # Format agent thinking for MCP response
                agent_thinking = []
                for message in agent_messages:
                    agent_thinking.append({
                        "type": "reasoning",
                        "content": message,
                        "source": "nova_act"
                    })
                
                # Create result properly formatted for JSON-RPC
                agent_message_text = "\n".join([msg["content"] for msg in agent_thinking]) if agent_thinking else "No agent messages recorded"
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Successfully executed: {instruction}\n\nCurrent URL: {updated_url}\nPage Title: {page_title}"
                        }
                    ],
                    "agent_thinking": agent_thinking,
                    "isError": False
                }
                
                # Include debug info if in debug mode
                if DEBUG_MODE:
                    mcp_result["debug"] = {
                        "html_paths": output_html_paths,
                        "extraction_info": debug_info
                    }
                
                return mcp_result
                
            except Exception as e:
                error_message = str(e)
                error_tb = traceback.format_exc()
                log(f"Error executing instruction: {error_message}")
                log(f"Traceback: {error_tb}")
                
                raise Exception(error_message)
        
        # Run the synchronous code in a thread pool
        try:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                # Use run_in_executor to run the synchronous code in a separate thread
                result = await asyncio.get_event_loop().run_in_executor(
                    executor, execute_instruction
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
                "message": f"Error executing instruction: {error_message}",
                "data": {
                    "traceback": error_tb,
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
        
        # Get the session data
        with session_lock:
            session_data = active_sessions.get(session_id)
        
        if not session_data:
            error = {
                "code": -32602,
                "message": f"No active session found with session_id: {session_id}",
                "data": None
            }
            return create_jsonrpc_response(request_id, error=error)
        
        # For "end", we just update the state in our registry
        def end_browser_session():
            try:
                # Update session registry
                with session_lock:
                    if session_id in active_sessions:
                        active_sessions[session_id]["status"] = "ended"
                        active_sessions[session_id]["complete"] = True
                
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
        
        # Run the synchronous code in a thread pool
        try:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                # Use run_in_executor to run the synchronous code in a separate thread
                result = await asyncio.get_event_loop().run_in_executor(
                    executor, end_browser_session
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
                    "traceback": error_tb,
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
