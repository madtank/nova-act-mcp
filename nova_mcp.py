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
from typing import Any, Dict, Optional, Literal, List

# Third-party imports
from pydantic import BaseModel

# Local application/library specific imports
from fastmcp import FastMCP

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
_logging_initialized = True

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
        class ActError(Exception):
            pass

        class ActGuardrailsError(Exception):
            pass

    NOVA_ACT_AVAILABLE = True
except ImportError:
    # Define dummy exceptions if SDK not installed
    class ActError(Exception):
        pass

    class ActGuardrailsError(Exception):
        pass

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

        if nova_instance:
            log(f"Attempting to close lingering session: {session_id}")
            try:
                # Try to properly close the NovaAct instance
                if hasattr(nova_instance, "close") and callable(nova_instance.close):
                    nova_instance.close()
                    log(f"Closed instance for session {session_id}")
                elif hasattr(nova_instance, "__exit__") and callable(
                    nova_instance.__exit__
                ):
                    # Fallback to context manager exit if no close method
                    nova_instance.__exit__(None, None, None)
                    log(f"Called __exit__ for session {session_id}")
                else:
                    log(
                        f"Warning: No close() or __exit__ method found on NovaAct instance for session {session_id}. Browser might remain open."
                    )
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
                error=data.get("progress", {}).get("error", None),
            ).model_dump()
            for session_id, data in active_sessions.items()
        ]


def get_nova_act_api_key():
    """Read the API key from the MCP server config or environment variables"""
    global NOVA_ACT_API_KEY
    try:
        # Check for an environment variable first (highest priority)
        api_key = os.environ.get("NOVA_ACT_API_KEY")
        if api_key:
            NOVA_ACT_API_KEY = api_key
            log(f"✅ Found API key in environment variable NOVA_ACT_API_KEY")
            return NOVA_ACT_API_KEY

        # Try to get it from MCP server config
        if hasattr(mcp, "config") and mcp.config is not None:
            config_data = mcp.config

            # Try direct access first
            if isinstance(config_data, dict) and "novaActApiKey" in config_data:
                NOVA_ACT_API_KEY = config_data["novaActApiKey"]
                log("✅ Found API key in MCP config (direct)")
                return NOVA_ACT_API_KEY

            # Try nested config access
            if (
                isinstance(config_data, dict)
                and "config" in config_data
                and isinstance(config_data["config"], dict)
            ):
                if "novaActApiKey" in config_data["config"]:
                    NOVA_ACT_API_KEY = config_data["config"]["novaActApiKey"]
                    log("✅ Found API key in MCP config (nested)")
                    return NOVA_ACT_API_KEY

        log(
            "⚠️ Warning: Nova Act API key not found in environment variables or MCP config."
        )
        log(
            "Please set the NOVA_ACT_API_KEY environment variable or add 'novaActApiKey' to your MCP configuration."
        )
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
    success_count = sum(1 for s in step_results if s.get("success", False))
    failure_count = sum(1 for s in step_results if not s.get("success", False))
    return success_count, failure_count


# Add logging for session tracking to debug session ID issues
def log_session_info(prefix, session_id, nova_session_id=None):
    """Log information about the session to help debug session ID discrepancies"""
    if nova_session_id and nova_session_id != session_id:
        log(
            f"⚠️ {prefix}: Session ID mismatch - MCP: {session_id}, Nova: {nova_session_id}"
        )
    else:
        log(f"{prefix}: {session_id}")


# Helper function to create proper JSON-RPC 2.0 response
def create_jsonrpc_response(id, result=None, error=None):
    """Create a properly formatted JSON-RPC 2.0 response"""
    response = {"jsonrpc": "2.0", "id": id}

    if error is not None:
        response["error"] = error
    else:
        response["result"] = result

    # Return as Python dict, not as JSON string - let the MCP framework handle serialization
    return response


# Flag to enable debug mode - false by default, can be enabled with env var
DEBUG_MODE = os.environ.get("NOVA_MCP_DEBUG", "0") == "1"


