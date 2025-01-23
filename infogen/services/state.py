from typing import TypedDict, List, Union
import numpy as np

class SearchResult(TypedDict):
    title: str
    url: str
    score: float
    markdown_summary: str

class WorkflowState(TypedDict):
    original_query: str
    enhanced_query: Union[str, None]
    enhanced_query_embedding: Union[List[float], None]
    search_results: List[dict]
    infographic_content: Union[str, None]
    status: str
    error: Union[str, None]
    retry_count: int
    bad_domains: List[str]  # List of domains to exclude from search

def create_workflow_state(original_query: str, enhanced_query: Union[str, None], enhanced_query_embedding: Union[List[float], None], search_results: List[dict], infographic_content: Union[str, None], status: str, error: Union[str, None], retry_count: int, bad_domains: List[str]) -> WorkflowState:
    return {
        "original_query": original_query,
        "enhanced_query": enhanced_query,
        "enhanced_query_embedding": enhanced_query_embedding,
        "search_results": search_results,
        "infographic_content": infographic_content,
        "status": status,
        "error": error,
        "retry_count": retry_count,
        "bad_domains": bad_domains
    } 