from typing import TypedDict, List

class SearchResult(TypedDict):
    title: str
    url: str
    score: float
    markdown_summary: str

class WorkflowState(TypedDict):
    original_query: str
    enhanced_query: str | None
    search_results: List[SearchResult] | None
    infographic_content: str | None 