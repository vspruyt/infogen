from typing import TypedDict, List, Literal, Union, cast
from langgraph.graph import StateGraph
from dotenv import load_dotenv
import asyncio
from .agents.query_interpreter import enhance_initial_query
from .agents.web_searcher import process_search_results
from .state import WorkflowState
from .agents.content_editor import edit_content

MAX_SEARCH_TRIES = 3

# Load environment variables from .env file if it exists
load_dotenv()

class WorkflowOutput(TypedDict):
    original_query: str
    enhanced_query: str
    search_results: List[dict]
    infographic_content: str
    status: str
    error: Union[str, None]
    retry_count: int

def handle_error(state: WorkflowState, error: Union[Exception, str]) -> WorkflowState:
    """Handle errors in the workflow."""
    # Don't treat insufficient_results as an error
    if state.get("status") == "insufficient_results":
        return state
        
    error_msg = f"Error in workflow: {str(error)}"
    print(f"\n❌ {error_msg}")
    
    state["error"] = error_msg
    state["status"] = "error"
    return state

def check_search_results(state: WorkflowState) -> WorkflowState:
    """Check if we have valid search results to continue."""
    if state.get("status") == "insufficient_results":
        retry_count = state.get("retry_count", 0)
        if retry_count < MAX_SEARCH_TRIES:
            # Keep status as insufficient_results
            return state
        else:
            print("\n⚠️ Maximum retry attempts reached, proceeding with available results")
            state["status"] = "continue"
            return state
    elif not state.get("search_results"):
        state["error"] = "No search results found"
        state["status"] = "error"
    else:
        state["status"] = "continue"
    return state

def create_workflow_graph() -> StateGraph:
    """Creates and returns the complete workflow graph with error handling."""
    
    # Create the graph with our state type
    workflow = StateGraph(WorkflowState)
    
    # Add all processing nodes
    # Wrap query interpreter to preserve retry count
    def wrapped_query_interpreter(state: WorkflowState) -> WorkflowState:        
        
        # If we're retrying, increment the retry count
        if state.get("status") == "insufficient_results":
            retry_count = state.get("retry_count", 0) + 1
            print(f"\n🔄 Retrying with enhanced query (attempt {retry_count + 1}/{MAX_SEARCH_TRIES})")
        else:
            retry_count = 0
            
        # Create a copy of the input state to preserve all fields
        new_state = dict(state)
        
        # Clear enhanced query if retrying to force a new one
        if retry_count > 0:
            new_state["previous_enhanced_query"] = new_state.get("enhanced_query")
            new_state["enhanced_query"] = None
            
        # Ensure bad_domains exists in state
        if "bad_domains" not in new_state:
            new_state["bad_domains"] = []
            
        # Run original function with potentially cleared enhanced_query
        enhanced_state = enhance_initial_query(new_state)
        
        # Update our state copy with the enhanced query results while preserving other fields
        new_state.update(enhanced_state)
        
        # Set the retry count
        new_state["retry_count"] = retry_count
                            
        return new_state
        
    # Wrap web searcher to track state
    def wrapped_web_searcher(state: WorkflowState) -> WorkflowState:        
        
        # Ensure bad_domains exists
        if "bad_domains" not in state:
            state["bad_domains"] = []
            
        # Track the number of URLs before processing
        urls_before = len(state.get("search_results", []))
        
        # Process search results
        result = process_search_results(state)
        
        # Track the number of URLs after processing
        urls_after = len(result.get("search_results", []))
        
        # If we lost any URLs during processing, their domains were bad
        if urls_after < urls_before:
            # Get the URLs that were removed
            before_urls = {url["url"] for url in state.get("search_results", [])}
            after_urls = {url["url"] for url in result.get("search_results", [])}
            removed_urls = before_urls - after_urls
            
            # Extract and add their domains to bad_domains
            from urllib.parse import urlparse
            for url in removed_urls:
                domain = urlparse(url).netloc
                if domain and domain not in result["bad_domains"]:
                    print(f"\n⚠️ Adding {domain} to bad domains list")
                    result["bad_domains"].append(domain)
                
        return result
        
    workflow.add_node("query_interpreter", wrapped_query_interpreter)
    workflow.add_node("web_searcher", wrapped_web_searcher)
    
    # Create a synchronous wrapper for the async content editor
    def sync_edit_content(state: WorkflowState) -> WorkflowState:
        try:
            return asyncio.run(edit_content(state))
        except Exception as e:
            state["error"] = f"Error in content editor: {str(e)}"
            state["status"] = "error"
            return state
    
    workflow.add_node("content_editor", sync_edit_content)
    workflow.add_node("check_results", check_search_results)
    workflow.add_node("handle_error", lambda state: handle_error(state, Exception("Workflow error")))
    
    # Define the edges with conditional routing
    workflow.set_entry_point("query_interpreter")
    
    def route_after_search(state: WorkflowState) -> str:
        """Route after web search."""        
        status = state.get("status")
        retry_count = state.get("retry_count", 0)
        
        if status == "error":
            return "handle_error"
        elif status == "insufficient_results":
            # Check if we've hit max retries
            if retry_count >= MAX_SEARCH_TRIES - 1:
                print("\n⚠️ Maximum retry attempts reached, proceeding with available results")
                state["status"] = "continue"
                return "check_results"
            return "query_interpreter"
            
        return "check_results"
    
    def route_after_check(state: WorkflowState) -> str:
        """Route after checking search results."""
        if state.get("status") == "error":
            return "handle_error"
        return "content_editor"
    
    # Add edges with conditional routing
    workflow.add_conditional_edges(
        "query_interpreter",
        lambda s: "handle_error" if s.get("status") == "error" else "web_searcher"
    )
    
    workflow.add_conditional_edges(
        "web_searcher",
        route_after_search
    )
    
    workflow.add_conditional_edges(
        "check_results",
        route_after_check
    )
    
    workflow.add_conditional_edges(
        "content_editor",
        lambda s: "handle_error" if s.get("status") == "error" else "end"
    )
    
    # Set finish points
    workflow.add_node("end", lambda x: x)
    workflow.set_finish_point("end")
    workflow.set_finish_point("handle_error")
    
    return workflow.compile()

