from tavily import TavilyClient
from openai import AsyncOpenAI
import os
import asyncio
from ..state import WorkflowState
from typing import List, Dict, AsyncGenerator, Annotated, TypedDict, Literal, Union
import tiktoken
from functools import partial
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
import json

# Constants
MIN_REQUIRED_RESULTS = 1  # Minimum number of search results required
MAX_TAVILY_SEARCH_RESULTS = 2
MAX_CONCURRENT_REQUESTS = 5  # Adjust based on your API limits

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

    try:
        response = await client.chat.completions.create(
            model="gpt-4",  # Fixed typo in model name
            messages=[
                {"role": "system", "content": "You are a helpful research assistant that summarizes content for infographics."},
                {"role": "user", "content": prompt}
            ]
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
    except Exception as e:
        print(f"\n❌ Error in summarize_content: {str(e)}")
        return None

class SearchState(TypedDict):
    query: str
    results: Annotated[list, add_messages]
    status: str
    error: str | None

def handle_error(error: str) -> Dict:
    """Handle errors in the workflow"""
    return {
        "results": [],
        "error": error,
        "status": "error"
    }

async def search_node(state: SearchState):
    try:
        tavily_key = os.getenv("TAVILY_API_KEY")
        if not tavily_key:
            return handle_error("Missing TAVILY_API_KEY")
            
        tavily_client = TavilyClient(api_key=tavily_key)
        print(f"\n🌐 Searching the web for: {state['query']}")
        
        response = tavily_client.search(
            query=state['query'],
            search_depth="advanced",
            max_results=MAX_TAVILY_SEARCH_RESULTS,
            include_raw_content=True,
        )
        
        results_count = len(response['results'])
        print(f"\n📊 Found {results_count} search result{'s' if results_count != 1 else ''}")
        
        if results_count < MIN_REQUIRED_RESULTS:
            print("\n⚠️ Insufficient search results, will try to enhance query...")
            return {
                "results": [],
                "status": "insufficient_results"
            }
        
        # Only format and return results if we have enough
        formatted_results = [{
            'role': 'assistant',
            'content': json.dumps({
                'title': result.get('title', ''),
                'url': result.get('url', ''),
                'raw_content': result.get('raw_content', ''),
                'content': result.get('content', '')
            })
        } for result in response['results']]
        
        return {
            "results": formatted_results,
            "status": "success"
        }
        
    except Exception as e:
        return handle_error(str(e))

async def process_node(state: SearchState):
    try:
        openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        
        async def process_single_result(message):
            async with semaphore:
                try:
                    content = message.content if hasattr(message, 'content') else message.get('content')
                    if not content:
                        return None
                        
                    result = json.loads(content)
                    content_text = result.get('raw_content') or result.get('content')
                    if not content_text or not isinstance(content_text, str):
                        print(f"\n⚠️ No valid content found for {result.get('url', 'unknown URL')}")
                        return None
                    
                    print(f"\n🔍 Processing data from {result.get('url', 'unknown URL')}")
                    
                    processed = await summarize_content(
                        openai_client, 
                        state['query'], 
                        {
                            'title': result.get('title', ''),
                            'url': result.get('url', ''),
                            'content': content_text
                        }
                    )
                    
                    if processed:  # Only return if we got valid processed content
                        print(f"\n✅ Finished processing: {result.get('url', 'unknown URL')}")
                        return {
                            'role': 'assistant',
                            'content': json.dumps(processed)
                        }
                    return None  # Return None if processing didn't yield valid content
                        
                except Exception as e:
                    print(f"\n⚠️ Error processing result: {str(e)}")
                    return None
            
            return None
        
        results = await asyncio.gather(
            *[process_single_result(message) for message in state['results']]
        )
        
        # Filter out None results
        processed_results = [r for r in results if r is not None]
        
        return {
            "results": processed_results, 
            "status": "insufficient_results" if len(processed_results) < MIN_REQUIRED_RESULTS else "success"
        }
    except Exception as e:
        print(f"\n❌ Error in process_node: {str(e)}")
        return handle_error(str(e))

def should_continue(state: SearchState) -> str:
    """Route to next node based on state."""
    if state.get("error") or state.get("status") == "error":
        return "end"
    if state.get("status") == "insufficient_results":
        return "end"  # Return to orchestrator for retry
    return "process"

# Define the workflow
workflow = StateGraph(SearchState)

# Add nodes
workflow.add_node("search", search_node)
workflow.add_node("process", process_node)

# Add edges
workflow.add_edge(START, "search")
workflow.add_edge("process", END)

# Add conditional edge routes
workflow.add_conditional_edges(
    "search",
    should_continue,
    {
        "process": "process",
        "end": END
    }
)

# Compile the graph
app = workflow.compile()

async def execute_search(state: WorkflowState) -> AsyncGenerator[dict, None]:
    """Execute search and yield results as they become available."""
    
    inputs = {
        "query": state.get('enhanced_query', state.get('original_query', '')),
        "results": [],
        "status": "start",
        "error": None
    }
    
    try:
        event = None
        async for event in app.astream(inputs):
            if event.get("error"):
                print(f"\n❌ Error: {event['error']}")
                state["error"] = event["error"]
                state["status"] = "error"
                return
            
            # Check for insufficient results status
            if event.get("status") == "insufficient_results":
                state["status"] = "insufficient_results"
                return
                
            if "results" in event:
                for result in event["results"]:
                    try:
                        # Get content from message object
                        content = result.content if hasattr(result, 'content') else result.get('content')
                        if not content:
                            continue
                            
                        # Parse JSON string back to dict
                        content_dict = json.loads(content)
                        
                        if isinstance(content_dict, dict):
                            if 'markdown_summary' in content_dict:
                                yield content_dict
                            else:
                                # Ensure we have either raw_content or content
                                content_text = content_dict.get('raw_content') or content_dict.get('content')
                                if content_text and isinstance(content_text, str):
                                    try:
                                        processed = await summarize_content(
                                            AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY")),
                                            state.get('enhanced_query', state.get('original_query', '')),
                                            {
                                                'title': content_dict.get('title', ''),
                                                'url': content_dict.get('url', ''),
                                                'content': content_text
                                            }
                                        )
                                        if processed:
                                            yield processed
                                    except Exception as e:
                                        print(f"\n⚠️ Error processing content: {str(e)}")
                                        continue
                                
                    except json.JSONDecodeError:
                        print(f"\n⚠️ Failed to parse result content")
                        continue
                    except Exception as e:
                        print(f"\n⚠️ Error processing result: {str(e)}")
                        continue
        
        if event and "results" in event:
            # Store only valid results with markdown summaries
            state['search_results'] = []
            for r in event["results"]:
                try:
                    content = r.content if hasattr(r, 'content') else r.get('content')
                    if not content:
                        continue
                        
                    content_dict = json.loads(content)
                    if isinstance(content_dict, dict) and 'markdown_summary' in content_dict:
                        # Only add results that have a markdown summary (meaning they were successfully processed)
                        state['search_results'].append(content_dict)
                except Exception:
                    continue
            
    except Exception as e:
        print(f"\n❌ Error in execute_search: {str(e)}")
        state["error"] = str(e)
        state["status"] = "error"

async def process_search_results_async(state: WorkflowState) -> WorkflowState:
    """Async version of process_search_results."""
    try:
        processed_results = {}  # Use dict to ensure uniqueness by URL
        retry_count = state.get("retry_count", 0)
        
        print("\nSearching and processing sources...")
        inputs = {
            "query": state.get('enhanced_query', state.get('original_query', '')),
            "results": [],
            "status": "start",
            "error": None,
            "retry_count": retry_count
        }
        
        try:
            event = None
            async for event in app.astream(inputs):
                if event.get("error"):
                    state["error"] = event["error"]
                    state["status"] = "error"
                    return state
                
                if event.get("status") == "insufficient_results":
                    state["status"] = "insufficient_results"
                    state["retry_count"] = retry_count
                    return state
                
                if "results" in event:
                    for result in event["results"]:
                        try:
                            content = result.content if hasattr(result, 'content') else result.get('content')
                            if not content:
                                continue
                                
                            content_dict = json.loads(content)
                            
                            if isinstance(content_dict, dict):
                                url = content_dict.get('url')
                                if url:  # Only add if we have a URL
                                    if 'markdown_summary' in content_dict:
                                        processed_results[url] = content_dict
                                    elif content_dict.get('raw_content') or content_dict.get('content'):
                                        processed_results[url] = content_dict
                        except Exception as e:
                            print(f"\n⚠️ Error processing result: {str(e)}")
                            continue
            
            # Store unique results in state
            state['search_results'] = list(processed_results.values())
            state['status'] = 'continue'
            return state
            
        except Exception as e:
            print(f"\n❌ Error in execute_search: {str(e)}")
            state["error"] = str(e)
            state["status"] = "error"
            return state
            
    except Exception as e:
        state["error"] = f"Error processing search results: {str(e)}"
        state["status"] = "error"
        return state

def process_search_results(state: WorkflowState) -> WorkflowState:
    """Process search results and update state."""
    return asyncio.run(process_search_results_async(state)) 