def extract_agent_thinking(result, nova=None, html_path_to_parse=None, instruction=None):
    """
    Extract agent thinking from Nova Act results using multiple methods.
    Prioritizes direct fields, then captures logs immediately, then falls back to HTML parsing.
    """
    agent_messages = []
    extraction_methods_tried = []
    debug_info = {}
    
    # Helper function to clean thought strings
    def _clean_thought(t: str) -> str:
        return t.strip().replace("\\n", "\n")
    
    # Method 1: Direct fields (result.metadata.thinking, result.thoughts)
    extraction_methods_tried.append("direct_fields")
    if result:
        # Try result.metadata.thinking
        if hasattr(result, "metadata") and hasattr(result.metadata, "thinking") and result.metadata.thinking:
            log(f"Found thinking in result.metadata.thinking")
            for t in result.metadata.thinking:
                cleaned = _clean_thought(t)
                if cleaned and cleaned not in agent_messages:
                    agent_messages.append(cleaned)
        
        # Try result.thoughts
        if hasattr(result, "thoughts") and result.thoughts:
            log(f"Found thinking in result.thoughts")
            for t in result.thoughts:
                cleaned = _clean_thought(t)
                if cleaned and cleaned not in agent_messages:
                    agent_messages.append(cleaned)
    
    # Method 2: Raw log buffer - capture immediately
    extraction_methods_tried.append("raw_logs")
    if not agent_messages and nova and callable(getattr(nova, "get_logs", None)):
        try:
            raw_logs = nova.get_logs()  # Get logs immediately after act()
            
            # IMPORTANT FIX: Handle if raw_logs is a string rather than a list
            if isinstance(raw_logs, str):
                raw_logs = raw_logs.splitlines()
                
            log(f"Got {len(raw_logs)} raw log lines from nova.get_logs()")
            think_count = 0
            
            for line in raw_logs:
                # IMPROVED: More flexible pattern that handles whitespace and captures all content
                m = re.search(r'\bthink\s*\(\s*[\'"]([\s\S]*?)[\'"]\s*\)', line)
                if m:
                    cleaned = _clean_thought(m.group(1))
                    if cleaned and cleaned not in agent_messages:
                        agent_messages.append(cleaned)
                        think_count += 1
            
            log(f"Extracted {think_count} thinking patterns from raw logs")
            if think_count > 0:
                debug_info["source"] = "raw_logs"
                debug_info["think_patterns_found"] = think_count
        except Exception as e:
            log(f"Error extracting from raw logs: {str(e)}")
            debug_info["raw_logs_error"] = str(e)
    
    # Method 3: HTML Log - only if still empty
    extraction_methods_tried.append("html_file")
    if not agent_messages and html_path_to_parse and os.path.exists(html_path_to_parse):
        log(f"Parsing HTML file for thinking: {html_path_to_parse}")
        debug_info["html_path_parsed"] = html_path_to_parse
        try:
            import html
            # Read the HTML file
            with open(html_path_to_parse, "r", encoding="utf-8", errors="ignore") as f:
                html_content = f.read()
            
            # Replace escaped quotes before unescaping HTML
            html_content = html_content.replace('\\"', '"')
            
            # 1. Unescape HTML entities (convert &quot; back to ", etc.)
            unescaped_content = html.unescape(html_content)
            
            # 2. Remove HTML tags
            text_content = re.sub(r'<[^>]*>', ' ', unescaped_content)
            
            # 3. IMPROVED: Search for thinking patterns - more flexible pattern that handles everything
            think_count = 0
            for m in re.finditer(r'\bthink\s*\(\s*[\'"]([\s\S]*?)[\'"]\s*\)', text_content, re.DOTALL):
                cleaned = _clean_thought(m.group(1))
                if cleaned and cleaned not in agent_messages:
                    agent_messages.append(cleaned)
                    think_count += 1
            
            # Log results
            log(f"Extracted {think_count} thinking patterns from HTML")
            debug_info["html_patterns_found_count"] = think_count
            debug_info["source"] = "html_file" if think_count > 0 else debug_info.get("source")
            
        except Exception as e:
            log(f"Error parsing HTML file {html_path_to_parse}: {str(e)}")
            debug_info["html_error"] = str(e)
    
    # Add fallback methods only if we still haven't found anything
    if not agent_messages:
        # Method 4: Check result.response if it's a string (unchanged)
        extraction_methods_tried.append("result_response")
        if hasattr(result, "response") and isinstance(result.response, str):
            agent_messages.append(result.response)
    
    # Log summary
    debug_info["extraction_methods"] = extraction_methods_tried
    debug_info["message_count"] = len(agent_messages)
    log(f"Final agent thinking message count: {len(agent_messages)}")
    
    return agent_messages, debug_info


@mcp.tool(
    name="list_browser_sessions",
    description="List all active and recent web browser sessions managed by Nova Act agent"
)
async def list_browser_sessions() -> Dict[str, Any]:
    """List all active and recent web browser sessions managed by Nova Act agent.

    Returns a JSON string with session IDs, status, progress, and error details for each session.
    """
    # Ensure environment is initialized
    initialize_environment()

    sessions = get_session_status()

    # Clean up old completed sessions that are more than 10 minutes old
    current_time = time.time()
    with session_lock:
        # Use list() to avoid modifying dict during iteration
        for session_id, session_data in list(active_sessions.items()):
            # Only clean up sessions that are marked complete and are old
            if session_data.get("complete", False) and (
                current_time - session_data.get("last_updated", 0) > 600
            ):
                log(f"Cleaning up old completed session {session_id}")

                # Close NovaAct instance if present
                nova_instance = session_data.get("nova_instance")
                if nova_instance:
                    try:
                        if hasattr(nova_instance, "close") and callable(
                            nova_instance.close
                        ):
                            nova_instance.close()
                        elif hasattr(nova_instance, "__exit__") and callable(
                            nova_instance.__exit__
                        ):
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
        "active_count": len(
            [s for s in sessions if s.get("status") not in ("complete", "error")]
        ),
        "total_count": len(sessions),
    }

    return result  # FastMCP will wrap this


