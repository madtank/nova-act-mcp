import pytest
import os
import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

# Import the functions from your nova_mcp module
from nova_mcp import browser_session, compress_logs_tool, initialize_environment

# Skip integration tests if env var is set
skip_integration_tests = os.environ.get("SKIP_INTEGRATION_TESTS", "0") != "0"
skip_reason = "Skipping integration tests because SKIP_INTEGRATION_TESTS is set"

@pytest.mark.skipif(skip_integration_tests, reason=skip_reason)
@pytest.mark.asyncio
async def test_single_screenshot_compression(capsys):
    initialize_environment()

    # 1) start session – pick a tiny, stable site
    start = await browser_session(
        action="start",
        url="https://example.com",  # small, loads fast
        headless=True,
    )
    sid = start["session_id"]

    # 2) take one screenshot
    await browser_session(
        action="execute",
        session_id=sid,
        instruction="Take a screenshot of the current page",
    )

    # 3) noop so we're sure a calls‑log exists
    await browser_session(action="execute", session_id=sid, instruction="noop")

    # 4) compress
    comp = await compress_logs_tool(session_id=sid)
    
    # Debug response structure
    print("\nCompression tool response structure:")
    print(json.dumps(comp, indent=2, default=str)[:500] + "...")
    
    # Handle both response structures (direct stats or nested within compression_stats)
    if "compression_stats" in comp:
        stats = comp["compression_stats"]
    else:
        # Assume stats are at the top level
        stats = comp
        
    # Check if preview data exists
    if "preview" in stats:
        prev = stats["preview"]
        has_preview = True
    else:
        prev = {"first_50_bytes": "N/A", "first_50_b64_of_screenshot": "N/A"}
        has_preview = False

    # 5) assertions - use more flexible checks
    assert stats.get("success", False), "Compression failed"
    assert int(stats.get("compressed_size", 0)) > 0, "Compressed size is zero or missing"
    
    if "original_size" in stats and "compressed_size" in stats:
        assert int(stats["compressed_size"]) < int(stats["original_size"]), "No compression achieved"
    
    if "screenshot_count" in stats:
        assert int(stats["screenshot_count"]) >= 1, "No screenshots found"

    # 6) human‑readable dump with error handling
    print("\n=== Log‑compression summary ===")
    print(f"Original : {stats.get('original_size', 'UNKNOWN')} bytes")
    print(f"Compressed: {stats.get('compressed_size', 'UNKNOWN')} bytes "
          f"({stats.get('size_reduction_compressed', 'UNKNOWN')})")
    
    if has_preview:
        print("gzip header hex preview :", prev["first_50_bytes"])
        print("screenshot b64 preview  :", prev["first_50_b64_of_screenshot"])
    else:
        print("Preview data not available in response")
    
    print("==============================\n")

    # 7) end session (and ignore result)
    await browser_session(action="end", session_id=sid)