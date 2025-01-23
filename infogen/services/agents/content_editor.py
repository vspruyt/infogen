from openai import AsyncOpenAI
import os
from ..state import WorkflowState
from typing import List
import asyncio
from datetime import datetime, timezone
from langchain_core.callbacks import Callbacks
from langchain_core.messages import BaseMessage
from langchain_core.callbacks.manager import adispatch_custom_event

def format_research_report(search_results: List[dict]) -> str:
    """Format search results into a research report."""
    # Handle empty or None search results
    if not search_results:
        return "No search results available."
    
    report = []
    
    for i, result in enumerate(search_results, 1):
        # Only include results that have content
        if result.get('markdown_summary'):
            report.append(f"## Document {i}: {result['title']}")
            report.append(f"Source: {result['url']}\n")
            report.append(result['markdown_summary'])
            report.append("\n---\n")
    
    # If no valid results were found
    if not report:
        return "No valid search results available."
        
    return "\n".join(report)

async def edit_content(state: WorkflowState) -> WorkflowState:
    """Process search results into infographic content."""
    try:
        # Emit custom event showing we're starting content generation
        await adispatch_custom_event(
            "content_start",
            {"message": "--->> Starting infographic content generation"}
        )
            
        # Get unique search results by URL to avoid duplicates
        unique_results = {}
        for result in state.get('search_results', []):
            if isinstance(result, dict):
                url = result.get('url')
                if url and url not in unique_results:
                    unique_results[url] = result

        search_results = list(unique_results.values())
        print(f"\nSearch results in content editor: {len(search_results)}")
        
        if not search_results:
            state["error"] = "No valid search results to process"
            state["status"] = "error"
            return state
            
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        # Format the research report
        research_report = format_research_report(search_results)
        
        # Print debug info
        print(f"\nFormatted research report length: {len(research_report)}")
        if len(research_report) < 100:  # If report is suspiciously short
            print(f"Research report content: {research_report}")
        
        prompt = f"""#### Instructions ####
You are an experienced desk researcher tasked with preparing content for a visually stunning infographic. The infographic will be created by designers based on your output and the research report below. 

*Your output must be in Markdown format and adhere to the detailed specifications provided.*

In case you need it: The current date is {datetime.now(timezone.utc).strftime('%B %d, %Y')}.

---

### Infographic Content Specification

#### Objective
Prepare engaging, thought-provoking, and accurate content for a 1-4 page infographic. The infographic must:
- Be informative, visually appealing, and suitable for web display, PDF, and physical print.
- Contain real, sourced data for all statistics and information.
- Include references for every data point and section.
- Don't specify which visual elements (e.g. charts, maps, etc.) to be used. That will be decided later by the designer.
- Be concise and don't use too much text. Prefer numbers, tables, facts that can be visualized in charts over continuous text.

#### Structure
The infographic will include:
1. **Header**: Title
2. **Sections**: Multiple sections, each covering a key aspect of the topic, with sources/references listed at the end of each section.
3. **Footer**: List of all sources/references used.

#### Guidelines

1. **Content Requirements**
   - Provide complete, accurate text and data, ready for direct use in the infographic.
   - Prioritize including relevant and high-quality information, especially when containing statistics, numbers, verifiable facts, or concrete data.
   - Do not use placeholders or fake data. If data is unavailable, omit the section.
   - Use Markdown tables where appropriate for listing data.
   - Summarize or combine relevant information from the research report; include only what is necessary for clarity and impact.
   - Focus on the content, not on the visuals or design. Don't include Visual Instruction or guidelines, that will be done later by the designer.
   - You can include a small paragraph of continuous text in the sections if that helps (e.g. a small intro paragraph in the first section). 
   - Prefer lists, tables, numbers, statistics, categories, etc. over continuous text.

2. **Format**
   - Use valid Markdown.
   - Separate sections with `[//]: # "Section Nr"`. Example:
     `[//]: # "Header"`, `[//]: # "Section 1"`, `[//]: # "Section 2"`, `[//]: # "Footer"`. (Don't use the section title, instead use the section number!).
   - Provide detailed instructions for visual elements. For example:
     - Instead of "show a chart about security," write: 
       "Include a bar chart showing hacking attempts per year: {{2019: 120, 2020: 150, 2021: 180}}."

3. **Reminder**
   - No placeholders, fake data, or vague descriptions.
   - Ensure clarity and precision; the designer will use your output verbatim.
   - If data visualization is needed, specify the exact type and data (e.g., tables, charts, or lists).

### Research Report

{research_report}"""

        print("\n📝 Editing content for infographic...")
        
        client = AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user", 
                "content": prompt  # prompt remains the same
            }]
        )
        
        content = response.choices[0].message.content
        state['infographic_content'] = content
        state['status'] = 'continue'
        return state
        
    except Exception as e:
        state["error"] = f"Error editing content: {str(e)}"
        state["status"] = "error"
        return state 