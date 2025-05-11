"""
Functional tests for Nova Act MCP using natural language agent workflows.

These tests simulate an agent performing sequences of actions on live websites.
They provide higher-level testing of the nova-act-mcp functionality in real-world scenarios.
"""
import pytest
import asyncio
import os
import uuid

# Add project root to sys.path if necessary (adjust path based on actual structure)
import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

from nova_mcp_server.tools import browser_session, inspect_browser
from nova_mcp_server.config import initialize_environment

# Skip conditions - check if we're in a CI environment
IS_CI = os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true"
API_KEY = os.environ.get("NOVA_ACT_API_KEY")
# Assuming NOVA_ACT_AVAILABLE and REAL_MCP_LOADED are checked/imported similarly or handled by initialize_environment
# For simplicity, focusing on API_KEY and CI here. Adapt if more checks are needed.
skip_reason = "Functional tests skipped: NOVA_ACT_API_KEY not set or in CI without integration flag"

if IS_CI:
    skip_functional_tests = not os.environ.get("RUN_INTEGRATION_TESTS_IN_CI") == "true" # Or a specific flag for functional tests
else:
    skip_functional_tests = not API_KEY # Add other conditions like NOVA_ACT_AVAILABLE if needed

pytestmark = pytest.mark.skipif(skip_functional_tests, reason=skip_reason)

TEST_BASE_URL = "https://the-internet.herokuapp.com"

@pytest.fixture(scope="function")
async def agent_session():
    """
    Setup fixture that creates a browser session for each test.
    
    Returns:
        str: Session ID of the started browser session
    """
    initialize_environment()
    session_id = None
    start_res = await browser_session(
        action="start",
        url=TEST_BASE_URL, # Start at the base URL
        headless=True
    )
    assert "error" not in start_res, f"Session start error: {start_res.get('error')}"
    session_id = start_res.get("session_id")
    assert session_id, "Failed to get session_id"
    
    yield session_id
    
    if session_id:
        await browser_session(action="end", session_id=session_id)

@pytest.mark.asyncio
async def test_navigate_and_get_title(agent_session):
    """Test basic navigation and title inspection."""
    sid = agent_session

    # Navigate to a specific page (example.com for simplicity here, or a subpage of herokuapp)
    exec_res = await browser_session(
        action="execute",
        session_id=sid,
        instruction=f"Navigate to {TEST_BASE_URL}/status_codes" # Example sub-navigation
    )
    assert "error" not in exec_res, f"Navigation error: {exec_res.get('error')}"

    inspect_res = await inspect_browser(session_id=sid)
    assert "error" not in inspect_res, f"Inspect error: {inspect_res.get('error')}"
    assert f"{TEST_BASE_URL}/status_codes" in inspect_res.get("current_url", "")
    assert "Status Codes" in inspect_res.get("page_title", "")

@pytest.mark.asyncio
async def test_checkbox_interaction(agent_session):
    """Test checking and unchecking checkboxes."""
    sid = agent_session

    # Navigate to checkboxes page
    nav_res = await browser_session(action="execute", session_id=sid, instruction=f"Navigate to {TEST_BASE_URL}/checkboxes")
    assert "error" not in nav_res, f"Navigation error: {nav_res.get('error')}"
    
    # Initial state inspection (optional, good for debugging)
    # inspect_initial = await inspect_browser(session_id=sid)
    # print("Initial checkboxes page:", inspect_initial.get("content"))

    # Check the first checkbox (assuming it's initially unchecked)
    exec_check_res = await browser_session(
        action="execute",
        session_id=sid,
        instruction="Check the first checkbox" # Relies on Nova Act's ability to find "first"
    )
    assert "error" not in exec_check_res, f"Error checking checkbox: {exec_check_res.get('error')}"

    # Inspect and verify (this is tricky without DOM access, relies on visual change or Nova's understanding)
    # For a robust test, you'd ideally need a way to query checkbox state.
    # For NL test, we trust Nova Act and look for screenshot changes or success.
    # inspect_after_check = await inspect_browser(session_id=sid)
    # TODO: Add a way to verify checkbox state if possible, or rely on screenshot diff if advanced.
    # For now, we'll assume success if no error.

    # Uncheck the second checkbox (assuming it's initially checked)
    exec_uncheck_res = await browser_session(
        action="execute",
        session_id=sid,
        instruction="Uncheck the second checkbox"
    )
    assert "error" not in exec_uncheck_res, f"Error unchecking checkbox: {exec_uncheck_res.get('error')}"
    # inspect_after_uncheck = await inspect_browser(session_id=sid)
    # TODO: Verification

