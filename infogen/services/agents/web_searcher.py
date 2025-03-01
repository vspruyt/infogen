from openai import AsyncOpenAI
import os
import asyncio
from ..state import WorkflowState
from typing import List, Dict, AsyncGenerator, Optional
import tiktoken
import json
from datetime import datetime, timezone
from ..clients.cached_tavily_client_v2 import CachedTavilyClient
from langchain_core.callbacks.manager import adispatch_custom_event
from ..message_types import LogLevel, ProgressPhase, WorkflowMessage

# Constants
MIN_REQUIRED_RESULTS = 3  # Minimum number of search results required for a valid report
MAX_TAVILY_SEARCH_RESULTS = 5 # Number of URLs to fetch from DB or web

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

async def summarize_content(client: AsyncOpenAI, enhanced_query: str, result: dict) -> dict | None:
    
    if result['score']==0:        
        return None
        
    if len(result.get('content', ''))==0:          
        return None

    # Get content and truncate if needed
    content = result.get('raw_content', result.get('content', 'No content available'))
    truncated_content = truncate_text(content)

    prompt = f"""I am researching the user query "{enhanced_query}" to create an engaging infographic. 

Here is content from a source:
Title: {result['title']}
URL: {result['url']}
Content: {truncated_content}

First, determine if this content is at least tangentially relevant to the user query and contains useful information for our research topic.
If it does NOT contain relevant information or if it is not relevant to the user query at all, respond with exactly "INVALID_CONTENT" and nothing else.
If the content IS somewhat relevant, create a structured markdown summary.

Make sure your summary doesn't become a commercial advertisement for the website! Try to extract the relevant information.

Prioritize using authoritative sources like Wikipedia (en.wikipedia.org), Britannica, government websites, and reputable news sources. Those usually contain relevant information so try to use them if you can.

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
        if len(content)<len("INVALID_CONTENT")*2 and "INVALID_CONTENT" in content.strip():                        
            return None
        else:
            await adispatch_custom_event(
                    "web_searcher",
                    {"message": WorkflowMessage.progress(phase=ProgressPhase.WEB_SEARCH, 
                                                        message=f"👉 Successfully scraped and analyzed the contents of {result['url']}",
                                                        data={"url": result['url']})}
                )
            
        # If we got here, content was valid
        return {
            'title': result['title'],
            'url': result['url'],
            'score': result.get('score', 0),
            'markdown_summary': content
        }
    except Exception as e:
        await adispatch_custom_event(
                        "web_searcher",
                        {"message": WorkflowMessage.log(level=LogLevel.ERROR, 
                        message=f"❌ Error while analyzing content: {str(e)}",
                        data={"exception":e})}
                        )        
        return None

async def calculate_expiration_days(client: AsyncOpenAI, content: str, query: str, enhanced_query: str, url: str) -> int:
    """Calculate how many days to cache the content based on its nature."""
    try:
        prompt = """The following is information from a website that I crawled. I am considering caching the result so that I don't have to crawl it again every time I need it. However, I'm not sure how many days I should cache it before the content becomes stale. 

For example, if the website is about real-time weather or news, we want to cache it for 0 days. If the website is about the history of a topic, then it's unlikely to change any time soon so we can safely cache it for 30 days, etc.

The proposed expiration should always between 0 and 30 days.

Please output only a number. Don't add the word 'days' to it or anything else. Just return a number between 0 and 30, which represents the number of days I should cache the result.

Never output any other text. If you really don't know, then just output the number 1.

