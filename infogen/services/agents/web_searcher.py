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
from datetime import datetime, timezone
from ..clients.cached_tavily_client import CachedTavilyClient
from langchain_core.callbacks import Callbacks
from langchain_core.messages import BaseMessage
from langchain_core.callbacks.manager import adispatch_custom_event

# Constants
MIN_REQUIRED_RESULTS = 1  # Minimum number of search results required
MAX_TAVILY_SEARCH_RESULTS = 2
MAX_CONCURRENT_REQUESTS = 5  # Adjust based on your API limits

def truncate_text(text: str, max_tokens: int = 100000) -> str:
    """Truncate text to fit within token limit, trying to keep complete sentences."""
    # Initialize tokenizer
    encoding = tiktoken.encoding_for_model("gpt-4o")
    
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
If the content IS relevant, create a structured markdown summary.

Prioritize including relevant and high-quality information, especially when containing statistics, numbers, verifiable facts, or concrete data.
In case you need it: The current date is {datetime.now(timezone.utc).strftime('%B %d, %Y')}.

The summary should be in the following Markdown format:

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
            model="gpt-4o",
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
    query: str  # original query
    enhanced_query: str  # enhanced version of the query
    enhanced_query_embedding: Union[List[float], None]  # embedding of enhanced query
    results: Annotated[list, add_messages]
    status: str
    error: str | None
    bad_domains: List[str]  # List of domains to exclude

def handle_error(error: str, state: SearchState = None) -> Dict:
    """Handle errors in the workflow"""
    return {
        "results": [],
        "error": error,
        "status": "error",
        "bad_domains": state.get("bad_domains", []) if state else []  # Preserve bad_domains if state is available
    }

async def search_node(state: SearchState):
    try:
        tavily_key = os.getenv("TAVILY_API_KEY")
        if not tavily_key:
            return handle_error("Missing TAVILY_API_KEY")
            
        tavily_client = CachedTavilyClient(api_key=tavily_key)
        print(f"\n🌐 Searching the web for: {state['enhanced_query']}")
        
        try:
            # Get bad_domains from state if available
            bad_domains = state.get('bad_domains', [])
            if bad_domains:
                print(f"\n🚫 Excluding previously failed domains: {bad_domains}")
            
            # First get the list of URLs without raw content
            response = await tavily_client.search(
                query=state['query'],  # original query
                enhanced_query=state['enhanced_query'],  # enhanced query
                enhanced_query_embedding=state.get('enhanced_query_embedding'),  # pass the embedding
                min_required_results=MIN_REQUIRED_RESULTS,
                search_depth="advanced",
                max_results=MAX_TAVILY_SEARCH_RESULTS,
                include_raw_content=False,
                exclude_domains=bad_domains if bad_domains else None,
            )
            
            # Close the client connection
            await tavily_client.close()
            
            results_count = len(response['results'])
            print(f"\n📊 Found {results_count} search result{'s' if results_count != 1 else ''}")
            
            if results_count < MIN_REQUIRED_RESULTS:
                print("\n⚠️ Insufficient search results, will try to enhance query...")
                return {
                    "results": [],
                    "status": "insufficient_results",
                    "bad_domains": bad_domains  # Preserve bad_domains in state
                }
            
            # Only format and return results if we have enough
            formatted_results = [{
                'role': 'assistant',
                'content': json.dumps({
                    'title': result.get('title', ''),
                    'url': result.get('url', ''),
                    'score': result.get('score', 0)
                })
            } for result in response['results']]
            
            return {
                "results": formatted_results,
                "status": "success",
                "bad_domains": bad_domains  # Preserve bad_domains in state
            }
        finally:
            await tavily_client.close()
            
    except Exception as e:
        return {
            "results": [],
            "error": str(e),
            "status": "error",
            "bad_domains": state.get("bad_domains", [])  # Preserve bad_domains even on error
        }

