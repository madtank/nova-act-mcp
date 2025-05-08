#!/usr/bin/env python
"""
Simple demo script for nova-act-mcp v3.0.0's inspect_browser functionality.
This streamlined version avoids potential hanging issues.
"""

import asyncio
import json
import sys
from nova_mcp import browser_session, inspect_browser, initialize_environment

def truncate_base64(data, max_length=50):
    """Truncate base64 data for display purposes."""
    if not data or not isinstance(data, str):
        return None
    parts = data.split(',', 1)
    if len(parts) != 2:
        return data[:max_length] + "..." if len(data) > max_length else data
    prefix, base64_part = parts
    truncated = base64_part[:max_length] + "..." if len(base64_part) > max_length else base64_part
    return f"{prefix},{truncated}"

async def simple_demo():
    """Run a simplified demo of the inspect_browser tool."""
    print("\n=== Nova Act MCP v3.0.0 - inspect_browser Simple Demo ===\n")
    
    # Initialize the environment
    initialize_environment()
    
    # Set a shorter timeout
    timeout = 30  # seconds
    
    try:
        print("Starting browser session...")
        start_result = await asyncio.wait_for(
            browser_session(
                action="start",
                url="https://example.com",
                headless=True
            ), 
            timeout=timeout
        )
        
        session_id = start_result["session_id"]
        print(f"Session started with ID: {session_id}")
        
        print("\nUsing inspect_browser to get a screenshot...")
        inspect_result = await asyncio.wait_for(
            inspect_browser(session_id=session_id),
            timeout=timeout
        )
        
        # Get and truncate the image data for display
        content = inspect_result.get("content", [])
        img_content = next((c for c in content if c.get("type") == "image_base64"), None)
        
        if img_content and "data" in img_content:
            # Truncate the base64 data for display
            original_img_data = img_content["data"]
            img_content["data"] = truncate_base64(original_img_data)
        
        # Print key information
        print(f"\nCurrent URL: {inspect_result.get('current_url')}")
        print(f"Page title: {inspect_result.get('page_title')}")
        print(f"Screenshot included: {img_content is not None}")
        
        if img_content and "data" in img_content:
            print(f"\nTruncated image data: {img_content['data']}")
        
        print("\nEnding browser session...")
        await asyncio.wait_for(
            browser_session(action="end", session_id=session_id),
            timeout=timeout
        )
        print("Session ended successfully")
        
    except asyncio.TimeoutError:
        print("\nTIMEOUT ERROR: Operation took too long to complete.")
        print("This might be due to issues with browser initialization or network connectivity.")
        return 1
    except Exception as e:
        print(f"\nERROR: {type(e).__name__}: {e}")
        return 1
    
    print("\n=== Demo completed successfully ===")
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(simple_demo())
    sys.exit(exit_code)