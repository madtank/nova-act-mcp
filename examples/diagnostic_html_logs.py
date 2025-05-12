#!/usr/bin/env python
"""
Diagnostic script to help understand HTML log path finding in Nova Act MCP.
This directly tests the relevant components without going through pytest.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

# Add project root to path
project_root = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_root)

try:
    # Import required functions
    from nova_mcp_server.config import initialize_environment, get_nova_act_api_key
    from nova_mcp_server.tools import browser_session, view_html_log
    print("Successfully imported nova_mcp module")
except ImportError as e:
    print(f"Failed to import from nova_mcp: {e}")
    sys.exit(1)

async def run_diagnostic():
    """Run basic diagnostic tests for HTML path finding"""
    print("\n=== Nova Act MCP HTML Path Finding Diagnostic ===\n")
    
    # Initialize environment
    initialize_environment()
    api_key = get_nova_act_api_key()
    if not api_key:
        print("ERROR: No API key found. Please set NOVA_ACT_API_KEY environment variable.")
        return
    
    print(f"API Key found: {'✓' if api_key else '❌'}")
    
    # 1. Start a browser session
    print("\n1. Starting browser session...")
    start_result = await browser_session(
        action="start", 
        url="https://example.com", 
        headless=True
    )
    
    if "error" in start_result:
        print(f"ERROR starting session: {start_result['error']}")
        return
    
    session_id = start_result["session_id"]
    print(f"Session started successfully. ID: {session_id}")
    
    # 2. Execute a simple action that should generate HTML logs
    print("\n2. Executing browser action...")
    execute_result = await browser_session(
        action="execute",
        session_id=session_id,
        instruction="Click the 'More information...' link"
    )
    
    if "error" in execute_result:
        print(f"ERROR executing action: {execute_result['error']}")
    else:
        print("Action executed successfully")
        
        # 3. Check if we have agent thinking
        agent_thinking = execute_result.get("agent_thinking", [])
        print(f"Agent thinking found: {len(agent_thinking)} messages")
        
        # 4. Try to access the HTML log
        print("\n3. Checking for HTML log...")
        log_result = await view_html_log(session_id=session_id)
        
        if "error" in log_result:
            print(f"ERROR viewing HTML log: {log_result['error']}")
            
            # Attempt to find logs in expected locations
            print("\n4. Diagnostic: Searching common log locations...")
            # A. Check temp directory
            temp_dir = tempfile.gettempdir()
            print(f"Checking temp directory: {temp_dir}")
            
            nova_logs = []
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    if file.endswith("_output.html") and "act_" in file:
                        path = os.path.join(root, file)
                        mtime = os.path.getmtime(path)
                        nova_logs.append((path, mtime))
                        
            # Sort by modification time, newest first
            nova_logs.sort(key=lambda x: x[1], reverse=True)
            
            if nova_logs:
                print(f"Found {len(nova_logs)} potential Nova Act HTML logs")
                for i, (path, mtime) in enumerate(nova_logs[:5]):  # Show top 5
                    print(f"  {i+1}. {path}")
                    
                    # Try accessing the most recent log directly
                    if i == 0:
                        print("\n5. Attempting to view the most recent HTML log directly...")
                        direct_result = await view_html_log(html_path=path)
                        if "error" in direct_result:
                            print(f"ERROR viewing direct HTML log: {direct_result['error']}")
                        else:
                            print("Successfully retrieved HTML content directly")
                            content_length = 0
                            if "content" in direct_result and isinstance(direct_result["content"], list):
                                for item in direct_result["content"]:
                                    if item.get("type") == "html":
                                        content_length = len(item.get("html", ""))
                            print(f"HTML content length: {content_length} characters")
            else:
                print("No Nova Act HTML logs found in temporary directory")
                
        else:
            print("HTML log found successfully")
            content_length = 0
            if "content" in log_result and isinstance(log_result["content"], list):
                for item in log_result["content"]:
                    if item.get("type") == "html":
                        content_length = len(item.get("html", ""))
            print(f"HTML content length: {content_length} characters")
    
    # 5. End the session
    print("\n6. Ending browser session...")
    end_result = await browser_session(
        action="end",
        session_id=session_id
    )
    
    if "error" in end_result:
        print(f"ERROR ending session: {end_result['error']}")
    else:
        print("Session ended successfully")

if __name__ == "__main__":
    asyncio.run(run_diagnostic())