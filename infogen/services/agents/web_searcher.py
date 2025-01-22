from tavily import TavilyClient
from openai import AsyncOpenAI
import os
import asyncio
from ..state import WorkflowState
from typing import List, Dict, AsyncGenerator
import tiktoken
from functools import partial

def truncate_text(text: str, max_tokens: int = 100000) -> str:
    """Truncate text to fit within token limit, trying to keep complete sentences."""
    # Initialize tokenizer
    encoding = tiktoken.encoding_for_model("gpt-4")
    
    # Get tokens for the text
    tokens = encoding.encode(text)
    
    if len(tokens) <= max_tokens:
        return text
        
    # Truncate tokens and decode
    truncated_tokens = tokens[:max_tokens]
    truncated_text = encoding.decode(truncated_tokens)
    
    # Try to end at a sentence boundary
    last_period = truncated_text.rfind('.')
    if last_period > 0:
        truncated_text = truncated_text[:last_period + 1]
    
    return truncated_text + "\n\n[Content truncated due to length...]"

async def summarize_content(client: AsyncOpenAI, query: str, result: dict) -> dict | None:
    # Get content and truncate if needed
    content = result.get('raw_content', result.get('content', 'No content available'))
    truncated_content = truncate_text(content)
    
    prompt = f"""I am researching "{query}" to create an engaging infographic. 

Here is content from a source:
Title: {result['title']}
URL: {result['url']}
Content: {truncated_content}

First, determine if this content is relevant and contains useful information for our research topic.
If it does NOT contain relevant information, respond with exactly "INVALID_CONTENT" and nothing else.
If the content IS relevant, create a structured markdown summary that includes:

# Short Summary
[Brief summary of what the document is about]

# Key Facts & Statistics
[Extract numerical data, statistics, and key factual statements]

# Main Topics/Themes
[Provide a brief summary of the key facts/conclusion of each topic, so that the info can be added to our infographic.]

# Important Details
[Extract specific details, examples, or explanations that could be visualized]

# Document Summary
[Provide a brief summary of the key facts/conclusion of each section in the document, so that the info can be added to our infographic. Don't refer back to the original document, just add the summarized content for each section of the original document here.]

Don't refer back the the original document. This Markdown document is a new document on its own, acting as a shorter version of the original.
Please be concise but specific, focusing on elements that would be valuable for creating an infographic. Include actual numbers, dates, and specific details when present."""        

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )
    
    content = response.choices[0].message.content
    
    # Check if content was invalid
    if content.strip() == "INVALID_CONTENT":
        print(f"\n⚠️  Skipping {result['url']} - No relevant content found")
        return None
        
    # If we got here, content was valid
    return {
        'title': result['title'],
        'url': result['url'],
        'score': result.get('score', 0),
        'markdown_summary': content
    }

async def execute_search(state: WorkflowState) -> AsyncGenerator[dict, None]:
    """Execute search and yield results as they become available."""
    # Get API keys
    tavily_key = os.getenv("TAVILY_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    
    if not tavily_key or not openai_key:
        raise ValueError("Missing required API keys (TAVILY_API_KEY or OPENAI_API_KEY)")
    
    # Initialize clients
    tavily_client = TavilyClient(api_key=tavily_key)
    openai_client = AsyncOpenAI(api_key=openai_key)
    
    # Signal start of web search
    print(f"\n🌐 Searching the web for: {state['enhanced_query']}")
    
    # Execute initial search with content gathering
    response = tavily_client.search(
        query=state['enhanced_query'],
        search_depth="advanced",
        max_results=5,
        include_raw_content=True,  # Get full content        
    )
    
    # Show number of results found
    results_count = len(response['results'])
    print(f"\n📊 Found {results_count} search result{'s' if results_count != 1 else ''}")
    
    # Process results in parallel
    tasks = []
    for result in response['results']:
        if result['raw_content'] is not None:
            print(f"\n🔍 Processing data from {result['url']}")
            task = asyncio.create_task(summarize_content(openai_client, state['enhanced_query'], result))
            tasks.append(task)
    
    # As each result completes, yield it
    for completed_task in asyncio.as_completed(tasks):
        try:
            result = await completed_task
            if result is not None:  # Only yield valid results
                print(f"\n✅ Finished processing: {result['url']}")
                yield result
        except Exception as e:
            print(f"\n❌ Error processing result: {str(e)}")
            continue

def process_search_results(state: WorkflowState) -> WorkflowState:
    """Process search results and update state."""
    processed_results = []
    
    # Run the async search and collect results
    async def collect_results():
        print("\nSearching and processing sources...")
        async for result in execute_search(state):
            processed_results.append(result)
            # Show running count of processed sources
            print(f"\nProcessed {len(processed_results)} source(s) so far...")
    
    # Run the async code
    asyncio.run(collect_results())
    
    # Update state with all results
    state['search_results'] = processed_results
    return state 