Original user query: {query}
Enriched user query: {enhanced_query}
URL: {url}
Content: {content}"""

        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that determines content expiration times."},
                {"role": "user", "content": prompt.format(
                    query=query,
                    enhanced_query=enhanced_query,
                    url=url,
                    content=content
                )}
            ]
        )
        
        try:
            days = int(response.choices[0].message.content.strip())
            # Ensure the value is between 0 and 30
            return max(0, min(30, days))
        except (ValueError, TypeError):
            return 1  # Default to 1 day if we can't parse the response
            
    except Exception as e:
        await adispatch_custom_event(
                        "web_searcher",
                        {"message": WorkflowMessage.log(level=LogLevel.ERROR, 
                        message=f"❌ Error calculating expiration days: {str(e)}",
                        data={"exception":e})}
                        )        
        return 1  # Default to 1 day on error

async def handle_bad_url(url: str, state: WorkflowState, reason: str):
    """Helper function to handle bad URLs consistently"""
    try:                

        await adispatch_custom_event(
                    "web_searcher",
                    {"message": WorkflowMessage.progress(phase=ProgressPhase.WEB_SEARCH, 
                                                        message=f"👉 Skipping {url}: {reason}",
                                                        )}
                )
        
        # Add domain to bad_domains list
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        if domain and domain not in state.get("bad_domains", []):
            if "bad_domains" not in state:
                state["bad_domains"] = []
            
            state["bad_domains"].append(domain)                                
        
    except Exception as e:
        await adispatch_custom_event(
                        "web_searcher",
                        {"message": WorkflowMessage.log(level=LogLevel.ERROR, 
                        message=f"❌ Error while handling bad URL: {str(e)}",
                        data={"exception":e})}
                        )        

async def search_web(state: WorkflowState) -> WorkflowState:
    """Search the web and process results."""
    try:

        # Logging message streamed to the user
        await adispatch_custom_event(
            "web_searcher",
            {"message": WorkflowMessage.progress(phase=ProgressPhase.WEB_SEARCH, 
                                                 message=f"🚀 Step 2: Searching the web for '{state['enhanced_query']}'",
                                                 data={"enhanced_query": state["enhanced_query"]})}
        )

        tavily_key = os.getenv("TAVILY_API_KEY")
        if not tavily_key:
            state["error"] = "Missing TAVILY_API_KEY"
            state["status"] = "error"
            return state
            
        tavily_client = CachedTavilyClient(api_key=tavily_key)
        openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))                
        
        try:
            # Get bad_domains from state if available
            bad_domains = state.get('bad_domains', [])
            if bad_domains:                
                # Logging message streamed to the user
                await adispatch_custom_event(
                    "web_searcher",
                    {"message": WorkflowMessage.progress(phase=ProgressPhase.WEB_SEARCH, 
                                                        message=f"👉 Excluding previously failed domains: {bad_domains}",
                                                        data={"bad_domains": bad_domains})}
                )
            
            # First get the list of URLs without raw content
            try:
                response = await tavily_client.search(
                    query=state['original_query'],  # original query
                    min_required_results=MIN_REQUIRED_RESULTS,
                    enhanced_query=state['enhanced_query'],  # enhanced query
                    enhanced_query_embedding=state.get('enhanced_query_embedding'),  # pass the embedding
                    exclude_domains=bad_domains if bad_domains else None,
                    max_results=MAX_TAVILY_SEARCH_RESULTS,
                    search_depth="advanced"                    
                )
            except Exception as e:
                if "UsageLimitExceededError" in str(type(e)):                    
                    # Logging message streamed to the user
                    await adispatch_custom_event(
                        "web_searcher",
                        {"message": WorkflowMessage.log(level=LogLevel.ERROR, 
                                                            message=f"❌ API rate limit exceeded. Please try again later",
                                                            data={"exception":e})}
                        )
                    state["error"] = "Tavily API rate limit exceeded. Please try again later."
                    state["status"] = "error"
                    return state
                raise  # Re-raise other exceptions
            
            if not response or 'results' not in response:                
                await adispatch_custom_event(
                        "web_searcher",
                        {"message": WorkflowMessage.log(level=LogLevel.INFO, 
                                                            message=f"No results in Tavily response",
                                                            )}
                        )
                state["status"] = "insufficient_results"
                return state
            
            results_count = len(response['results'])

            await adispatch_custom_event(
                        "web_searcher",
                        {"message": WorkflowMessage.log(level=LogLevel.INFO, 
                                                            message=f"Found {results_count} URL{'s' if results_count != 1 else ''} during our search job",
                                                            )}
                        )
                        
            if results_count < MIN_REQUIRED_RESULTS:
                await adispatch_custom_event(
                    "web_searcher",
                    {"message": WorkflowMessage.progress(phase=ProgressPhase.WEB_SEARCH, 
                                                        message=f"👉 Insufficient web search results, will try to enhance query",
                                                        data={"nr_search_results": results_count})}
                )
                state["status"] = "insufficient_results"
                return state

            async def process_result(result: dict) -> Optional[dict]:
                """Process a single search result."""
                url = result.get('url')
                if not url:
                    return None

                try:
                    # Calculate expiration days
                    content = result.get('content', '')
                    expires_after_days = await calculate_expiration_days(
                        openai_client,
                        content,
                        state['original_query'],
                        state['enhanced_query'],
                        url
                    )
                    
                    await adispatch_custom_event(
                    "web_searcher",
                    {"message": WorkflowMessage.progress(phase=ProgressPhase.WEB_SEARCH, 
                                                        message=f"👉 Extracting content from {url}",
                                                        data={"url": url})}
                    )
                    
                                    
                    # Extract raw content
                    try:
                        extract_response = await tavily_client.extract(
                            urls=[url],
                            query=state['original_query'],
                            enhanced_query=state['enhanced_query'],
                            expires_after_days=expires_after_days
                        )
                    except Exception as e:
                        if "UsageLimitExceededError" in str(type(e)):
                            await adispatch_custom_event(
                                "web_searcher",
                                {"message": WorkflowMessage.log(level=LogLevel.ERROR, 
                                                                    message=f"❌ Rate limit exceeded while extracting {url}. Please try again later",
                                                                    data={"exception":e})}
                                )                            
                            return None
                        raise  # Re-raise other exceptions
                                                

                    if not isinstance(extract_response, dict) or 'results' not in extract_response:
                        await handle_bad_url(url, state, "invalid response format")
                        return None
                        
                    extracted = extract_response['results']
                    if not extracted:                        
                        await handle_bad_url(url, state, "no extract results")
                        return None
                                                      
                    content_text = extracted[0].get('raw_content')
                    if not content_text or not isinstance(content_text, str):                        
                        await handle_bad_url(url, state, "invalid content")
                        return None                                            
                                                   
                    # Process and summarize content
                    processed = await summarize_content(
                        openai_client,
                        state['enhanced_query'],
                        {
                            'title': result.get('title', ''),
                            'url': url,
                            'score': result.get('score', 0),
                            'content': content_text,
                            'expires_after_days': expires_after_days
                        }
                    )                                     
                    
                    if processed:                                                                 
                        
                        # Cache the validated content
                        try:
                            await tavily_client.update_url_cache(
                                state['original_query'],
                                state['enhanced_query'],
                                url,
                                state.get('enhanced_query_embedding'),
                                expires_after_days
                            )
                            await adispatch_custom_event(
                                "web_searcher",
                                {"message": WorkflowMessage.log(level=LogLevel.INFO, 
                                                                    message=f"Successfully cached URL {url}",
                                                                    )}
                                )                                 
                            return processed
                        except Exception as e:
                            await adispatch_custom_event(
                                "web_searcher",
                                {"message": WorkflowMessage.log(level=LogLevel.ERROR, 
                                                                    message=f"❌ Error caching URL {url}: {str(e)}",
                                                                    data={"exception":e})}
                                )
                            return None
                    else:
                        await handle_bad_url(url, state, "irrelevant content")
                        return None
                        
                except Exception as e:
                    await adispatch_custom_event(
                                "web_searcher",
                                {"message": WorkflowMessage.log(level=LogLevel.ERROR, 
                                                                    message=f"❌ Error processing URL {url}: {str(e)}",
                                                                    data={"exception":e})}
                                )                         
                    await handle_bad_url(url, state, f"processing error: {str(e)}")
                    return None
            
            # Process all results in parallel
            processed_results = await asyncio.gather(
                *[process_result(result) for result in response['results']]
            )
            
            # Filter out None results and update state
            processed_results = [r for r in processed_results if r is not None]
            state['search_results'] = processed_results
            state['status'] = 'insufficient_results' if len(processed_results) < MIN_REQUIRED_RESULTS else 'success'
            
            return state
            
        finally:
            await tavily_client.close()
            
    except Exception as e:
        await adispatch_custom_event(
            "web_searcher",
            {"message": WorkflowMessage.log(level=LogLevel.ERROR, 
                                                message=f"❌ Unexpected error while searching the web: {str(e)}",
                                                data={"exception":e})}
            )             
        state["error"] = str(e)
        state["status"] = "error"
        return state 