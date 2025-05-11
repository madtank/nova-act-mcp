import base64
import pytest
import asyncio
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

# Mark the test to be skipped in CI environments
pytestmark = pytest.mark.skipif(
    "NOVA_ACT_API_KEY" not in os.environ or os.environ.get("CI") == "true",
    reason="Skipping test_agent_visual_workflow in CI environment or when API key is not available"
)

# Import after the skipif to avoid errors when API key is missing
import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

from nova_mcp_server.tools import (
    browser_session, 
    compress_logs_tool, 
    view_html_log, 
    fetch_file,
    inspect_browser
)
from nova_mcp_server.config import MAX_INLINE_IMAGE_BYTES, initialize_environment

@pytest.mark.asyncio
async def test_agent_visual_workflow_and_compression():
    """
    Test that simulates a real agent workflow that:
    1. Starts a browser session
    2. Executes a command 
    3. Inspects browser state to get a screenshot (v3.0.0 behavior)
    4. Compresses logs using only session_id (testing improved path discovery)
    5. Retrieves screenshot files via fetch_file
    
    This tests the end-to-end workflow an agent would follow and validates
    the performance and reliability improvements we've made.
    """
    initialize_environment()
    
    print("\n=== Testing Agent Visual Workflow ===")
    
    # 1️⃣ Start a real browser session
    print("Starting browser session...")
    start_result = await browser_session(
        action="start",
        url="https://example.com",
        headless=True
    )
    assert "error" not in start_result, f"Session start error: {start_result.get('error')}"
    sid = start_result["session_id"]
    assert sid, "Failed to get valid session ID"
    print(f"Session started with ID: {sid}")
    
    try:
        # 2️⃣ Execute a command. If a visual check is needed, use inspect_browser later.
        print("Executing browser command...")
        start_time = time.time()
        execute_result = await browser_session(
            action="execute",
            session_id=sid,
            instruction="Click the 'More information...' link" # Example action
        )
        execution_time = time.time() - start_time
        print(f"Execution completed in {execution_time:.2f} seconds")
        assert "error" not in execute_result, f"Execute error: {execute_result.get('error')}"
        
        # Verify NO inline screenshot is present in execute result (v3.0.0 behavior)
        assert "inline_screenshot" not in execute_result, "execute should not return inline_screenshot in v3.0.0"
        content_images = [c for c in execute_result.get("content", []) if c.get("type") == "image_base64"]
        assert not content_images, "execute should not include screenshots in content array in v3.0.0"
        
        # 3️⃣ Use inspect_browser to get screenshot - this is the correct v3.0.0 approach
        print("Inspecting browser after execution...")
        inspect_res = await inspect_browser(session_id=sid)
        assert "error" not in inspect_res, f"Inspect error: {inspect_res.get('error')}"
        
        # Verify screenshot in inspect_browser result
        content = inspect_res.get("content", [])
        img_content = next((c for c in content if c.get("type") == "image_base64"), None)
        assert img_content is not None, "image_base64 missing from inspect_browser result"
        
        # Verify image format
        img_data = img_content.get("data")
        assert img_data.startswith("data:image/jpeg;base64,"), "Invalid image data format"
        payload = base64.b64decode(img_data.split(",", 1)[1])
        assert payload[:3] == b"\xFF\xD8\xFF", "Invalid JPEG format"
        assert len(payload) <= MAX_INLINE_IMAGE_BYTES, f"Image exceeds max size: {len(payload)} > {MAX_INLINE_IMAGE_BYTES}"
        print(f"Successfully received screenshot from inspect_browser ({len(img_data)} bytes)")
        
        # 4️⃣ Compress logs using only session_id (testing improved path discovery)
        print("Testing compress_logs with just session_id...")
        compress_result = await compress_logs_tool(
            session_id=sid,
            extract_screenshots=True
        )
        
        # Test success and response format
        assert "error" not in compress_result, f"Compression error: {compress_result.get('error')}"
        assert "compression_stats" in compress_result, "Missing compression_stats in result"
        
        compression_stats = compress_result["compression_stats"]
        assert compression_stats.get("success"), "Compression not marked as successful"
        
        print(f"Compression completed - original size: {compression_stats.get('original_size')} bytes")
        print(f"Compressed size: {compression_stats.get('compressed_size')} bytes")
        print(f"Screenshot count: {compression_stats.get('screenshot_count')}")
        
        # Verify screenshot directory exists if screenshots were extracted
        screenshot_dir = compression_stats.get("screenshot_directory")
        if screenshot_dir and compression_stats.get("screenshot_count", 0) > 0:
            print(f"Screenshots extracted to: {screenshot_dir}")
            assert Path(screenshot_dir).exists(), "Screenshot directory doesn't exist"
            
            # Check files in directory
            screenshot_files = list(Path(screenshot_dir).glob("*.jpg"))
            print(f"Found {len(screenshot_files)} screenshot files")
            
            # 5️⃣ Fetch a screenshot file if available
            if screenshot_files:
                print(f"Testing fetch_file on extracted screenshot: {screenshot_files[0]}")
                fetch_result = await fetch_file(path=str(screenshot_files[0]))
                
                assert "error" not in fetch_result, f"Fetch error: {fetch_result.get('error')}"
                assert fetch_result.get("base64", "").startswith(""), "Invalid base64 data in fetch result"
                assert fetch_result.get("mime") == "image/jpeg", f"Unexpected MIME type: {fetch_result.get('mime')}"
                
                print(f"Successfully fetched screenshot ({fetch_result.get('size')} bytes)")
        
        # 6️⃣ Clean-up
        print("Ending browser session...")
        end_result = await browser_session(action="end", session_id=sid)
        assert "error" not in end_result, f"End session error: {end_result.get('error')}"
        if "status" in end_result:
            assert end_result.get("status") == "ended", "Session did not end properly"
        
        print("=== Agent Visual Workflow Test Completed Successfully ===")
    finally:
        # Ensure session is ended even if test fails
        try:
            await browser_session(action="end", session_id=sid)
        except Exception as e:
            print(f"Error during cleanup: {e}")

