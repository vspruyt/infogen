import sys
import os
from pathlib import Path
import asyncio
from typing import Any, Dict

# Add the project root to Python path
project_root = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, project_root)

from infogen.services.orchestrator import process_query
from infogen.services.message_types import MessageType, LogLevel, ProgressPhase

# ANSI color codes
COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "italic": "\033[3m",
    "cyan": "\033[36m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "red": "\033[31m",
    "green": "\033[32m",
    "magenta": "\033[35m"
}

def print_separator(char="=", length=80):
    print(f"\n{char * length}\n")

def format_markdown(text: str):
    """Format markdown text with nice terminal colors and formatting."""
    print_separator("-")
    
    # Print the markdown with formatting
    lines = text.split('\n')
    for line in lines:
        if line.startswith('# '):  # Main headers
            print(f"\n{COLORS['yellow']}{COLORS['bold']}{line[2:]}{COLORS['reset']}")
        elif line.startswith('## '):  # Sub headers
            print(f"\n{COLORS['blue']}{COLORS['bold']}{line[3:]}{COLORS['reset']}")
        elif line.startswith('- '):  # List items
            print(f"{COLORS['reset']}  •{line[1:]}")
        else:
            print(f"{COLORS['reset']}{line}")
    
    print_separator("-")

def format_message(msg: Dict[str, Any]) -> str:
    """Format a workflow message with appropriate colors and structure."""
    msg_type = msg["type"]
    subtype = msg["subtype"]
    message = msg["message"]
    
    if msg_type == MessageType.LOG:
        if subtype == LogLevel.ERROR:
            return f"{COLORS['red']}❌ {message}{COLORS['reset']}"
        elif subtype == LogLevel.WARNING:
            return f"{COLORS['yellow']}⚠️  {message}{COLORS['reset']}"
        elif subtype == LogLevel.DEBUG:
            return f"{COLORS['dim']}🔍 {message}{COLORS['reset']}"
        else:  # INFO
            return f"{COLORS['reset']}ℹ️  {message}"
            
    elif msg_type == MessageType.PROGRESS:
        phase_colors = {
            ProgressPhase.QUERY_INTERPRETATION: COLORS['cyan'],
            ProgressPhase.WEB_SEARCH: COLORS['blue'],
            ProgressPhase.CONTENT_EDITING: COLORS['green'],
            ProgressPhase.RESULT_CHECK: COLORS['magenta']
        }
        color = phase_colors.get(subtype, COLORS['reset'])
        return f"{color}[{subtype}] {message}{COLORS['reset']}"
        
    return message  # Default case

async def test_workflow():
    print("\n🔍 Testing Research Workflow\n")
    
    # Test query
    query = "dogs"
    
    # Process the query and handle streaming output
    final_result = None
    async for event in process_query(query):
        if event["type"] in [MessageType.LOG, MessageType.PROGRESS]:
            print(format_message(event)+"\n")            
        elif event["type"] == MessageType.RESULT:
            final_result = event["data"]
    
    if not final_result:
        print(f"{COLORS['red']}❌ Error: No result received{COLORS['reset']}")
        return
    
    # Check for errors
    if final_result['status'] == "error":
        print(f"\n{COLORS['red']}❌ Error: {final_result['error']}{COLORS['reset']}")
        if final_result['infographic_content']:
            print("\nPartial Infographic Content:")
            format_markdown(final_result['infographic_content'])
        return
    
    # print(f"\nSearch Results: {len(final_result['search_results'])} found")
    
    # # Print each search result with nice formatting
    # for i, result_item in enumerate(final_result['search_results'], 1):
    #     print(f"\nResult {i}:")
    #     print(f"{COLORS['cyan']}{COLORS['bold']}{result_item['title']}{COLORS['reset']}")
    #     print(f"{COLORS['italic']}{result_item['url']}{COLORS['reset']}")
    #     if 'markdown_summary' in result_item:
    #         format_markdown(result_item['markdown_summary'])
    
    print("\nInfographic Content:")
    format_markdown(final_result['infographic_content'])

if __name__ == "__main__":
    asyncio.run(test_workflow()) 