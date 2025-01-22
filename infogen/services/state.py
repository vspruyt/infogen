from typing import TypedDict, List, Union

class SearchResult(TypedDict):
    title: str
    url: str
    score: float
    markdown_summary: str

class WorkflowState(TypedDict):
    original_query: str
    enhanced_query: Union[str, None]
    search_results: List[dict]
    infographic_content: Union[str, None]
    status: str
    error: Union[str, None]
    retry_count: int 