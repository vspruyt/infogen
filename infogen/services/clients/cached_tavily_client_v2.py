from tavily import AsyncTavilyClient, TavilyClient
from typing import List, Dict, Optional
import psycopg2
from psycopg2.extras import Json, register_uuid
from psycopg2.pool import ThreadedConnectionPool
import uuid
from datetime import datetime
import os
import threading
from langchain.tools import StructuredTool
from .cached_embedding_client import CachedEmbeddingClient

class CachedTavilyClient:
    # Configuration constants
    CACHE_EXPIRY_MINUTES = 14400  # 10 days by default
    _instance_lock = threading.Lock()
    _connection_pools = {}  # Dictionary to store connection pools per process
    
    def __init__(self, api_key: str, db_connection_string: str, embedding_client: CachedEmbeddingClient, min_connections: int = 1, max_connections: int = 20):
        """
        Initialize the CachedTavilyClient with connection pooling support.
        
        Args:
            api_key: Tavily API key
            db_connection_string: PostgreSQL connection string
            embedding_client: CachedEmbeddingClient instance for embedding-related operations
            min_connections: Minimum number of database connections in the pool
            max_connections: Maximum number of database connections in the pool
        """
        self.tavily_client = TavilyClient(api_key=api_key)
        self.embedding_client = embedding_client
        
        # Register UUID type adapter
        register_uuid()
        
        # Create a unique key for this process's connection pool
        self._process_key = os.getpid()
        self._thread_id = threading.get_ident()
        print(f"[INIT] Initializing CachedTavilyClient for process {self._process_key}, thread {self._thread_id}")
        
        with self._instance_lock:
            if self._process_key not in self._connection_pools:
                print(f"[INIT] Creating new connection pool for process {self._process_key}")
                self._connection_pools[self._process_key] = ThreadedConnectionPool(
                    min_connections,
                    max_connections,
                    db_connection_string
                )
        
        self._db_pool = self._connection_pools[self._process_key]
        self._local = threading.local()
        self._local.connection = None
        
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        
    def close(self):
        """Close all connections and clean up resources for this process"""
        with self._instance_lock:
            if self._process_key in self._connection_pools:
                if hasattr(self._local, 'connection') and self._local.connection is not None:
                    try:
                        self._db_pool.putconn(self._local.connection)
                    except Exception:
                        pass  # Ignore errors during cleanup
                    self._local.connection = None
                
                print(f"[CLOSE] Closing connection pool for process {self._process_key}")
                try:
                    self._connection_pools[self._process_key].closeall()
                except Exception:
                    pass  # Ignore errors during cleanup
                del self._connection_pools[self._process_key]
                
    def _execute_with_connection(self, operation):
        """Execute an operation with proper connection handling"""
        thread_id = threading.get_ident()
        process_key = os.getpid()
        
        # Get a fresh connection for each operation to avoid timeout issues
        print(f"[CONN] Getting new connection for process {process_key}, thread {thread_id}")
        conn = self._db_pool.getconn()
        conn.autocommit = False
        
        try:
            cur = conn.cursor()
            try:
                result = operation(cur)
                conn.commit()
                return result
            finally:
                cur.close()
        except Exception as e:
            conn.rollback()
            raise
        finally:
            print(f"[CONN] Returning connection for process {process_key}, thread {thread_id}")
            self._db_pool.putconn(conn)
        
    def basic_search(self, query: str) -> Dict:
        """
        Perform a basic web search using Tavily with caching support.
        
        Args:
            query: The search query string
            
        Returns:
            Dict containing search results with relevant snippets
        """
        return self._execute_with_connection(lambda cur: self._basic_search_internal(cur, query))

    def _basic_search_internal(self, cur, query: str) -> Dict:
        # Get embedding for the query
        query_embedding = self.embedding_client.get_embedding(query)
        
        # Check cache using cosine similarity
        cur.execute("""
            SELECT api_response 
            FROM tavily_basic_search_cache 
            WHERE 1 - (embedding <-> %s::vector) > 0.4
                AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
            ORDER BY embedding <-> %s::vector ASC
            LIMIT 1
        """, (query_embedding, query_embedding))
        
        cache_result = cur.fetchone()
        
        if cache_result:
            print(f"[CACHE HIT] Found semantically similar cached Tavily result for query: {query}")
            return cache_result[0]
            
        # If not in cache, call API
        print(f"[API CALL] Calling Tavily API: basic search for query '{query}'")
        response = self.tavily_client.search(
            query=query, 
            search_depth="basic", 
            max_results=5,
            include_answer=False,
            include_images=False
        )
        
        # Cache the results along with the embedding
        cur.execute("""
            INSERT INTO tavily_basic_search_cache 
            (id, query, api_response, embedding, creation_date, expires_after_minutes)
            VALUES (%s, %s, %s, %s::vector, %s, %s)
            ON CONFLICT (query) DO UPDATE
            SET api_response = EXCLUDED.api_response,
                embedding = EXCLUDED.embedding,
                creation_date = EXCLUDED.creation_date,
                expires_after_minutes = EXCLUDED.expires_after_minutes
        """, (
            uuid.uuid4(),
            query,
            Json(response),
            query_embedding,
            datetime.now(),
            self.CACHE_EXPIRY_MINUTES
        ))
        return response
                
    def get_basic_search_tool(self) -> StructuredTool:
        """
        Returns a StructuredTool for use with LangGraph agents that performs a basic web search.
        
        Returns:
            StructuredTool: A tool that can be used by LangGraph agents to perform basic web searches
        """
        return StructuredTool.from_function(
            func=self.basic_search,
            name="basic_search",
            description="Use this tool to execute a simple web search using Tavily for the given search query. For each URL this tool found, it returns the most relevant snippet in the 'content' field of the 'results' section of the returned JSON."
        )

    def search(self, query: str, include_raw_content:bool=False, time_range:str=None, max_results: int = 5, exclude_domains: Optional[List[str]] = None, search_depth='advanced', **kwargs) -> List[Dict]:
        """
        Search with caching support.
        
        Args:
            query: The search query string
            include_raw_content: Whether to include raw content in results
            time_range: Time range filter for search results
            max_results: Maximum number of results to return
            exclude_domains: List of domains to exclude from search
            search_depth: Depth of search ('basic' or 'advanced')
            **kwargs: Additional arguments to pass to Tavily search
            
        Returns:
            List of dictionaries containing search results
        """
        return self._execute_with_connection(lambda cur: self._search_internal(cur, query, include_raw_content, time_range, max_results, exclude_domains, search_depth, **kwargs))

    def _search_internal(self, cur, query: str, include_raw_content: bool, time_range: str, max_results: int, exclude_domains: Optional[List[str]], search_depth: str, **kwargs) -> List[Dict]:
        # Get embedding for the query
        query_embedding = self.embedding_client.get_embedding(query)
        
        # Check cache using cosine similarity
        cur.execute("""
            SELECT api_response, max_results
            FROM tavily_search_cache 
            WHERE 1 - (embedding <-> %s::vector) > 0.4
                AND search_depth = %s
                AND max_results >= %s
                AND (time_range IS NULL AND %s IS NULL OR time_range = %s)
                AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
            ORDER BY max_results DESC, embedding <-> %s::vector ASC
            LIMIT 1
        """, (
            query_embedding, 
            search_depth,
            max_results,
            time_range, time_range,
            query_embedding
        ))
        
        cache_result = cur.fetchone()
        
        if cache_result:
            print(f"[CACHE HIT] Found semantically similar cached Tavily result for query: {query}")
            cached_response, cached_max_results = cache_result
            return cached_response['results']
            
        # If not in cache, call API
        print(f"[API CALL] Calling Tavily API: {search_depth} search for query '{query}'")
        response = self.tavily_client.search(
            query=query, 
            search_depth=search_depth, 
            max_results=max_results,
            include_raw_content=include_raw_content,
            include_answer=False,
            include_images=False,
            exclude_domains=exclude_domains,
            time_range=time_range,
            **kwargs
        )
        
        # Cache the results along with the embedding
        cur.execute("""
            INSERT INTO tavily_search_cache 
            (id, query, search_depth, max_results, include_raw_content, time_range, exclude_domains,
             api_response, embedding, creation_date, expires_after_minutes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s)
            ON CONFLICT (query, search_depth, time_range) 
            DO UPDATE
            SET api_response = EXCLUDED.api_response,
                embedding = EXCLUDED.embedding,
                max_results = EXCLUDED.max_results,
                exclude_domains = EXCLUDED.exclude_domains,
                include_raw_content = EXCLUDED.include_raw_content,
                creation_date = EXCLUDED.creation_date,
                expires_after_minutes = EXCLUDED.expires_after_minutes
        """, (
            uuid.uuid4(),
            query,
            search_depth,
            max_results,
            include_raw_content,
            time_range,
            Json(exclude_domains) if exclude_domains else None,
            Json(response),
            query_embedding,
            datetime.now(),
            self.CACHE_EXPIRY_MINUTES
        ))
        
        return response['results']

    def extract(self, urls: List[str], **kwargs) -> Dict:
        """Extract content from URLs"""
        try:
            results = self.tavily_client.extract(urls=urls, extract_depth="advanced", **kwargs)                    
                                                                                                        
            for failure in results['failed_results']:                            
                print(f"Failed to scrape {failure['url']}: {failure['error']}")
                
            return results['results']
        
        except Exception as e:            
            print(f"Error in extract: {str(e)}")
            raise

    def nearest_neighbors(self, query: str, k: int) -> List[Dict[str, any]]:
        """
        Find the k nearest neighbors in the cache based on query embedding similarity.
        
        Args:
            query: The query string to find similar matches for
            k: Number of nearest neighbors to return
            
        Returns:
            List of dictionaries containing the similar queries, their responses, and similarity scores
        """
        return self._execute_with_connection(lambda cur: self._nearest_neighbors_internal(cur, query, k))
        
    def _nearest_neighbors_internal(self, cur, query: str, k: int) -> List[Dict[str, any]]:
        # Get embedding for the query
        query_embedding = self.embedding_client.get_embedding(query)
        
        # Find k nearest neighbors using cosine similarity
        cur.execute("""
            SELECT 
                query,
                api_response,
                1 - (embedding <-> %s::vector) as similarity
            FROM tavily_basic_search_cache 
            WHERE CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
            ORDER BY embedding <-> %s::vector ASC
            LIMIT %s
        """, (query_embedding, query_embedding, k))
        
        results = []
        for row in cur.fetchall():
            results.append({
                "query": row[0],
                "response": row[1],
                "similarity": row[2]
            })
            
        if results:
            print(f"[NEIGHBORS] Found {len(results)} similar queries for: {query}")
            for r in results:
                print(f"[NEIGHBORS] Similarity {r['similarity']:.3f} for query: {r['query']}")
        else:
            print(f"[NEIGHBORS] No similar queries found for: {query}")
            
        return results

    def nearest_neighbors_advanced(self, query: str, k: int, search_depth: str = 'advanced', time_range: str = None) -> List[Dict[str, any]]:
        """
        Find the k nearest neighbors in the advanced search cache based on query embedding similarity.
        
        Args:
            query: The query string to find similar matches for
            k: Number of nearest neighbors to return
            search_depth: Filter results by search depth ('basic' or 'advanced')
            time_range: Filter results by time range
            
        Returns:
            List of dictionaries containing the similar queries, their responses, and similarity scores
        """
        return self._execute_with_connection(lambda cur: self._nearest_neighbors_advanced_internal(cur, query, k, search_depth, time_range))
        
    def _nearest_neighbors_advanced_internal(self, cur, query: str, k: int, search_depth: str, time_range: str) -> List[Dict[str, any]]:
        # Get embedding for the query
        query_embedding = self.embedding_client.get_embedding(query)
        
        # Find k nearest neighbors using cosine similarity
        cur.execute("""
            SELECT 
                query,
                search_depth,
                max_results,
                time_range,
                api_response,
                1 - (embedding <-> %s::vector) as similarity
            FROM tavily_search_cache 
            WHERE CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
                AND search_depth = %s
                AND (time_range IS NULL AND %s IS NULL OR time_range = %s)
            ORDER BY embedding <-> %s::vector ASC
            LIMIT %s
        """, (query_embedding, search_depth, time_range, time_range, query_embedding, k))
        
        results = []
        for row in cur.fetchall():
            results.append({
                "query": row[0],
                "search_depth": row[1],
                "max_results": row[2],
                "time_range": row[3],
                "response": row[4],
                "similarity": row[5]
            })
            
        if results:
            print(f"[NEIGHBORS] Found {len(results)} similar {search_depth} search queries for: {query}")
            for r in results:
                print(f"[NEIGHBORS] Similarity {r['similarity']:.3f} for query: {r['query']} (max_results={r['max_results']})")
        else:
            print(f"[NEIGHBORS] No similar {search_depth} search queries found for: {query}")
            
        return results

    