async def process_node(state: SearchState):
    try:
        openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        tavily_client = CachedTavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        
        async def handle_bad_url(url: str, state: dict, reason: str):
            """Helper function to handle bad URLs consistently"""
            try:
                # Delete from cache
                await tavily_client.delete_from_cache(url)
                
                # Add domain to bad_domains list
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
                if domain and domain not in state.get("bad_domains", []):
                    if "bad_domains" not in state:
                        state["bad_domains"] = []
                    print(f"\n⚠️ Adding {domain} to bad domains list (reason: {reason})")
                    state["bad_domains"].append(domain)
            except Exception as e:
                print(f"\n⚠️ Error handling bad URL {url}: {str(e)}")
        
        try:
            async def process_single_result(message):                
            
                async with semaphore:
                    try:
                        content = message.content if hasattr(message, 'content') else message.get('content')
                        if not content:
                            return None
                            
                        result = json.loads(content)
                        url = result.get('url')
                        if not url:
                            print(f"\n⚠️ No URL found in result")
                            return None
                        
                        print(f"\n🔍 Extracting content from {url}")
                        
                        # Extract raw content using Tavily's extract method
                        try:
                            print(f"\n🔍 Requesting content extraction for {url}")
                            response = await tavily_client.extract(
                                urls=[url],
                                query=state['query'],  # original query
                                enhanced_query=state['enhanced_query'],  # enhanced query
                            )
                            
                            if not isinstance(response, dict) or 'results' not in response:
                                print(f"\n⚠️ Invalid response format from extract API for {url}. Response: {response}")
                                await handle_bad_url(url, state, "invalid response format")
                                return None
                                
                            extracted = response['results']
                            if not extracted or len(extracted) == 0:
                                print(f"\n⚠️ No results in extract response for {url}")
                                await handle_bad_url(url, state, "no extract results")
                                return None
                                
                            content_text = extracted[0].get('raw_content')
                            if not content_text or not isinstance(content_text, str):
                                print(f"\n⚠️ No valid content in extract response for {url}. Result: {extracted[0]}")
                                await handle_bad_url(url, state, "invalid content")
                                return None
                                
                            print(f"\n✅ Successfully extracted {len(content_text)} characters from {url}")
                            
                        except Exception as e:
                            print(f"\n⚠️ Failed to extract content from {url}. Error: {str(e)}")
                            print(f"Error type: {type(e)}")
                            await handle_bad_url(url, state, f"extraction error: {str(e)}")
                            return None
                        
                        print(f"\n📝 Processing content from {url}")
                        
                        processed = await summarize_content(
                            openai_client, 
                            state['enhanced_query'],  # Use enhanced query for summarization
                            {
                                'title': result.get('title', ''),
                                'url': url,
                                'score': result.get('score', 0),
                                'content': content_text
                            }
                        )
                        
                        if processed:  # Only return if we got valid processed content
                            print(f"\n✅ Finished processing: {url}")
                            return {
                                'role': 'assistant',
                                'content': json.dumps(processed)
                            }
                        
                        # Content was not relevant
                        await handle_bad_url(url, state, "irrelevant content")
                        return None
                            
                    except Exception as e:
                        print(f"\n⚠️ Error processing result: {str(e)}")
                        if url:
                            await handle_bad_url(url, state, f"processing error: {str(e)}")
                        return None
                
                return None
            
            results = await asyncio.gather(
                *[process_single_result(message) for message in state['results']]
            )
            
            # Filter out None results
            processed_results = [r for r in results if r is not None]
            
            # Get the bad_domains list that was potentially modified during processing
            bad_domains = state.get("bad_domains", [])
            
            return {
                "results": processed_results, 
                "status": "insufficient_results" if len(processed_results) < MIN_REQUIRED_RESULTS else "success",
                "bad_domains": bad_domains  # Preserve the bad_domains list
            }
        finally:
            await tavily_client.close()
            
    except Exception as e:
        print(f"\n❌ Error in process_node: {str(e)}")
        return {
            "results": [],
            "error": str(e),
            "status": "error",
            "bad_domains": state.get("bad_domains", [])  # Preserve bad_domains even on error
        }

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
    
    # Initialize state with existing bad_domains
    bad_domains = state.get("bad_domains", [])
    
    inputs = {
        "query": state.get('original_query', ''),  # original query
        "enhanced_query": state.get('enhanced_query', state.get('original_query', '')),  # enhanced query, fallback to original
        "enhanced_query_embedding": state.get('enhanced_query_embedding'),  # pass the embedding
        "results": [],
        "status": "start",
        "error": None,
        "bad_domains": bad_domains
    }
    
    try:
        state['search_results'] = []  # Initialize search results list
        async for event in app.astream(inputs):
            if event.get("error"):
                print(f"\n❌ Error: {event['error']}")
                state["error"] = event["error"]
                state["status"] = "error"
                if "bad_domains" in event:
                    state["bad_domains"] = event["bad_domains"]
                return
            
            # Check for insufficient results status
            if event.get("status") == "insufficient_results":
                state["status"] = "insufficient_results"
                # Update bad_domains if event has them
                if "bad_domains" in event:
                    state["bad_domains"] = event["bad_domains"]
                return
                
            if "results" in event:
                # Update bad_domains if event has them
                if "bad_domains" in event:
                    state["bad_domains"] = event["bad_domains"]
                for result in event["results"]:
                    try:
                        # Get content from message object
                        content = result.content if hasattr(result, 'content') else result.get('content')
                        if not content:
                            continue
                            
                        # Parse JSON string back to dict
                        content_dict = json.loads(content)
                        
                        # Only process results that have already been processed and have a markdown summary
                        if isinstance(content_dict, dict) and 'markdown_summary' in content_dict:
                            state['search_results'].append(content_dict)  # Update state
                            yield content_dict  # Yield the result
                            
                    except json.JSONDecodeError:
                        print(f"\n⚠️ Failed to parse result content")
                        continue
                    except Exception as e:
                        print(f"\n⚠️ Error processing result: {str(e)}")
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
            "query": state.get('original_query', ''),  # original query
            "enhanced_query": state.get('enhanced_query', state.get('original_query', '')),  # enhanced query, fallback to original
            "enhanced_query_embedding": state.get('enhanced_query_embedding'),  # pass the embedding
            "results": [],
            "status": "start",
            "error": None,
            "retry_count": retry_count,
            "bad_domains": state.get("bad_domains", [])  # Pass bad_domains to inner workflow
        }
        
        try:
            event = None
            async for event in app.astream(inputs):
                if event.get("error"):
                    state["error"] = event["error"]
                    state["status"] = "error"
                    state["bad_domains"] = event.get("bad_domains", [])  # Preserve bad_domains
                    return state
                
                if event.get("status") == "insufficient_results":
                    state["status"] = "insufficient_results"
                    state["retry_count"] = retry_count
                    if "bad_domains" in event:  # Only update if event has bad_domains
                        state["bad_domains"] = event["bad_domains"]
                    return state
                
                if "results" in event:
                    # Update bad_domains from event if it exists
                    if "bad_domains" in event:
                        state["bad_domains"] = event["bad_domains"]
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

async def process_search_results(state: WorkflowState) -> WorkflowState:
    """Process search results and update state."""
    try:
        result = await process_search_results_async(state)
        
        # Emit custom event showing number of URLs processed
        num_urls = len(result.get("search_results", []))
        await adispatch_custom_event(
            "url_count",
            {"message": f"--->> Processed {num_urls} URLs"}
        )
            
        return result
    except Exception as e:
        state["error"] = f"Error processing search results: {str(e)}"
        state["status"] = "error"
        return state 