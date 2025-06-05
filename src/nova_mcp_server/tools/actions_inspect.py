"""
Browser inspection for the Nova Act MCP Server.

This module provides functionality for inspecting the state of browser sessions.
"""

import asyncio
import base64
import time
import traceback
import glob
import os
from typing import Dict, Any, List, Optional

from ..config import (
    log,
    log_info,
    log_debug,
    log_error,
    log_warning,  # Added log_warning import
    initialize_environment,
    NOVA_ACT_AVAILABLE,
    SCREENSHOT_QUALITY,
    MAX_INLINE_IMAGE_BYTES,
    INLINE_IMAGE_QUALITY,
)
from ..session_manager import (
    active_sessions,
    session_lock,
)
from ..utils import _normalize_logs_dir


def inspect_browser_action(session_id: str, include_screenshot: bool = False) -> Dict[str, Any]:
    """
    Get screenshots and current state of browser sessions.

    Args:
        session_id: The session ID to inspect
        include_screenshot: If True, attempts to capture and include a base64 JPEG screenshot.
                           Defaults to False to save LLM context space.

    Returns:
        dict: A dictionary containing browser state information
    """
    initialize_environment()

    if not session_id:
        return {
            "error": "Missing required parameter: session_id",
            "error_code": "MISSING_PARAMETER",
        }

    if not NOVA_ACT_AVAILABLE:
        return {
            "error": "Nova Act SDK is not installed. Please install it with: pip install nova-act",
            "error_code": "NOVA_ACT_NOT_AVAILABLE",
        }

    return _inspect_browser(session_id=session_id, include_screenshot_flag=include_screenshot, inline_image_quality=INLINE_IMAGE_QUALITY)

async def _inspect_browser_async(session_id: str, include_screenshot_flag: bool = False, inline_image_quality: int = 60) -> dict:
    """
    Async wrapper for browser inspection that handles thread-safe Nova Act calls.

    Args:
        session_id: ID of the browser session to inspect
        include_screenshot_flag: Whether to include a screenshot in the response
        inline_image_quality: JPEG quality (1-100) for screenshot if included
    """
    import anyio
    from .actions_start import active_sessions

    nova = None
    browser_state = {}
    agent_thinking_messages = []
    current_url = "Unknown URL"
    page_title = "Unknown Title"
    screenshot_status_message = None
    inline_screenshot = None

    try:
        session_data = active_sessions[session_id]
        nova = session_data.get("nova_instance")
        if not nova:
            return {
                "error": f"Nova instance not found for session: {session_id}",
                "error_code": "NOVA_INSTANCE_NOT_FOUND",
                "session_id": session_id,
                "success": False,
            }
    except Exception as e:
        return {
            "error": f"Session not found: {session_id}",
            "error_code": "SESSION_NOT_FOUND",
            "session_id": session_id,
            "success": False,
        }

    # Helper function to get URL safely
    def _get_url():
        return nova.page.url

    # Helper function to get title safely
    def _get_title():
        return nova.page.title()

    # Helper function to get screenshot safely
    def _get_screenshot():
        return nova.page.screenshot(type="jpeg", quality=inline_image_quality)

    # Get current URL via thread-safe call
    try:
        current_url = await anyio.to_thread.run_sync(_get_url, cancellable=True)
        log_debug(f"[{session_id}] Retrieved current URL via nova.page.url: {current_url}")
        browser_state["current_url"] = current_url
        browser_state["urls"] = [current_url]
    except Exception as e_url_direct:
        error_msg = f"Exception getting browser URL via nova.page.url: {str(e_url_direct)}"
        log_error(f"[{session_id}] {error_msg} \n{traceback.format_exc()}")
        browser_state["urls_error"] = str(e_url_direct)
        agent_thinking_messages.append({"type": "system_error", "content": error_msg, "source": "inspect_browser"})

    # Get page title via thread-safe call
    try:
        page_title_val = await anyio.to_thread.run_sync(_get_title, cancellable=True)
        if not isinstance(page_title_val, str):
            log_warning(f"[{session_id}] Page title from nova.page.title() is not a string ({type(page_title_val)}), converting.")
            page_title = str(page_title_val) if page_title_val is not None else "Unknown Title"
        else:
            page_title = page_title_val
        log_debug(f"[{session_id}] Retrieved page title via nova.page.title(): {page_title}")
        browser_state["page_title"] = page_title
    except Exception as e_title_direct:
        error_msg = f"Exception getting page title via nova.page.title(): {str(e_title_direct)}"
        log_error(f"[{session_id}] {error_msg} \n{traceback.format_exc()}")
        browser_state["title_error"] = str(e_title_direct)
        agent_thinking_messages.append({"type": "system_error", "content": error_msg, "source": "inspect_browser"})

    # Screenshot logic: only try if include_screenshot_flag is True
    if include_screenshot_flag:
        try:
            screenshot_data_bytes = await anyio.to_thread.run_sync(_get_screenshot, cancellable=True)
            log_debug(f"[{session_id}] Screenshot captured via nova.page, size: {len(screenshot_data_bytes) if screenshot_data_bytes else 0} bytes")
            if screenshot_data_bytes:
                if len(screenshot_data_bytes) <= MAX_INLINE_IMAGE_BYTES:
                    inline_screenshot = "data:image/jpeg;base64," + base64.b64encode(screenshot_data_bytes).decode()
                    log_debug(f"[{session_id}] Screenshot prepared for inline ({len(screenshot_data_bytes)} bytes).")
                else:
                    screenshot_status_message = f"Screenshot captured but too large for inline response ({len(screenshot_data_bytes)}B > {MAX_INLINE_IMAGE_BYTES}B limit)."
                    log_debug(f"[{session_id}] {screenshot_status_message}")
                    agent_thinking_messages.append({"type": "system_warning", "content": screenshot_status_message, "source": "inspect_browser"})
        except Exception as e_screenshot:
            screenshot_status_message = f"Error capturing screenshot via nova.page.screenshot(): {str(e_screenshot)}"
            log_error(f"[{session_id}] Screenshot capture failed: {screenshot_status_message} \n{traceback.format_exc()}")
            agent_thinking_messages.append({"type": "system_error", "content": screenshot_status_message, "source": "inspect_browser"})
    else:
        log_debug(f"[{session_id}] Skipping screenshot capture as include_screenshot_flag is False")
        # Don't set screenshot_status_message for the default case (no screenshot)
        # Don't add a system_info message to agent_thinking for the default case

    # Prepare content response
    content_for_response = [{"type": "text", "text": f"Current URL: {current_url}\nPage Title: {page_title}"}]
    
    # Only add screenshot to content if include_screenshot_flag is True AND we have a valid screenshot
    if include_screenshot_flag and inline_screenshot is not None:
        content_for_response.insert(0, {
            "type": "image_base64",
            "data": inline_screenshot,
            "caption": "Current viewport"
        })
    
    # Add screenshot status message to agent_thinking if it exists (only happens when include_screenshot_flag is True)
    if screenshot_status_message and not any(msg.get('content') == screenshot_status_message for msg in agent_thinking_messages):
        agent_thinking_messages.append({
            "type": "system_info",
            "content": screenshot_status_message,
            "source": "inspect_browser"
        })

    return {
        "session_id": session_id,
        "current_url": current_url,
        "page_title": page_title,
        "content": content_for_response,
        "agent_thinking": agent_thinking_messages,
        "browser_state": browser_state,
        "timestamp": time.time(),
        "success": True
    }