@mcp.tool(
    name="view_html_log",
    description=(
        "Render a Nova-Act HTML log file as inline HTML. "
        "Provide either 'html_path' (absolute) or a 'session_id' "
        "whose last action produced a log."
    ),
)
async def view_html_log(
    html_path: Optional[str] = None,
    session_id: Optional[str] = None,
    truncate_to_kb: int = 512,
) -> Dict[str, Any]:
    """
    Stream an HTML log back to the caller so Claude (or other MCP UIs)
    can embed it. If both args are given, html_path wins.
    Large files are truncated to keep JSON-RPC payloads reasonable.
    Returns a dictionary representing a JSON-RPC result or error.
    """

    initialize_environment()
    # request_id = getattr(mcp, "request_id", 1) # Not needed for return value

    # Resolve path from session registry if only session_id given
    found_path = None
    if not html_path and session_id:
        with session_lock:
            sess = active_sessions.get(session_id, {})
            # Grab the most recent *list* of html paths stored in results
            for r in reversed(sess.get("results", [])):
                # Ensure we look for the key where absolute paths are stored
                potential_paths = r.get("output_html_paths", []) # Key should match storage
                if potential_paths:
                    # Check each absolute path in the list for existence
                    for p in potential_paths:
                        # Ensure p is a non-empty string before checking existence
                        if isinstance(p, str) and p and os.path.exists(p):
                            found_path = p
                            log(f"Found existing HTML log via session results: {found_path}")
                            break # Found a valid path in this result entry
                    if found_path:
                        break # Stop searching backwards once a valid path is found
        html_path = found_path # Assign the found absolute path

    # If html_path was provided directly, ensure it's absolute and exists
    elif html_path:
        absolute_provided_path = os.path.abspath(html_path)
        if not os.path.exists(absolute_provided_path):
             log(f"Provided HTML log path does not exist: {absolute_provided_path}")
             # Return JSON-RPC error structure
             return {
                "error": {
                    "code": -32602, # Invalid params
                    "message": f"Provided HTML log path does not exist: {absolute_provided_path}",
                    "data": None,
                }
            }
        html_path = absolute_provided_path # Use the validated absolute path

    # Check if we actually found or validated a path
    if not html_path:
        error_detail = f"session_id: {session_id}" if session_id else "no identifier provided"
        log(f"Could not find an existing HTML log for {error_detail}")
        # Return JSON-RPC error structure
        return {
            "error": {
                "code": -32602, # Invalid params
                "message": f"Could not find an existing HTML log for {error_detail}",
                "data": None,
            }
        }
    # Path existence is checked above, no need for redundant check here

    # Read & (optionally) truncate
    try:
        raw = Path(html_path).read_bytes()
        truncated = False
        if len(raw) > truncate_to_kb * 1024:
            raw = raw[: truncate_to_kb * 1024] + b"\\n<!-- ...truncated... -->"
            truncated = True

        # Return as an MCP artifact (JSON-RPC result structure)
        log(f"Returning HTML content from {html_path} (truncated: {truncated})")
        # IMPORTANT: FastMCP expects the function to return the *value* for the "result" key
        # It will automatically wrap it in {"jsonrpc": "2.0", "id": ..., "result": ...}
        # So, we return the dictionary that should go *inside* "result"
        return {
            "content": [{"type": "html", "html": raw.decode("utf-8", "ignore")}],
            "source_path": html_path,
            "truncated": truncated
        }
    except Exception as e:
        log(f"Error reading HTML log file {html_path}: {e}")
        # For errors, FastMCP expects a dictionary matching the JSON-RPC error object structure
        # to be returned, which it will place inside the "error" key.
        return {
            "code": -32603, # Internal error
            "message": f"Error reading HTML log file: {e}",
            "data": {"path": html_path},
        }


