import base64
import pytest
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock, AsyncMock

# Mark the test to be skipped in CI environments
pytestmark = pytest.mark.skipif(
    "NOVA_ACT_API_KEY" not in os.environ or os.environ.get("CI") == "true",
    reason="Skipping test_inline_execute in CI environment or when API key is not available"
)

# Import after the skipif to avoid errors when API key is missing
from nova_mcp import browser_session, MAX_INLINE_IMAGE_BYTES, initialize_environment

# This is a tiny JPEG image (1x1 pixel) with proper JPEG headers
SAMPLE_JPEG_B64 = "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD9/wDwT4J8E+FtOjg8PaJY6TGqgFbaFVY4/vMBknPckmigqP/Z"

@pytest.mark.asyncio
async def test_execute_returns_inline_image():
    """Test that execute action returns an inline screenshot in the response"""
    initialize_environment()

    # 1️⃣ start a real browser session
    sid = (await browser_session(action="start",
                                 url="https://example.com",
                                 headless=True))["session_id"]

    # 2️⃣ execute – request screenshot
    res = await browser_session(action="execute",
                               session_id=sid,
                               instruction="Take a screenshot of this page")

    # 3️⃣ clean‑up
    await browser_session(action="end", session_id=sid)
    
    # Verify results
    img = res.get("inline_screenshot")
    assert img and img.startswith("data:image/jpeg;base64,")

    # Print the base64 image data for visual verification (shorter output)
    print(f"\n\nINLINE (first 80): {img[:80]} … {len(img)} bytes")

    # Assert that the image is also in the content array (new in Option B)
    assert any(
        c.get("type") == "image_base64" for c in res["content"]
    ), "Image element missing from result.content"

    payload = base64.b64decode(img.split(",", 1)[1])
    assert payload[:3] == b"\xFF\xD8\xFF"  # JPEG SOI bytes
    assert len(payload) <= MAX_INLINE_IMAGE_BYTES