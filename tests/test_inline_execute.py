import base64
import pytest
import asyncio
from nova_mcp import browser_session, MAX_INLINE_IMAGE_BYTES, initialize_environment

@pytest.mark.asyncio
async def test_execute_returns_inline_image():
    """Test that execute action returns an inline screenshot in the response"""
    initialize_environment()

    # 1️⃣ start
    sid = (await browser_session(action="start",
                                 url="https://example.com",
                                 headless=True))["session_id"]

    # 2️⃣ execute – request screenshot
    res = await browser_session(action="execute",
                                session_id=sid,
                                instruction="Take a screenshot of this page")

    img = res.get("inline_screenshot")
    assert img and img.startswith("data:image/jpeg;base64,")

    # Print the base64 image data for visual verification
    print("\n\nINLINE SCREENSHOT DATA:")
    print(img)
    print("\n")

    payload = base64.b64decode(img.split(",", 1)[1])
    assert payload[:3] == b"\xFF\xD8\xFF"            # JPEG SOI bytes
    assert len(payload) <= MAX_INLINE_IMAGE_BYTES
    
    # Print image size info
    print(f"Image size: {len(payload)} bytes ({len(payload)/1024:.2f} KB)")
    print(f"Size limit: {MAX_INLINE_IMAGE_BYTES} bytes ({MAX_INLINE_IMAGE_BYTES/1024:.2f} KB)")

    # 3️⃣ clean‑up
    await browser_session(action="end", session_id=sid)