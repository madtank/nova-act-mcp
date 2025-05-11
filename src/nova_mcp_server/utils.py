"""
Utilities for the Nova Act MCP Server.

This module provides various utility functions used throughout the
Nova Act MCP Server, including file handling, data parsing, and more.
"""

import base64
import glob
import gzip
import html
import json
import os
import re
import sys
import tempfile
import time  # Added for timestamp comparisons
import traceback # Module-level import
import uuid
from pathlib import Path  # Ensure Path is imported
from typing import Any, Dict, List, Optional, Tuple # Removed Set, Union

from .config import log_error, log_warning, log_debug, log_info  # Add log_info


def extract_agent_thinking(
    result: Any, 
    nova_instance: Optional[Any] = None,  # Add nova_instance parameter
    html_path_to_parse: Optional[str] = None,
    instruction: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Extract agent thinking steps from NovaAct results.
    
    Args:
        result: NovaAct result object
        nova_instance: The NovaAct instance (optional)
        html_path_to_parse: Path to HTML log file to parse
        instruction: Original instruction for context
        
    Returns:
        tuple: A tuple containing a list of agent messages and debug info
    """
    agent_messages_structured = []
    debug_info = {}
    
    def _clean_thought(t: str) -> str:
        """Clean up raw thinking text by handling escapes and whitespace."""
        return t.strip().replace("\\n", "\n").replace('\\"', '"')
    
    log_debug(f"[extract_agent_thinking] Starting with result: {type(result)}, nova_instance: {type(nova_instance) if nova_instance else None}")
    
    # Method 1: Direct fields from result object
    if result:
        log_debug("[extract_agent_thinking] Checking result object attributes")
        # Check result.metadata.thinking
        if hasattr(result, "metadata") and hasattr(result.metadata, "thinking") and result.metadata.thinking:
            log_debug("[extract_agent_thinking] Found result.metadata.thinking")
            thinking_items = result.metadata.thinking
            if isinstance(thinking_items, list):
                for i, t in enumerate(thinking_items):
                    cleaned = _clean_thought(str(t))
                    if cleaned:
                        agent_messages_structured.append({
                            "role": "agent_thinking",
                            "step": i + 1,
                            "content": cleaned,
                            "source": "result_metadata_thinking",
                        })
            elif thinking_items:  # Handle single item
                cleaned = _clean_thought(str(thinking_items))
                if cleaned:
                    agent_messages_structured.append({
                        "role": "agent_thinking",
                        "step": 1,
                        "content": cleaned,
                        "source": "result_metadata_thinking",
                    })
        
        # Check result.thinking
        if hasattr(result, "thinking") and result.thinking:
            log_debug("[extract_agent_thinking] Found result.thinking")
            thinking_items = result.thinking
            if isinstance(thinking_items, list):
                for i, t in enumerate(thinking_items):
                    cleaned = _clean_thought(str(t))
                    if cleaned:
                        agent_messages_structured.append({
                            "role": "agent_thinking",
                            "step": i + 1,
                            "content": cleaned,
                            "source": "result_thinking",
                        })
            elif thinking_items:  # Handle single item
                cleaned = _clean_thought(str(thinking_items))
                if cleaned:
                    agent_messages_structured.append({
                        "role": "agent_thinking",
                        "step": 1,
                        "content": cleaned,
                        "source": "result_thinking",
                    })
        
        # Check result.thoughts
        if hasattr(result, "thoughts") and result.thoughts:
            log_debug("[extract_agent_thinking] Found result.thoughts")
            thoughts_items = result.thoughts
            if isinstance(thoughts_items, list):
                for i, t in enumerate(thoughts_items):
                    cleaned = _clean_thought(str(t))
                    if cleaned:
                        agent_messages_structured.append({
                            "role": "agent_thinking",
                            "step": i + 1,
                            "content": cleaned,
                            "source": "result_thoughts",
                        })
            elif thoughts_items:  # Handle single item
                cleaned = _clean_thought(str(thoughts_items))
                if cleaned:
                    agent_messages_structured.append({
                        "role": "agent_thinking",
                        "step": 1,
                        "content": cleaned,
                        "source": "result_thoughts",
                    })
    
    # Method 2: Raw logs from nova_instance.get_logs() if available
    if nova_instance and hasattr(nova_instance, "get_logs") and callable(getattr(nova_instance, "get_logs")):
        try:
            log_debug("[extract_agent_thinking] Attempting to get logs from nova_instance.get_logs()")
            raw_logs = nova_instance.get_logs()
            
            if raw_logs:
                log_debug(f"[extract_agent_thinking] Got logs of type: {type(raw_logs)}")
                log_lines = []
                
                # Handle different return types from get_logs()
                if isinstance(raw_logs, str):
                    log_lines = raw_logs.splitlines()
                elif isinstance(raw_logs, list):
                    log_lines = raw_logs
                
                # Process log lines looking for thinking patterns
                thinking_count = 0
                for line in log_lines:
                    if not line:
                        continue
                        
                    # Patterns for think() calls, including various quote styles
                    # Standard think("...") pattern
                    think_match = re.search(r'think\s*\(\s*["\']([^"\']+)["\']', str(line))
                    if not think_match:
                        # Try multiline pattern with triple quotes or backticks
                        think_match = re.search(r'think\s*\(\s*(?:"""|\'\'\')(.*?)(?:"""|\'\'\')(?:\s*\))?', str(line), re.DOTALL)
                    if not think_match:
                        # Try think(`...`) pattern with backticks
                        think_match = re.search(r'think\s*\(\s*`(.*?)`\s*\)', str(line), re.DOTALL)
                    
                    if think_match:
                        thinking_content = think_match.group(1)
                        cleaned = _clean_thought(thinking_content)
                        if cleaned:
                            thinking_count += 1
                            agent_messages_structured.append({
                                "role": "agent_thinking",
                                "step": thinking_count,
                                "content": cleaned,
                                "source": "nova_raw_logs",
                            })
                
                if thinking_count > 0:
                    log_debug(f"[extract_agent_thinking] Found {thinking_count} thinking steps in raw logs")
                    debug_info["raw_logs_thinking_count"] = thinking_count
        except Exception as e:
            log_error(f"[extract_agent_thinking] Error extracting thinking from raw logs: {str(e)}")
            debug_info["raw_logs_error"] = str(e)
    
    # Method 3: HTML log parsing if available and needed
    if html_path_to_parse and os.path.exists(html_path_to_parse):
        try:
            log_debug(f"[extract_agent_thinking] Parsing HTML log: {html_path_to_parse}")
            with open(html_path_to_parse, "r", encoding="utf-8") as f:
                html_content = f.read()
            
            # Extract messages using regex patterns
            thinking_pattern = r'<div class="message-thinking">(.*?)</div>'
            action_pattern = r'<div class="message-action">(.*?)</div>'
            
            # Find all thinking steps
            thinking_matches = re.findall(thinking_pattern, html_content, re.DOTALL)
            html_thinking_count = 0
            
            for thinking in thinking_matches:
                cleaned = _clean_thought(html.unescape(thinking).strip())
                if cleaned:
                    html_thinking_count += 1
                    # Check if this thinking is already in our list (avoid duplicates)
                    if not any(msg.get("content") == cleaned for msg in agent_messages_structured):
                        agent_messages_structured.append({
                            "role": "agent_thinking",
                            "step": html_thinking_count,
                            "content": cleaned,
                            "source": "html_log",
                        })
            
            # Find all action steps (only if we need them)
            action_matches = re.findall(action_pattern, html_content, re.DOTALL)
            for i, action in enumerate(action_matches):
                cleaned = _clean_thought(html.unescape(action).strip())
                if cleaned:
                    agent_messages_structured.append({
                        "role": "agent_action",
                        "step": i + 1,
                        "content": cleaned,
                        "source": "html_log",
                    })
            
            if html_thinking_count > 0:
                log_debug(f"[extract_agent_thinking] Found {html_thinking_count} thinking steps in HTML log")
                debug_info["html_thinking_count"] = html_thinking_count
        except Exception as e:
            log_error(f"[extract_agent_thinking] Error parsing HTML log: {str(e)}")
            debug_info["html_parse_error"] = str(e)
    
    # Fallback: If no thinking found and result has a response, use it as a fallback
    if not agent_messages_structured and result and hasattr(result, "response"):
        response = result.response
        log_debug("[extract_agent_thinking] No thinking found, checking result.response as fallback")
        
        if response and isinstance(response, str):
            # Check if it looks like actual thinking (not just a simple status)
            if not re.match(r'^\s*(action|task)\s+(executed|complete|finished|done)', response.lower()):
                cleaned = _clean_thought(response)
                if cleaned:
                    agent_messages_structured.append({
                        "role": "agent_thinking",
                        "step": 1,
                        "content": cleaned,
                        "source": "result_response_fallback",
                    })
                    log_debug("[extract_agent_thinking] Using result.response as fallback thinking")
                    debug_info["used_response_fallback"] = True
    
    # Add debug info
    debug_info["message_count"] = len(agent_messages_structured)
    debug_info["sources"] = list(set(msg.get("source") for msg in agent_messages_structured))
    
    # Sort messages by step for a consistent order
    agent_messages_structured.sort(key=lambda x: x.get("step", 0))
    
    log_debug(f"[extract_agent_thinking] Extracted {len(agent_messages_structured)} agent messages")
    
    # Add original instruction for context
    if instruction:
        debug_info["original_instruction"] = instruction
    
    return agent_messages_structured, debug_info


