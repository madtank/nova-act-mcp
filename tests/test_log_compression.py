import sys
import os
import pytest
import json
import tempfile
import gzip
import base64
from unittest.mock import patch, MagicMock, Mock
from pathlib import Path

# Import the mocks from test_nova_mcp.py
from test_nova_mcp import MockTool, MockFastMCP, setup_module, teardown_module

def create_test_log_file(with_screenshots=True, image_size=5000):
    """Create a test log file with optional screenshots for testing compression"""
    temp_dir = tempfile.mkdtemp()
    log_path = os.path.join(temp_dir, "test_act_calls.json")
    
    # Create fake image data of specified size
    image_data = ""
    if with_screenshots:
        # Generate base64 encoded fake image data of specified size
        raw_data = b'X' * image_size
        image_data = base64.b64encode(raw_data).decode('utf-8')
    
    # Create sample log entries
    log_entries = []
    
    # Entry with screenshot
    if with_screenshots:
        log_entries.append({
            "request": {
                "instruction": "Click the login button",
                "screenshot": image_data
            },
            "response": {
                "status": "success"
            }
        })
        
        # Add another entry with screenshot
        log_entries.append({
            "request": {
                "instruction": "Enter username and password",
                "screenshot": image_data
            },
            "response": {
                "status": "success"
            }
        })
    
    # Entry without screenshot
    log_entries.append({
        "request": {
            "instruction": "Navigate to homepage"
        },
        "response": {
            "status": "success"
        }
    })
    
    # Write log entries to file
    with open(log_path, 'w') as f:
        json.dump(log_entries, f)
    
    return log_path

@pytest.mark.unit
def test_compress_log_file():
    """Test the compress_log_file function"""
    from nova_mcp import compress_log_file
    
    # Create a test log file with screenshots
    log_path = create_test_log_file(with_screenshots=True, image_size=5000)
    
    # Test compression
    result = compress_log_file(log_path, extract_screenshots=True)
    
    # Verify the result
    assert result["success"] is True
    assert result["original_size"] > 0
    assert result["compressed_size"] > 0
    assert result["screenshot_count"] == 2
    
    # Check size reduction
    assert result["original_size"] > result["no_screenshots_size"]
    assert result["no_screenshots_size"] > result["compressed_size"]
    
    # Verify that screenshot directory exists and contains files
    screenshot_dir = result["screenshot_directory"]
    assert os.path.exists(screenshot_dir)
    assert len(os.listdir(screenshot_dir)) == 2
    
    # Verify the compressed file exists
    assert os.path.exists(result["compressed_path"])
    
    # Verify content can be decompressed
    with gzip.open(result["compressed_path"], 'rb') as f:
        decompressed_data = json.loads(f.read().decode('utf-8'))
    
    # Verify screenshots are removed from the decompressed data
    assert "screenshot" not in decompressed_data[0]["request"]
    assert "screenshot_path" in decompressed_data[0]["request"]
    
    # Verify compressed size is less than 5 KB (as required)
    assert result["compressed_size"] < 5 * 1024, f"Compressed size is {result['compressed_size']} bytes, expected less than 5 KB"
    
    # Verify the screenshot preview looks like JPEG base64
    if "preview" in result and "first_50_b64_of_screenshot" in result["preview"] and result["preview"]["first_50_b64_of_screenshot"]:
        preview_b64 = result["preview"]["first_50_b64_of_screenshot"]
        # In a real scenario, JPEG would start with /9j/ but our test uses fake data (XXX...)
        assert (
            "data:image/jpeg;base64," in preview_b64  # We at least have the correct prefix
            or "/9j/" in preview_b64                  # Real JPEG data
            or "WFhY" in preview_b64                 # Base64 'XXX' in our test
        ), "Screenshot preview should be in expected format"
    
    # Clean up
    if os.path.exists(log_path):
        os.remove(log_path)
    if os.path.exists(result["compressed_path"]):
        os.remove(result["compressed_path"])
    if os.path.exists(result["no_screenshots_path"]):
        os.remove(result["no_screenshots_path"])
    if os.path.exists(screenshot_dir):
        for file in os.listdir(screenshot_dir):
            os.remove(os.path.join(screenshot_dir, file))
        os.rmdir(screenshot_dir)
    os.rmdir(os.path.dirname(log_path))

@pytest.mark.unit
def test_image_size_impact():
    """Test the impact of different image sizes on compression"""
    from nova_mcp import compress_log_file
    
    # Test with different image sizes
    image_sizes = [1000, 5000, 10000]
    compression_results = []
    
    for size in image_sizes:
        # Create a test log file with screenshots of specified size
        log_path = create_test_log_file(with_screenshots=True, image_size=size)
        
        # Compress the log file
        result = compress_log_file(log_path, extract_screenshots=True)
        compression_results.append(result)
        
        # Clean up
        if os.path.exists(log_path):
            os.remove(log_path)
        if os.path.exists(result["compressed_path"]):
            os.remove(result["compressed_path"])
        if os.path.exists(result["no_screenshots_path"]):
            os.remove(result["no_screenshots_path"])
        if os.path.exists(result["screenshot_directory"]):
            for file in os.listdir(result["screenshot_directory"]):
                os.remove(os.path.join(result["screenshot_directory"], file))
            os.rmdir(result["screenshot_directory"])
        os.rmdir(os.path.dirname(log_path))
    
    # Verify that larger images result in greater size reduction
    for i in range(1, len(image_sizes)):
        # Larger images should lead to greater original size
        assert compression_results[i]["original_size"] > compression_results[i-1]["original_size"]
        
        # Verify compression ratio improves with larger images
        size_reduction_previous = float(compression_results[i-1]["size_reduction_compressed"].rstrip('%'))
        size_reduction_current = float(compression_results[i]["size_reduction_compressed"].rstrip('%'))
        
        # Larger images should provide at least similar compression ratios
        # Note: We use >= rather than > because compression algorithms can have thresholds
        # where efficiency plateaus for very similar content
        assert size_reduction_current >= size_reduction_previous - 1  # Allow 1% tolerance
        
        # After removing screenshots, the remaining content should be similar in size
        assert abs(compression_results[i]["no_screenshots_size"] - compression_results[i-1]["no_screenshots_size"]) < 1000

if __name__ == "__main__":
    # This allows running the tests directly using `python tests/test_log_compression.py`
    pytest.main(["-v", "-s", __file__])