import asyncio
import atexit
import base64
import concurrent.futures
import gzip  # Added for log compression
import html  # Added for HTML parsing in extract_agent_thinking
import json
import logging
import mimetypes
import os
import re
import shutil  # Added for directory removal
import sys
import tempfile
import threading
import time
import traceback
import uuid  # Added for unique session dirs
from pathlib import Path
from typing import Any, Dict, Optional, Literal, List, Tuple, Union, Annotated
import importlib.metadata  # For version info in main()

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
SCREENSHOT_QUALITY = 45  # JPEG quality for screenshots (lower = smaller file size)

# === Screenshot compression/embedding limits ===
MAX_INLINE_IMAGE_BYTES = int(os.getenv("NOVA_MCP_MAX_INLINE_IMG", "256000"))  # ≈250 KB
INLINE_IMAGE_QUALITY   = int(os.getenv("NOVA_MCP_INLINE_IMG_QUALITY", "45"))   # JPEG quality

# User profiles directory - Now determined dynamically
# PROFILES_DIR = "./profiles" # Removed
DEFAULT_PROFILE_IDENTITY = "default"  # Default identity name if none provided

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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[NOVA_LOG] %(message)s',
    stream=sys.stderr  # Changed from stdout to stderr
)
logger = logging.getLogger("nova_mcp")

# Add a verbose flag that can be set through environment variable
VERBOSE_LOGGING = os.environ.get("NOVA_MCP_VERBOSE_LOGGING", "false").lower() == "true"

def log_info(message: str):
    """Log info message with consistent format"""
    logger.info(message)

def log_debug(message: str):
    """Log debug message only if verbose logging is enabled"""
    if VERBOSE_LOGGING:
        logger.info(f"DEBUG: {message}")

def log_error(message: str):
    """Log error message with consistent format"""
    logger.error(message)


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
        if (api_key):
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


