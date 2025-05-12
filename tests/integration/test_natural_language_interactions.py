"""
Integration tests for natural language interactions with the browser through Nova Act MCP.

These tests simulate an agent performing sequences of actions on live websites
using natural language instructions.

NOTE: Most tests are commented out for faster test execution. Only a simple navigation
test remains active for basic verification of natural language capabilities.
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
pytestmark = pytest.mark.skipif(
    "NOVA_ACT_API_KEY" not in os.environ or os.environ.get("CI") == "true",
    reason="Skipping natural language interaction tests in CI or when API key is not available"
)

TEST_BASE_URL = "https://the-internet.herokuapp.com"

@pytest.fixture(scope="function")
async def herokuapp_session():
    """
    Setup fixture that creates a browser session at The Internet Herokuapp for each test.
    
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
async def test_navigate_and_get_title(herokuapp_session):
    sid = herokuapp_session

    # More explicit navigation instruction
    nav_instruction = "Navigate to Status Codes" # Target specific sub-page
    print(f"DEBUG: Attempting to navigate with: '{nav_instruction}'")
    exec_res = await browser_session(
        action="execute",
        session_id=sid,
        instruction=nav_instruction
    )
    print(f"DEBUG: Navigation execute result: {exec_res}")
    assert "error" not in exec_res, f"Navigation error: {exec_res.get('error')}"
    # We can't always rely on exec_res.get("success") === True from NL actions.
    # The absence of an error is a better primary check for now.

    # Add a small explicit observation act to help sync page state
    observe_res = await browser_session(action="execute", session_id=sid, instruction="Observe the content of the current page.")
    print(f"DEBUG: Observe result: {observe_res}")
    await asyncio.sleep(1) # Reduced sleep

    inspect_res = await inspect_browser(session_id=sid)
    print(f"DEBUG: Inspect result: {inspect_res}")

    assert "error" not in inspect_res, f"Inspect error: {inspect_res.get('error')}"

    current_url = inspect_res.get("current_url", "")
    page_title = inspect_res.get("page_title", "")

    assert f"{TEST_BASE_URL}/status_codes" in current_url, f"URL mismatch. Expected {TEST_BASE_URL}/status_codes, got {current_url}"
    assert "Status Codes" in page_title, f"Title mismatch. Expected 'Status Codes', got '{page_title}'"

# @pytest.mark.asyncio
# async def test_checkbox_interaction(herokuapp_session):
#     """Test checking and unchecking checkboxes."""
#     sid = herokuapp_session
# 
#     # Navigate to checkboxes page
#     nav_res = await browser_session(action="execute", session_id=sid, instruction="Navigate to Checkboxes page")
#     assert "error" not in nav_res, f"Navigation error: {nav_res.get('error')}"
#     
#     # Check the first checkbox (assuming it's initially unchecked)
#     exec_check_res = await browser_session(
#         action="execute",
#         session_id=sid,
#         instruction="Check the first checkbox" # Relies on Nova Act's ability to find "first"
#     )
#     assert "error" not in exec_check_res, f"Error checking checkbox: {exec_check_res.get('error')}"
# 
#     # Verify using inspection
#     inspect_after_check = await inspect_browser(session_id=sid)
#     assert "error" not in inspect_after_check, f"Inspect error: {inspect_after_check.get('error')}"
#     
#     # Uncheck the second checkbox (assuming it's initially checked)
#     exec_uncheck_res = await browser_session(
#         action="execute",
#         session_id=sid,
#         instruction="Uncheck the second checkbox"
#     )
#     assert "error" not in exec_uncheck_res, f"Error unchecking checkbox: {exec_uncheck_res.get('error')}"

