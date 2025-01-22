from typing import TypedDict, List, Literal, Union, cast
from langgraph.graph import StateGraph
from dotenv import load_dotenv
import asyncio
from .agents.query_interpreter import enhance_initial_query
from .agents.web_searcher import process_search_results
from .state import WorkflowState
from .agents.content_editor import edit_content

MAX_SEARCH_RETRIES = 0

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
        if retry_count < MAX_SEARCH_RETRIES:
            print(f"\n🔄 Not enough results, attempt {retry_count + 1}/3")
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
    workflow.add_node("query_interpreter", enhance_initial_query)
    workflow.add_node("web_searcher", process_search_results)
    
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
    
    def route_based_on_status(state: WorkflowState) -> str:
        """Route after query interpretation."""
        status = state.get("status")
        
        if status == "error":
            return "handle_error"
        return "web_searcher"
    
    def route_after_search(state: WorkflowState) -> str:
        """Route after web search."""
        status = state.get("status")
        retry_count = state.get("retry_count", 0)  # Get current retry count
        
        if status == "error":
            return "handle_error"
        elif status == "insufficient_results":
            if retry_count >= 2:
                print("\n⚠️ Maximum retry attempts reached, proceeding with available results")
                state["status"] = "continue"
                return "check_results"
                
            # Increment retry count and reset enhanced query
            retry_count += 1  # Increment counter
            state["retry_count"] = retry_count  # Store back in state
            state["enhanced_query"] = None
            print(f"\n🔄 Retrying with enhanced query (attempt {retry_count}/3)")
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
        route_based_on_status
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
    
    # Initialize the state with retry_count
    initial_state = WorkflowState(
        original_query=query,
        enhanced_query=None,
        search_results=[],
        infographic_content=None,
        status="started",
        error=None,
        retry_count=0  # Initialize retry counter
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