def _normalize_logs_dir(nova: Any, sdk_session_id_override: Optional[str] = None) -> Optional[str]:
    """
    Attempt to determine the NovaAct SDK's session-specific logs directory.
    Priority:
      1. nova._logs_directory + sdk_session_id_override (if override is validly provided)
      2. nova.logs_directory (if valid dir and appears to be a session log dir)
      3. Other fallback attributes from the nova instance (legacy/SDK internal changes)
    """
    # Assuming log_debug, log_info, log_warning, log_error are imported and available
    log_debug(f"_normalize_logs_dir: START. nova type: {type(nova)}, sdk_session_id_override='{sdk_session_id_override}'")

    # Method 1: Preferred method using nova._logs_directory and the sdk_session_id_override
    # sdk_session_id_override is expected to come from initial_result.metadata.session_id
    base_dir_from_attr = getattr(nova, '_logs_directory', None)
    
    log_debug(f"_normalize_logs_dir: Method 1 Pre-check: base_dir_from_attr='{base_dir_from_attr}', sdk_session_id_override='{sdk_session_id_override}'")

    if base_dir_from_attr and isinstance(base_dir_from_attr, (str, Path)) and \
       sdk_session_id_override and isinstance(sdk_session_id_override, str) and sdk_session_id_override.strip():
        
        base_path = Path(str(base_dir_from_attr))
        # sdk_session_id_override is the specific sub-directory name created by the SDK
        constructed_path = base_path / sdk_session_id_override.strip()
        
        log_info(f"_normalize_logs_dir: Method 1: Constructed candidate path: '{constructed_path}' (from nova._logs_directory + sdk_session_id_override)")
        
        if constructed_path.is_dir():
            resolved_path = str(constructed_path.resolve())
            log_info(f"_normalize_logs_dir: Method 1: SUCCESS - Verified path '{resolved_path}' is a directory.")
            return resolved_path
        else:
            log_warning(f"_normalize_logs_dir: Method 1: Constructed path '{constructed_path}' is NOT a directory. "
                        f"Checking if base_dir_from_attr ('{base_path}') itself might be the session log directory.")
            if base_path.is_dir():
                if list(base_path.glob("act_*.html")) or \
                   list(base_path.glob("*_calls.json")) or \
                   list(base_path.glob("trace.playwright.dev.json")):
                    resolved_base_path = str(base_path.resolve())
                    log_info(f"_normalize_logs_dir: Method 1 (Fallback): SUCCESS - Base path '{resolved_base_path}' "
                             f"appears to be the session log directory itself.")
                    return resolved_base_path
                else:
                    log_warning(f"_normalize_logs_dir: Method 1 (Fallback): Base path '{base_path}' is a directory, "
                                f"but does not contain characteristic log files to confirm it's a session log dir.")
            log_warning(f"_normalize_logs_dir: Method 1: Failed to validate a directory using nova._logs_directory and sdk_session_id_override. Proceeding to other methods.")
    else:
        log_debug(f"_normalize_logs_dir: Method 1: Requirements not met. "
                  f"base_dir_from_attr ('{base_dir_from_attr}') or sdk_session_id_override ('{sdk_session_id_override}') is invalid or missing. "
                  f"Proceeding to other methods.")

    # Method 2: Check nova.logs_directory (attribute without underscore)
    logs_dir_attr_no_underscore = getattr(nova, "logs_directory", None)
    log_debug(f"_normalize_logs_dir: Method 2: Checking nova.logs_directory (attribute without underscore) = '{logs_dir_attr_no_underscore}'")
    if logs_dir_attr_no_underscore and isinstance(logs_dir_attr_no_underscore, (str, Path)):
        path_from_logs_directory_attr = Path(str(logs_dir_attr_no_underscore))
        if path_from_logs_directory_attr.is_dir():
            if list(path_from_logs_directory_attr.glob("act_*.html")) or \
               list(path_from_logs_directory_attr.glob("*_calls.json")) or \
               list(path_from_logs_directory_attr.glob("trace.playwright.dev.json")):
                resolved_path = str(path_from_logs_directory_attr.resolve())
                log_info(f"_normalize_logs_dir: Method 2: SUCCESS - Verified path from nova.logs_directory attribute: '{resolved_path}'")
                return resolved_path
            else:
                log_warning(f"_normalize_logs_dir: Method 2: Path from nova.logs_directory ('{path_from_logs_directory_attr}') "
                            f"is a directory but doesn't appear to be a session log directory (no characteristic files).")
        else:
            log_debug(f"_normalize_logs_dir: Method 2: Path from nova.logs_directory ('{path_from_logs_directory_attr}') is not a directory.")
    else:
        log_debug(f"_normalize_logs_dir: Method 2: nova.logs_directory attribute not found or invalid type.")

    # Method 3: Iterate through other potential attribute names
    log_debug(f"_normalize_logs_dir: Method 3: Checking other candidate attributes.")
    candidate_attrs = [
        "logs_dir", "log_directory", "log_dir", "logs_path", "log_path",
        "output_dir", "output_directory", 
        "_session_user_data_dir"
    ]
    for attr_name in candidate_attrs:
        val = getattr(nova, attr_name, None)
        if val and isinstance(val, (str, Path)):
            candidate_path = Path(str(val))
            log_debug(f"_normalize_logs_dir: Method 3: Checking attribute '{attr_name}', path='{candidate_path}'")
            if candidate_path.is_dir():
                if list(candidate_path.glob("act_*.html")) or \
                   list(candidate_path.glob("*_calls.json")) or \
                   list(candidate_path.glob("trace.playwright.dev.json")):
                    resolved_path = str(candidate_path.resolve())
                    log_info(f"_normalize_logs_dir: Method 3: SUCCESS - Found logs dir via attribute '{attr_name}': '{resolved_path}'")
                    return resolved_path
                else:
                    log_warning(f"_normalize_logs_dir: Method 3: Path from '{attr_name}' ('{candidate_path}') is a dir but doesn't look like a session log dir.")
    
    # Method 4: Last resort - Check base_dir_from_attr (nova._logs_directory) itself
    if base_dir_from_attr and isinstance(base_dir_from_attr, (str, Path)):
        base_path_for_fallback_check = Path(str(base_dir_from_attr))
        if base_path_for_fallback_check.is_dir():
            log_debug(f"_normalize_logs_dir: Method 4 (Last Resort Fallback): Checking if nova._logs_directory ('{base_path_for_fallback_check}') itself is a session log dir.")
            if list(base_path_for_fallback_check.glob("act_*.html")) or \
               list(base_path_for_fallback_check.glob("*_calls.json")) or \
               list(base_path_for_fallback_check.glob("trace.playwright.dev.json")):
                resolved_path = str(base_path_for_fallback_check.resolve())
                log_info(f"_normalize_logs_dir: Method 4: SUCCESS - Using nova._logs_directory ('{resolved_path}') as fallback session log dir.")
                return resolved_path
            else:
                log_warning(f"_normalize_logs_dir: Method 4: nova._logs_directory ('{base_path_for_fallback_check}') "
                            f"does not appear to be a session log directory (no characteristic files).")

    log_warning("_normalize_logs_dir: FAILURE - Could not determine a valid logs directory for the NovaAct session after all attempts.")
    return None


