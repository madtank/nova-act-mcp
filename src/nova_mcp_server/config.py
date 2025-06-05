"""
Configuration module for the Nova Act MCP Server.

This module provides configuration settings, environment variable handling,
and logging functionality for the Nova Act MCP Server.
"""

import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# Load dotenv at the very beginning
try:
    from dotenv import load_dotenv
    # Find the project root and .env file
    current_dir = Path(__file__).parent  # src/nova_mcp_server
    project_root = current_dir.parent.parent  # nova-act-mcp (project root)
    dotenv_path = project_root / ".env"
    
    # Load .env file if it exists
    if (dotenv_path.exists()):
        load_dotenv(dotenv_path=dotenv_path)
        print(f"[NOVA_LOG_DEBUG] Loaded .env file from: {dotenv_path}", file=sys.stderr)
        print(f"[NOVA_LOG_DEBUG] API Key from env after dotenv: {os.getenv('NOVA_ACT_API_KEY')}", file=sys.stderr)
    else:
        print(f"[NOVA_LOG_DEBUG] No .env file found at: {dotenv_path}", file=sys.stderr)
except ImportError:
    print("[NOVA_LOG_DEBUG] python-dotenv not installed. Skipping .env loading.", file=sys.stderr)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
    ],
)

# Get the logger
logger = logging.getLogger("nova_mcp_server")

# Set up constants for configuration
DEFAULT_TIMEOUT = 120  # seconds
PROGRESS_INTERVAL = 2  # seconds
MAX_RETRY_ATTEMPTS = 2
SCREENSHOT_QUALITY = 60  # 0-100 quality for JPEG compression (reduced for smaller files)
MAX_INLINE_IMAGE_BYTES = int(os.getenv("NOVA_MCP_MAX_INLINE_IMG", "256000"))  # ≈250 KB (no longer used for inspect_browser)
INLINE_IMAGE_QUALITY = int(os.getenv("NOVA_MCP_INLINE_IMG_QUALITY", "30"))   # JPEG quality (reduced further)
DEFAULT_PROFILE_IDENTITY = "default"
DEFAULT_VERBOSE_LOGGING = True
SESSION_CLEANUP_AGE = 3600  # 1 hour in seconds
CACHED_ENV = {}  # Cache for environment variables


# Define exception classes for error handling
class ActError(Exception):
    """Base exception for Act-related errors."""
    pass


class ActGuardrailsError(ActError):
    """Exception raised when guardrails are triggered."""
    pass


# Check if NovaAct is available
try:
    import nova_act
    NOVA_ACT_AVAILABLE = True
except ImportError:
    NOVA_ACT_AVAILABLE = False


def initialize_environment() -> None:
    """
    Initialize the environment for Nova Act MCP Server.
    Load environment variables and set up logging.
    """
    global CACHED_ENV
    
    # Check if we've already initialized
    if CACHED_ENV:
        return
    
    # Load environment variables
    env_vars = {
        "NOVA_ACT_API_KEY": os.environ.get("NOVA_ACT_API_KEY", ""),
        "NOVA_ACT_PROFILE": os.environ.get("NOVA_ACT_PROFILE", DEFAULT_PROFILE_IDENTITY),
        "NOVA_ACT_MCP_TIMEOUT": os.environ.get("NOVA_ACT_MCP_TIMEOUT", str(DEFAULT_TIMEOUT)),
        "NOVA_ACT_MCP_VERBOSE": os.environ.get("NOVA_ACT_MCP_VERBOSE", str(DEFAULT_VERBOSE_LOGGING)),
    }
    
    # Convert string values to appropriate types
    try:
        if "NOVA_ACT_MCP_TIMEOUT" in env_vars:
            env_vars["NOVA_ACT_MCP_TIMEOUT"] = int(env_vars["NOVA_ACT_MCP_TIMEOUT"])
    except ValueError:
        env_vars["NOVA_ACT_MCP_TIMEOUT"] = DEFAULT_TIMEOUT
    
    try:
        if "NOVA_ACT_MCP_VERBOSE" in env_vars:
            env_vars["NOVA_ACT_MCP_VERBOSE"] = env_vars["NOVA_ACT_MCP_VERBOSE"].lower() in ("true", "1", "yes")
    except ValueError:
        env_vars["NOVA_ACT_MCP_VERBOSE"] = DEFAULT_VERBOSE_LOGGING
    
    # Load from config file if it exists
    home_dir = os.path.expanduser("~")
    config_paths = [
        os.path.join(home_dir, ".novaact", "config.json"),
        os.path.join(home_dir, ".nova_act", "config.json"),
    ]
    
    for config_path in config_paths:
        if (os.path.exists(config_path)):
            try:
                with open(config_path, "r") as f:
                    config_data = json.load(f)
                
                # Update env_vars with values from config file
                for key, value in config_data.items():
                    if key.startswith("NOVA_ACT_"):
                        env_vars[key] = value
                
                log_debug(f"Loaded configuration from {config_path}")
                break
                
            except Exception as e:
                log_error(f"Error loading configuration from {config_path}: {str(e)}")
    
    # Store in cache
    CACHED_ENV = env_vars


def get_nova_act_api_key() -> Optional[str]:
    """
    Get the Nova Act API key from environment variables or config files.
    
    Returns:
        Optional[str]: The Nova Act API key or None if not found
    """
    # API key is already loaded into os.environ by dotenv at the top of this file,
    # or was already set in the environment.
    api_key = os.getenv("NOVA_ACT_API_KEY")
    if api_key:
        log_debug("API Key found via os.getenv('NOVA_ACT_API_KEY')")
        return api_key
    else:
        log_error("API Key NOT found via os.getenv('NOVA_ACT_API_KEY')")
        # Removed mcp.config check for simplification and to avoid import issues.
        return None


def get_config(key: str, default: Any = None) -> Any:
    """
    Get a configuration value from environment variables or config files.
    
    Args:
        key: The configuration key to retrieve
        default: The default value to return if the key is not found
        
    Returns:
        Any: The configuration value or default if not found
    """
    initialize_environment()
    return CACHED_ENV.get(key, default)


def log(message: str, level: str = "INFO") -> None:
    """
    Log a message at the specified level.
    
    Args:
        message: The message to log
        level: The logging level (INFO, DEBUG, ERROR, WARNING)
    """
    # Always use stderr for all logging output
    stream = sys.stderr
    
    # Print directly to the appropriate stream
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{timestamp} [{level}] - {message}", file=stream, flush=True)
    
    # Also log to the logger
    level_upper = level.upper()
    
    if level_upper == "DEBUG":
        logger.debug(message)
    elif level_upper == "INFO":
        logger.info(message)
    elif level_upper == "WARNING":
        logger.warning(message)
    elif level_upper == "ERROR":
        logger.error(message)
    else:
        logger.info(message)


def log_info(message: str) -> None:
    """
    Log a message at INFO level.
    
    Args:
        message: The message to log
    """
    logger.info(message)


def log_debug(message: str) -> None:
    """
    Log a message at DEBUG level.
    
    Args:
        message: The message to log
    """
    logger.debug(message)


def log_error(message: str) -> None:
    """
    Log a message at ERROR level.
    
    Args:
        message: The message to log
    """
    logger.error(message)


def log_warning(message: str) -> None:
    """
    Log a message at WARNING level.
    
    Args:
        message: The message to log
    """
    logger.warning(message)