@pytest.mark.asyncio
async def test_dropdown_selection(agent_session):
    """Test selecting an option from a dropdown."""
    sid = agent_session
    nav_res = await browser_session(action="execute", session_id=sid, instruction=f"Navigate to {TEST_BASE_URL}/dropdown")
    assert "error" not in nav_res, f"Navigation error: {nav_res.get('error')}"

    exec_select_res = await browser_session(
        action="execute",
        session_id=sid,
        instruction="Select 'Option 1' from the dropdown"
    )
    assert "error" not in exec_select_res, f"Error selecting from dropdown: {exec_select_res.get('error')}"
    
    # Inspect (e.g., screenshot) to see if "Option 1" is visually selected.
    # Or, if Nova Act provides text feedback confirming selection, check that.
    # inspect_after_select = await inspect_browser(session_id=sid)
    # TODO: Verification, e.g. by asking Nova to read selected option or screenshot.

@pytest.mark.asyncio
async def test_form_authentication_valid_credentials(agent_session):
    """Test logging in with valid credentials."""
    sid = agent_session
    nav_res = await browser_session(action="execute", session_id=sid, instruction=f"Navigate to {TEST_BASE_URL}/login")
    assert "error" not in nav_res, f"Navigation error: {nav_res.get('error')}"

    # Use the direct username/password parameters for browser_session
    # This allows Nova MCP to potentially use Playwright's fill directly.
    login_exec_res = await browser_session(
        action="execute",
        session_id=sid,
        instruction="Enter username 'tomsmith' and password 'SuperSecretPassword!' and click the login button",
        # Alternatively, if your MCP tool handles username/password params separately:
        # username="tomsmith", # This depends on how browser_session is implemented
        # password="SuperSecretPassword!",
        # instruction="Click the login button"
    )
    assert "error" not in login_exec_res, f"Login error: {login_exec_res.get('error')}"

    # Inspect the page after login attempt
    inspect_after_login = await inspect_browser(session_id=sid)
    assert "error" not in inspect_after_login, f"Inspect error after login: {inspect_after_login.get('error')}"
    
    # Check for successful login indicators
    assert f"{TEST_BASE_URL}/secure" in inspect_after_login.get("current_url", ""), "Should be redirected to secure area"
    
    page_content_text = ""
    for item in inspect_after_login.get("content", []):
        if item.get("type") == "text":
            page_content_text += item.get("text", "") + " "

    assert "Welcome to the Secure Area" in page_content_text or "You logged into a secure area!" in page_content_text, \
        "Login success message not found"

    # Example: Logout
    logout_res = await browser_session(action="execute", session_id=sid, instruction="Click the logout button")
    assert "error" not in logout_res, f"Logout error: {logout_res.get('error')}"
    inspect_after_logout = await inspect_browser(session_id=sid)
    assert f"{TEST_BASE_URL}/login" in inspect_after_logout.get("current_url", ""), "Should be redirected back to login page"


@pytest.mark.asyncio
async def test_form_authentication_invalid_credentials(agent_session):
    """Test logging in with invalid credentials."""
    sid = agent_session
    nav_res = await browser_session(action="execute", session_id=sid, instruction=f"Navigate to {TEST_BASE_URL}/login")
    assert "error" not in nav_res, f"Navigation error: {nav_res.get('error')}"

    login_exec_res = await browser_session(
        action="execute",
        session_id=sid,
        instruction="Enter username 'wronguser' and password 'wrongpassword' and click the login button"
    )
    assert "error" not in login_exec_res, f"Login attempt (invalid) should not error at MCP level: {login_exec_res.get('error')}"

    inspect_after_invalid_login = await inspect_browser(session_id=sid)
    assert "error" not in inspect_after_invalid_login
    
    page_content_text = ""
    for item in inspect_after_invalid_login.get("content", []):
        if item.get("type") == "text":
            page_content_text += item.get("text", "") + " "
            
    assert "Your username is invalid!" in page_content_text or "invalid" in page_content_text.lower(), \
        "Error message for invalid login not found"
    assert f"{TEST_BASE_URL}/login" in inspect_after_invalid_login.get("current_url", ""), "Should remain on login page"

# Add more tests based on Nova Act README features:
# - Information extraction with schema (might be complex for NL, better for integration with mock schema)
# - File upload/download (requires a page with these features)
# - Date picking (requires a page with a date picker)
# - Handling new tabs/windows if Nova Act supports it and you want to test MCP's role

if __name__ == "__main__":
    pytest.main(["-v", __file__])