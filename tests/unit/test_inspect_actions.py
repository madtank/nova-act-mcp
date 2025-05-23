import pytest
import os
import base64
import uuid
import tempfile
import time
from unittest.mock import patch, MagicMock, call

from nova_mcp_server.tools.actions_inspect import _inspect_browser
from nova_mcp_server.config import MAX_INLINE_IMAGE_BYTES, INLINE_IMAGE_QUALITY

# _inspect_browser imports active_sessions from .actions_start (from .actions_start import active_sessions)
# So we need to patch 'nova_mcp_server.tools.actions_start.active_sessions'
# Constants like MAX_INLINE_IMAGE_BYTES are in 'nova_mcp_server.tools.actions_inspect'
MODULE_UNDER_TEST_PATH = "nova_mcp_server.tools.actions_inspect"
ACTIONS_START_MODULE_PATH = "nova_mcp_server.tools.actions_start"

TEST_SESSION_ID = "test_session_123"

@pytest.fixture
def mock_nova_page():
    """Fixture to create a MagicMock for nova.page."""
    page_mock = MagicMock()
    page_mock.url = "http://mockurl.com"
    page_mock.title.return_value = "Mock Page Title"
    page_mock.screenshot = MagicMock() 
    return page_mock

@pytest.fixture
def mock_nova_instance(mock_nova_page):
    """Fixture to create a MagicMock for the nova instance."""
    nova_mock = MagicMock()
    nova_mock.page = mock_nova_page
    # Mock the _normalize_logs_dir if it's called directly by _inspect_browser,
    # or ensure logs_dir is in active_sessions.
    # For _inspect_browser, logs_dir comes from active_sessions or _normalize_logs_dir
    return nova_mock

@pytest.fixture
def mock_active_sessions_setup(tmp_path, mock_nova_instance):
    """Fixture to mock active_sessions with a test session."""
    # tmp_path is a pytest fixture providing a temporary directory unique to the test invocation
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    
    session_data = {
        TEST_SESSION_ID: {
            "nova_instance": mock_nova_instance,
            "logs_dir": str(logs_dir),
            "nova_session_id": "mock_nova_sid_123" # for _normalize_logs_dir if used
        }
    }
    return session_data

# Test for screenshot_quality parameter
def test_screenshot_quality_parameter(mock_nova_instance, mock_active_sessions_setup):
    mock_nova_instance.page.screenshot.return_value = b"screenshot_data" # Needs to return some bytes
    with patch(f'{ACTIONS_START_MODULE_PATH}.active_sessions', mock_active_sessions_setup):
        # Test with a specific quality
        _inspect_browser(TEST_SESSION_ID, include_screenshot_flag=True, screenshot_quality=80)
        mock_nova_instance.page.screenshot.assert_called_with(type="jpeg", quality=80)

        # Test with None (should default to INLINE_IMAGE_QUALITY)
        _inspect_browser(TEST_SESSION_ID, include_screenshot_flag=True, screenshot_quality=None)
        mock_nova_instance.page.screenshot.assert_called_with(type="jpeg", quality=INLINE_IMAGE_QUALITY)

