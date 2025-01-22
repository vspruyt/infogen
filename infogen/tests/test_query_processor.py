import sys
import os
from pathlib import Path
import asyncio

# Add the project root to Python path
project_root = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, project_root)

from infogen.services.orchestrator import run_workflow

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

async def main():
    # Test queries
    test_queries = [
        "dogs",
    ]
    
    print("\n🔍 Testing Research Workflow\n")
    for query in test_queries:
        try:
            print(f"Original Query: \033[1m{query}\033[0m")
            
            prev_result_count = 0
            async for output in run_workflow(query):
                # Show enhanced query when available
                if output.enhanced_query and not hasattr(main, 'shown_query'):
                    print(f"\nEnhanced Query: \033[1;32m{output.enhanced_query}\033[0m")
                    main.shown_query = True
                
                # Show status messages
                for message in output.status_messages:
                    print(message)
                
                # Show new results
                if len(output.search_results) > prev_result_count:
                    for result in output.search_results[prev_result_count:]:
                        print_markdown_result(result)
                    prev_result_count = len(output.search_results)
                
                # Show infographic content when available
                if output.infographic_content and not hasattr(main, 'shown_content'):
                    print_infographic_content(output.infographic_content)
                    main.shown_content = True
                
        except Exception as e:
            print(f"\n\033[1;31mError processing query '{query}': {str(e)}\033[0m")

if __name__ == "__main__":
    asyncio.run(main()) 