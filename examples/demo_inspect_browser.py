#!/usr/bin/env python
"""
Demo script for nova-act-mcp v3.0.0's inspect_browser functionality.
This script demonstrates the new on-demand screenshot approach.
"""

import asyncio
import json
from nova_mcp_server.tools import browser_session, inspect_browser
from nova_mcp_server.config import initialize_environment

def truncate_base64(data, max_length=80):
    """Truncate base64 data for display purposes."""
    if not data or not isinstance(data, str):
        return None
    parts = data.split(',', 1)
    if len(parts) != 2:
        return data[:max_length] + "..." if len(data) > max_length else data
    prefix, base64_part = parts
    truncated = base64_part[:max_length] + "..." if len(base64_part) > max_length else base64_part
    return f"{prefix},{truncated}"

async def demo_inspect_browser():
    """Run a demo of the new inspect_browser tool."""
    print("\n=== Nova Act MCP v3.0.0 - inspect_browser Demo ===\n")
    
    # Initialize the environment
    initialize_environment()
    
    try:
        # 1. Start a browser session
        print("1. Starting browser session...")
        start_result = await browser_session(
            action="start",
            url="https://example.com",
            headless=True
        )
        session_id = start_result["session_id"]
        print(f"   Session started with ID: {session_id}")
        
        # 2. Execute an action without getting a screenshot
        print("\n2. Executing an action (without screenshot)...")
        execute_result = await browser_session(
            action="execute",
            session_id=session_id,
            instruction="Look at the page title"
        )
        print("   Action executed successfully")
        print("   Content items:", len(execute_result.get("content", [])))
        
        # Check if there's any image in the content array
        has_image = any(c.get("type") == "image_base64" for c in execute_result.get("content", []))
        print(f"   Contains image: {has_image} (should be False in v3.0.0)")
        
        # 3. Now use inspect_browser to get a screenshot
        print("\n3. Using inspect_browser to get a screenshot...")
        inspect_result = await inspect_browser(session_id=session_id)
        
        # Get and truncate the image data for display
        content = inspect_result.get("content", [])
        img_content = next((c for c in content if c.get("type") == "image_base64"), None)
        if img_content and "data" in img_content:
            # Truncate the base64 data for display
            original_img_data = img_content["data"]
            img_content["data"] = truncate_base64(original_img_data)
            
            # Calculate the size in bytes
            if "," in original_img_data:
                base64_part = original_img_data.split(",", 1)[1]
                img_size = len(base64_part) * 3 // 4  # Approximate size in bytes
                print(f"   Screenshot size: ~{img_size} bytes")
        
        # Pretty print the result
        print("\n=== inspect_browser Result ===")
        formatted_result = json.dumps(inspect_result, indent=2)
        print(formatted_result)
        
        # 4. Execute another action (clicking a link)
        print("\n4. Executing another action (clicking a link)...")
        await browser_session(
            action="execute",
            session_id=session_id,
            instruction="Click on the 'More information...' link"
        )
        print("   Action executed successfully")
        
        # 5. Use inspect_browser again to see the new page
        print("\n5. Using inspect_browser again to see the new page...")
        inspect_result2 = await inspect_browser(session_id=session_id)
        
        # Get and truncate the image data for display
        content2 = inspect_result2.get("content", [])
        img_content2 = next((c for c in content2 if c.get("type") == "image_base64"), None)
        if img_content2 and "data" in img_content2:
            # Truncate the base64 data for display
            original_img_data = img_content2["data"]
            img_content2["data"] = truncate_base64(original_img_data)
        
        # Now just output the key information
        print(f"   Current URL: {inspect_result2.get('current_url')}")
        print(f"   Page title: {inspect_result2.get('page_title')}")
        print(f"   Screenshot included: {img_content2 is not None}")
    
    finally:
        # Clean up: end the browser session
        print("\n6. Ending browser session...")
        await browser_session(action="end", session_id=session_id)
        print("   Session ended successfully")
    
    print("\n=== Demo completed ===")

if __name__ == "__main__":
    asyncio.run(demo_inspect_browser())