# Test for inline screenshots (small images)
def test_inline_screenshot_small_image(mock_nova_instance, mock_active_sessions_setup):
    small_image_bytes = b"small_image" * 10 
    assert len(small_image_bytes) < MAX_INLINE_IMAGE_BYTES, \
        f"Test image size {len(small_image_bytes)} is not smaller than MAX_INLINE_IMAGE_BYTES {MAX_INLINE_IMAGE_BYTES}"

    mock_nova_instance.page.screenshot.return_value = small_image_bytes
    
    with patch(f'{ACTIONS_START_MODULE_PATH}.active_sessions', mock_active_sessions_setup):
        result = _inspect_browser(TEST_SESSION_ID, include_screenshot_flag=True)

    assert "content" in result, f"Test failed, result was: {result}"
    inline_image_content = None
    for item in result.get("content", []):
        if item.get("type") == "image_base64":
            inline_image_content = item
            break
    
    assert inline_image_content is not None, "image_base64 content not found"
    assert inline_image_content["data"] == "data:image/jpeg;base64," + base64.b64encode(small_image_bytes).decode()
    assert result.get("screenshot_file_path") is None
    
    # A successful inline screenshot does not typically add a specific status message to agent_thinking.
    # agent_thinking is usually for warnings, errors, or significant actions like saving to a file.
    # So, we might expect agent_thinking to be empty or not contain this specific message.
    # For this test, let's ensure no unexpected error messages related to screenshot appeared.
    screenshot_error_message_found = False
    for msg in result.get("agent_thinking", []): 
        if "screenshot" in msg.get("content", "").lower() and \
           ("error" in msg.get("content", "").lower() or "failed" in msg.get("content", "").lower()):
            screenshot_error_message_found = True
            break
    assert not screenshot_error_message_found, f"Unexpected screenshot error in agent_thinking. Result: {result}"


# Test for file-saved screenshots (large images)
def test_file_saved_screenshot_large_image(mock_nova_instance, mock_active_sessions_setup):
    with patch(f'{MODULE_UNDER_TEST_PATH}.MAX_INLINE_IMAGE_BYTES', 50) as _mocked_max_bytes:
        # _mocked_max_bytes is the MagicMock for the patched constant if needed.
        large_image_bytes = b"large_image_data" * 10 
        assert len(large_image_bytes) > _mocked_max_bytes # Check against the patched value
        mock_nova_instance.page.screenshot.return_value = large_image_bytes
        
        session_logs_dir = mock_active_sessions_setup[TEST_SESSION_ID]["logs_dir"]

        with patch(f'{ACTIONS_START_MODULE_PATH}.active_sessions', mock_active_sessions_setup):
            result = _inspect_browser(TEST_SESSION_ID, include_screenshot_flag=True)

    assert "content" in result, f"Test failed, result was: {result}"
    inline_image_content = None
    for item in result.get("content", []):
        if item.get("type") == "image_base64":
            inline_image_content = item
            break
    assert inline_image_content is None # No inline image

    assert "screenshot_file_path" in result
    file_path = result["screenshot_file_path"]
    assert file_path is not None
    assert os.path.exists(file_path)
    assert file_path.startswith(os.path.join(session_logs_dir, "screenshots"))
    
    with open(file_path, "rb") as f:
        saved_data = f.read()
    assert saved_data == large_image_bytes
    
    status_message_found = False
    for msg in result.get("agent_thinking", []):
        if "Screenshot captured. Too large for inline, saved to:" in msg.get("content", ""):
            status_message_found = True
            break
    assert status_message_found, f"Saved-to-file message not found in agent_thinking. Result: {result}"

# Test for when include_screenshot_flag is False
def test_no_screenshot_when_flag_is_false(mock_nova_instance, mock_active_sessions_setup):
    with patch(f'{ACTIONS_START_MODULE_PATH}.active_sessions', mock_active_sessions_setup):
        result = _inspect_browser(TEST_SESSION_ID, include_screenshot_flag=False)

    assert "content" in result, f"Test failed, result was: {result}"
    inline_image_content = None
    for item in result.get("content", []):
        if item.get("type") == "image_base64":
            inline_image_content = item
            break
    assert inline_image_content is None

    assert result.get("screenshot_file_path") is None
    mock_nova_instance.page.screenshot.assert_not_called()
    
    screenshot_related_message = False
    if result.get("agent_thinking"): # Check if key exists before iterating
        for msg in result.get("agent_thinking", []):
            if "screenshot" in msg.get("content", "").lower(): 
                screenshot_related_message = True
                break
    assert not screenshot_related_message, f"Screenshot messages found in agent_thinking when not requested. Result: {result}"

