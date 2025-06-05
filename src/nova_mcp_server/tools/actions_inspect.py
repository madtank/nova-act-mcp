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
        include_screenshot: If True, captures a screenshot and saves it to the logs directory.
                           The screenshot path is returned in the response for retrieval via fetch_file.
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

def _inspect_browser(session_id: str, include_screenshot_flag: bool = False, inline_image_quality: int = 60) -> dict:
    """
    Inspect the current browser session and return page info and screenshot.
    This is run in a worker thread to avoid blocking the main event loop.

    Args:
        session_id: ID of the browser session to inspect
        include_screenshot_flag: Whether to include a screenshot in the response
        inline_image_quality: JPEG quality (1-100) for screenshot if included
    """
    from .actions_start import active_sessions

    nova = None
    browser_state = {}
    agent_thinking_messages = []
    current_url = "Unknown URL"
    page_title = "Unknown Title"
    screenshot_status_message = None

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

    # Get current URL via direct Playwright property
    try:
        current_url = nova.page.url
        log_debug(f"[{session_id}] Retrieved current URL via nova.page.url: {current_url}")
        browser_state["current_url"] = current_url
        browser_state["urls"] = [current_url]
    except Exception as e_url_direct:
        error_msg = f"Exception getting browser URL via nova.page.url: {str(e_url_direct)}"
        log_error(f"[{session_id}] {error_msg} \n{traceback.format_exc()}")
        browser_state["urls_error"] = str(e_url_direct)
        agent_thinking_messages.append({"type": "system_error", "content": error_msg, "source": "inspect_browser"})

    # Get page title via direct Playwright method
    try:
        page_title_val = nova.page.title()
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
    screenshot_path = None
    if include_screenshot_flag:
        try:
            screenshot_data_bytes = nova.page.screenshot(type="jpeg", quality=inline_image_quality)
            log_debug(f"[{session_id}] Screenshot captured via nova.page, size: {len(screenshot_data_bytes) if screenshot_data_bytes else 0} bytes")
            if screenshot_data_bytes:
                # Save screenshot to file in logs directory
                logs_dir_from_session = active_sessions.get(session_id, {}).get("logs_dir")
                if logs_dir_from_session:
                    logs_dir = logs_dir_from_session
                else:
                    sdk_session_id_for_logs = active_sessions.get(session_id, {}).get("nova_session_id")
                    logs_dir = _normalize_logs_dir(nova, sdk_session_id_override=sdk_session_id_for_logs)
                
                if logs_dir:
                    # Create screenshot filename with timestamp
                    timestamp = int(time.time() * 1000)
                    screenshot_filename = f"screenshot_{session_id}_{timestamp}.jpg"
                    screenshot_path = os.path.join(logs_dir, screenshot_filename)
                    
                    # Write screenshot to file
                    with open(screenshot_path, 'wb') as f:
                        f.write(screenshot_data_bytes)
                    
                    screenshot_status_message = f"Screenshot saved to: {screenshot_path} ({len(screenshot_data_bytes)} bytes)"
                    log_debug(f"[{session_id}] {screenshot_status_message}")
                    browser_state["screenshot_path"] = screenshot_path
                    browser_state["screenshot_size"] = len(screenshot_data_bytes)
                else:
                    screenshot_status_message = "Could not save screenshot: logs directory not available"
                    log_warning(f"[{session_id}] {screenshot_status_message}")
                    agent_thinking_messages.append({"type": "system_warning", "content": screenshot_status_message, "source": "inspect_browser"})
        except Exception as e_screenshot:
            screenshot_status_message = f"Error capturing screenshot via nova.page.screenshot(): {str(e_screenshot)}"
            log_error(f"[{session_id}] Screenshot capture failed: {screenshot_status_message} \n{traceback.format_exc()}")
            agent_thinking_messages.append({"type": "system_error", "content": screenshot_status_message, "source": "inspect_browser"})
    else:
        log_debug(f"[{session_id}] Skipping screenshot capture as include_screenshot_flag is False")
        # Don't set screenshot_status_message for the default case (no screenshot)
        # Don't add a system_info message to agent_thinking for the default case

    # Logs directory
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

    content_for_response = [{"type": "text", "text": f"Current URL: {current_url}\nPage Title: {page_title}"}]
    
    # Add screenshot path to content if screenshot was captured
    if screenshot_path:
        content_for_response.append({
            "type": "text", 
            "text": f"\nScreenshot saved to: {screenshot_path}\nUse the fetch_file tool to retrieve the screenshot."
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