def _inspect_browser(session_id: str, include_screenshot_flag: bool = False, inline_image_quality: int = 60) -> dict:
    """
    Synchronous wrapper that runs the async inspection function.
    This is called by anyio.to_thread.run_sync() from browser_control.py.

    Args:
        session_id: ID of the browser session to inspect
        include_screenshot_flag: Whether to include a screenshot in the response
        inline_image_quality: JPEG quality (1-100) for screenshot if included
    """
    import anyio
    
    async def _run_async():
        return await _inspect_browser_async(session_id, include_screenshot_flag, inline_image_quality)
    
    # Run the async function and get the result
    result = anyio.run(_run_async)
    
    # Extract values from the async result for logs processing
    from .actions_start import active_sessions
    
    # Get the nova instance and other data for logs processing
    try:
        session_data = active_sessions[session_id]
        nova = session_data.get("nova_instance")
    except:
        # If we can't get session data, return the async result as-is
        return result
    
    # Extract values from async result
    current_url = result.get("current_url", "Unknown URL")
    page_title = result.get("page_title", "Unknown Title")
    browser_state = result.get("browser_state", {})
    agent_thinking_messages = result.get("agent_thinking", [])
    content_for_response = result.get("content", [])
    
    # Handle screenshot data if present
    inline_screenshot = None
    screenshot_status_message = None
    for content_item in content_for_response:
        if content_item.get("type") == "image_base64":
            inline_screenshot = content_item.get("data")
            break
    
    # Check for screenshot status in agent thinking
    for msg in agent_thinking_messages:
        if msg.get("source") == "inspect_browser" and "screenshot" in msg.get("content", "").lower():
            screenshot_status_message = msg.get("content")
            break

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

    # Return the updated result with logs information
    return {
        "session_id": session_id,
        "current_url": current_url,
        "page_title": page_title,
        "content": content_for_response,
        "agent_thinking": agent_thinking_messages,
        "browser_state": browser_state,
        "timestamp": time.time(),
        "success": True
    }