@mcp.tool(
    name="control_browser",
    description=(
        """Controls web browser sessions via Nova Act.
        Actions:
        - start: Opens browser with required 'url'. Optional 'headless' (default: True). Returns 'session_id'.
        - execute: Performs actions with required 'session_id'.
            - 'url': Navigate to a new page (use full URL)
            - 'instruction': Natural language command (e.g., "click login button")
            - 'username'/'password': For authentication forms
            - 'schema': Extract structured data in JSON format (auto-detects page elements or accepts custom extraction templates)
        - end: Closes session (requires 'session_id')

        Returns session details including current URL/title and execution log path. 
        HTTP logs are available as hyperlinks in the response when containing notable information.

        Form Element Tips:
        - Dropdowns: Use "select [option name] from dropdown" or "choose [option name] from the dropdown menu"
        - Checkboxes:
            - Actions: "check the checkbox labeled [label]" or "uncheck the checkbox labeled [label]"
            - Verification: "identify all checkboxes and their states" or use schema for reliable verification
        - Radio buttons: Use "select the radio button labeled [label]"
        - Input fields: Use "type [text] into the [field name] field"

        Error Handling:
        - Element not found: Returns error message with page context
        - Timeouts: Default 30-second timeout with automatic retry (configurable)
        - Execution errors: Detailed logs available for troubleshooting

        Note: For verifying form element states, prefer using the schema parameter or "identify" instructions
        rather than "check if" or "verify" which might be interpreted as toggle actions.

        Example workflow: Start with URL → search for specific product → 
        find product → add to cart → login → share items in cart for logged-in user

        Schema example: Use 'schema': {"products": {"selector": ".product-item", "fields": {"name": ".title", "price": ".price"}}}
        or simply 'schema': {"extract": "products"} to auto-detect common elements"""
    ),
)
async def browser_session(
    action: Literal["start", "execute", "end"] = "execute",
    session_id: Optional[str] = None,
    url: Optional[str] = None,
    instruction: Optional[str] = None,
    headless: bool = True,  # Changed default to True
    username: Optional[str] = None,
    password: Optional[str] = None,
    schema: Optional[dict] = None,
) -> Dict[str, Any]:
    """
    Control a web browser session via Nova Act agent.

    Performs actions ('start', 'execute', 'end') based on the Nova Act SDK principles.
    The 'execute' action uses the 'instruction' parameter for natural language commands
    or the 'schema' parameter for data extraction.

    Sensitive credentials should be passed via 'username'/'password' parameters for
    direct Playwright handling, not within the 'instruction' text itself.

    Args:
        action: One of "start", "execute", or "end".
        session_id: Session identifier (required for 'execute' and 'end').
        url: Initial URL (required for 'start').
        instruction: Natural language instruction for the Nova Act agent (for 'execute').
                     Keep instructions specific and step-by-step.
        headless: Run browser in headless mode (default: True).
        username: Username for direct input (use cautiously, see Nova Act docs).
        password: Password for direct input (use cautiously, see Nova Act docs).
        schema: Optional JSON schema for data extraction with 'execute'.

    Returns:
        A dictionary representing the JSON-RPC result or error.
    """

    # Ensure environment is initialized
    initialize_environment()

    # Get the request ID from the MCP context if available
    request_id = getattr(mcp, "request_id", 1)

    if not NOVA_ACT_AVAILABLE:
        error = {
            "code": -32603,
            "message": "Nova Act package is not installed. Please install with: pip install nova-act",
            "data": None,
        }
        return {"error": error}

    # Get API key at runtime
    api_key = get_nova_act_api_key()
    if not api_key:
        error = {
            "code": -32603,
            "message": "Nova Act API key not found. Please check your MCP config or set the NOVA_ACT_API_KEY environment variable.",
            "data": None,
        }
        return {"error": error}

    # Handle the "start" action
    if action == "start":
        if not url:
            error = {
                "code": -32602,
                "message": "URL is required for 'start' action.",
                "data": None,
            }
            return {"error": error}

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
                "executor": None,  # Single-thread executor for this session
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

                # Create NovaAct instance with proper parameters for your installed version
                nova_instance = NovaAct(
                    starting_page=url,
                    nova_act_api_key=api_key,
                    user_data_dir=profile_dir,
                    headless=headless,
                    # Removed unsupported parameters: capture_logs and capture_screenshots
                )

                # --- Explicitly start the client - THIS FIXES THE ERROR ---
                log(f"[{session_id}] Calling nova_instance.start()...")
                if hasattr(nova_instance, "start") and callable(nova_instance.start):
                    nova_instance.start()
                    log(f"[{session_id}] nova_instance.start() completed.")
                else:
                    # This case should ideally not happen based on docs/error
                    log(
                        f"[{session_id}] Warning: nova_instance does not have a callable start() method!"
                    )

                # Now it should be safe to access nova_instance.page
                log(f"[{session_id}] Accessing page properties...")

                # Wait for initial page to load
                try:
                    nova_instance.page.wait_for_load_state(
                        "domcontentloaded", timeout=15000
                    )
                except Exception as wait_e:
                    log(
                        f"[{session_id}] Info: Initial page wait timed out or errored: {wait_e}"
                    )

                # Store NovaAct's own session ID for debugging
                nova_session_id = None
                if hasattr(nova_instance, "session_id"):
                    nova_session_id = nova_instance.session_id
                    log_session_info(
                        "NovaAct session started", session_id, nova_session_id
                    )

                # Take a screenshot
                screenshot_data = None
                try:
                    screenshot_bytes = nova_instance.page.screenshot()
                    screenshot_data = base64.b64encode(screenshot_bytes).decode("utf-8")
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
                        active_sessions[session_id][
                            "error"
                        ] = None  # Clear previous error
                        if nova_session_id:
                            active_sessions[session_id][
                                "nova_session_id"
                            ] = nova_session_id
                    else:
                        # Session might have been cancelled/ended externally
                        log(
                            f"[{session_id}] Warning: Session disappeared before instance could be stored."
                        )
                        # Need to clean up the instance we just created
                        if nova_instance:
                            try:
                                if hasattr(nova_instance, "close") and callable(
                                    nova_instance.close
                                ):
                                    nova_instance.close()
                                elif hasattr(nova_instance, "__exit__"):
                                    nova_instance.__exit__(None, None, None)
                            except Exception:
                                pass  # Avoid errors during cleanup
                        return None  # Indicate failure to store

                # Create result formatted for JSON-RPC
                result = {
                    "session_id": session_id,
                    "url": current_url,
                    "title": page_title,
                    "status": "ready",
                    "success": True,  # NEW – lets tests verify successful start
                }

                return result

            except Exception as e:
                error_message = str(e)
                error_tb = traceback.format_exc()
                log(
                    f"[{session_id}] Error during start_browser_session: {error_message}"
                )
                log(f"Traceback: {error_tb}")

                # Clean up the instance if it was partially created
                if nova_instance:
                    try:
                        log(f"[{session_id}] Attempting cleanup after error...")
                        if hasattr(nova_instance, "close") and callable(
                            nova_instance.close
                        ):
                            nova_instance.close()
                        elif hasattr(nova_instance, "__exit__"):
                            nova_instance.__exit__(None, None, None)
                    except Exception as cleanup_e:
                        log(
                            f"[{session_id}] Error during cleanup after failed start: {cleanup_e}"
                        )

                # Update session registry with error
                with session_lock:
                    if session_id in active_sessions:
                        active_sessions[session_id]["status"] = "error"
                        active_sessions[session_id]["error"] = error_message
                        active_sessions[session_id][
                            "nova_instance"
                        ] = None  # Ensure no broken instance is stored
                        active_sessions[session_id]["last_updated"] = time.time()

                # Return the error in JSON-RPC format
                raise Exception(f"Error starting browser session: {error_message}")

        # Run the synchronous code in the session's dedicated thread
        try:
            # Use run_in_executor to run the synchronous code in the session's thread
            result = await asyncio.get_event_loop().run_in_executor(
                executor, start_browser_session
            )

            # Return the result directly
            return result

        except Exception as e:
            error_message = str(e)
            error_tb = traceback.format_exc()
            log(f"Error in thread execution: {error_message}")
            log(f"Traceback: {error_tb}")

            error = {
                "code": -32603,
                "message": f"Error starting browser session: {error_message}",
                "data": {"traceback": error_tb, "session_id": session_id},
            }

            return {"error": error}

    # Handle the "execute" action
    elif action == "execute":
        # Require session_id for execute (no longer auto-starting)
        if not session_id:
            error = {
                "code": -32602,
                "message": "session_id is required for 'execute' action. Please 'start' a session first.",
                "data": None,
            }
            return {"error": error}

        # Require instruction or credentials for execution
        if not instruction and not (username or password or schema):
            error = {
                "code": -32602,
                "message": "instruction, schema, or credentials are required for 'execute' action.",
                "data": None,
            }
            return {"error": error}

        # Get the session data and the NovaAct instance
        with session_lock:
            session_data = active_sessions.get(session_id)

        if not session_data or session_data.get("status") == "ended":
            error = {
                "code": -32602,
                "message": f"No active session found or session ended: {session_id}",
                "data": None,
            }
            return {"error": error}

        # Get the NovaAct instance and session's dedicated executor
        nova_instance = session_data.get("nova_instance")
        executor = session_data.get("executor")

        if not nova_instance:
            error = {
                "code": -32603,
                "message": f"NovaAct instance missing for session: {session_id}",
                "data": None,
            }
            return {"error": error}

        if executor is None:
            error = {
                "code": -32603,
                "message": "Internal error – executor missing for session.",
                "data": {"session_id": session_id},
            }
            return {"error": error}

        # Define a synchronous function to run in a separate thread
        def execute_instruction():
            original_instruction = instruction  # Keep original for logging/reporting
            instruction_to_execute = instruction  # This one might be modified
            absolute_html_output_paths = [] # Store absolute paths here
            action_handled_directly = False

            try:
                # If a URL is provided for execute, navigate first
                current_url = session_data.get("url")
                if url and nova_instance.page.url != url:
                    log(f"[{session_id}] Navigating to execute URL: {url}")
                    try:
                        # Use the SDK's navigation if available, otherwise use page.goto
                        if hasattr(nova_instance, "go_to_url"):
                            nova_instance.go_to_url(url)  # Use SDK's method per docs
                        else:
                            nova_instance.page.goto(
                                url, wait_until="domcontentloaded", timeout=60000
                            )
                        current_url = url
                        log(f"[{session_id}] Navigation complete.")
                    except Exception as nav_e:
                        raise Exception(
                            f"Failed to navigate to execute URL {url}: {nav_e}"
                        )

                # Optional credential typing
                if username or password:
                    try:
                        log(f"[{session_id}] Handling credentials...")
                        # Prefer explicit selectors
                        if username:
                            nova_instance.page.fill(
                                "input#username, input[name='username'], input[type='text'], input[name*='user']",
                                username,
                                timeout=5000,
                            )
                        if password:
                            nova_instance.page.fill(
                                "input#password, input[name='password'], input[type='password'], input[name*='pass']",
                                password,
                                timeout=5000,
                            )
                    except Exception:
                        log(
                            f"[{session_id}] Falling back to focus/type for credentials"
                        )
                        # Fallback: focus + type
                        if username:
                            nova_instance.act("focus the username field")
                            nova_instance.page.keyboard.type(username)
                        if password:
                            nova_instance.act("focus the password field")
                            nova_instance.page.keyboard.type(password)

                    if (
                        not original_instruction
                    ):  # Auto-click Login if no other instruction
                        log(f"[{session_id}] Auto-clicking login after credentials.")
                        instruction_to_execute = (
                            "click the Login button"  # Set instruction
                        )
                        original_instruction = "[Auto-Login]"  # For reporting
                    else:
                        # Sanitize the instruction that WILL be executed
                        log(
                            f"[{session_id}] Sanitizing instruction after credential input."
                        )
                        safe_instruction = original_instruction
                        if username:
                            safe_instruction = safe_instruction.replace(
                                username, "«username»"
                            )
                        if password:
                            safe_instruction = safe_instruction.replace(
                                password, "«password»"
                            )
                        safe_instruction = re.sub(
                            r"(?i)password", "••••••", safe_instruction
                        )
                        instruction_to_execute = safe_instruction

                # --- Direct Playwright Action Interpretation ---
                # Example: Look for "Type 'text' into 'selector'" pattern
                type_match = re.match(
                    r"^\s*Type\s+['\"](.*)['\"]\s+into\s+element\s+['\"](.*)['\"]\s*$",
                    original_instruction or "",
                    re.IGNORECASE,
                )

                if type_match:
                    text_to_type = type_match.group(1)
                    element_selector = type_match.group(2)
                    log(
                        f"[{session_id}] Handling instruction directly: Typing '{text_to_type}' into '{element_selector}'"
                    )
                    try:
                        # Use page.fill which is often better for inputs
                        nova_instance.page.fill(
                            element_selector, text_to_type, timeout=10000
                        )
                        # Alternatively, use type:
                        # nova_instance.page.locator(element_selector).type(text_to_type, delay=50, timeout=10000)
                        log(f"[{session_id}] Direct fill successful.")
                        action_handled_directly = True
                        result = None  # No result object from nova.act needed
                        response_content = f"Successfully typed text into '{element_selector}' using direct Playwright call."

                    except Exception as direct_e:
                        log(
                            f"[{session_id}] Error during direct Playwright fill/type: {direct_e}"
                        )
                        raise Exception(
                            f"Failed direct Playwright action: {direct_e}"
                        )  # Propagate error

                # --- Look for "Click element 'selector'" pattern ---
                elif re.match(
                    r"^\s*Click\s+element\s+['\"](.*)['\"]\s*$",
                    original_instruction or "",
                    re.IGNORECASE,
                ):
                    element_selector = re.match(
                        r"^\s*Click\s+element\s+['\"](.*)['\"]\s*$",
                        original_instruction,
                        re.IGNORECASE,
                    ).group(1)
                    log(
                        f"[{session_id}] Handling click directly: Clicking element '{element_selector}'"
                    )
                    try:
                        nova_instance.page.click(element_selector, timeout=10000)
                        log(f"[{session_id}] Direct click successful.")
                        action_handled_directly = True
                        result = None
                        response_content = f"Successfully clicked element '{element_selector}' using direct Playwright call."
                    except Exception as direct_e:
                        log(
                            f"[{session_id}] Error during direct Playwright click: {direct_e}"
                        )
                        raise Exception(f"Failed direct Playwright click: {direct_e}")

                # --- If not handled directly, try using nova.act (as fallback/default) ---
                elif instruction_to_execute or schema:
                    log(
                        f"[{session_id}] Passing instruction to nova.act: {instruction_to_execute}"
                    )
                    result = nova_instance.act(
                        instruction_to_execute
                        or "Observe the page and respond based on the schema.",
                        timeout=DEFAULT_TIMEOUT,
                        schema=schema,  # Pass schema if provided
                    )

                    # Extract the response properly
                    if (
                        result
                        and hasattr(result, "response")
                        and result.response is not None
                    ):
                        # Handle different response types (string, dict, object)
                        if isinstance(
                            result.response, (str, dict, list, int, float, bool)
                        ):
                            response_content = result.response
                        elif hasattr(result.response, "__dict__"):
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
                    elif (
                        result
                        and hasattr(result, "matches_schema")
                        and result.matches_schema
                        and hasattr(result, "parsed_response")
                    ):
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
                    log(
                        f"[{session_id}] No specific instruction to execute via nova.act."
                    )
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
                html_output_path = None # Temporary variable for path finding
                log(f"[{session_id}] Attempting to find HTML output path...") # ADDED LOG
                if result and hasattr(result, "metadata") and result.metadata:
                    nova_session_id = result.metadata.session_id
                    nova_act_id = result.metadata.act_id
                    log(f"[{session_id}] Found metadata: nova_session_id={nova_session_id}, nova_act_id={nova_act_id}") # ADDED LOG

                    # Try to get the HTML output path from logs_directory
                    logs_dir = (
                        nova_instance.logs_directory
                        if hasattr(nova_instance, "logs_directory")
                        else None
                    )
                    log(f"[{session_id}] Using logs_dir: {logs_dir}") # ADDED LOG

                    if logs_dir and nova_session_id and nova_act_id:
                        possible_html_path = os.path.join(
                            logs_dir, nova_session_id, f"act_{nova_act_id}_output.html"
                        )
                        log(f"[{session_id}] Constructed possible_html_path: {possible_html_path}") # ADDED LOG
                        path_exists = os.path.exists(possible_html_path) # ADDED Check
                        log(f"[{session_id}] Does path exist? {path_exists}") # ADDED LOG
                        if path_exists:
                            html_output_path = os.path.abspath(possible_html_path) # Get absolute path
                            if html_output_path not in absolute_html_output_paths:
                                absolute_html_output_paths.append(html_output_path) # Store absolute path
                            log(f"[{session_id}] Found and stored absolute HTML output path: {html_output_path}") # MODIFIED LOG

                    # If logs_directory is not set or path not found, try temp directory
                    if not html_output_path:
                        log(f"[{session_id}] Path not found in logs_dir, searching temp dir...")
                        temp_dir = tempfile.gettempdir()
                        log(f"[{session_id}] Temp directory: {temp_dir}")
                        
                        # Broader search for HTML logs
                        for root, dirs, files in os.walk(temp_dir):
                            # Look for directories that contain 'nova_act_logs' in the path
                            # Less restrictive - don't require exact session ID match
                            if 'nova_act_logs' in root:
                                log(f"[{session_id}] Found nova_act_logs directory: {root}")
                                for file in files:
                                    if file.endswith("_output.html"):
                                        log(f"[{session_id}] Found potential output HTML: {file}")
                                        temp_path = os.path.join(root, file)
                                        if os.path.exists(temp_path): 
                                            abs_temp_path = os.path.abspath(temp_path)
                                            file_mtime = os.path.getmtime(temp_path)
                                            # Add creation time to sort newest files first
                                            log(f"[{session_id}] Found HTML file: {abs_temp_path} (modified: {file_mtime})")
                                            if abs_temp_path not in absolute_html_output_paths:
                                                absolute_html_output_paths.append(abs_temp_path)
                                                log(f"[{session_id}] Added HTML file to results list")
                            # Don't search too deeply - only go one level deeper in matching directories
                            if 'nova_act_logs' not in root:
                                # Remove directories that don't seem promising
                                dirs[:] = [d for d in dirs if 'nova' in d.lower() or 'act' in d.lower() or 'log' in d.lower() or 'tmp' in d.lower()]
                            
                        # If we found multiple paths, sort by modification time (newest first)
                        if len(absolute_html_output_paths) > 1:
                            absolute_html_output_paths.sort(key=lambda path: os.path.getmtime(path), reverse=True)
                            log(f"[{session_id}] Sorted {len(absolute_html_output_paths)} HTML logs by modification time")
                else:
                     log(f"[{session_id}] No result or result.metadata found. Cannot search for HTML path.") # ADDED LOG

                # Extract agent thinking (only if we used nova.act)
                agent_messages = []
                debug_info = {}
                
                # --- Always sort collected HTML log paths by mtime (newest first) ---
                if absolute_html_output_paths:
                    absolute_html_output_paths.sort(key=os.path.getmtime, reverse=True)
                
                # Pass the *first found* absolute path to the extraction function
                found_log_path_for_thinking = absolute_html_output_paths[0] if absolute_html_output_paths else None
                if result: # Only try extraction if nova.act was called
                    agent_messages, debug_info = extract_agent_thinking(
                        result,
                        nova_instance,
                        found_log_path_for_thinking, # Pass the specific path found
                        instruction_to_execute,
                    )
                elif action_handled_directly:
                    debug_info = {
                        "direct_action": True,
                        "action_type": "playwright_direct",
                    }

                # Screenshot code remains disabled
                screenshot_data = None

                # Update session registry with results - USE ABSOLUTE PATHS
                with session_lock:
                    if session_id in active_sessions:
                        active_sessions[session_id]["url"] = updated_url
                        # Ensure results list exists
                        if "results" not in active_sessions[session_id]:
                             active_sessions[session_id]["results"] = []
                        active_sessions[session_id]["results"].append(
                            {
                                "action": original_instruction,
                                "executed": (
                                    instruction_to_execute
                                    if not action_handled_directly
                                    else "direct_playwright"
                                ),
                                "response": response_content,
                                "agent_messages": agent_messages,
                                "output_html_paths": absolute_html_output_paths, # Store absolute paths list
                                "screenshot_included": False,
                                "direct_action": action_handled_directly,
                                "timestamp": time.time() # Add timestamp for easier debugging
                            }
                        )
                        active_sessions[session_id]["last_updated"] = time.time()
                        active_sessions[session_id]["status"] = "browser_ready"
                        active_sessions[session_id]["error"] = None
                    else:
                         log(f"[{session_id}] Session disappeared before results could be stored.")


                # Find the first valid HTML log path from the stored list for reporting
                final_html_log_path_for_reporting = None
                for path in absolute_html_output_paths:
                    if path and os.path.exists(path):
                        final_html_log_path_for_reporting = path
                        break

                # Format agent thinking for MCP response
                agent_thinking_mcp = [] # Use different variable name to avoid confusion
                for message in agent_messages:
                    agent_thinking_mcp.append(
                        {"type": "reasoning", "content": message, "source": "nova_act"}
                    )

                # Create result properly formatted for JSON-RPC result field
                action_type = (
                    "direct Playwright" if action_handled_directly else "Nova Act SDK"
                )

                # Assemble the main text, adding the HTML log path if found
                main_text = (
                    f"Successfully executed via {action_type}: {original_instruction or 'Schema Observation'}\\n\\n"
                    f"Current URL: {updated_url}\\nPage Title: {page_title}\\n"
                    # Limit response content length in main text
                    f"Response: {json.dumps(response_content)[:1000]}{'...' if len(json.dumps(response_content)) > 1000 else ''}"
                )
                if final_html_log_path_for_reporting:
                    main_text += f"\\nNova Act HTML Log Path (for server reference): {final_html_log_path_for_reporting}"

                # This is the dictionary that goes into the "result" field of the JSON-RPC response
                mcp_result_value = {
                    "content": [{"type": "text", "text": main_text}],
                    "agent_thinking": agent_thinking_mcp, # Use the formatted list
                    "isError": False,
                    "session_id": session_id,
                    "direct_action": action_handled_directly,
                    "success": True, # Indicate logical success of the operation
                    "current_url": updated_url, # Add current URL for context
                    "page_title": page_title, # Add page title for context
                }

                # Include debug info if in debug mode
                if DEBUG_MODE:
                    mcp_result_value["debug"] = {
                        "html_paths_found": absolute_html_output_paths,
                        "html_log_path_selected_for_reporting": final_html_log_path_for_reporting,
                        "extraction_info": debug_info,
                        # Avoid putting potentially large response object in debug if already in main text
                        # "response_object": response_content,
                    }

                return mcp_result_value # Return the dictionary for the "result" field

            except (ActGuardrailsError, ActError, Exception) as e:
                # Refined Error Handling
                error_message = f"Execution error: {str(e)}"
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

                # Ensure the exception raised contains the error message
                raise Exception(f"({error_type}) {error_message}") from e

        # Run the synchronous code in the session's dedicated thread
        try:
            # Use run_in_executor to run the synchronous code in the session's thread
            result_value = await asyncio.get_event_loop().run_in_executor(
                executor, execute_instruction
            )
            # FastMCP expects the result value directly
            return result_value

        except Exception as e:
            error_message = str(e)
            error_tb = traceback.format_exc()
            log(f"Error in thread execution: {error_message}")
            log(f"Traceback: {error_tb}")

            # FastMCP expects the error dictionary directly
            error_obj = {
                "code": -32603,
                "message": f"Error executing instruction: {error_message}",
                "data": {"session_id": session_id},
            }
            return error_obj # Return the error dictionary

    # Handle the "end" action
    elif action == "end":
        if not session_id:
            error = {
                "code": -32602,
                "message": "session_id is required for 'end' action.",
                "data": None,
            }
            return {"error": error}

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
                        if hasattr(nova_instance, "close") and callable(
                            nova_instance.close
                        ):
                            nova_instance.close()
                            log(f"[{session_id}] NovaAct instance closed.")
                        elif hasattr(nova_instance, "__exit__") and callable(
                            nova_instance.__exit__
                        ):
                            nova_instance.__exit__(
                                None, None, None
                            )  # Try context manager exit
                            log(f"[{session_id}] NovaAct instance exited via __exit__.")
                        else:
                            log(
                                f"[{session_id}] Warning: No close() or __exit__ method found. Browser might remain."
                            )
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
                        active_sessions[session_id][
                            "nova_instance"
                        ] = None  # Clear the instance
                        active_sessions[session_id][
                            "executor"
                        ] = None  # Clear the executor

                return {"session_id": session_id, "status": "ended", "success": True}
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
                    "data": None,
                }
                return {"error": error}
            executor = session_data.get("executor")

        # Run the synchronous code in the session's dedicated thread
        try:
            # Use run_in_executor to run the synchronous code in the session's thread
            result = await asyncio.get_event_loop().run_in_executor(
                executor if executor else None, end_browser_session
            )

            # Return the result directly
            return result

        except Exception as e:
            error_message = str(e)
            error_tb = traceback.format_exc()
            log(f"Error in thread execution: {error_message}")
            log(f"Traceback: {error_tb}")

            error = {
                "code": -32603,
                "message": f"Error ending browser session: {error_message}",
                "data": {"session_id": session_id},
            }

            return {"error": error}

    else:
        error = {
            "code": -32601,
            "message": f"Unknown action '{action}'. Valid actions are 'start', 'execute', 'end'.",
            "data": None,
        }
        return {"error": error}


