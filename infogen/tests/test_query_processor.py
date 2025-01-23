import sys
import os
from pathlib import Path
import asyncio

# Add the project root to Python path
project_root = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, project_root)

from infogen.services.orchestrator import process_query

def print_separator(char="=", length=80):
    print(f"\n{char * length}\n")

def print_markdown_result(result: dict):
    print("\n--- Result ---")  # Add clear separation
    # Print title and URL
    print(f"\033[1;36m{result['title']}\033[0m")
    print(f"\033[3m{result['url']}\033[0m")
    print_separator("-")
    
    # Print the markdown summary with some formatting
    summary_lines = result['markdown_summary'].split('\n')
    for line in summary_lines:
        if line.startswith('# '):  # Main headers
            print(f"\n\033[1;33m{line[2:]}\033[0m")  # Yellow, bold
        elif line.startswith('## '):  # Sub headers
            print(f"\n\033[1;34m{line[3:]}\033[0m")  # Blue, bold
        elif line.startswith('- '):  # List items
            print(f"\033[0m  •{line[1:]}")  # Normal color, bullet point
        else:
            print(f"\033[0m{line}")  # Normal color
    
    print_separator()

def print_infographic_content(content: str):
    print("\n=== Infographic Content ===\n")
    print(content)
    print("\n=========================\n")

async def test_workflow():
    print("\n🔍 Testing Research Workflow\n")
    
    # Test query
    query = "dogs"
    
    # Process the query
    result = await process_query(query)
    
    # Print results
    print(f"Original Query: {result['original_query']}")
    print(f"Enhanced Query: {result['enhanced_query']}")
    
    # Check for errors
    if result['status'] == "error":
        print(f"\n❌ Error: {result['error']}")
        if result['infographic_content']:
            print("\nPartial Infographic Content:")
            print(result['infographic_content'])
        return
    
    print(f"\nSearch Results: {len(result['search_results'])} found")
    
    # Print each search result
    for i, result_item in enumerate(result['search_results'], 1):
        print(f"\nResult {i}:")
        print(f"Title: {result_item['title']}")
        print(f"URL: {result_item['url']}")
    
    print("\nInfographic Content:")
    print(result['infographic_content'])

if __name__ == "__main__":
    asyncio.run(test_workflow()) 