def compress_html_log(html_path: str, output_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Compress an HTML log file for efficient storage or transfer.
    
    Args:
        html_path: Path to the HTML log file
        output_path: Path to save the compressed file (defaults to {html_path}.gz)
        
    Returns:
        dict: Results of the compression operation
    """
    if not os.path.exists(html_path):
        return {
            "success": False,
            "error": f"File not found: {html_path}",
            "path": html_path,
        }
    
    if not output_path:
        output_path = html_path + ".gz"
    
    try:
        input_size = os.path.getsize(html_path)
        
        # Read the HTML file
        with open(html_path, "rb") as f_in:
            html_data = f_in.read()
        
        # Compress the data
        compressed_data = gzip.compress(html_data)
        
        # Write the compressed data
        with open(output_path, "wb") as f_out:
            f_out.write(compressed_data)
        
        output_size = os.path.getsize(output_path)
        compression_ratio = input_size / output_size if output_size > 0 else 0
        
        return {
            "success": True,
            "input_path": html_path,
            "output_path": output_path,
            "input_size": input_size,
            "output_size": output_size,
            "compression_ratio": compression_ratio,
        }
    except (OSError, gzip.BadGzipFile) as e: # Made exception more specific
        error_details = traceback.format_exc()
        log_error(f"Error compressing HTML log: {str(e)}\n{error_details}")
        
        return {
            "success": False,
            "error": str(e),
            "error_details": error_details,
            "path": html_path,
        }


def decompress_html_log(gz_path: str, output_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Decompress a gzipped HTML log file.
    
    Args:
        gz_path: Path to the gzipped HTML log file
        output_path: Path to save the decompressed file (defaults to removing .gz extension)
        
    Returns:
        dict: Results of the decompression operation
    """
    if not os.path.exists(gz_path):
        return {
            "success": False,
            "error": f"File not found: {gz_path}",
            "path": gz_path,
        }
    
    if not output_path:
        # Remove .gz extension if present
        if gz_path.endswith(".gz"):
            output_path = gz_path[:-3]
        else:
            output_path = gz_path + ".decompressed"
    
    try:
        input_size = os.path.getsize(gz_path)
        
        # Read the compressed file
        with open(gz_path, "rb") as f_in:
            compressed_data = f_in.read()
        
        # Decompress the data
        decompressed_data = gzip.decompress(compressed_data)
        
        # Write the decompressed data
        with open(output_path, "wb") as f_out:
            f_out.write(decompressed_data)
        
        output_size = os.path.getsize(output_path)
        
        return {
            "success": True,
            "input_path": gz_path,
            "output_path": output_path,
            "input_size": input_size,
            "output_size": output_size,
        }
    except (OSError, gzip.BadGzipFile) as e: # Made exception more specific
        error_details = traceback.format_exc()
        log_error(f"Error decompressing HTML log: {str(e)}\n{error_details}")
        
        return {
            "success": False,
            "error": str(e),
            "error_details": error_details,
            "path": gz_path,
        }


def find_log_files(directory: Optional[str] = None, pattern: str = "*.html") -> List[Dict[str, Any]]:
    """
    Find log files in the specified directory.
    
    Args:
        directory: Directory to search (defaults to current directory)
        pattern: File pattern to match (defaults to *.html)
        
    Returns:
        list: A list of dictionaries with information about each log file
    """
    if not directory:
        directory = os.getcwd()
    
    if not os.path.exists(directory) or not os.path.isdir(directory):
        return []
    
    # Find files matching the pattern
    file_paths = glob.glob(os.path.join(directory, pattern))
    
    # Sort by modification time (newest first)
    file_paths.sort(key=os.path.getmtime, reverse=True)
    
    # Gather information about each file
    file_info = []
    for file_path in file_paths:
        try:
            stats = os.stat(file_path)
            file_info.append({
                "path": file_path,
                "name": os.path.basename(file_path),
                "size": stats.st_size,
                "modified": stats.st_mtime,
                "created": stats.st_ctime,
            })
        except OSError as e: # Made exception more specific
            log_error(f"Error getting file info for {file_path}: {str(e)}")
    
    return file_info


def encode_image_to_base64(image_path: str) -> Optional[str]:
    """
    Encode an image file to a base64 string.
    
    Args:
        image_path: Path to the image file
        
    Returns:
        str: Base64-encoded string or None if an error occurs
    """
    if not os.path.exists(image_path):
        log_error(f"Image file not found: {image_path}")
        return None
    
    try:
        with open(image_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
        
        # Determine the MIME type based on file extension
        file_ext = os.path.splitext(image_path)[1].lower()
        mime_type = "image/jpeg"  # Default
        
        if file_ext == ".png":
            mime_type = "image/png"
        elif file_ext in [".jpg", ".jpeg"]:
            mime_type = "image/jpeg"
        elif file_ext == ".gif":
            mime_type = "image/gif"
        elif file_ext == ".webp":
            mime_type = "image/webp"
        
        # Return as a data URL
        return f"data:{mime_type};base64,{encoded_string}"
    
    except (IOError, OSError, base64.binascii.Error) as e: # Made exception more specific
        log_error(f"Error encoding image {image_path}: {str(e)}")
        return None


def compress_log_file(log_path: str, extract_screenshots: bool = True, compression_level: int = 9) -> Dict[str, Any]:
    """
    Compress a JSON log file by extracting screenshots and applying gzip compression.
    
    Args:
        log_path: Path to the JSON log file
        extract_screenshots: Whether to extract screenshots to a separate directory
        compression_level: Gzip compression level (1-9)
        
    Returns:
        dict: Results of the compression operation
    """
    if not os.path.exists(log_path):
        return {
            "success": False,
            "error": f"File not found: {log_path}",
            "path": log_path,
        }
    
    try:
        # Read the original log file
        with open(log_path, "r", encoding="utf-8") as f:
            log_data = f.read()
        
        # Get original file size
        original_size = os.path.getsize(log_path)
        
        # Parse the JSON
        try:
            log_entries = json.loads(log_data)
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"Invalid JSON in log file: {str(e)}",
                "path": log_path,
            }
        
        # Prepare the output paths
        file_dir = os.path.dirname(log_path)
        file_base = os.path.basename(log_path)
        file_name, _ = os.path.splitext(file_base)
        
        # Create paths for output files
        compressed_path = os.path.join(file_dir, f"{file_name}_compressed.gz")
        no_screenshots_path = os.path.join(file_dir, f"{file_name}_no_screenshots.json")
        screenshot_dir = os.path.join(file_dir, f"{file_name}_screenshots_{uuid.uuid4().hex[:8]}")
        
        # Extract screenshots if requested
        screenshot_count = 0
        
        if extract_screenshots and isinstance(log_entries, list):
            # Create screenshots directory if it doesn't exist
            if not os.path.exists(screenshot_dir):
                os.makedirs(screenshot_dir)
            
            # Process each log entry
            for i, entry in enumerate(log_entries):
                # Handle request screenshots
                if isinstance(entry, dict) and "request" in entry and isinstance(entry["request"], dict):
                    req = entry["request"]
                    if "screenshot" in req and req["screenshot"] and isinstance(req["screenshot"], str):
                        screenshot_data = req["screenshot"]
                        # Check if it's a data URL
                        if screenshot_data.startswith("data:image"):
                            # Extract the base64 part
                            match = re.match(r"data:image/[^;]+;base64,(.+)", screenshot_data)
                            if match:
                                # Save the screenshot to a file
                                screenshot_path = os.path.join(screenshot_dir, f"request_{i}.jpg")
                                try:
                                    with open(screenshot_path, "wb") as f:
                                        f.write(base64.b64decode(match.group(1)))
                                    # Replace the screenshot with the file path
                                    req["screenshot"] = f"FILE:{screenshot_path}"
                                    screenshot_count += 1
                                except (IOError, OSError, base64.binascii.Error) as screenshot_error: # Made exception more specific
                                    log_error(f"Error saving screenshot: {str(screenshot_error)}")
                
                # Handle response screenshots
                if isinstance(entry, dict) and "response" in entry and isinstance(entry["response"], dict):
                    resp = entry["response"]
                    if "screenshot" in resp and resp["screenshot"] and isinstance(resp["screenshot"], str):
                        screenshot_data = resp["screenshot"]
                        # Check if it's a data URL
                        if screenshot_data.startswith("data:image"):
                            # Extract the base64 part
                            match = re.match(r"data:image/[^;]+;base64,(.+)", screenshot_data)
                            if match:
                                # Save the screenshot to a file
                                screenshot_path = os.path.join(screenshot_dir, f"response_{i}.jpg")
                                try:
                                    with open(screenshot_path, "wb") as f:
                                        f.write(base64.b64decode(match.group(1)))
                                    # Replace the screenshot with the file path
                                    resp["screenshot"] = f"FILE:{screenshot_path}"
                                    screenshot_count += 1
                                except (IOError, OSError, base64.binascii.Error) as screenshot_error: # Made exception more specific
                                    log_error(f"Error saving screenshot: {str(screenshot_error)}")
        
        # Write the modified log entries to a file
        with open(no_screenshots_path, "w", encoding="utf-8") as f:
            json.dump(log_entries, f)
        
        # Get the size of the file without screenshots
        no_screenshots_size = os.path.getsize(no_screenshots_path)
        
        # Compress the file
        with open(no_screenshots_path, "rb") as f_in:
            with gzip.open(compressed_path, "wb", compresslevel=compression_level) as f_out:
                f_out.write(f_in.read())
        
        # Get the size of the compressed file
        compressed_size = os.path.getsize(compressed_path)
        
        # Calculate compression statistics
        size_reduction_no_screenshots = ((original_size - no_screenshots_size) / original_size) * 100
        size_reduction_compressed = ((original_size - compressed_size) / original_size) * 100
        
        # Prepare the result
        result = {
            "success": True,
            "original_path": log_path,
            "no_screenshots_path": no_screenshots_path,
            "compressed_path": compressed_path,
            "screenshot_directory": screenshot_dir if extract_screenshots and screenshot_count > 0 else None,
            "original_size": original_size,
            "no_screenshots_size": no_screenshots_size,
            "compressed_size": compressed_size,
            "size_reduction_no_screenshots": f"{size_reduction_no_screenshots:.1f}%",
            "size_reduction_compressed": f"{size_reduction_compressed:.1f}%",
            "screenshot_count": screenshot_count,
            "compression_stats": {
                "success": True,
                "original_size": original_size,
                "no_screenshots_size": no_screenshots_size,
                "compressed_size": compressed_size,
                "size_reduction_no_screenshots_abs": original_size - no_screenshots_size,
                "size_reduction_compressed_abs": no_screenshots_size - compressed_size,
                "total_reduction_abs": original_size - compressed_size,
            }
        }
        
        return result
    
    except (IOError, OSError, gzip.BadGzipFile) as e: # Made exception more specific
        error_details = traceback.format_exc()
        log_error(f"Error compressing log file: {str(e)}\n{error_details}")
        
        return {
            "success": False,
            "error": str(e),
            "error_details": error_details,
            "path": log_path,
        }