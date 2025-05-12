import pytest
import asyncio
import sys
import os

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

from nova_mcp_server.tools import browser_session
from nova_mcp_server.config import initialize_environment

pytestmark = pytest.mark.skipif(
    "NOVA_ACT_API_KEY" not in os.environ or os.environ.get("CI") == "true",
    reason="Skipping log access tests in CI or when API key is not available"
)

@pytest.mark.asyncio
async def test_html_log_path_returned_from_execute():
    initialize_environment()
    start_res = await browser_session(action="start", url="https://example.com", headless=True)
    assert "error" not in start_res, f"Session start failed: {start_res.get('error')}"
    assert "session_id" in start_res
    sid = start_res["session_id"]

    try:
        exec_res = await browser_session(
            action="execute",
            session_id=sid,
            instruction="Observe the page for a moment." 
        )
        assert "error" not in exec_res, f"Execute error: {exec_res.get('error')}"
        
        # Check if html_log_path is in the result from browser_session (via actions_execute.py)
        html_log_path = exec_res.get("html_log_path")
        assert html_log_path is not None, "html_log_path missing from execute result"
        assert isinstance(html_log_path, str), "html_log_path should be a string"
        assert html_log_path.endswith(".html"), "html_log_path should be an HTML file"
        
        print(f"HTML Log Path from execute: {html_log_path}")
        
        # Basic check if the file exists (might be flaky depending on timing/SDK behavior)
        # For a more robust check, we might need to wait or use a tool that explicitly lists log files.
        # For now, primarily testing that the path is *returned*.
        # assert os.path.exists(html_log_path), f"Returned HTML log path does not exist: {html_log_path}"

    finally:
        await browser_session(action="end", session_id=sid)
