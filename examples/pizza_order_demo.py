#!/usr/bin/env python3
"""
Demo of the Nova Act MCP browser session for pizza ordering,
showing how to switch between headless and visible sessions.

This script demonstrates how to:
1. Start a headless browser session for the initial steps
2. Start a visible session for user review and checkout
"""

import os
import sys
import json
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

def order_pizza(client, pizza_site="https://order.pizzahut.com"):
    """
    Order a pizza using Nova Act, demonstrating headless and visible sessions.
    
    Args:
        client: MCPClient instance
        pizza_site: URL of pizza ordering site
    """
    print(f"\n----- Starting Pizza Order Demo -----\n")
    
    # Start a browser session in headless mode (invisible)
    print(f"🌐 Opening headless browser to {pizza_site}...")
    response = client.request(
        method="nova-browser.control_browser",
        params={
            "action": "start",
            "url": pizza_site,
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
    time.sleep(3)
    
    # Navigate to the menu page (using natural language)
    print("🍕 Navigating to order menu...")
    response = client.request(
        method="nova-browser.control_browser",
        params={
            "action": "execute",
            "session_id": headless_session_id,
            "instruction": "Find and click on the 'Start Your Order' button or link"
        }
    )
    
    # Let the page load
    time.sleep(3)
    
    # Select pizza type
    print("🍕 Selecting pizza options...")
    response = client.request(
        method="nova-browser.control_browser",
        params={
            "action": "execute",
            "session_id": headless_session_id,
            "instruction": "Choose a large pizza option from the menu"
        }
    )
    
    # Let the page load
    time.sleep(3)
    
    # Select toppings
    print("🧀 Adding toppings...")
    response = client.request(
        method="nova-browser.control_browser",
        params={
            "action": "execute",
            "session_id": headless_session_id,
            "instruction": "Add extra cheese, pepperoni, mushrooms, sausage, and black olives if possible"
        }
    )
    
    # Let the page load
    time.sleep(3)
    
    # Add to cart
    print("🛒 Adding to cart...")
    response = client.request(
        method="nova-browser.control_browser",
        params={
            "action": "execute",
            "session_id": headless_session_id,
            "instruction": "Click the 'Add to Cart' or 'Add to Order' button"
        }
    )
    
    # Let the page load
    time.sleep(3)
    
    # Get order summary and current URL in headless mode
    print("📝 Getting order summary...")
    response = client.request(
        method="nova-browser.control_browser",
        params={
            "action": "execute",
            "session_id": headless_session_id,
            "instruction": "Check what items are in the cart and summarize the order. Also return the current URL."
        }
    )
    
    # Check to make sure we have content
    current_url = None
    if "result" in response and "content" in response["result"]:
        print("\n----- Current Order Summary (Headless Mode) -----")
        for content_item in response["result"]["content"]:
            if content_item["type"] == "text":
                print(content_item["text"])
                # Extract URL from the text if possible
                import re
                url_match = re.search(r"Current URL: (https?://[^\s]+)", content_item["text"])
                if url_match:
                    current_url = url_match.group(1)
        print("-------------------------------------------------\n")
    
    # End the headless session
    print("🔚 Ending headless browser session...")
    response = client.request(
        method="nova-browser.control_browser",
        params={
            "action": "end",
            "session_id": headless_session_id
        }
    )
    
    # Start a new session in visible mode with the cart URL
    print("👁️ Starting visible browser for user review...")
    if not current_url:
        current_url = pizza_site  # Fallback if we couldn't get the URL
    
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
    
    # Let the user review the order
    print("\n👨‍💻 Browser is now visible for customer review")
    print("   Customer can review the order and make any changes")
    input("   Press Enter when ready to continue with checkout...\n")
    
    # Proceed to checkout in the visible browser
    print("🛍️ Proceeding to checkout...")
    response = client.request(
        method="nova-browser.control_browser",
        params={
            "action": "execute",
            "session_id": visible_session_id,
            "instruction": "Click the 'Checkout' button or proceed to delivery information"
        }
    )
    
    # Let the user decide when to end the demo
    input("\n📢 Demo complete. The browser is still open for you to explore.\nPress Enter to close the browser and end the demo...\n")
    
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
    
    print("\n----- Pizza Order Demo Complete -----\n")

def main():
    parser = argparse.ArgumentParser(description="Pizza ordering demo with Nova Act")
    parser.add_argument("--site", default="https://order.pizzahut.com", help="Pizza ordering website URL")
    parser.add_argument("--host", default="localhost", help="MCP server host")
    parser.add_argument("--port", type=int, default=8000, help="MCP server port")
    
    args = parser.parse_args()
    
    # Create MCP client
    client = MCPClient(host=args.host, port=args.port)
    
    try:
        # Run the pizza order demo
        order_pizza(client, pizza_site=args.site)
    except KeyboardInterrupt:
        print("\n\nDemo interrupted by user. Exiting...")
    except Exception as e:
        print(f"\n\nError during demo: {e}")
    
if __name__ == "__main__":
    main()