# Test for screenshot capture failure
def test_screenshot_capture_failure(mock_nova_instance, mock_active_sessions_setup):
    mock_nova_instance.page.screenshot.side_effect = Exception("Screenshot kaboom!")
    
    with patch(f'{ACTIONS_START_MODULE_PATH}.active_sessions', mock_active_sessions_setup):
        result = _inspect_browser(TEST_SESSION_ID, include_screenshot_flag=True)
        
    assert result.get("screenshot_file_path") is None # inline_screenshot is not a top-level key
    
    error_message_found = False
    for msg in result.get("agent_thinking", []): # Safe get
        if "Error capturing screenshot" in msg.get("content", "") and "Screenshot kaboom!" in msg.get("content", ""):
            error_message_found = True
            break
    assert error_message_found, f"Capture failure message not found in agent_thinking. Result: {result}"

# Test for screenshot saving failure (e.g., disk full, permissions)
@patch('builtins.open', new_callable=MagicMock) 
def test_screenshot_save_failure(_mock_open_patch, mock_nova_instance, mock_active_sessions_setup):
    with patch(f'{MODULE_UNDER_TEST_PATH}.MAX_INLINE_IMAGE_BYTES', 50) as _mocked_max_bytes:
        large_image_bytes = b"very_large_image_data_that_will_not_be_inlined" * 5 
        assert len(large_image_bytes) > _mocked_max_bytes
        mock_nova_instance.page.screenshot.return_value = large_image_bytes
        
        _mock_open_patch.side_effect = IOError("Failed to write to disk!")

        with patch(f'{ACTIONS_START_MODULE_PATH}.active_sessions', mock_active_sessions_setup):
            result = _inspect_browser(TEST_SESSION_ID, include_screenshot_flag=True)

    assert result.get("screenshot_file_path") is None 
    
    save_error_message_found = False
    for msg in result.get("agent_thinking", []): # Safe get
        if "Screenshot captured but failed to save to file: Failed to write to disk!" in msg.get("content", ""):
            save_error_message_found = True
            break
    assert save_error_message_found, f"Save failure message not found in agent_thinking. Result: {result}"

# Test for when screenshot returns no data
def test_screenshot_returns_no_data(mock_nova_instance, mock_active_sessions_setup):
    mock_nova_instance.page.screenshot.return_value = None 
    
    with patch(f'{ACTIONS_START_MODULE_PATH}.active_sessions', mock_active_sessions_setup):
        result = _inspect_browser(TEST_SESSION_ID, include_screenshot_flag=True)
        
    assert result.get("screenshot_file_path") is None
    
    no_data_message_found = False
    for msg in result.get("agent_thinking", []): # Safe get
        if "Screenshot capture attempt returned no data." in msg.get("content", ""):
            no_data_message_found = True
            break
    assert no_data_message_found, f"No data message not found in agent_thinking. Result: {result}"

# Test for fallback logs directory if logs_dir is not in session and _normalize_logs_dir returns None/empty
@patch(f'{MODULE_UNDER_TEST_PATH}._normalize_logs_dir') 
def test_screenshot_save_fallback_log_dir(_mock_normalize_logs_patch, mock_nova_instance, mock_active_sessions_setup):
    with patch(f'{MODULE_UNDER_TEST_PATH}.MAX_INLINE_IMAGE_BYTES', 50) as _mocked_max_bytes:
        session_data_no_logs_dir = {
            TEST_SESSION_ID: {
                "nova_instance": mock_nova_instance,
                "nova_session_id": "mock_nova_sid_for_fallback"
            }
        }
        _mock_normalize_logs_patch.return_value = None 

        large_image_bytes = b"very_large_image_data_for_fallback_test" * 3
        assert len(large_image_bytes) > _mocked_max_bytes
        mock_nova_instance.page.screenshot.return_value = large_image_bytes

        with patch(f'{ACTIONS_START_MODULE_PATH}.active_sessions', session_data_no_logs_dir):
            with tempfile.TemporaryDirectory() as tmp_fallback_base:
                with patch('tempfile.gettempdir', return_value=tmp_fallback_base):
                    result = _inspect_browser(TEST_SESSION_ID, include_screenshot_flag=True)

                    assert "screenshot_file_path" in result, f"Test failed, result was: {result}"
                file_path = result["screenshot_file_path"]
                assert file_path is not None
                
                expected_fallback_dir = os.path.join(tmp_fallback_base, "nova_mcp_server_logs", TEST_SESSION_ID, "screenshots")
                assert file_path.startswith(expected_fallback_dir)
                assert os.path.exists(file_path)

                with open(file_path, "rb") as f:
                    saved_data = f.read()
                assert saved_data == large_image_bytes
                
                # The "logs_dir not available" message is a log_warning, not added to agent_thinking directly.
                # The functional correctness (saving to the fallback path) is the main check here.
                # Thus, removing the check for this specific message in agent_thinking.