# Helper function to determine the root directory for browser profiles
def _profile_root() -> Path:
    """Determine the root directory for browser profiles."""
    # 1) Caller can force a location via environment variable
    override = os.getenv("NOVA_ACT_PROFILE_DIR")
    if (override):
        log(f"Using profile directory override from NOVA_ACT_PROFILE_DIR: {override}")
        return Path(override).expanduser()

    # 2) Otherwise use OS-temp (always writable in Claude / uvx)
    default_path = Path(tempfile.gettempdir()) / "nova_act_mcp_profiles"
    log(f"Using default profile directory in temp: {default_path}")
    return default_path


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

    # No longer creating ./profiles here
    # os.makedirs(os.path.join(PROFILES_DIR, DEFAULT_PROFILE), exist_ok=True)


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
        "whose last action produced a log. "
        "Returns { content:[{type:\"html\", html:\"…\"}], truncated:bool } — consume the html field directly."
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
        "Start, operate and end a Nova Act browser session. "
        "Use 'inspect_browser' to get screenshots of the current browser state."
    ),
)
async def browser_session(
    action: Literal["start", "execute", "end"] = "execute",
    session_id: Optional[str] = None,
    url: Optional[str] = None,
    instruction: Optional[str] = None,
    headless: Annotated[bool, "Run browser in headless mode"] = True,
    username: Optional[str] = None,
    password: Optional[str] = None,
    schema: Optional[dict] = None,
    identity: str = DEFAULT_PROFILE_IDENTITY, # Added identity parameter
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
        identity: A string to group related sessions (e.g., 'user123'). Used for profile directory naming. Defaults to 'default'.

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
        log(f"Starting new browser session with session ID: {session_id} for identity: {identity}")

        # Create a progress context
        progress_context = {
            "current_step": 0,
            "total_steps": 1,
            "current_action": "initializing",
            "is_complete": False,
            "last_update": time.time(),
        }

        # Determine the unique profile directory for this specific session
        session_profile_dir = _profile_root() / identity / session_id # Use session_id for uniqueness
        log(f"[{session_id}] Calculated profile directory: {session_profile_dir}")

        # Register this session in the global registry, including the profile path
        with session_lock:
            active_sessions[session_id] = {
                "session_id": session_id,
                "identity": identity, # Store the identity used
                "profile_dir": str(session_profile_dir), # Store the profile path
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
                # Create the unique profile directory for this session
                log(f"[{session_id}] Creating profile directory: {session_profile_dir}")
                session_profile_dir.mkdir(parents=True, exist_ok=True) # Use Path object's mkdir
                log(f"[{session_id}] Profile directory created successfully.")

                log(f"[{session_id}] Opening browser to {url}")

                # Create NovaAct instance using the unique session profile dir
                nova_instance = NovaAct(
                    starting_page=url,
                    nova_act_api_key=api_key,
                    user_data_dir=str(session_profile_dir), # Pass the unique dir
                    headless=headless,
                )

                # Normalize the logs directory attribute names
                logs_dir_value = _normalize_logs_dir(nova_instance)
                if logs_dir_value:
                    with session_lock:
                        active_sessions[session_id]["logs_dir"] = logs_dir_value
                        log(f"[{session_id}] Captured logs directory: {logs_dir_value}")

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

                # --- CRITICAL: Capture and store the specific logs directory ---
                base_logs_dir_from_sdk = _normalize_logs_dir(nova_instance)
                nova_act_internal_session_id = getattr(nova_instance, 'session_id', None)
                final_session_specific_logs_dir = None

                if base_logs_dir_from_sdk and nova_act_internal_session_id:
                    # NovaAct often creates a subdirectory named after its internal session_id
                    candidate_specific_dir = Path(base_logs_dir_from_sdk) / nova_act_internal_session_id
                    if candidate_specific_dir.is_dir():
                        final_session_specific_logs_dir = str(candidate_specific_dir.resolve())
                        log(f"[{session_id}] Confirmed NovaAct session-specific logs directory: {final_session_specific_logs_dir}")
                    elif Path(base_logs_dir_from_sdk).name == nova_act_internal_session_id:
                        # Sometimes the SDK attribute already points to the specific session dir
                        final_session_specific_logs_dir = str(Path(base_logs_dir_from_sdk).resolve())
                        log(f"[{session_id}] Using logs_dir attribute directly as session-specific: {final_session_specific_logs_dir}")
                    else:
                        # Fallback: If SDK provides a base and subdir isn't immediately there,
                        # it might be created on the first `act`. Store base for now.
                        final_session_specific_logs_dir = str(Path(base_logs_dir_from_sdk).resolve())
                        log(f"[{session_id}] Storing base NovaAct logs directory: {final_session_specific_logs_dir}. May be refined by first 'act'.")
                elif base_logs_dir_from_sdk: # No internal session ID from SDK, but got a base logs_dir
                    final_session_specific_logs_dir = str(Path(base_logs_dir_from_sdk).resolve())
                    log(f"[{session_id}] Storing provided base NovaAct logs directory (no internal session ID from SDK): {final_session_specific_logs_dir}")
                else:
                    log(f"[{session_id}] CRITICAL WARNING: Could not retrieve logs_dir from NovaAct instance at start. Log discovery for subsequent tools will be impacted.")
                    if VERBOSE_LOGGING: # Help debug if logs_dir is missing
                        log(f"[{session_id}] Attributes of nova_instance: {dir(nova_instance)}")

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
                    screenshot_bytes = nova_instance.page.screenshot(type="jpeg", quality=SCREENSHOT_QUALITY)
                    # Use our helper function to get logs_dir consistently
                    logs_dir_attr = _normalize_logs_dir(nova_instance)
                    
                    # If we found any valid logs directory attribute
                    if logs_dir_attr:
                        # Save screenshot to disk
                        shot_path = Path(logs_dir_attr) / f"screenshot_{uuid.uuid4().hex}.jpg"
                        shot_path.write_bytes(screenshot_bytes)
                        # Still keep base64 encoding for backward compatibility
                        screenshot_data = base64.b64encode(screenshot_bytes).decode("utf-8")
                    else:
                        log(f"[{session_id}] Warning: Couldn't find logs directory in nova_instance attributes")
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
                                elif hasattr(nova_instance, "__exit__") and callable(
                                    nova_instance.__exit__
                                ):
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
                        elif hasattr(nova_instance, "__exit__") and callable(
                            nova_instance.__exit__
                        ):
                            nova_instance.__exit__(None, None, None)
                    except Exception as cleanup_e:
                        log(
                            f"[{session_id}] Error during cleanup after failed start: {cleanup_e}"
                        )

                # Attempt to clean up profile dir if creation failed mid-way or start failed
                if session_profile_dir.exists():
                    try:
                        log(f"[{session_id}] Cleaning up profile directory after error: {session_profile_dir}")
                        shutil.rmtree(session_profile_dir)
                    except Exception as cleanup_e:
                        log(f"[{session_id}] Error cleaning up profile directory after failed start: {cleanup_e}")

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

                    # --- Capture logs_dir after nova.act (the SDK may populate it late)
                    try:
                        new_logs_dir = (
                            getattr(nova_instance, "logs_directory", None)
                            or getattr(nova_instance, "logs_dir", None)
                            or getattr(nova_instance, "log_dir", None)
                        )
                        if new_logs_dir:
                            with session_lock:
                                active_sessions[session_id]["logs_dir"] = new_logs_dir
                                log(f"[{session_id}] Updated logs_dir after act(): {new_logs_dir}")
                    except Exception as e:
                        log(f"[{session_id}] Error capturing logs_dir after act(): {e}")
                        pass

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
                log(f"[{session_id}] Action completed. Current URL: {updated_url}, Title: {page_title}")

                # No longer capturing screenshots in execute - use inspect_browser instead

                # Look for the output HTML file in the logs (only if we used nova.act)
                html_output_path = None # Temporary variable for path finding
                log(f"[{session_id}] Attempting to find HTML output path...") # ADDED LOG
                if result and hasattr(result, "metadata") and result.metadata:
                    nova_session_id = result.metadata.session_id
                    nova_act_id = result.metadata.act_id
                    log(f"[{session_id}] Found metadata: nova_session_id={nova_session_id}, nova_act_id={nova_act_id}") # ADDED LOG

                    # Try to get the HTML output path directly from nova_instance
                    if hasattr(nova_instance, "last_output_html_path") and nova_instance.last_output_html_path:
                        html_output_path = os.path.abspath(nova_instance.last_output_html_path)
                        log(f"[{session_id}] Found HTML path from nova_instance.last_output_html_path: {html_output_path}")
                        if html_output_path not in absolute_html_output_paths:
                            absolute_html_output_paths.append(html_output_path)
                    
                    # If that didn't work, try to construct the path from logs_directory
                    if not html_output_path:
                        # Try every known attribute for Act log directory
                        logs_dir = (
                            getattr(nova_instance, "logs_directory", None)
                            or getattr(nova_instance, "logs_dir", None)
                            or getattr(nova_instance, "log_dir", None)
                        )
                        # Cache for later tools
                        if logs_dir:
                            with session_lock:
                                active_sessions[session_id]["logs_dir"] = logs_dir
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
                            
                            # ------------------------------------------------------------------
                            # Capture *_calls.json for later compression
                            har_json_path = None
                            if logs_dir and nova_session_id and nova_act_id:
                                candidate = Path(logs_dir) / nova_session_id / f"act_{nova_act_id}_calls.json"
                                if candidate.exists():
                                    har_json_path = str(candidate.resolve())
                                    log(f"[{session_id}] Found HAR JSON path: {har_json_path}")

                            # store it in the session dict
                            with session_lock:
                                if session_id in active_sessions:
                                    if har_json_path:
                                        active_sessions[session_id]["last_har_path"] = har_json_path
                            # ------------------------------------------------------------------

                    # If logs_directory is not set or path not found, try temp directory
                    if not html_output_path:
                        log(f"[{session_id}] Path not found in logs_dir, searching temp dir...")
                        temp_dir = tempfile.gettempdir()
                        log(f"[{session_id}] Temp directory: {temp_dir}")
                        
                        # Track count of directories found for less verbose logging
                        logs_dir_count = 0
                        html_files_found = 0
                        
                        # Broader search for HTML logs
                        for root, dirs, files in os.walk(temp_dir):
                            # Look for directories that contain 'nova_act_logs' in the path
                            if 'nova_act_logs' in root:
                                # Only log directory paths if verbose logging is enabled
                                if VERBOSE_LOGGING:
                                    log(f"[{session_id}] Found nova_act_logs directory: {root}")
                                else:
                                    logs_dir_count += 1
                                    
                                for file in files:
                                    if file.endswith("_output.html"):
                                        # Only log file discovery if verbose or it's potentially the right file
                                        if VERBOSE_LOGGING:
                                            log(f"[{session_id}] Found potential output HTML: {file}")
                                        temp_path = os.path.join(root, file)
                                        if os.path.exists(temp_path): 
                                            abs_temp_path = os.path.abspath(temp_path)
                                            file_mtime = os.path.getmtime(temp_path)
                                            # Add creation time to sort newest files first
                                            if VERBOSE_LOGGING:
                                                log(f"[{session_id}] Found HTML file: {abs_temp_path} (modified: {file_mtime})")
                                            if abs_temp_path not in absolute_html_output_paths:
                                                absolute_html_output_paths.append(abs_temp_path)
                                                html_files_found += 1
                                                if VERBOSE_LOGGING:
                                                    log(f"[{session_id}] Added HTML file to results list")
                            # Don't search too deeply - only go one level deeper in matching directories
                            if 'nova_act_logs' not in root:
                                # Remove directories that don't seem promising
                                dirs[:] = [d for d in dirs if 'nova' in d.lower() or 'act' in d.lower() or 'log' in d.lower() or 'tmp' in d.lower()]
                        
                        # Log summary instead of verbose details when not in verbose mode
                        if not VERBOSE_LOGGING and logs_dir_count > 0:
                            log(f"[{session_id}] Found {logs_dir_count} nova_act_logs directories and {html_files_found} HTML files")
                            
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

                # Find HAR JSON log files to store in session data
                # This will be used for auto-compression
                har_json_path = None
                # --- Locate the HAR / calls JSON for compression ----
                har_json_path = None

                # 1) First, prefer a direct attribute on the NovaAct instance
                for attr in ("last_calls_json_path", "last_har_path", "last_output_calls_json_path"):
                    candidate = getattr(nova_instance, attr, None)
                    if candidate and os.path.exists(candidate):
                        har_json_path = os.path.abspath(candidate)
                        log(f"[{session_id}] Found HAR path directly from nova_instance.{attr}: {har_json_path}")
                        break

                # 2) Fallback to constructing it from logs_dir + IDs
                if not har_json_path and logs_dir and nova_session_id and nova_act_id:
                    possible = os.path.join(
                        logs_dir, nova_session_id, f"act_{nova_act_id}_calls.json"
                    )
                    if os.path.exists(possible):
                        har_json_path = os.path.abspath(possible)
                        log(f"[{session_id}] Found HAR path by constructing from logs_dir: {har_json_path}")

                # 3) Save for later compression
                if har_json_path:
                    with session_lock:
                        active_sessions[session_id]["last_har_path"] = har_json_path
                        log(f"[{session_id}] Saved HAR path to session: {har_json_path}")
                
                # Update session registry with results - USE ABSOLUTE PATHS
                with session_lock:
                    if session_id in active_sessions:
                        active_sessions[session_id]["url"] = updated_url
                        # Ensure results list exists
                        if "results" not in active_sessions[session_id]:
                             active_sessions[session_id]["results"] = []
                        
                        # Store the HAR path for potential compression
                        result_entry = {
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
                            "timestamp": time.time(), # Add timestamp for easier debugging
                        }
                        
                        # Add HAR path if found
                        if har_json_path:
                            result_entry["har_json_path"] = har_json_path
                        
                        active_sessions[session_id]["results"].append(result_entry)
                        active_sessions[session_id]["last_updated"] = time.time()
                        active_sessions[session_id]["status"] = "browser_ready"
                        active_sessions[session_id]["error"] = None
                        
                        # Store the last HAR path in the session for easy access
                        if har_json_path:
                            active_sessions[session_id]["last_har_path"] = har_json_path
                            
                            # --- Auto-compress the HAR and remember where it went ---
                            comp_info = compress_log_file(har_json_path, extract_screenshots=True)
                            if comp_info.get("success"):
                                comp_path = comp_info.get("compressed_path")
                                log(f"[{session_id}] HAR compressed ➜ {comp_path}")
                                active_sessions[session_id]["last_compressed_log_path"] = comp_path
                    else:
                         log(f"[{session_id}] Session disappeared before results could be stored.")

                # --- Refined Log Path Discovery & Storage ---
                # Get base logs_dir and nova_act_session_id stored during "start"
                session_data_locked = active_sessions.get(session_id, {}) # Read from shared dict safely if needed
                current_mcp_session_logs_dir = session_data_locked.get('logs_dir')
                current_nova_act_session_id = session_data_locked.get('nova_session_id')
                
                # The logs_dir stored at "start" might be a base. Refine if NovaAct created its session_id subdir.
                if current_mcp_session_logs_dir and current_nova_act_session_id and \
                   not Path(current_mcp_session_logs_dir).name == current_nova_act_session_id:
                    
                    candidate_specific_dir = Path(current_mcp_session_logs_dir) / current_nova_act_session_id
                    if candidate_specific_dir.is_dir():
                        current_mcp_session_logs_dir = str(candidate_specific_dir.resolve())
                        log(f"[{session_id}] Refined logs_dir to NovaAct session specific: {current_mcp_session_logs_dir}")
                        with session_lock: # Update in shared dict
                            if session_id in active_sessions: active_sessions[session_id]['logs_dir'] = current_mcp_session_logs_dir
                    # If logs_dir from SDK is already specific, use it
                    elif _normalize_logs_dir(nova_instance) and Path(_normalize_logs_dir(nova_instance)).name == current_nova_act_session_id:
                        current_mcp_session_logs_dir = str(Path(_normalize_logs_dir(nova_instance)).resolve())
                        log(f"[{session_id}] Updated logs_dir from SDK to specific: {current_mcp_session_logs_dir}")
                        with session_lock:
                            if session_id in active_sessions: active_sessions[session_id]['logs_dir'] = current_mcp_session_logs_dir

                # Extract act_id from result.metadata
                current_act_id = getattr(result.metadata, 'act_id', None) if result and hasattr(result, 'metadata') else None
                
                absolute_html_output_paths_for_this_act = []
                har_json_path_for_this_act = None

                if current_act_id and current_mcp_session_logs_dir and Path(current_mcp_session_logs_dir).is_dir():
                    log(f"[{session_id}] Searching for logs for act_id '{current_act_id}' in: {current_mcp_session_logs_dir}")
                    
                    # HTML output path for this specific act
                    constructed_html_path = Path(current_mcp_session_logs_dir) / f"act_{current_act_id}_output.html"
                    if constructed_html_path.exists():
                        html_path_val = str(constructed_html_path.resolve())
                        log(f"[{session_id}] Found HTML path for this act: {html_path_val}")
                        absolute_html_output_paths_for_this_act.append(html_path_val)
                    else:
                        log(f"[{session_id}] WARNING: Constructed HTML path for this act does not exist: {constructed_html_path}")

                    # HAR/JSON calls path for this specific act
                    constructed_calls_json_path = Path(current_mcp_session_logs_dir) / f"act_{current_act_id}_calls.json"
                    if constructed_calls_json_path.exists():
                        har_json_path_for_this_act = str(constructed_calls_json_path.resolve())
                        log(f"[{session_id}] Found HAR JSON path for this act: {har_json_path_for_this_act}")
                    else:
                        log(f"[{session_id}] WARNING: Constructed calls.json path for this act does not exist: {constructed_calls_json_path}")
                elif not current_act_id:
                     log(f"[{session_id}] WARNING: No act_id from NovaAct result.metadata, cannot construct specific log paths.")
                elif not (current_mcp_session_logs_dir and Path(current_mcp_session_logs_dir).is_dir()):
                     log(f"[{session_id}] WARNING: logs_dir ('{current_mcp_session_logs_dir}') is not valid for log path construction.")


                # Fallback to SDK's last known paths if direct construction failed
                if not absolute_html_output_paths_for_this_act and hasattr(nova_instance, "last_output_html_path") and nova_instance.last_output_html_path:
                    sdk_html_path = str(Path(nova_instance.last_output_html_path).resolve())
                    if Path(sdk_html_path).exists():
                        log(f"[{session_id}] Using SDK's last_output_html_path: {sdk_html_path}")
                        absolute_html_output_paths_for_this_act.append(sdk_html_path)
                
                if not har_json_path_for_this_act:
                    for attr in ("last_calls_json_path", "last_har_path", "last_output_calls_json_path"):
                        candidate = getattr(nova_instance, attr, None)
                        if candidate and Path(candidate).exists():
                            har_json_path_for_this_act = str(Path(candidate).resolve())
                            log(f"[{session_id}] Using SDK's {attr}: {har_json_path_for_this_act}")
                            break
                
                # Store these specific paths in the current step's result entry
                with session_lock:
                    if session_id in active_sessions and active_sessions[session_id].get("results"):
                        # Assuming result_entry was just appended to active_sessions[session_id]["results"]
                        # by the preceding code block that created it.
                        # Let's ensure we are updating the correct (last) result entry.
                        if active_sessions[session_id]["results"]:
                            last_result_entry = active_sessions[session_id]["results"][-1]
                            last_result_entry["output_html_paths"] = absolute_html_output_paths_for_this_act
                            if har_json_path_for_this_act:
                                last_result_entry["har_json_path"] = har_json_path_for_this_act
                                # Also update the session-level 'last_har_path' for convenience for compress_logs
                                active_sessions[session_id]["last_har_path"] = har_json_path_for_this_act
                        else:
                            log(f"[{session_id}] WARNING: 'results' list is empty, cannot store log paths for this step.")
                    else:
                        log(f"[{session_id}] WARNING: Session or results list not found, cannot store log paths.")

                # --- Agent Thinking Extraction ---
                # Use the most recently found HTML path for thinking extraction
                final_html_log_path_for_thinking = None
                if absolute_html_output_paths_for_this_act: # This list now contains paths for *this* act
                    # If multiple, could sort by mtime, but usually it's just one from current_act_id
                    absolute_html_output_paths_for_this_act.sort(key=lambda p: Path(p).stat().st_mtime, reverse=True)
                    final_html_log_path_for_thinking = absolute_html_output_paths_for_this_act[0]
                    log(f"[{session_id}] Using HTML log for thinking extraction: {final_html_log_path_for_thinking}")

                agent_messages, debug_info = extract_agent_thinking(
                    result,
                    nova_instance,
                    final_html_log_path_for_thinking,
                    instruction_to_execute,
                )

                # Find the first valid HTML log path from the stored list for reporting
                final_html_log_path_for_reporting = None
                for path in absolute_html_output_paths:
                    if path and os.path.exists(path):
                        final_html_log_path_for_reporting = path
                        break

                # Format agent thinking for MCP response
                agent_thinking_mcp = [] # Use different variable name to avoid confusion
                
                # Add any agent reasoning messages from NovaAct
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
            session_profile_dir_to_remove = None # Store path before removing from registry
            try:
                # Get the session data and NovaAct instance
                with session_lock:
                    session_data = active_sessions.get(session_id)
                    if not session_data:
                        raise Exception(f"No active session found to end: {session_id}")
                    nova_instance = session_data.get("nova_instance")
                    executor = session_data.get("executor")
                    session_profile_dir_to_remove = session_data.get("profile_dir") # Get path for cleanup

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

                # Clean up the profile directory AFTER closing browser/executor
                if session_profile_dir_to_remove:
                    profile_path = Path(session_profile_dir_to_remove)
                    if profile_path.exists() and profile_path.is_dir():
                        log(f"[{session_id}] Cleaning up profile directory: {profile_path}")
                        try:
                            shutil.rmtree(profile_path)
                            log(f"[{session_id}] Profile directory removed successfully.")
                        except Exception as cleanup_e:
                            log(f"[{session_id}] Error removing profile directory {profile_path}: {cleanup_e}")
                    else:
                        log(f"[{session_id}] Profile directory not found or not a directory, skipping cleanup: {session_profile_dir_to_remove}")
                else:
                    log(f"[{session_id}] No profile directory path found in session data, skipping cleanup.")


                return {"session_id": session_id, "status": "ended", "success": True}
            except Exception as e:
                error_message = str(e)
                error_tb = traceback.format_exc()
                log(f"Error ending browser session: {error_message}")
                log(f"Traceback: {error_tb}")

                error = {
                    "code": -32603,
                    "message": f"Error ending browser session: {error_message}",
                    "data": {"session_id": session_id},
                }

                return {"error": error}

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


def compress_log_file(log_path, extract_screenshots=True, compression_level=9):
    """
    Compress Nova Act logs by removing screenshots and applying gzip compression.
    
    Args:
        log_path (str): Path to the log file to compress
        extract_screenshots (bool): Whether to extract screenshots to separate files
        compression_level (int): Compression level for gzip (1-9)
        
    Returns:
        dict: Information about the compression including paths and size reduction
    """
    if not os.path.exists(log_path):
        log(f"Log file not found: {log_path}")
        return {"success": False, "error": "Log file not found", "compressed_path": None}
    
    try:
        # Get the original file size
        original_size = os.path.getsize(log_path)
        
        # Parse JSON file
        with open(log_path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                log(f"Invalid JSON in log file: {log_path}")
                return {"success": False, "error": "Invalid JSON in log file"}
        
        # Create screenshot directory if extracting screenshots
        screenshot_dir = None
        screenshots = []  # Store extracted screenshots for preview
        screenshot_paths = []  # Store paths to the extracted screenshots
        inline_screenshots = []  # NEW: Store embeddable screenshots
        
        if extract_screenshots:
            screenshot_dir = os.path.join(os.path.dirname(log_path), "screenshots")
            os.makedirs(screenshot_dir, exist_ok=True)
            
            # Extract screenshots to separate files
            for i, entry in enumerate(data):
                if entry.get("request") and entry["request"].get("screenshot"):
                    screenshot_data = entry["request"]["screenshot"]
                    screenshots.append(screenshot_data)  # Store for preview
                    screenshot_path = os.path.join(screenshot_dir, f"screenshot_{uuid.uuid4().hex}.jpg")
                    screenshot_paths.append(screenshot_path)  # Store path for later use
                    try:
                        # Save the screenshot
                        with open(screenshot_path, 'wb') as f:
                            # If it's a data URL, extract the base64 data
                            if screenshot_data.startswith('data:image'):
                                base64_data = screenshot_data.split(',', 1)[1]
                                raw = base64.b64decode(base64_data)
                                f.write(raw)
                            else:
                                # Assume it's already base64
                                try:
                                    raw = base64.b64decode(screenshot_data)
                                    f.write(raw)
                                except:
                                    # If decoding fails, write as text
                                    raw = screenshot_data.encode('utf-8')
                                    f.write(raw)
                        # Record the screenshot path in the data
                        entry["request"]["screenshot_path"] = screenshot_path
                        # NEW: add to inline payload if small enough
                        if isinstance(raw, bytes) and len(raw) <= MAX_INLINE_IMAGE_BYTES:
                            inline_screenshots.append({
                                "filename": Path(screenshot_path).name,
                                "data": f"data:image/jpeg;base64,{base64.b64encode(raw).decode()}"
                            })
                    except Exception as e:
                        log(f"Error saving screenshot {i}: {str(e)}")
        
        # Remove screenshots from the data
        screenshot_size_total = 0
        screenshot_count = 0
        for entry in data:
            # Strip any legacy "screenshot":"data:image/..." keys
            if entry.get("request"):
                # Remove the screenshot data but keep the path if we extracted it
                if entry["request"].get("screenshot"):
                    screenshot_size_total += len(entry["request"]["screenshot"])
                    screenshot_count += 1
                    entry["request"].pop("screenshot", None)
        
        # Create the compressed JSON file path
        compressed_json_path = log_path.replace('.json', '_compressed.json')
        if compressed_json_path == log_path:
            compressed_json_path = log_path + '.compressed'
            
        # Save the JSON without screenshots
        with open(compressed_json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
            
        # Get the size of the JSON without screenshots
        no_screenshots_size = os.path.getsize(compressed_json_path)
        
        # Compress the JSON file with gzip
        gzip_path = compressed_json_path + '.gz'
        with open(compressed_json_path, 'rb') as f_in:
            with gzip.open(gzip_path, 'wb', compresslevel=compression_level) as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        # Get the raw compressed data for preview
        with open(gzip_path, 'rb') as f:
            compressed_data = f.read()
                
        # Get the compressed file size
        compressed_size = os.path.getsize(gzip_path)
        
        # Calculate size reductions
        size_reduction_no_screenshots = round((original_size - no_screenshots_size) / original_size * 100, 2)
        size_reduction_compressed = round((original_size - compressed_size) / original_size * 100, 2)
        
        # Create screenshot preview from the first screenshot if available
        first_screenshot_preview = None
        if screenshot_count > 0 and extract_screenshots and screenshot_paths:
            try:
                screenshot_file_path = screenshot_paths[0]  # Use the first screenshot we saved
                if os.path.exists(screenshot_file_path):
                    with open(screenshot_file_path, 'rb') as f:
                        screenshot_bytes = f.read()[:50]  # Just read first 50 bytes
                        first_screenshot_preview = f"data:image/jpeg;base64,{base64.b64encode(screenshot_bytes).decode()}"
            except Exception as e:
                log(f"Error creating screenshot preview: {str(e)}")
        
        # Return compression statistics
        result = {
            "success": True,
            "original_path": log_path,
            "original_size": original_size,
            "compressed_path": gzip_path,
            "compressed_size": compressed_size,
            "no_screenshots_path": compressed_json_path,
            "no_screenshots_size": no_screenshots_size,
            "screenshot_count": screenshot_count,
            "screenshot_size_total": screenshot_size_total,
            "screenshot_directory": screenshot_dir if extract_screenshots else None,
            "size_reduction_no_screenshots": f"{size_reduction_no_screenshots}%",
            "size_reduction_compressed": f"{size_reduction_compressed}%",
            # Add preview data
            "preview": {
                "first_50_bytes": compressed_data[:50].hex(),  # quick check it's valid gzip
                "first_50_b64_of_screenshot": first_screenshot_preview
            },
            "inline_screenshots": inline_screenshots  # NEW: embeddable screenshots
        }
        
        log(f"Log compression complete: {result['size_reduction_compressed']}% reduction")
        return result
    
    except Exception as e:
        log(f"Error compressing log file: {str(e)}")
        return {"success": False, "error": str(e), "compressed_path": None}


@mcp.tool(
    name="compress_logs",
    description=(
        "Compress a Nova-Act HAR/JSON log file. "
        "Provide either 'log_path' or a 'session_id' whose last action "
        "produced a HAR. Returns compression stats and a screenshot preview. "
        "If log_path is omitted but session_id is supplied, the tool automatically locates the newest *_calls.json for that session. "
        "⚠ compressed_path is local to the MCP server. Agents should not attempt to open it. To display the log use view_html_log."
    ),
)
async def compress_logs_tool(
    log_path: Optional[str] = None,
    session_id: Optional[str] = None,
    extract_screenshots: bool = True,
    compression_level: int = 9,
) -> Dict[str, Any]:
    """
    Compress Nova Act logs by removing screenshots and applying gzip compression.
    
    Args:
        log_path: Path to the log file to compress, optional if session_id is provided
        session_id: Session ID to find the most recent HAR log, optional if log_path is provided
        extract_screenshots: Whether to extract screenshots to separate files
        compression_level: Compression level for gzip (1-9)
        
    Returns:
        dict: Information about the compression including paths and size reduction
    """
    initialize_environment()
    
    # If the log has already been compressed in this session, use it
    if not log_path and session_id:
        with session_lock:
            sess = active_sessions.get(session_id, {})
            log_path = sess.get("last_har_path")
            
            # Get the Nova Act session ID if available, may be different from MCP session ID
            nova_session_id = sess.get("nova_session_id")
            
            # Fall‑back: scan the session's logs_dir for the newest *_calls.json
            if not log_path:
                logs_dir = sess.get("logs_dir")
                if logs_dir and os.path.isdir(logs_dir):
                    try:
                        # First, try the Nova Act session ID directory if available
                        if nova_session_id and os.path.isdir(os.path.join(logs_dir, nova_session_id)):
                            nova_dir = os.path.join(logs_dir, nova_session_id)
                            log(f"[{session_id}] Checking Nova session directory: {nova_dir}")
                            # Find all *_calls.json files in that directory
                            calls_files = list(Path(nova_dir).glob("*_calls.json"))
                            if calls_files:
                                # Get the newest one
                                newest_file = max(calls_files, key=lambda p: p.stat().st_mtime)
                                log_path = str(newest_file.resolve())
                                log(f"[{session_id}] Found newest calls.json in Nova session dir: {log_path}")
                            
                        # If still not found, search recursively
                        if not log_path:
                            log(f"[{session_id}] Scanning logs_dir recursively for *_calls.json: {logs_dir}")
                            all_json_files = list(Path(logs_dir).rglob("*_calls.json"))
                            if all_json_files:
                                # Get the newest one
                                newest_file = max(all_json_files, key=lambda p: p.stat().st_mtime)
                                log_path = str(newest_file.resolve())
                                log(f"[{session_id}] Found newest calls.json by recursive scan: {log_path}")
                    except Exception as e:
                        log(f"[{session_id}] Error scanning for calls.json: {e}")
                        
                # If still not found, try scanning the temp directory for nova_act_logs
                if not log_path:
                    try:
                        log(f"[{session_id}] No HAR found in logs_dir, scanning temp directory")
                        temp_dir = tempfile.gettempdir()
                        # Get all *_nova_act_logs directories
                        nova_dirs = [
                            d for d in Path(temp_dir).glob("*nova_act_logs*") 
                            if d.is_dir()
                        ]
                        log(f"[{session_id}] Found {len(nova_dirs)} nova_act_logs directories")
                        
                        # Find all *_calls.json files in these directories (non-recursively for speed)
                        all_json_files = []
                        for nova_dir in nova_dirs:
                            all_json_files.extend(list(nova_dir.rglob("*_calls.json")))
                            
                        log(f"[{session_id}] Found {len(all_json_files)} calls.json files")
                        
                        if all_json_files:
                            # Sort by modification time (newest first)
                            sorted_files = sorted(
                                all_json_files, 
                                key=lambda p: p.stat().st_mtime, 
                                reverse=True
                            )
                            # Use the newest one
                            log_path = str(sorted_files[0].resolve())
                            log(f"[{session_id}] Using most recently modified calls.json: {log_path}")
                    except Exception as e:
                        log(f"[{session_id}] Error scanning temp directory: {e}")
            
            # Maybe we already compressed it once
            if not log_path:
                compressed_path = sess.get("last_compressed_log_path")
                if compressed_path and os.path.exists(compressed_path):
                    log(f"[{session_id}] Found already compressed log: {compressed_path}")
                    result = {
                        "success": True,
                        "compressed_path": compressed_path,
                        "reused_existing": True,
                        "preview": {
                            "first_50_bytes": "reused_existing",
                            "first_50_b64_of_screenshot": "reused_existing"
                        }
                    }
                    return {
                        "content": [{"type": "text", "text": f"Using previously compressed log: {compressed_path}"}],
                        "compression_stats": result, # Return nested properly
                        "success": True
                    }
    
    # Ensure the log path exists
    if not log_path or not os.path.exists(log_path):
        return {
            "error": {
                "code": -32602,
                "message": f"Log file not found: {log_path}",
                "data": {"log_path": log_path, "session_id": session_id},
            }
        }
    
    try:
        # Use the compression function
        compression_result = compress_log_file(
            log_path, 
            extract_screenshots=extract_screenshots, 
            compression_level=compression_level
        )
        
        if not compression_result.get("success", False):
            return {
                "error": {
                    "code": -32603,
                    "message": compression_result.get("error", "Unknown compression error"),
                    "data": None,
                }
            }
        
        # Store the compressed path in the session data if session_id is provided
        if session_id:
            with session_lock:
                if session_id in active_sessions:
                    active_sessions[session_id]["last_compressed_log_path"] = compression_result.get("compressed_path")
        
        # Format the compression stats for reporting
        result_text = (
            f"Log compression complete for: {log_path}\n\n"
            f"Original size: {compression_result['original_size']} bytes\n"
            f"Size without screenshots: {compression_result['no_screenshots_size']} bytes "
            f"({compression_result['size_reduction_no_screenshots']} reduction)\n"
            f"Compressed size: {compression_result['compressed_size']} bytes "
            f"({compression_result['size_reduction_compressed']} reduction)\n\n"
            f"Screenshots extracted: {compression_result['screenshot_count']}\n"
            f"Screenshot directory: {compression_result['screenshot_directory'] or 'None'}\n\n"
            f"Compressed file: {compression_result['compressed_path']}"
        )
        
        # Preview data should already be in compression_result from compress_log_file
        
        # Return the compression result directly in the compression_stats key
        return {
            "content": [{"type": "text", "text": result_text}],
            "compression_stats": compression_result, # This is what the test expects
            "success": True
        }
    
    except Exception as e:
        error_message = str(e)
        error_tb = traceback.format_exc()
        log(f"Error compressing logs: {error_message}")
        log(f"Traceback: {error_tb}")
        
        return {
            "error": {
                "code": -32603,
                "message": f"Error compressing logs: {error_message}",
                "data": {"traceback": error_tb},
            }
        }


@mcp.tool(
    name="view_compressed_log",
    description=(
        "Render a compressed Nova-Act log file as inline HTML or text. "
        "Provide either 'compressed_path' (absolute) or a 'session_id' "
        "whose logs were compressed. Large files are truncated for safety."
    ),
)
async def view_compressed_log(
    compressed_path: Optional[str] = None,
    session_id: Optional[str] = None,
    truncate_to_kb: int = 512,
) -> Dict[str, Any]:
    """
    Stream a compressed log file (gzip) back to the caller so Claude (or other MCP UIs)
    can embed it directly. If both args are given, compressed_path wins.
    Large files are truncated to keep JSON-RPC payloads reasonable.
    
    Args:
        compressed_path: Absolute path to the compressed log file (.gz)
        session_id: Session ID to find the most recent compressed log
        truncate_to_kb: Size limit in KB before truncation is applied
        
    Returns:
        Dictionary containing the uncompressed content suitable for embedding in UI
    """
    initialize_environment()
    
    # Resolve path from session registry if only session_id given
    found_path = None
    if not compressed_path and session_id:
        with session_lock:
            sess = active_sessions.get(session_id, {})
            # Try to get the last compressed log path
            found_path = sess.get("last_compressed_log_path")
            if found_path:
                log(f"[{session_id}] Found compressed log path in session: {found_path}")
            else:
                # If not found, see if we can compress one now
                har_path = sess.get("last_har_path")
                if har_path and os.path.exists(har_path):
                    try:
                        log(f"[{session_id}] Compressing HAR on-demand: {har_path}")
                        comp_result = compress_log_file(har_path, extract_screenshots=True)
                        if comp_result.get("success") and comp_result.get("compressed_path"):
                            found_path = comp_result["compressed_path"]
                            # Store for future reference
                            active_sessions[session_id]["last_compressed_log_path"] = found_path
                            log(f"[{session_id}] Created and stored compressed path: {found_path}")
                    except Exception as e:
                        log(f"[{session_id}] Error compressing on-demand: {e}")
                        
        compressed_path = found_path
    
    # Check if the path exists and has the expected extension
    if not compressed_path or not os.path.exists(compressed_path):
        error_detail = f"session_id: {session_id}" if session_id else "no identifier provided"
        log(f"Could not find a compressed log for {error_detail}")
        return {
            "error": {
                "code": -32602,
                "message": f"Compressed log file not found for {error_detail}",
                "data": {"compressed_path": compressed_path, "session_id": session_id},
            }
        }
    
    # Ensure it's a gzip file
    is_gzip = compressed_path.endswith('.gz')
    
    try:
        # Open and read the compressed file
        if (is_gzip):
            with gzip.open(compressed_path, 'rb') as f:
                decompressed_data = f.read()
        else:
            with open(compressed_path, 'rb') as f:
                decompressed_data = f.read()
        
        # Check if it's JSON and handle accordingly
        try:
            # Try to parse as JSON
            if isinstance(decompressed_data, bytes):
                json_data = json.loads(decompressed_data.decode('utf-8', 'ignore'))
            else:
                json_data = json.loads(decompressed_data)
                
            # Format JSON nicely
            formatted_json = json.dumps(json_data, indent=2)
            
            # Truncate if needed
            truncated = False
            if len(formatted_json) > truncate_to_kb * 1024:
                formatted_json = formatted_json[:truncate_to_kb * 1024] + "\n... (truncated)"
                truncated = True
                
            # Return as formatted code
            return {
                "content": [{"type": "code", "language": "json", "code": formatted_json}],
                "source_path": compressed_path,
                "truncated": truncated,
                "format": "json"
            }
            
        except json.JSONDecodeError:
            # Not JSON, handle as HTML or text
            if isinstance(decompressed_data, bytes):
                content = decompressed_data.decode('utf-8', 'ignore')
            else:
                content = decompressed_data
                
            # Check if it looks like HTML
            is_html = content.strip().startswith('<!DOCTYPE html>') or content.strip().startswith('<html')
            
            # Truncate if needed
            truncated = False
            if len(content) > truncate_to_kb * 1024:
                if is_html:
                    content = content[:truncate_to_kb * 1024] + "\n<!-- ...truncated... -->"
                else:
                    content = content[:truncate_to_kb * 1024] + "\n... (truncated)"
                truncated = True
            
            # Return as appropriate content type
            if is_html:
                return {
                    "content": [{"type": "html", "html": content}],
                    "source_path": compressed_path,
                    "truncated": truncated,
                    "format": "html"
                }
            else:
                return {
                    "content": [{"type": "text", "text": content}],
                    "source_path": compressed_path,
                    "truncated": truncated,
                    "format": "text"
                }
    
    except Exception as e:
        error_message = str(e)
        error_tb = traceback.format_exc()
        log(f"Error processing compressed log file {compressed_path}: {error_message}")
        log(f"Traceback: {error_tb}")
        
        return {
            "error": {
                "code": -32603,
                "message": f"Error processing compressed log: {error_message}",
                "data": {"path": compressed_path, "error": error_message},
            }
        }


@mcp.tool(
    name="fetch_file",
    description="Return a local file (≤2 MB) as base64 so the caller can download it."
)
async def fetch_file(path: str) -> Dict[str, Any]:
    """
    Return a small binary file (≤2 MB) as base64 so the caller can download it.
    This is useful for downloading compressed logs or screenshots for offline analysis.
    
    Args:
        path: Absolute path to the file to fetch
        
    Returns:
        Dictionary containing the file as base64, along with filename and MIME type
    """
    from pathlib import Path, PurePosixPath
    
    initialize_environment()
    
    try:
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            return {
                "error": {
                    "code": -32602,
                    "message": f"File not found: {path}",
                    "data": {"path": path}
                }
            }
            
        file_size = p.stat().st_size
        if file_size > 2 * 1024 * 1024:  # 2 MB limit
            return {
                "error": {
                    "code": -32602,
                    "message": f"File too large: {file_size} bytes (limit is 2 MB)",
                    "data": {"path": path, "size": file_size}
                }
            }
            
        import base64, mimetypes
        
        # Read the file as binary data
        b64 = base64.b64encode(p.read_bytes()).decode()
        
        # Guess MIME type from file extension
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        
        # Return file info and base64-encoded content
        return {
            "filename": p.name,
            "mime": mime,
            "size": file_size,
            "base64": b64
        }
        
    except Exception as e:
        error_message = str(e)
        error_tb = traceback.format_exc()
        log(f"Error fetching file {path}: {error_message}")
        log(f"Traceback: {error_tb}")
        
        return {
            "error": {
                "code": -32603,
                "message": f"Error fetching file: {error_message}",
                "data": {"path": path, "error": error_message}
            }
        }


# Helper function to normalize logs directory across NovaAct versions
def _normalize_logs_dir(nova_instance):
    """
    Normalize the logs directory attribute across different versions of NovaAct.
    NovaAct <=0.8 used .logs_directory and .logs_dir
    NovaAct 0.9+ switched to .log_directory
    This function ensures all versions are supported.
    
    Args:
        nova_instance: NovaAct instance to check for logs directory
        
    Returns:
        str: The normalized logs directory path or None if not found
    """
    if not nova_instance:
        return None
        
    # Try all known attribute names for log directory
    logs_dir = None
    
    # Try each attribute name in order of preference
    for attr_name in ["logs_directory", "logs_dir", "log_directory", "log_dir"]:
        if hasattr(nova_instance, attr_name):
            logs_dir = getattr(nova_instance, attr_name)
            if logs_dir:  # If attribute exists and has a value
                break
                
    return logs_dir


@mcp.tool(
    name="inspect_browser",
    description=(
        "Inspect the current state of an active browser session without performing any action. "
        "Returns the current URL, page title, and captures a screenshot of the viewport. "
        "Use this tool to get visual feedback without performing any browser actions."
    )
)
async def inspect_browser(session_id: str) -> Dict[str, Any]:
    """
    Retrieves the current URL, title, and a screenshot of the specified browser session.
    
    Args:
        session_id: The ID of the active browser session to inspect
        
    Returns:
        A dictionary containing the current state of the browser, including URL,
        page title, and (if possible) an inline screenshot
    """
    initialize_environment()
    log(f"[{session_id}] Received inspect_browser request.")

    with session_lock:
        session_data = active_sessions.get(session_id)

    if not session_data or session_data.get("status") == "ended":
        log(f"[{session_id}] Inspect failed: Session not active.")
        return {"error": {"code": -32602, "message": f"No active session found: {session_id}", "data": None}}

    nova_instance = session_data.get("nova_instance")
    executor = session_data.get("executor")

    if not nova_instance or not executor:
        log(f"[{session_id}] Inspect failed: Missing Nova instance or executor.")
        return {"error": {"code": -32603, "message": f"Internal error for session: {session_id}", "data": None}}

    # Define synchronous inspection logic
    def _sync_inspect():
        log(f"[{session_id}] Getting current page state...")
        current_url = "Error: Could not get URL"
        page_title = "Error: Could not get title"
        inline_b64 = None
        screenshot_status_message = None

        try:
            current_url = nova_instance.page.url
            page_title = nova_instance.page.title()
            log(f"[{session_id}] Current state: URL={current_url}, Title={page_title}")
        except Exception as state_e:
            log(f"[{session_id}] Error getting URL/Title: {state_e}")

        # Capture screenshot
        try:
            log(f"[{session_id}] Attempting screenshot capture for inspect.")
            raw_screenshot_bytes = nova_instance.page.screenshot(type="jpeg", quality=INLINE_IMAGE_QUALITY)
            if len(raw_screenshot_bytes) <= MAX_INLINE_IMAGE_BYTES:
                inline_b64 = "data:image/jpeg;base64," + base64.b64encode(raw_screenshot_bytes).decode()
                log(f"[{session_id}] Screenshot captured ({len(raw_screenshot_bytes)} bytes).")
            else:
                screenshot_status_message = f"Screenshot captured but too large for inline response ({len(raw_screenshot_bytes)}B > {MAX_INLINE_IMAGE_BYTES}B limit). Use 'compress_logs_tool' then 'fetch_file'."
                log(f"[{session_id}] {screenshot_status_message}")
        except Exception as e:
            screenshot_status_message = f"Error capturing screenshot: {str(e)}"
            log(f"[{session_id}] Screenshot capture failed: {screenshot_status_message}")

        # Prepare result content
        content_list = [{"type": "text", "text": f"Current URL: {current_url}\nPage Title: {page_title}"}]
        if inline_b64:
            content_list.insert(0, {
                "type": "image_base64",
                "data": inline_b64,
                "caption": "Current viewport"
            })

        agent_thinking = []
        if screenshot_status_message:
            agent_thinking.append({
                "type": "system_warning", 
                "content": screenshot_status_message,
                "source": "nova_mcp"
            })

        # Return result structure for FastMCP
        return {
            "session_id": session_id,
            "current_url": current_url,
            "page_title": page_title,
            "content": content_list,
            "agent_thinking": agent_thinking,
            "success": True # Inspection itself succeeded
        }

    # Run inspection in the session's thread
    try:
        result_value = await asyncio.get_event_loop().run_in_executor(executor, _sync_inspect)
        return result_value # Return the dictionary for the 'result' field
    except Exception as e:
        error_message = str(e)
        log(f"[{session_id}] Error during inspect_browser execution: {error_message}")
        return {"error": {"code": -32603, "message": f"Error inspecting browser: {error_message}", "data": {"session_id": session_id}}}


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