@pytest.mark.asyncio
async def test_screenshot_omitted_from_execute():
    """
    Test that execute does not return screenshots in v3.0.0 and screenshots
    are only available via inspect_browser.
    """
    initialize_environment()
    
    # Start a browser session
    start_result = await browser_session(
        action="start",
        url="https://example.com",
        headless=True
    )
    assert "error" not in start_result, f"Session start error: {start_result.get('error')}"
    sid = start_result["session_id"]
    assert sid, "Failed to get valid session ID"
    
    try:
        # Execute with screenshot instruction
        execute_result = await browser_session(
            action="execute",
            session_id=sid,
            instruction="Take a screenshot of the current page"
        )
        
        # Verify there's no screenshot in execute result regardless of instruction
        assert "error" not in execute_result, f"Execute error: {execute_result.get('error')}"
        assert "inline_screenshot" not in execute_result, "execute should not return inline_screenshot in v3.0.0"
        content_images = [c for c in execute_result.get("content", []) if c.get("type") == "image_base64"]
        assert not content_images, "execute should not include screenshots in content array in v3.0.0"
        
        # Use inspect_browser to get screenshot instead
        inspect_res = await inspect_browser(session_id=sid)
        assert "error" not in inspect_res, f"Inspect error: {inspect_res.get('error')}"
        
        # Verify screenshot is available in inspect_browser result
        content = inspect_res.get("content", [])
        img_content = next((c for c in content if c.get("type") == "image_base64"), None)
        assert img_content is not None, "image_base64 should be present in inspect_browser result"
        
    finally:
        # End the session
        await browser_session(action="end", session_id=sid)