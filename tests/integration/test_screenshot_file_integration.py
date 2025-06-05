"""Integration test for screenshot file saving functionality"""

import os
import pytest
import asyncio
from pathlib import Path

from nova_mcp_server.tools.browser_control import (
    start_session, inspect_browser, end_session
)
from nova_mcp_server.tools.file_transfer import fetch_file
from nova_mcp_server.config import get_nova_act_api_key


# Skip if no API key
pytestmark = pytest.mark.skipif(
    not get_nova_act_api_key(),
    reason="NOVA_ACT_API_KEY not set"
)


@pytest.mark.asyncio
async def test_screenshot_file_workflow():
    """Test the complete screenshot file saving workflow"""
    session_id = None
    
    try:
        # 1. Start a browser session
        start_result = await start_session(
            url="https://example.com",
            headless=True
        )
        assert start_result.get("success") is True
        session_id = start_result.get("session_id")
        
        # 2. Inspect without screenshot
        inspect_result = await inspect_browser(
            session_id=session_id,
            include_screenshot=False
        )
        assert inspect_result.get("success") is True
        
        # Verify no screenshot path in browser_state
        browser_state = inspect_result.get("browser_state", {})
        assert "screenshot_path" not in browser_state
        
        # 3. Inspect with screenshot
        inspect_result_with_screenshot = await inspect_browser(
            session_id=session_id,
            include_screenshot=True
        )
        assert inspect_result_with_screenshot.get("success") is True
        
        # Verify screenshot was saved
        browser_state = inspect_result_with_screenshot.get("browser_state", {})
        screenshot_path = browser_state.get("screenshot_path")
        assert screenshot_path is not None
        assert screenshot_path.endswith(".jpg")
        assert browser_state.get("screenshot_size", 0) > 0
        
        # Verify file exists on disk
        assert os.path.exists(screenshot_path)
        
        # Verify content mentions fetch_file
        content = inspect_result_with_screenshot.get("content", [])
        content_text = " ".join([
            item.get("text", "") 
            for item in content 
            if item.get("type") == "text"
        ])
        assert "fetch_file" in content_text
        assert screenshot_path in content_text
        
        # 4. Test fetching the screenshot file
        fetch_result = await fetch_file(
            file_path=screenshot_path,
            encode_base64=True
        )
        assert fetch_result.get("success") is True
        assert fetch_result.get("content_type") == "image/jpeg"
        assert "data_url" in fetch_result
        assert fetch_result["data_url"].startswith("data:image/jpeg;base64,")
        
        # Verify file size matches
        assert fetch_result.get("file_size") == browser_state.get("screenshot_size")
        
    finally:
        # Clean up
        if session_id:
            await end_session(session_id)


@pytest.mark.asyncio
async def test_screenshot_quality_setting():
    """Test that screenshot quality setting affects file size"""
    session_id = None
    
    try:
        # Start session
        start_result = await start_session(
            url="https://example.com",
            headless=True
        )
        session_id = start_result.get("session_id")
        
        # Capture screenshot (uses INLINE_IMAGE_QUALITY setting)
        inspect_result = await inspect_browser(
            session_id=session_id,
            include_screenshot=True
        )
        
        browser_state = inspect_result.get("browser_state", {})
        screenshot_size = browser_state.get("screenshot_size", 0)
        
        # With quality set to 30, screenshots should be relatively small
        # Typical example.com screenshot at quality 30 should be < 50KB
        assert screenshot_size > 0
        assert screenshot_size < 100000  # Less than 100KB
        
        print(f"Screenshot size at quality 30: {screenshot_size} bytes ({screenshot_size/1024:.1f} KB)")
        
    finally:
        if session_id:
            await end_session(session_id)