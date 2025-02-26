from openai import AsyncOpenAI
import os
from ..state import WorkflowState
from datetime import datetime, timezone
from langchain_core.callbacks import Callbacks
from langchain_core.messages import BaseMessage
from langchain_core.callbacks.manager import adispatch_custom_event
from ..message_types import LogLevel, ProgressPhase, WorkflowMessage

async def enhance_initial_query(state: WorkflowState) -> WorkflowState:
    """Enhance the initial query to be more specific and searchable."""
    try:

        # Logging message streamed to the user
        await adispatch_custom_event(
            "query_interpreter",
            {"message": WorkflowMessage.progress(phase=ProgressPhase.QUERY_INTERPRETATION, 
                                                 message=f"🚀 Step 1: Enhancing initial query '{state['original_query']}'",
                                                 data={"original_query": state["original_query"]})}
        )

        # Initialize state if needed
        if "bad_domains" not in state:
            state["bad_domains"] = []
            
        # Handle retry logic
        if state.get("status") == "insufficient_results":
            retry_count = state.get("retry_count", 0) + 1
            # Logging message streamed to the user
            # Logging message streamed to the user
            await adispatch_custom_event(
                "query_interpreter",
                {"message": WorkflowMessage.progress(phase=ProgressPhase.QUERY_INTERPRETATION, 
                                                    message=f"🔄 Retrying with improved query (attempt {retry_count + 1}/3)",
                                                    data={"retry": retry_count})}
            )
            state["retry_count"] = retry_count
            
            # Clear enhanced query if retrying to force a new one
            state["previous_enhanced_query"] = state.get("enhanced_query")
            state["enhanced_query"] = None
            
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        client = AsyncOpenAI(api_key=api_key)
        
        prompt = f"""I built a product that takes in a user query, and generates an infographic on that topic. The user input sometimes is very short, but under the hood I'm using an AI agent based framework that requires a clear topic or question to be researched through web search queries.

I will give you the user's search query. If that query already represents a good topic or question to be researched for an engaging infographic, then just return the input query. If not, then please turn the query into a good topic or question phrase.

In case you need it: The current date is {datetime.now(timezone.utc).strftime('%B %d, %Y')}.

{"The previous query that didn't yield good web search results was: '" + state["previous_enhanced_query"] + "', so make sure the new one is different." if state.get("previous_enhanced_query") else ""}

Here is the user query: "{state['original_query']}"."""            

        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        
        result = response.choices[0].message.content
        enhanced_query = result    
        
        # Calculate embedding for the enhanced query
        embedding_response = await client.embeddings.create(
            model="text-embedding-3-small",
            input=enhanced_query
        )
        embedding = embedding_response.data[0].embedding
        
        state["enhanced_query"] = enhanced_query
        state["enhanced_query_embedding"] = embedding
        state["status"] = "continue"        
        
        return state
        
    except Exception as e:
        state["error"] = f"Error enhancing query: {str(e)}"
        state["status"] = "error"
        await adispatch_custom_event(
                "query_interpreter",
                {"message": WorkflowMessage.log(level=LogLevel.ERROR, message=f"❌ Unexpected error while enhancing query: {str(e)}", data={"exception":e})}
            )
        return state 