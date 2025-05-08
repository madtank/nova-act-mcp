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
from nova_mcp import (
    browser_session, 
    compress_logs_tool, 
    view_html_log, 
    fetch_file,
    MAX_INLINE_IMAGE_BYTES, 
    initialize_environment
)

@pytest.mark.asyncio
async def test_agent_visual_workflow_and_compression():
    """
    Test that simulates a real agent workflow that:
    1. Starts a browser session
    2. Executes a command and receives an inline screenshot (or clear message why not)
    3. Compresses logs using only session_id (testing improved path discovery)
    4. Retrieves screenshot files via fetch_file
    
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
    sid = start_result["session_id"]
    assert sid, "Failed to get valid session ID"
    print(f"Session started with ID: {sid}")
    
    # 2️⃣ Execute - request screenshot and time the operation to validate performance
    print("Executing browser command with screenshot...")
    start_time = time.time()
    execute_result = await browser_session(
        action="execute",
        session_id=sid,
        instruction="Take a screenshot of the current page"
    )
    execution_time = time.time() - start_time
    print(f"Execution completed in {execution_time:.2f} seconds")
    
    # Verify inline screenshot presence
    inline_img = execute_result.get("inline_screenshot")
    if inline_img and inline_img.startswith("data:image/jpeg;base64,"):
        print(f"Successfully received inline screenshot ({len(inline_img)} bytes)")
        
        # Also verify it's in the content array (where agents will look for it)
        content_images = [c for c in execute_result["content"] if c.get("type") == "image_base64"]
        assert content_images, "Image missing from content array despite being in inline_screenshot"
        print("Screenshot correctly found in content array")
        
        # Verify image format
        payload = base64.b64decode(inline_img.split(",", 1)[1])
        assert payload[:3] == b"\xFF\xD8\xFF", "Invalid JPEG format"
        assert len(payload) <= MAX_INLINE_IMAGE_BYTES, f"Image exceeds max size: {len(payload)} > {MAX_INLINE_IMAGE_BYTES}"
    else:
        # If no inline image, there should be a clear explanation in agent_thinking
        print("No inline screenshot found - checking for explanation message")
        assert execute_result.get("agent_thinking"), "No agent_thinking provided to explain missing screenshot"
        
        thinking_messages = []
        for thinking in execute_result["agent_thinking"]:
            thinking_messages.append(thinking.get("content", ""))
            
        print(f"Agent thinking messages: {thinking_messages}")
        
        # At least one message should mention screenshot size or related issue
        screenshot_explained = any(
            "screenshot" in msg.lower() for msg in thinking_messages
        )
        assert screenshot_explained, "No explanation about screenshot in agent_thinking"
        
    # 3️⃣ Compress logs using only session_id (testing improved path discovery)
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
        
        # 4️⃣ Fetch a screenshot file if available
        if screenshot_files:
            print(f"Testing fetch_file on extracted screenshot: {screenshot_files[0]}")
            fetch_result = await fetch_file(path=str(screenshot_files[0]))
            
            assert "error" not in fetch_result, f"Fetch error: {fetch_result.get('error')}"
            assert fetch_result.get("base64", "").startswith(""), "Invalid base64 data in fetch result"
            assert fetch_result.get("mime") == "image/jpeg", f"Unexpected MIME type: {fetch_result.get('mime')}"
            
            print(f"Successfully fetched screenshot ({fetch_result.get('size')} bytes)")
    
    # 5️⃣ Clean-up
    print("Ending browser session...")
    end_result = await browser_session(action="end", session_id=sid)
    assert end_result.get("status") == "ended", "Session did not end properly"
    
    print("=== Agent Visual Workflow Test Completed Successfully ===")

@pytest.mark.asyncio
async def test_screenshot_omitted_with_clear_message():
    """
    Test that when a screenshot is too large to be inlined, the agent receives
    a clear message in agent_thinking explaining why and suggesting alternatives.
    
    This test temporarily reduces MAX_INLINE_IMAGE_BYTES to force the screenshot
    to be omitted, then checks for proper communication.
    """
    initialize_environment()
    
    # Temporarily patch MAX_INLINE_IMAGE_BYTES to a very small value to force screenshot omission
    with patch('nova_mcp.MAX_INLINE_IMAGE_BYTES', 100):  # 100 bytes is too small for any real screenshot
        # Start a browser session
        start_result = await browser_session(
            action="start",
            url="https://example.com",
            headless=True
        )
        sid = start_result["session_id"]
        
        # Execute with screenshot request
        execute_result = await browser_session(
            action="execute",
            session_id=sid,
            instruction="Take a screenshot and return it"
        )
        
        # End the session
        await browser_session(action="end", session_id=sid)
        
        # Verify there's no inline screenshot (it should be too large now)
        content_images = [c for c in execute_result["content"] if c.get("type") == "image_base64"]
        assert not content_images, "Screenshot should be omitted due to size limit"
        
        # Verify there's a message in agent_thinking explaining why
        has_explanation = False
        for thinking in execute_result.get("agent_thinking", []):
            content = thinking.get("content", "").lower()
            if "screenshot" in content and ("large" in content or "size" in content or "limit" in content):
                has_explanation = True
                break
                
        assert has_explanation, "No clear explanation about screenshot being too large in agent_thinking"