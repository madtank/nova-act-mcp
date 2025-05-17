import base64
import pytest
import asyncio
import os
from unittest.mock import patch

# Mark the test to be skipped in CI environments
pytestmark = pytest.mark.skipif(
    "NOVA_ACT_API_KEY" not in os.environ or os.environ.get("CI") == "true",
    reason="Skipping test_inspect_browser in CI environment or when API key is not available"
)

# Import after the skipif to avoid errors when API key is missing
import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

from nova_mcp_server.tools import start_session, end_session, inspect_browser
from nova_mcp_server.config import MAX_INLINE_IMAGE_BYTES
from nova_mcp_server.config import initialize_environment

@pytest.mark.xfail(reason="NovaAct/Playwright threading issues in pytest for inspect_browser direct page access", raises=AssertionError, strict=False)
@pytest.mark.asyncio
async def test_inspect_browser_returns_screenshot():
    """Test that inspect_browser returns a screenshot of the current browser state"""
    initialize_environment()

    # Start a browser session
    start_res = await start_session(
        url="https://example.com",
        headless=True
    )
    assert "error" not in start_res, f"Session start error: {start_res.get('error')}"
    sid = start_res["session_id"]
    
    try:
        # Call the inspect_browser tool
        inspect_res = await inspect_browser(session_id=sid)
        
        # Verify basic response structure
        assert "error" not in inspect_res, f"Inspect error: {inspect_res.get('error')}"
        assert inspect_res.get("success") is True, "Inspect should return success=True"
        assert inspect_res.get("current_url") == "https://example.com/", "URL should match"
        assert "Example Domain" in inspect_res.get("page_title", ""), "Title should contain 'Example Domain'"
        
        # Verify content array contains text
        content = inspect_res.get("content", [])
        assert any(c.get("type") == "text" for c in content), "Text content missing"
        
        # Check for screenshot in content array
        img_content = next((c for c in content if c.get("type") == "image_base64"), None)
        assert img_content is not None, "image_base64 missing from content array"
        
        img_data = img_content.get("data", "")
        print(f"Screenshot data (truncated): {img_data[:100]}...")  # Print first 100 chars of base64 data

        assert img_data.startswith("data:image/jpeg;base64,"), "Image data should be base64 JPEG"
        
        # Validate the image data
        payload = base64.b64decode(img_data.split(",", 1)[1])
        assert payload[:3] == b"\xFF\xD8\xFF", "Image should be valid JPEG header"
        assert len(payload) > 1000, "Decoded screenshot payload seems too small (expected >1KB for a real image)"
        assert len(payload) <= MAX_INLINE_IMAGE_BYTES, "Image should be within size limits"
        
    finally:
        # Clean up the browser session
        await end_session(session_id=sid)

# @pytest.mark.asyncio
# async def test_inspect_browser_handles_large_screenshots():
#     initialize_environment()
    
#     # Start a browser session
#     start_res = await start_session(
#         url="https://example.com",
#         headless=True
#     )
#     assert "error" not in start_res, f"Session start error: {start_res.get('error')}"
#     sid = start_res["session_id"]
    
#     try:
#         # Patch MAX_INLINE_IMAGE_BYTES to a very small value to force the screenshot to be too large
#         with patch('nova_mcp_server.config.MAX_INLINE_IMAGE_BYTES', 100):  # Force screenshot to be "too large"
#             inspect_res = await inspect_browser(session_id=sid)
            
#             # Verify basic response structure
#             assert "error" not in inspect_res, "Inspect shouldn't return an error when screenshot is too large"
#             assert inspect_res.get("current_url") == "https://example.com/", "URL should match"
            
#             # Image should be omitted from content array
#             content = inspect_res.get("content", [])
#             img_content = next((c for c in content if c.get("type") == "image_base64"), None)
#             assert img_content is None, "image_base64 should be omitted when too large"
            
#             # Should have a warning in agent_thinking
#             agent_thinking = inspect_res.get("agent_thinking", [])
#             has_size_warning = False
#             for thought in agent_thinking:
#                 if (thought.get("type") == "system_warning" and 
#                     "too large" in thought.get("content", "").lower() and
#                     "screenshot" in thought.get("content", "").lower()):
#                     has_size_warning = True
#                     break
            
#             assert has_size_warning, "Missing system warning about screenshot size in agent_thinking"
            
#     finally:
#         # Clean up the browser session
#         await end_session(session_id=sid)

# @pytest.mark.asyncio
# async def test_execute_no_longer_returns_screenshot():
#     initialize_environment()
    
#     # Start a browser session
#     start_res = await start_session(
#         url="https://example.com",
#         headless=True
#     )
#     assert "error" not in start_res, f"Session start error: {start_res.get('error')}"
#     sid = start_res["session_id"]
    
#     try:
#         # Execute a simple action
#         execute_res = await browser_session(
#             action="execute",
#             session_id=sid,
#             instruction="Look at the page title"
#         )
        
#         # Verify basic response structure
#         assert "error" not in execute_res, f"Execute error: {execute_res.get('error')}"
        
#         # Check that no screenshot is included in the content array
#         content = execute_res.get("content", [])
#         has_image = any(c.get("type") == "image_base64" for c in content)
#         assert not has_image, "Execute should no longer include screenshots in content array"
        
#         # The inline_screenshot field should no longer be present or should be None
#         assert "inline_screenshot" not in execute_res or execute_res.get("inline_screenshot") is None, \
#             "Execute should no longer include inline_screenshot"
            
#     finally:
#         # Clean up the browser session
#         await end_session(session_id=sid)

# @pytest.mark.asyncio
# async def test_inspect_browser_after_execute():
#     initialize_environment()
    
#     # Start a browser session
#     start_res = await start_session(
#         url="https://example.com",
#         headless=True
#     )
#     assert "error" not in start_res, f"Session start error: {start_res.get('error')}"
#     sid = start_res["session_id"]
    
#     try:
#         # Execute an action that changes the page state
#         execute_res = await browser_session(
#             action="execute",
#             session_id=sid,
#             instruction="Click on the 'More information...' link"
#         )
#         assert "error" not in execute_res, f"Execute error: {execute_res.get('error')}"
        
#         # Now inspect the browser to see the result with a screenshot
#         inspect_res = await inspect_browser(session_id=sid)
        
#         # Verify the inspect shows the updated URL and has a screenshot
#         assert "error" not in inspect_res, f"Inspect error: {inspect_res.get('error')}"
#         assert "iana.org" in inspect_res.get("current_url", ""), "URL should have changed to iana.org domain"
        
#         # Check for screenshot in content array
#         content = inspect_res.get("content", [])
#         img_content = next((c for c in content if c.get("type") == "image_base64"), None)
#         assert img_content is not None, "image_base64 should be present in inspect_browser after execute"
        
#     finally:
#         # Clean up the browser session
#         await end_session(session_id=sid)