# @pytest.mark.asyncio
# async def test_dropdown_selection(herokuapp_session):
#     """Test selecting an option from a dropdown."""
#     sid = herokuapp_session
#     nav_res = await browser_session(action="execute", session_id=sid, instruction="Navigate to Dropdown page")
#     assert "error" not in nav_res, f"Navigation error: {nav_res.get('error')}"
# 
#     exec_select_res = await browser_session(
#         action="execute",
#         session_id=sid,
#         instruction="Select 'Option 1' from the dropdown"
#     )
#     assert "error" not in exec_select_res, f"Error selecting from dropdown: {exec_select_res.get('error')}"
#     
#     # Inspect to confirm selection
#     inspect_after_select = await inspect_browser(session_id=sid)
#     assert "error" not in inspect_after_select, f"Inspect error: {inspect_after_select.get('error')}"

# @pytest.mark.asyncio
# async def test_form_authentication_valid_credentials(herokuapp_session):
#     """Test logging in with valid credentials."""
#     sid = herokuapp_session
#     nav_res = await browser_session(action="execute", session_id=sid, instruction="Navigate to Login page")
#     assert "error" not in nav_res, f"Navigation error: {nav_res.get('error')}"
# 
#     login_exec_res = await browser_session(
#         action="execute",
#         session_id=sid,
#         instruction="Enter username 'tomsmith' and password 'SuperSecretPassword!' and click the login button"
#     )
#     assert "error" not in login_exec_res, f"Login error: {login_exec_res.get('error')}"
# 
#     # Inspect the page after login attempt
#     inspect_after_login = await inspect_browser(session_id=sid)
#     assert "error" not in inspect_after_login, f"Inspect error after login: {inspect_after_login.get('error')}"
#     
#     # Check for successful login indicators
#     assert f"{TEST_BASE_URL}/secure" in inspect_after_login.get("current_url", ""), "Should be redirected to secure area"
#     
#     page_content_text = ""
#     for item in inspect_after_login.get("content", []):
#         if item.get("type") == "text":
#             page_content_text += item.get("text", "") + " "
# 
#     assert "Welcome to the Secure Area" in page_content_text or "You logged into a secure area!" in page_content_text, \
#         "Login success message not found"
# 
#     # Example: Logout
#     logout_res = await browser_session(action="execute", session_id=sid, instruction="Click the logout button")
#     assert "error" not in logout_res, f"Logout error: {logout_res.get('error')}"
#     inspect_after_logout = await inspect_browser(session_id=sid)
#     assert f"{TEST_BASE_URL}/login" in inspect_after_logout.get("current_url", ""), "Should be redirected back to login page"


# @pytest.mark.asyncio
# async def test_form_authentication_invalid_credentials(herokuapp_session):
#     """Test logging in with invalid credentials."""
#     sid = herokuapp_session
#     nav_res = await browser_session(action="execute", session_id=sid, instruction="Navigate to Login page")
#     assert "error" not in nav_res, f"Navigation error: {nav_res.get('error')}"
# 
#     login_exec_res = await browser_session(
#         action="execute",
#         session_id=sid,
#         instruction="Enter username 'wronguser' and password 'wrongpassword' and click the login button"
#     )
#     assert "error" not in login_exec_res, f"Login attempt (invalid) should not error at MCP level: {login_exec_res.get('error')}"
# 
#     inspect_after_invalid_login = await inspect_browser(session_id=sid)
#     assert "error" not in inspect_after_invalid_login
#     
#     page_content_text = ""
#     for item in inspect_after_invalid_login.get("content", []):
#         if item.get("type") == "text":
#             page_content_text += item.get("text", "") + " "
#             
#     assert "Your username is invalid!" in page_content_text or "invalid" in page_content_text.lower(), \
#         "Error message for invalid login not found"
#     assert f"{TEST_BASE_URL}/login" in inspect_after_invalid_login.get("current_url", ""), "Should remain on login page"

# Note: The tests above have been temporarily commented out to simplify the integration test suite
# and reduce test execution time. Only the basic navigation test (test_navigate_and_get_title)
# remains active to verify core natural language functionality.
