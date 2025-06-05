"""Unit tests for screenshot file saving functionality"""

import os
import sys
import tempfile
from unittest.mock import Mock, patch, MagicMock
import pytest

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))

from nova_mcp_server.tools.actions_inspect import _inspect_browser


class TestScreenshotFileSaving:
    """Test the new screenshot file saving behavior"""
    
    @patch('nova_mcp_server.tools.actions_inspect.active_sessions')
    def test_inspect_without_screenshot(self, mock_sessions):
        """Test that inspect_browser without screenshot flag doesn't capture screenshots"""
        # Setup mock session
        mock_nova = Mock()
        mock_nova.page.url = "https://example.com"
        mock_nova.page.title.return_value = "Example Domain"
        
        mock_sessions.__getitem__.return_value = {
            "nova_instance": mock_nova,
            "logs_dir": "/tmp/test_logs"
        }
        
        # Call inspect without screenshot
        result = _inspect_browser("test_session", include_screenshot_flag=False)
        
        # Verify no screenshot was captured
        assert result["success"] is True
        assert result["current_url"] == "https://example.com"
        assert result["page_title"] == "Example Domain"
        
        # Check that screenshot method was not called
        mock_nova.page.screenshot.assert_not_called()
        
        # Verify no screenshot path in response
        assert "screenshot_path" not in result.get("browser_state", {})
        
        # Verify content doesn't mention screenshot
        content_text = str(result.get("content", []))
        assert "screenshot" not in content_text.lower()
    
    @patch('nova_mcp_server.tools.actions_inspect.active_sessions')
    @patch('builtins.open', create=True)
    @patch('os.path.exists')
    def test_inspect_with_screenshot_saves_file(self, mock_exists, mock_open, mock_sessions):
        """Test that inspect_browser with screenshot flag saves to file"""
        # Setup mock session
        mock_nova = Mock()
        mock_nova.page.url = "https://example.com"
        mock_nova.page.title.return_value = "Example Domain"
        
        # Mock screenshot data
        screenshot_data = b"fake_jpeg_data"
        mock_nova.page.screenshot.return_value = screenshot_data
        
        mock_sessions.__getitem__.return_value = {
            "nova_instance": mock_nova,
            "logs_dir": "/tmp/test_logs"
        }
        
        # Mock file operations
        mock_exists.return_value = True
        mock_file = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_file
        
        # Call inspect with screenshot
        result = _inspect_browser("test_session", include_screenshot_flag=True, inline_image_quality=30)
        
        # Verify screenshot was captured with correct quality
        mock_nova.page.screenshot.assert_called_once_with(type="jpeg", quality=30)
        
        # Verify file was written
        mock_open.assert_called()
        mock_file.write.assert_called_once_with(screenshot_data)
        
        # Check response structure
        assert result["success"] is True
        browser_state = result.get("browser_state", {})
        
        # Verify screenshot path is in browser_state
        assert "screenshot_path" in browser_state
        assert browser_state["screenshot_path"].startswith("/tmp/test_logs/screenshot_")
        assert browser_state["screenshot_path"].endswith(".jpg")
        assert browser_state["screenshot_size"] == len(screenshot_data)
        
        # Verify content mentions fetch_file
        content = result.get("content", [])
        content_text = " ".join([item.get("text", "") for item in content if item.get("type") == "text"])
        assert "fetch_file" in content_text
        assert "Screenshot saved to:" in content_text
    
    @patch('nova_mcp_server.tools.actions_inspect.active_sessions')
    def test_screenshot_capture_error_handling(self, mock_sessions):
        """Test error handling when screenshot capture fails"""
        # Setup mock session
        mock_nova = Mock()
        mock_nova.page.url = "https://example.com"
        mock_nova.page.title.return_value = "Example Domain"
        
        # Mock screenshot to raise exception
        mock_nova.page.screenshot.side_effect = Exception("Screenshot failed")
        
        mock_sessions.__getitem__.return_value = {
            "nova_instance": mock_nova,
            "logs_dir": "/tmp/test_logs"
        }
        
        # Call inspect with screenshot
        result = _inspect_browser("test_session", include_screenshot_flag=True)
        
        # Should still return success but with error in agent_thinking
        assert result["success"] is True
        
        # Check agent_thinking for error message
        agent_thinking = result.get("agent_thinking", [])
        error_messages = [msg for msg in agent_thinking if msg.get("type") == "system_error"]
        assert len(error_messages) > 0
        assert "Screenshot failed" in error_messages[0].get("content", "")
    
    @patch('nova_mcp_server.tools.actions_inspect.active_sessions')
    def test_no_logs_directory_handling(self, mock_sessions):
        """Test handling when logs directory is not available"""
        # Setup mock session without logs_dir
        mock_nova = Mock()
        mock_nova.page.url = "https://example.com"
        mock_nova.page.title.return_value = "Example Domain"
        mock_nova.page.screenshot.return_value = b"fake_jpeg_data"
        
        mock_sessions.__getitem__.return_value = {
            "nova_instance": mock_nova,
            # No logs_dir provided
        }
        
        # Mock _normalize_logs_dir to return None
        with patch('nova_mcp_server.tools.actions_inspect._normalize_logs_dir', return_value=None):
            result = _inspect_browser("test_session", include_screenshot_flag=True)
        
        # Should still succeed but with warning
        assert result["success"] is True
        
        # Check agent_thinking for warning
        agent_thinking = result.get("agent_thinking", [])
        warning_messages = [msg for msg in agent_thinking if msg.get("type") == "system_warning"]
        assert len(warning_messages) > 0
        assert "logs directory not available" in warning_messages[0].get("content", "")