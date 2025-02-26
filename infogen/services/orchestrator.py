from typing import TypedDict, List, Literal, Union, cast
from langgraph.graph import StateGraph
from dotenv import load_dotenv
import asyncio
from .agents.query_interpreter import enhance_initial_query
from .agents.web_searcher import search_web
from .state import WorkflowState
from .agents.content_editor import edit_content
from langchain_core.callbacks.manager import adispatch_custom_event
from .message_types import WorkflowMessage, MessageType, LogLevel, ProgressPhase

MAX_SEARCH_TRIES = 5

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

async def handle_error(state: WorkflowState, error: Union[Exception, str]) -> WorkflowState:
    """Handle errors in the workflow."""
    # Don't treat insufficient_results as an error
    if state.get("status") == "insufficient_results":
        return state
        
    error_msg = f"Error in workflow: {str(error)}"
    
    await adispatch_custom_event(
        "Orchestrator",
        {"message": WorkflowMessage.log(level=LogLevel.ERROR, 
        message=f"❌ {error_msg}",
        data={"exception":error})}
    )        
    
    state["error"] = error_msg
    state["status"] = "error"
    if "infographic_content" not in state or not state["infographic_content"]:
        state["infographic_content"] = "No content could be generated due to an error"
    return state

async def check_search_results(state: WorkflowState) -> WorkflowState:
    """Check if we have valid search results to continue."""
    if state.get("status") == "insufficient_results":
        retry_count = state.get("retry_count", 0)
        if retry_count < MAX_SEARCH_TRIES:
            # Keep status as insufficient_results to trigger another retry
            return state
        else:
            # If we've hit max retries, check if we have any results at all
            if not state.get("search_results"):
                state["error"] = "No valid search results found after maximum retries. Please try a different query."
                state["status"] = "error"
                return state
            else:
                # If we have some results, proceed with what we have
                await adispatch_custom_event(
                    "orchestrator",
                    {"message": WorkflowMessage.progress(phase=ProgressPhase.RESULT_CHECK, 
                                                        message=f"👉 Maximum retry attempts reached, trying to proceed with available results",
                                                        )}
                )
                state["status"] = "continue"
                return state
    elif not state.get("search_results"):
        state["error"] = "No search results found"
        state["status"] = "error"
        return state
    else:
        state["status"] = "continue"
        return state

def create_workflow_graph() -> StateGraph:
    """Creates and returns the complete workflow graph with error handling."""
    
    # Create the graph with our state type
    workflow = StateGraph(WorkflowState)
    
    # Add all processing nodes
    workflow.add_node("query_interpreter", enhance_initial_query)
    workflow.add_node("web_searcher", search_web)
    workflow.add_node("content_editor", edit_content)
    workflow.add_node("check_results", check_search_results)
    
    # Create an async wrapper for handle_error
    async def handle_error_wrapper(state: WorkflowState) -> WorkflowState:
        return await handle_error(state, "No valid search results found")
    
    workflow.add_node("handle_error", handle_error_wrapper)
    
    # Define the edges with conditional routing
    workflow.set_entry_point("query_interpreter")
    
    async def route_after_search(state: WorkflowState) -> str:
        """Route after web search."""        
        status = state.get("status")
        retry_count = state.get("retry_count", 0)
        
        if status == "error":
            return "handle_error"
        elif status == "insufficient_results":
            # Check if we've hit max retries
            if retry_count >= MAX_SEARCH_TRIES - 1:
                await adispatch_custom_event(
                    "orchestrator",
                    {"message": WorkflowMessage.progress(phase=ProgressPhase.RESULT_CHECK, 
                                                        message=f"👉 Maximum retry attempts reached, trying to proceed with available results",
                                                        )}
                )                
                state["status"] = "continue"
                return "check_results"
            return "query_interpreter"
            
        return "check_results"
    
    async def route_after_check(state: WorkflowState) -> str:
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

async def process_query(query: str):    
    """Process a query through the complete workflow. Yields progress messages and final result."""

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
        # Run the complete workflow with event streaming
        final_state = None
        
        async for event in graph.astream_events(initial_state, version="v2"):
            
            # Track the latest state
            if event["event"] == "on_chain_end":
                final_state = event["data"]["output"]
                                    
            # Handle custom events from our agents            
            elif event["event"] == "on_custom_event":            
                msg = event["data"]["message"]
                yield msg.to_dict()
                
        
        if not final_state:
            error_msg = WorkflowMessage.log(
                level=LogLevel.ERROR,
                message="No final state produced by workflow"
            ).to_dict()
            yield error_msg
            raise ValueError("No final state produced by workflow")
            
        # Yield the final results in our output format
        yield WorkflowMessage.result(
            message="Workflow completed successfully",
            data=WorkflowOutput(
                original_query=final_state["original_query"],
                enhanced_query=final_state["enhanced_query"],
                search_results=final_state.get("search_results", []),
                infographic_content=final_state.get("infographic_content", "No content generated"),
                status=final_state.get("status", "completed"),
                error=final_state.get("error"),
                retry_count=final_state.get("retry_count", 0)
            )
        ).to_dict()
    except Exception as e:
        # Handle any unexpected errors
        error_msg = WorkflowMessage.log(
            level=LogLevel.ERROR,
            message=f"Unexpected error: {str(e)}"
        ).to_dict()
        yield error_msg
        
        yield WorkflowMessage.result(
            message="Workflow failed",
            data=WorkflowOutput(
                original_query=query,
                enhanced_query=None,
                search_results=[],
                infographic_content="Error: No content could be generated",
                status="error",
                error=f"Unexpected error: {str(e)}",
                retry_count=0
            )
        ).to_dict()

