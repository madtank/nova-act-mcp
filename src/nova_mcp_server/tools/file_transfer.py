"""
File transfer tools for the Nova Act MCP Server.

This module provides functionality for transferring files between the client and server,
such as retrieving screenshots and logs.
"""

import base64
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional

from .. import mcp
from ..config import log, log_error, initialize_environment

@mcp.tool(
    name="fetch_file",
    description="Fetch a file from the server and return its content"
)
async def fetch_file(
    file_path: str,
    encode_base64: bool = False, 
    max_size: int = 10 * 1024 * 1024  # Default 10MB limit
) -> Dict[str, Any]:
    """
    Fetch a file from the server and optionally encode it as base64.
    
    Args:
        file_path: Path to the file to fetch
        encode_base64: Whether to encode the file as base64
        max_size: Maximum file size in bytes
        
    Returns:
        dict: A dictionary containing file content and metadata
    """
    initialize_environment()
    
    if not file_path:
        return {
            "error": {
                "message": "Missing required parameter: file_path",
                "code": "MISSING_PARAMETER"
            }
        }
    
    # Normalize path
    file_path = os.path.abspath(os.path.expanduser(file_path))
    
    # Check if the file exists
    if not os.path.isfile(file_path):
        return {
            "error": {
                "message": f"File not found: {file_path}",
                "code": "FILE_NOT_FOUND"
            }
        }
    
    # Check file size
    file_size = os.path.getsize(file_path)
    if file_size > max_size:
        return {
            "error": {
                "message": f"File too large: {file_size} bytes (max {max_size} bytes)",
                "code": "FILE_TOO_LARGE"
            },
            "file_path": file_path,
            "file_size": file_size,
        }
    
    try:
        # Get file metadata
        file_mtime = os.path.getmtime(file_path)
        file_name = os.path.basename(file_path)
        file_ext = os.path.splitext(file_name)[1].lower()
        
        # Determine content type
        content_type = "application/octet-stream"  # Default
        if file_ext in [".jpg", ".jpeg"]:
            content_type = "image/jpeg"
        elif file_ext == ".png":
            content_type = "image/png"
        elif file_ext == ".gif":
            content_type = "image/gif"
        elif file_ext in [".html", ".htm"]:
            content_type = "text/html"
        elif file_ext == ".json":
            content_type = "application/json"
        elif file_ext == ".txt":
            content_type = "text/plain"
        
        # Read the file
        with open(file_path, "rb") as f:
            file_content = f.read()
        
        # Encode as base64 if requested
        if encode_base64:
            encoded_content = base64.b64encode(file_content).decode("utf-8")
            
            # For images, create a data URL
            if content_type.startswith("image/"):
                data_url = f"data:{content_type};base64,{encoded_content}"
                
                # Prepare result with data URL
                result = {
                    "success": True,
                    "file_path": file_path,
                    "file_size": file_size,
                    "file_size_formatted": f"{file_size / 1024:.1f} KB",
                    "file_name": file_name,
                    "content_type": content_type,
                    "timestamp": file_mtime,
                    "timestamp_formatted": time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(file_mtime)
                    ),
                    "data_url": data_url,
                    "encoded_content": encoded_content,
                }
            else:
                # Non-image files
                result = {
                    "success": True,
                    "file_path": file_path,
                    "file_size": file_size,
                    "file_size_formatted": f"{file_size / 1024:.1f} KB",
                    "file_name": file_name,
                    "content_type": content_type,
                    "timestamp": file_mtime,
                    "timestamp_formatted": time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(file_mtime)
                    ),
                    "encoded_content": encoded_content,
                }
        else:
            # Try to decode as text if it looks like a text file
            if content_type.startswith(("text/", "application/json")):
                try:
                    text_content = file_content.decode("utf-8")
                    
                    # Prepare result with text content
                    result = {
                        "success": True,
                        "file_path": file_path,
                        "file_size": file_size,
                        "file_size_formatted": f"{file_size / 1024:.1f} KB",
                        "file_name": file_name,
                        "content_type": content_type,
                        "timestamp": file_mtime,
                        "timestamp_formatted": time.strftime(
                            "%Y-%m-%d %H:%M:%S", time.localtime(file_mtime)
                        ),
                        "content": text_content,
                    }
                except UnicodeDecodeError:
                    # Not valid UTF-8, treat as binary
                    result = {
                        "success": True,
                        "file_path": file_path,
                        "file_size": file_size,
                        "file_size_formatted": f"{file_size / 1024:.1f} KB",
                        "file_name": file_name,
                        "content_type": content_type,
                        "timestamp": file_mtime,
                        "timestamp_formatted": time.strftime(
                            "%Y-%m-%d %H:%M:%S", time.localtime(file_mtime)
                        ),
                        "is_binary": True,
                        "encoded_content": base64.b64encode(file_content).decode("utf-8"),
                    }
            else:
                # Binary file
                result = {
                    "success": True,
                    "file_path": file_path,
                    "file_size": file_size,
                    "file_size_formatted": f"{file_size / 1024:.1f} KB",
                    "file_name": file_name,
                    "content_type": content_type,
                    "timestamp": file_mtime,
                    "timestamp_formatted": time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(file_mtime)
                    ),
                    "is_binary": True,
                    "encoded_content": base64.b64encode(file_content).decode("utf-8"),
                }
        
        log(f"Fetched file: {file_path} ({result['file_size_formatted']})")
        return result
    
    except Exception as e:
        log_error(f"Error fetching file: {str(e)}")
        return {
            "error": {
                "message": f"Error fetching file: {str(e)}",
                "code": "READ_ERROR"
            },
            "file_path": file_path,
        }