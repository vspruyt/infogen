from openai import OpenAI
import os
from ..state import WorkflowState

def enhance_initial_query(state: WorkflowState) -> WorkflowState:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found in environment variables")
        
    client = OpenAI(api_key=api_key)
    
    prompt = f"""I built a product that takes in a user query, and generates an infographic on that topic. The user input sometimes is very short, but under the hood I'm using an AI agent based framework that requires a clear topic or question to be researched through web search queries.

I will give you the user query. If that query already represents a good topic or question to be researched for an engaging infographic, then just return the input query. If not, then please turn the query into a good topic or question phrase.

Here is the user query: "{state['original_query']}"."""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    
    result = response.choices[0].message.content
    state['enhanced_query'] = result    
    
    return state 