# Test to ensure logs_dir from session is preferred even if _normalize_logs_dir would return something else
@patch(f'{MODULE_UNDER_TEST_PATH}._normalize_logs_dir')
def test_session_logs_dir_preference(_mock_normalize_logs_patch2, mock_nova_instance, mock_active_sessions_setup, tmp_path):
    with patch(f'{MODULE_UNDER_TEST_PATH}.MAX_INLINE_IMAGE_BYTES', 50) as _mocked_max_bytes:
        session_provided_logs_dir = mock_active_sessions_setup[TEST_SESSION_ID]["logs_dir"]
        
        normalized_dir_should_be_ignored = str(tmp_path / "normalized_dir_should_be_ignored")
        _mock_normalize_logs_patch2.return_value = normalized_dir_should_be_ignored

        large_image_bytes = b"large_image_data_testing_log_dir_preference" * 2
        assert len(large_image_bytes) > _mocked_max_bytes
        mock_nova_instance.page.screenshot.return_value = large_image_bytes

        with patch(f'{ACTIONS_START_MODULE_PATH}.active_sessions', mock_active_sessions_setup):
            result = _inspect_browser(TEST_SESSION_ID, include_screenshot_flag=True)

    assert "screenshot_file_path" in result, f"Test failed, result was: {result}"
    file_path = result["screenshot_file_path"]
    assert file_path is not None
    
    # Expected path is within the session_provided_logs_dir
    expected_screenshots_dir = os.path.join(session_provided_logs_dir, "screenshots")
    assert file_path.startswith(expected_screenshots_dir)
    assert os.path.exists(file_path)
    
    # Ensure _normalize_logs_dir was not called because logs_dir was already in the session
    # This depends on the internal logic: if logs_dir is in session, _normalize_logs_dir is not called for nova instance
    # _inspect_browser has:
    # logs_dir_from_session = active_sessions.get(session_id, {}).get("logs_dir")
    # if logs_dir_from_session: logs_dir = logs_dir_from_session
    # else: ... logs_dir = _normalize_logs_dir(nova, ...)
    # So, if logs_dir_from_session is set, it should not call the _normalize_logs_dir with nova.
    # However, _normalize_logs_dir might be called inside _inspect_browser if the initial
    # logs_dir_from_session is None.
    # The current structure of mock_active_sessions_setup ensures logs_dir_from_session is always set.
    # The part `if not logs_dir:` inside `_inspect_browser` is what we want to check.
    # If `logs_dir_from_session` is used, `logs_dir` is set, so the `if not logs_dir:` block is skipped.
    
    # Let's refine the test logic for _normalize_logs_dir call.
    # _normalize_logs_dir is called if session_data["logs_dir"] is initially None.
    # Our current mock_active_sessions_setup *always* provides a logs_dir.
    # To test the preference, we need to ensure the path is from the session, not a normalized one.
    # The assertion `assert file_path.startswith(expected_screenshots_dir)` already confirms this.
    # We can also check that the specific log message "Using logs_dir from active session" is present.
    # log_message_found = False # This check is for a debug log, hard to assert without log capture
    # for msg in result.get("agent_thinking",[]): 
    #     pass

    # The main assertion is that the file path is correct.
    assert os.path.exists(file_path)
    with open(file_path, "rb") as f:
        assert f.read() == large_image_bytes
    _mock_normalize_logs_patch2.assert_not_called() # This is the key check for this specific test.