def main():
    """Main function to run the MCP server or display version information"""
    import argparse
    import importlib.metadata
    import sys

    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Nova Act MCP Server - FastMCP wrapper for Nova-Act"
    )
    parser.add_argument(
        "--version", action="store_true", help="Display version information"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument(
        "tool",
        nargs="?",
        default=None,
        help="Optional tool name (control_browser, list_browser_sessions, ...)",
    )
    args, unknown = parser.parse_known_args()

    # Set debug mode if requested
    if args.debug:
        global DEBUG_MODE
        DEBUG_MODE = True
        os.environ["NOVA_MCP_DEBUG"] = "1"

    # Display version and exit if requested
    if args.version or "--version" in unknown:
        try:
            version = importlib.metadata.version("nova-act-mcp")
            print(f"nova-act-mcp version {version}")
        except importlib.metadata.PackageNotFoundError:
            print("nova-act-mcp (development version)")
        return

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
        log(
            "  Please add 'novaActApiKey' to your MCP config or set NOVA_ACT_API_KEY environment variable"
        )

    log(
        "- Tool: list_browser_sessions - List all active and recent web browser sessions ✓"
    )
    log(
        "- Tool: control_browser - Manage and interact with web browser sessions via Nova Act agent ✓"
    )
    log("- Tool: view_html_log - View HTML logs from browser sessions ✓")

    log("\nStarting MCP server...")
    # Initialize and run the server
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
