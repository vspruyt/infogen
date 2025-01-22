from typing import TypedDict, List, AsyncGenerator
from langgraph.graph import StateGraph
from dotenv import load_dotenv
from .agents.query_interpreter import enhance_initial_query
from .agents.web_searcher import execute_search, process_search_results
from .state import WorkflowState
import asyncio
from .agents.content_editor import edit_content

# Load environment variables from .env file if it exists
load_dotenv()

class WorkflowOutput:
    def __init__(self):
        self.enhanced_query = None
        self.search_results = []
        self.status_messages = []
        self.infographic_content = None

    def add_status(self, message: str):
        self.status_messages.append(message)

async def run_workflow(query: str) -> AsyncGenerator[WorkflowOutput, None]:
    """Runs the complete workflow, yielding updates as they happen."""
    output = WorkflowOutput()
    
    # Initialize workflow state with empty list for search_results
    state = WorkflowState(
        original_query=query,
        enhanced_query=None,
        search_results=[],
        infographic_content=None
    )
    
    # First enhance the query
    workflow = StateGraph(WorkflowState)
    workflow.add_node("query_interpreter", enhance_initial_query)
    workflow.set_entry_point("query_interpreter")
    workflow.set_finish_point("query_interpreter")
    graph = workflow.compile()
    
    enhanced_state = graph.invoke(state)
    output.enhanced_query = enhanced_state["enhanced_query"]
    yield output
    
    # Update state with enhanced query
    state = enhanced_state
    
    # Signal start of web search before we begin
    output.add_status("Starting web search...")
    yield output
    output.status_messages.clear()  # Clear the message so it's not repeated
    
    # Run the web search and processing
    async def process_results():
        async for result in execute_search(state):
            # Update both output and state search results
            output.search_results.append(result)
            state["search_results"].append(result)
            yield output
    
    async for update in process_results():
        yield update
    
    output.add_status("Search complete")
    yield output
    
    # Now edit the content
    output.add_status("\nPreparing infographic content...")
    yield output
    
    # Print debug info
    print(f"\nNumber of search results before content editing: {len(state['search_results'])}")
    
    state = await edit_content(state)
    output.infographic_content = state['infographic_content']
    
    output.add_status("Content preparation complete")
    yield output

def create_workflow_graph() -> StateGraph:
    """Creates the complete workflow graph."""
    workflow = StateGraph(WorkflowState)
    
    # Add the processing nodes
    workflow.add_node("query_interpreter", enhance_initial_query)
    workflow.add_node("web_searcher", process_search_results)
    workflow.add_node("content_editor", edit_content)
    
    # Define the edges - sequential flow
    workflow.set_entry_point("query_interpreter")
    workflow.add_edge("query_interpreter", "web_searcher")
    workflow.add_edge("web_searcher", "content_editor")
    workflow.set_finish_point("content_editor")
    
    return workflow.compile()

def enhance_query(query: str) -> str:
    """Helper function to just enhance a query."""
    graph = create_workflow_graph()
    initial_state = WorkflowState(
        original_query=query,
        enhanced_query=None,
        search_results=None
    )
    final_state = graph.invoke(initial_state)
    return final_state["enhanced_query"]

def process_search_query(query: str) -> dict:
    """Process the complete workflow."""
    # Create the graph
    graph = create_workflow_graph()
    
    # Initialize the state with empty list for search_results
    initial_state = WorkflowState(
        original_query=query,
        enhanced_query=None,
        search_results=[],  # Initialize as empty list instead of None
        infographic_content=None
    )
    
    # Run the graph
    final_state = graph.invoke(initial_state)
    
    return {
        "original_query": final_state["original_query"],
        "enhanced_query": final_state["enhanced_query"],
        "search_results": final_state["search_results"],
        "infographic_content": final_state["infographic_content"]
    } 