def process_query(query: str) -> WorkflowOutput:
    """Process a query through the complete workflow."""
    # Create the workflow graph
    graph = create_workflow_graph()
    
    # Initialize the state with retry_count and bad_domains
    initial_state = WorkflowState(
        original_query=query,
        enhanced_query=None,
        search_results=[],
        infographic_content=None,
        status="started",
        error=None,
        retry_count=0,  # Initialize retry counter
        bad_domains=[]  # Initialize bad domains list
    )
    
    try:
        # Run the complete workflow
        final_state = graph.invoke(initial_state)
        
        # Return the results in our output format
        return WorkflowOutput(
            original_query=final_state["original_query"],
            enhanced_query=final_state["enhanced_query"],
            search_results=final_state.get("search_results", []),
            infographic_content=final_state.get("infographic_content", "No content generated"),
            status=final_state.get("status", "completed"),
            error=final_state.get("error"),
            retry_count=final_state.get("retry_count", 0)  # Include retry count in output
        )
    except Exception as e:
        # Handle any unexpected errors
        return WorkflowOutput(
            original_query=query,
            enhanced_query=None,
            search_results=[],
            infographic_content="Error: No content could be generated",
            status="error",
            error=f"Unexpected error: {str(e)}",
            retry_count=0
        )

def enhance_query(query: str) -> str:
    """Helper function to just enhance a query."""
    # Create a simplified graph that only does query enhancement
    workflow = StateGraph(WorkflowState)
    workflow.add_node("query_interpreter", enhance_initial_query)
    workflow.set_entry_point("query_interpreter")
    workflow.set_finish_point("query_interpreter")
    graph = workflow.compile()
    
    # Run the query enhancement
    initial_state = WorkflowState(
        original_query=query,
        enhanced_query=None,
        search_results=[],
        infographic_content=None,
        status="started",
        error=None,
        retry_count=0  # Add retry_count to initial state
    )
    
    try:
        final_state = graph.invoke(initial_state)
        return final_state["enhanced_query"]
    except Exception as e:
        print(f"Error enhancing query: {str(e)}")
        return query  # Return original query if enhancement fails 