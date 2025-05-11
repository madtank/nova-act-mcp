"""
Log management tools for the Nova Act MCP Server.

This module provides functionality for viewing and compressing HTML log files
produced by Nova Act during browser sessions.
"""

import base64
import glob
import gzip
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

from .. import mcp
from ..config import log, log_error, initialize_environment
from ..session_manager import active_sessions, session_lock
from ..utils import compress_log_file, _normalize_logs_dir

@mcp.tool(
    name="view_html_log",
    description="View HTML logs from browser sessions"
)
async def view_html_log(
    session_id: Optional[str] = None,
    html_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Display the HTML log file for a browser session.
    
    Args:
        session_id: ID of the browser session to view logs for
        html_path: Direct path to an HTML log file
        
    Returns:
        dict: A dictionary containing HTML log content
    """
    initialize_environment()
    
    if not session_id and not html_path:
        return {
            "error": {
                "message": "Missing required parameter: session_id or html_path",
                "code": "MISSING_PARAMETER"
            }
        }
    
    # If session ID is provided, try to find the logs directory
    logs_dir = None
    if session_id:
        with session_lock:
            session_data = active_sessions.get(session_id)
            if session_data:
                nova_instance = session_data.get("nova_instance")
                if nova_instance:
                    logs_dir = _normalize_logs_dir(nova_instance)
        
        if not logs_dir and not html_path:
            return {
                "error": {
                    "message": f"Session {session_id} not found or has no logs directory",
                    "code": "SESSION_NOT_FOUND"
                }
            }
    
    # If html_path is provided directly, use it
    if html_path:
        if os.path.isfile(html_path):
            html_file_path = html_path
        else:
            return {
                "error": {
                    "message": f"File not found: {html_path}",
                    "code": "FILE_NOT_FOUND"
                }
            }
    else:
        # Try to find the HTML log file in the logs directory
        html_files = []
        for ext in [".html", ".htm"]:
            html_files.extend(glob.glob(os.path.join(logs_dir, f"*{ext}")))
        
        if not html_files:
            return {
                "error": {
                    "message": f"No HTML log files found for session {session_id}",
                    "code": "NO_LOGS_FOUND"
                }
            }
        
        # Sort by modification time to get the most recent
        html_files.sort(key=os.path.getmtime, reverse=True)
        html_file_path = html_files[0]
    
    try:
        # Read the HTML file
        with open(html_file_path, "r", encoding="utf-8", errors="ignore") as f:
            html_content = f.read()
        
        # Get file info
        file_size = os.path.getsize(html_file_path)
        file_mtime = os.path.getmtime(html_file_path)
        
        # Return content as a structured object for proper display in FastMCP
        content = [{
            "type": "html",
            "html": html_content
        }]
        
        # Prepare result
        result = {
            "content": content,
            "file_path": html_file_path,
            "file_size": file_size,
            "file_size_formatted": f"{file_size / 1024:.1f} KB",
            "timestamp": file_mtime,
            "timestamp_formatted": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(file_mtime)
            ),
        }
        
        log(f"Returned HTML log: {html_file_path} ({result['file_size_formatted']})")
        return result
    
    except Exception as e:
        log_error(f"Error reading HTML log file: {str(e)}")
        return {
            "error": {
                "message": f"Error reading HTML log file: {str(e)}",
                "code": "READ_ERROR"
            }
        }

@mcp.tool(
    name="compress_logs",
    description="Compress log files for efficient storage and transfer"
)
async def compress_logs(
    log_path: str,
    extract_screenshots: bool = True,
    compression_level: int = 9
) -> Dict[str, Any]:
    """
    Compress a Nova Act log file by removing screenshots and applying gzip compression.
    
    Args:
        log_path: Path to the log file to compress
        extract_screenshots: Whether to extract screenshots to a separate directory
        compression_level: Gzip compression level (1-9)
        
    Returns:
        dict: A dictionary containing compression results
    """
    initialize_environment()
    
    if not log_path:
        return {
            "error": {
                "message": "Missing required parameter: log_path",
                "code": "MISSING_PARAMETER"
            }
        }
    
    # Normalize path
    log_path = os.path.abspath(os.path.expanduser(log_path))
    
    # Check if the file exists
    if not os.path.isfile(log_path):
        return {
            "error": {
                "message": f"Log file not found: {log_path}",
                "code": "FILE_NOT_FOUND"
            }
        }
    
    # Compress the log file
    result = compress_log_file(log_path, extract_screenshots=extract_screenshots, compression_level=compression_level)
    
    # Add a timestamp
    result["timestamp"] = time.time()
    
    return result

@mcp.tool(
    name="view_compressed_log",
    description="View the contents of a compressed log file"
)
async def view_compressed_log(
    compressed_path: str
) -> Dict[str, Any]:
    """
    View a compressed log file.
    
    Args:
        compressed_path: Path to the compressed log file
        
    Returns:
        dict: A dictionary containing the decompressed log content
    """
    initialize_environment()
    
    if not compressed_path:
        return {
            "error": {
                "message": "Missing required parameter: compressed_path",
                "code": "MISSING_PARAMETER"
            }
        }
    
    # Normalize path
    compressed_path = os.path.abspath(os.path.expanduser(compressed_path))
    
    # Check if the file exists
    if not os.path.isfile(compressed_path):
        return {
            "error": {
                "message": f"Compressed log file not found: {compressed_path}",
                "code": "FILE_NOT_FOUND"
            }
        }
    
    try:
        # Check if it's a gzip file
        if compressed_path.endswith(".gz"):
            with gzip.open(compressed_path, "rb") as f:
                decompressed_data = f.read().decode("utf-8")
            
            # Try to parse the JSON
            try:
                json_data = json.loads(decompressed_data)
                log(f"Successfully parsed JSON from compressed file ({len(json_data)} records)")
                
                # Prepare result with structured content
                content = [{
                    "type": "code",
                    "language": "json",
                    "code": json.dumps(json_data, indent=2)
                }]
                
                result = {
                    "success": True,
                    "content": content,
                    "compressed_path": compressed_path,
                    "record_count": len(json_data),
                    "parsed_json": True,
                }
                
                return result
            
            except json.JSONDecodeError:
                # Not valid JSON, just return the raw content
                content = [{
                    "type": "text",
                    "text": decompressed_data
                }]
                
                return {
                    "success": True,
                    "content": content,
                    "compressed_path": compressed_path,
                    "parsed_json": False,
                }
        
        else:
            # Not a gzip file, just read it normally
            with open(compressed_path, "r", encoding="utf-8") as f:
                content_data = f.read()
            
            # Try to parse JSON
            try:
                json_data = json.loads(content_data)
                log(f"Successfully parsed JSON from file ({len(json_data)} records)")
                
                # Prepare result with structured content
                content = [{
                    "type": "code",
                    "language": "json",
                    "code": json.dumps(json_data, indent=2)
                }]
                
                result = {
                    "success": True,
                    "content": content,
                    "file_path": compressed_path,
                    "record_count": len(json_data),
                    "parsed_json": True,
                }
                
                return result
            
            except json.JSONDecodeError:
                # Not valid JSON, just return the raw content
                content = [{
                    "type": "text",
                    "text": content_data
                }]
                
                return {
                    "success": True,
                    "content": content,
                    "file_path": compressed_path,
                    "parsed_json": False,
                }
    
    except Exception as e:
        log_error(f"Error reading compressed log file: {str(e)}")
        return {
            "error": {
                "message": f"Error reading compressed log file: {str(e)}",
                "code": "READ_ERROR"
            }
        }