#!/usr/bin/env python3
"""
Simple demo of Nova Act MCP browser sessions using both headless and visible modes.

This script demonstrates how to:
1. Start a headless browser session and fill out a simple form
2. Start a visible session to verify the form
"""

import os
import sys
import time
import argparse
from pathlib import Path

# Add parent directory to path so we can import nova_mcp
sys.path.append(str(Path(__file__).parent.parent))

try:
    from mcp.client.mcpclient import MCPClient
except ImportError:
    print("Error: mcpclient not found. Install with `pip install mcp-client-python`")
    sys.exit(1)

def form_test(client, form_url="https://testpages.herokuapp.com/styled/basic-html-form-test.html"):
    """
    Fill out a simple form using Nova Act, demonstrating headless and visible sessions.
    
    Args:
        client: MCPClient instance
        form_url: URL of a form test page
    """
    print(f"\n----- Starting Simple Form Demo -----\n")
    
    # Start a browser session in headless mode (invisible)
    print(f"🌐 Opening headless browser to {form_url}...")
    response = client.request(
        method="nova-browser.control_browser",
        params={
            "action": "start",
            "url": form_url,
            "headless": True  # Start in headless mode
        }
    )
    
    if "error" in response:
        print(f"❌ Error starting browser: {response['error']['message']}")
        return
    
    # Get the session ID
    headless_session_id = response["result"]["session_id"]
    print(f"✅ Headless browser started with session ID: {headless_session_id}")
    
    # Wait for page to load
    time.sleep(2)
    
    # Fill out the form with test data
    print("📝 Filling out form with test data...")
    response = client.request(
        method="nova-browser.control_browser",
        params={
            "action": "execute",
            "session_id": headless_session_id,
            "instruction": "Fill out the form with username 'TestUser', password 'TestPass123', and comments 'This is a test form submission'"
        }
    )
    
    # Get the current URL
    print("🔍 Getting current URL...")
    response = client.request(
        method="nova-browser.control_browser",
        params={
            "action": "execute",
            "session_id": headless_session_id,
            "instruction": "Return the current URL and describe what form fields have been filled out"
        }
    )
    
    # Extract URL and form status
    current_url = form_url  # Default fallback
    form_status = "Unknown form status"
    if "result" in response and "content" in response["result"]:
        print("\n----- Form Status (Headless Mode) -----")
        for content_item in response["result"]["content"]:
            if content_item["type"] == "text":
                print(content_item["text"])
                # Try to extract URL if present
                import re
                url_match = re.search(r"Current URL: (https?://[^\s]+)", content_item["text"])
                if url_match:
                    current_url = url_match.group(1)
                # Store the form status text
                form_status = content_item["text"]
        print("----------------------------------------\n")
    
    # End the headless session
    print("🔚 Ending headless browser session...")
    response = client.request(
        method="nova-browser.control_browser",
        params={
            "action": "end",
            "session_id": headless_session_id
        }
    )
    
    # Start a new session in visible mode with the same URL
    print("👁️ Starting visible browser for verification...")
    response = client.request(
        method="nova-browser.control_browser",
        params={
            "action": "start",
            "url": current_url,
            "headless": False  # Start in visible mode
        }
    )
    
    if "error" in response:
        print(f"❌ Error starting visible browser: {response['error']['message']}")
        return
        
    # Get the new session ID
    visible_session_id = response["result"]["session_id"]
    print(f"✅ Visible browser started with session ID: {visible_session_id}")
    
    # Let the user verify the form
    print("\n👨‍💻 Browser is now visible. You can verify the form is filled out.")
    print(f"   Previous form status: {form_status}")
    input("   Press Enter when ready to continue...\n")
    
    # Submit the form in the visible browser
    print("📤 Submitting the form...")
    response = client.request(
        method="nova-browser.control_browser",
        params={
            "action": "execute",
            "session_id": visible_session_id,
            "instruction": "Click the submit button"
        }
    )
    
    # Let the user review the results
    input("\n📢 Demo complete. You can verify the form submission results.\nPress Enter to close the browser and end the demo...\n")
    
    # End the visible browser session
    print("🔚 Ending visible browser session...")
    response = client.request(
        method="nova-browser.control_browser",
        params={
            "action": "end",
            "session_id": visible_session_id
        }
    )
    
    if "error" in response:
        print(f"❌ Error ending session: {response['error']['message']}")
    else:
        print("✅ Browser session ended successfully")
    
    print("\n----- Simple Form Demo Complete -----\n")

def main():
    parser = argparse.ArgumentParser(description="Simple form demo with Nova Act")
    parser.add_argument("--url", default="https://testpages.herokuapp.com/styled/basic-html-form-test.html", 
                      help="Form test website URL")
    parser.add_argument("--host", default="localhost", help="MCP server host")
    parser.add_argument("--port", type=int, default=8000, help="MCP server port")
    
    args = parser.parse_args()
    
    # Create MCP client
    client = MCPClient(host=args.host, port=args.port)
    
    try:
        # Run the form demo
        form_test(client, form_url=args.url)
    except KeyboardInterrupt:
        print("\n\nDemo interrupted by user. Exiting...")
    except Exception as e:
        print(f"\n\nError during demo: {e}")
    
if __name__ == "__main__":
    main()