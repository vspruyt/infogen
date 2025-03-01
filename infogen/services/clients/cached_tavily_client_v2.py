from tavily import AsyncTavilyClient, TavilyClient
from typing import List, Dict, Optional, Any, Literal, TypedDict, Annotated
import psycopg2
from psycopg2.extras import Json, register_uuid
from psycopg2.pool import ThreadedConnectionPool
import uuid
import datetime
import os
import threading
from langchain.tools import StructuredTool
from .cached_embedding_client import CachedEmbeddingClient
from infogen.core.logging_config import get_logger
import json

# Configure logging
logger = get_logger(__name__)

class CachedTavilyClient:
    # Configuration constants
    CACHE_EXPIRY_MINUTES = 14400  # 10 days by default
    _instance_lock = threading.Lock()
    _connection_pools = {}  # Dictionary to store connection pools per process
    
    def __init__(self, api_key: str, db_connection_string: str, embedding_client: CachedEmbeddingClient, 
                 llm: Any,
                 min_connections: int = 1, max_connections: int = 20):
        """
        Initialize the CachedTavilyClient with connection pooling support.
        
        Args:
            api_key: Tavily API key
            db_connection_string: PostgreSQL connection string
            embedding_client: CachedEmbeddingClient instance for embedding-related operations
            llm: Language model to use for determining cache duration
            min_connections: Minimum number of database connections in the pool
            max_connections: Maximum number of database connections in the pool
        """
        self.tavily_client = TavilyClient(api_key=api_key)
        self.embedding_client = embedding_client
        
        # Initialize the LLM for cache duration determination
        self.llm = llm
        
        # Register UUID type adapter
        register_uuid()
        
        # Create a unique key for this process's connection pool
        self._process_key = os.getpid()
        self._thread_id = threading.get_ident()
        logger.info(f"[INIT] Initializing CachedTavilyClient for process {self._process_key}, thread {self._thread_id}")
        
        with self._instance_lock:
            if self._process_key not in self._connection_pools:
                logger.info(f"[INIT] Creating new connection pool for process {self._process_key}")
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
                    except Exception as e:
                        logger.error(f"Error returning connection during close: {str(e)}")
                    self._local.connection = None
                
                logger.info(f"[CLOSE] Closing connection pool for process {self._process_key}")
                try:
                    self._connection_pools[self._process_key].closeall()
                except Exception as e:
                    logger.error(f"Error closing connection pool: {str(e)}")
                del self._connection_pools[self._process_key]
                
    def _execute_with_connection(self, operation):
        """Execute an operation with proper connection handling"""
        thread_id = threading.get_ident()
        process_key = os.getpid()
        
        # Get a fresh connection for each operation to avoid timeout issues
        logger.debug(f"[CONN] Getting new connection for process {process_key}, thread {thread_id}")
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
            logger.error(f"Database operation error: {str(e)}")
            conn.rollback()
            raise
        finally:
            logger.debug(f"[CONN] Returning connection for process {process_key}, thread {thread_id}")
            self._db_pool.putconn(conn)
        
    def basic_search(self, query: str) -> Dict:
        """
        Perform a basic web search using Tavily with caching support.
        
        Args:
            query: The search query string
            
        Returns:
            Dict containing search results with relevant snippets
        """
        logger.info(f"Performing basic search for query: '{query}'")
        return self._execute_with_connection(lambda cur: self._basic_search_internal(cur, query))

    def _basic_search_internal(self, cur, query: str) -> Dict:
        # Get embedding for the query
        query_embedding = self.embedding_client.get_embedding(query)
        
        # Get dynamic cache expiry duration based on query content
        search_params = self._get_search_cache_duration(query, query_embedding)
        cache_duration = search_params['cache_duration_minutes']
        time_range = search_params['time_range']
    
        # Check cache using cosine similarity
        cur.execute("""
            SELECT api_response 
            FROM tavily_basic_search_cache 
            WHERE 1 - (embedding <-> %s::vector) > 0.4
                AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
                    AND (time_range IS NULL AND %s IS NULL OR time_range = %s)
            ORDER BY embedding <-> %s::vector ASC
            LIMIT 1
        """, (query_embedding, time_range, time_range, query_embedding))
        
        cache_result = cur.fetchone()
        
        if cache_result:
            logger.info(f"[CACHE HIT] Found semantically similar cached Tavily result for query: {query}")
            return cache_result[0]
            
        # If not in cache, call API
        logger.info(f"[API CALL] Calling Tavily API: basic search for query '{query}' with time_range parameter: {time_range}")        
        try:

            response = self.tavily_client.search(
                query=query, 
                search_depth="basic", 
                max_results=5,
                include_answer=False,
                include_images=False,
                time_range=time_range
            )
            
            logger.info(f"[CACHE DURATION] Setting cache expiry for query '{query}' to {cache_duration} minutes")
            
            # Cache the results along with the embedding
            logger.debug("Caching search results in database")
            cur.execute("""
                INSERT INTO tavily_basic_search_cache 
                (id, query, time_range, api_response, embedding, creation_date, expires_after_minutes)
                VALUES (%s, %s, %s, %s, %s::vector, %s, %s)
                ON CONFLICT (query, time_range) DO UPDATE
                SET api_response = EXCLUDED.api_response,
                    embedding = EXCLUDED.embedding,
                    creation_date = EXCLUDED.creation_date,
                    expires_after_minutes = EXCLUDED.expires_after_minutes
            """, (
                uuid.uuid4(),
                query,
                time_range,
                Json(response),
                query_embedding,
                datetime.datetime.now(),
                cache_duration
            ))
            return response
        except Exception as e:
            logger.error(f"Error calling Tavily API for basic search: {str(e)}")
            raise
                
    def get_basic_search_tool(self) -> StructuredTool:
        """
        Returns a StructuredTool for use with LangGraph agents that performs a basic web search.
        
        Returns:
            StructuredTool: A tool that can be used by LangGraph agents to perform basic web searches
        """
        logger.debug("Creating basic search tool for LangGraph agents")
        return StructuredTool.from_function(
            func=self.basic_search,
            name="basic_search",
            description="Use this tool to execute a simple web search using Tavily for the given search query. For each URL this tool found, it returns the most relevant snippet in the 'content' field of the 'results' section of the returned JSON."
        )

    def search(self, query: str, include_raw_content:bool=False, max_results: int = 5, exclude_domains: Optional[List[str]] = None, search_depth='advanced', **kwargs) -> List[Dict]:
        """
        Search with caching support.
        
        Args:
            query: The search query string
            include_raw_content: Whether to include raw content in results            
            max_results: Maximum number of results to return
            exclude_domains: List of domains to exclude from search
            search_depth: Depth of search ('basic' or 'advanced')
            **kwargs: Additional arguments to pass to Tavily search
            
        Returns:
            List of dictionaries containing search results
        """
        logger.info(f"Performing {search_depth} search for query: '{query}', max_results: {max_results}")
        return self._execute_with_connection(lambda cur: self._search_internal(cur, query, include_raw_content, max_results, exclude_domains, search_depth, **kwargs))

    def _search_internal(self, cur, query, include_raw_content=False, max_results=None, exclude_domains=None, search_depth="basic", **kwargs):
        """
        Internal method to search using Tavily API with caching.
        
        Args:
            cur: Database cursor
            query: Search query
            include_raw_content: Whether to include raw content in the response            
            max_results: Maximum number of results to return
            exclude_domains: List of domains to exclude from the search
            search_depth: Depth of the search ("basic" or "advanced")
            **kwargs: Additional arguments to pass to the Tavily API
            
        Returns:
            List of search results
        """
        # Get embedding for the query
        query_embedding = self.embedding_client.get_embedding(query)
        
        search_params = self._get_search_cache_duration(query, query_embedding)
        cache_duration = search_params['cache_duration_minutes']
        time_range = search_params['time_range']
        
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
        
        if cache_result and len(cache_result) == 2:
            logger.info(f"[CACHE HIT] Found semantically similar cached Tavily result for query: {query}")
            cached_response, cached_max_results = cache_result
            # No need to parse JSON as PostgreSQL JSONB is automatically converted to Python dict
            return cached_response['results']
            
        # If not in cache, call API
        logger.info(f"[API CALL] Calling Tavily API: {search_depth} search for query '{query}'")
        try:
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
            
            # Cache the result
            self._cache_search_result(cur, query, query_embedding, response, max_results, search_depth, time_range, cache_duration, include_raw_content, exclude_domains)
            
            return response["results"]
        except Exception as e:
            logger.error(f"Error calling Tavily API for {search_depth} search: {str(e)}")
            raise ValueError(f"Error calling Tavily API for {search_depth} search: {str(e)}")

    def _cache_search_result(self, cur, query, query_embedding, response, max_results, search_depth, time_range, cache_duration, include_raw_content, exclude_domains):
        """Cache the search result in the database."""
        # Determine the appropriate expiration time based on time_range or query content
        if time_range == "day":
            # For day-specific queries, cache for 1 day
            expires_after_minutes = 1440  # 1 day in minutes
            logger.debug(f"Setting cache expiry to {expires_after_minutes} minutes due to time_range='day'")
        elif time_range == "week":
            # For week-specific queries, cache for 1 week
            expires_after_minutes = 10080  # 1 week in minutes
            logger.debug(f"Setting cache expiry to {expires_after_minutes} minutes due to time_range='week'")
        else:            # For None, "month", "year", or any other value, use the dynamic cache duration            
            logger.info(f"[CACHE DURATION] Setting cache expiry for query '{query}' to {cache_duration} minutes")
            expires_after_minutes = cache_duration
            logger.debug(f"Using calculated cache expiry of {expires_after_minutes} minutes")
        
        # Cache the results along with the embedding
        logger.debug("Caching search results in database")
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
            datetime.datetime.now(),
            expires_after_minutes
        ))

    def extract(self, urls: List[str], **kwargs) -> Dict:
        """
        Extract content from URLs with caching support.
        
        Args:
            urls: List of URLs to extract content from
            **kwargs: Additional arguments to pass to Tavily extract
            
        Returns:
            Dict containing extracted content from URLs
        """
        logger.info(f"Extracting content from {len(urls)} URLs")
        return self._execute_with_connection(lambda cur: self._extract_internal(cur, urls, **kwargs))

    def _extract_internal(self, cur, urls: List[str], **kwargs) -> Dict:
        results = {'results': [], 'failed_results': []}
        urls_to_fetch = []
        
        # Check cache for each URL
        for url in urls:
            cur.execute("""
                SELECT api_response
                FROM tavily_extract_cache
                WHERE url = %s
                    AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
                LIMIT 1
            """, (url,))
            
            cache_result = cur.fetchone()
            
            if cache_result:
                logger.info(f"[CACHE HIT] Found cached Tavily extract result for URL: {url}")
                results['results'].append(cache_result[0])
            else:
                logger.debug(f"[CACHE MISS] No cached extract for URL: {url}")
                urls_to_fetch.append(url)
        
        if urls_to_fetch:
            # Call API for uncached URLs
            logger.info(f"[API CALL] Calling Tavily API: extract for {len(urls_to_fetch)} URLs")
            try:
                api_results = self.tavily_client.extract(urls=urls_to_fetch, extract_depth="advanced", **kwargs)
                
                # Cache successful results
                for result in api_results['results']:
                    url = result['url']
                    # Use the default cache expiry for URL extracts
                    logger.info(f"[CACHE DURATION] Setting cache expiry for URL '{url}' to {self.CACHE_EXPIRY_MINUTES} minutes (default)")
                    
                    logger.debug(f"Caching extract result for URL: {url}")
                    cur.execute("""
                        INSERT INTO tavily_extract_cache 
                        (id, url, api_response, creation_date, expires_after_minutes)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (url) DO UPDATE
                        SET api_response = EXCLUDED.api_response,
                            creation_date = EXCLUDED.creation_date,
                            expires_after_minutes = EXCLUDED.expires_after_minutes
                    """, (
                        uuid.uuid4(),
                        url,
                        Json(result),
                        datetime.datetime.now(),
                        self.CACHE_EXPIRY_MINUTES
                    ))
                
                results['results'].extend(api_results['results'])
                results['failed_results'].extend(api_results['failed_results'])
                
                for failure in api_results['failed_results']:
                    logger.warning(f"Failed to scrape {failure['url']}: {failure['error']}")
                    
            except Exception as e:
                logger.error(f"Error in extract API call: {str(e)}")
                raise
        
        return results['results']

    def nearest_neighbors(self, query: str, k: int) -> List[Dict[str, any]]:
        """
        Find the k nearest neighbors in the cache based on query embedding similarity.
        
        Args:
            query: The query string to find similar matches for
            k: Number of nearest neighbors to return
            
        Returns:
            List of dictionaries containing the similar queries, their responses, and similarity scores
        """
        logger.info(f"Finding {k} nearest neighbors for query: '{query}'")
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
            logger.info(f"[NEIGHBORS] Found {len(results)} similar queries for: {query}")
            for i, r in enumerate(results):
                logger.debug(f"[NEIGHBORS] #{i+1}: Similarity {r['similarity']:.3f} for query: {r['query']}")
        else:
            logger.warning(f"[NEIGHBORS] No similar queries found for: {query}")
            
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
        logger.info(f"Finding {k} nearest neighbors for {search_depth} search query: '{query}', time_range: {time_range}")
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
            logger.info(f"[NEIGHBORS] Found {len(results)} similar {search_depth} search queries for: {query}")
            for i, r in enumerate(results):
                logger.debug(f"[NEIGHBORS] #{i+1}: Similarity {r['similarity']:.3f} for query: {r['query']} (max_results={r['max_results']})")
        else:
            logger.warning(f"[NEIGHBORS] No similar {search_depth} search queries found for: {query}")
            
        return results

    def _get_search_cache_duration(self, query, query_embedding=None):    
        """
        Determine appropriate cache duration and time range filter for a search query.
        
        This method first checks if there's a semantically similar query in the cache.
        If found, it returns the cached parameters. Otherwise, it uses an LLM to analyze
        the query and determine appropriate caching parameters, then stores the result
        in the cache for future use.
        
        Args:
            query: The search query string
            query_embedding: Optional pre-computed embedding for the query
            
        Returns:
            Dict containing time_range and cache_duration_minutes
        """
        # Get embedding for the query if not provided
        if query_embedding is None:
            query_embedding = self.embedding_client.get_embedding(query)
        
        # Check if we have a cached result for a similar query
        # This is executed within a database connection context
        def check_cache(cur):
            cur.execute("""
                SELECT time_range, cache_duration_minutes 
                FROM search_cache_duration 
                WHERE 1 - (embedding <-> %s::vector) > 0.4
                    AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
                ORDER BY embedding <-> %s::vector ASC
                LIMIT 1
            """, (query_embedding, query_embedding))
            
            cache_result = cur.fetchone()
            
            if cache_result:
                logger.info(f"[CACHE HIT] Found semantically similar cached search cache duration for query: {query}")
                return {"time_range": cache_result[0], "cache_duration_minutes": cache_result[1]}
            
            return None
        
        # Try to get result from cache
        cached_result = self._execute_with_connection(check_cache)
        if cached_result:
            logger.info(f"[CACHE HIT] Using cached search parameters for query '{query}': time_range={cached_result['time_range']}, cache_duration={cached_result['cache_duration_minutes']} minutes")
            return cached_result
            
        # If not in cache, use LLM to determine cache duration
        logger.info(f"[CACHE MISS] No cached search parameters found for query: '{query}', calling LLM")
        
        prompt = f"""I built a product that takes in a user search query and performs a web search for that topic phrase. The result of that web search is cached in a postgresql table for a number of minutes of my chosing.
        The amount of time we want to cache the results depends on what we're searching for. For example, if we are searching for something that is independent of time, we might want to cache for several months. But if we're searching for something that is only valid of a specific amount of time, we only want to cache for a little while.
        I need you to output the number of minutes we should cache the result of the search query. If you don't know or you can't make a good guess, then just output 1440 which represents the number of minutes in 1 day.
        Never output a number higher than 131400, which represents the number of minutes in 3 months.

        The web search API I'm using is Tavily, which also takes a time_range parameter as additional input. Valid values for time_range are:
        - None: If no time range filter is needed.
        - day, week, month, year if a time range filter is needed to filter the results to only contain data from the past day/week/month/year.
        
        So apart from the cache duration, I also want you to tell me what time_range filter to use. Be conservative because we'd rather get too much data than too little.
        So make sure the filter is broad enough. Examples:
        - if the user asks for news reports the past 4 days, then the filter should be 'week'. (because 'day' is too short)
        - if the user asks for product price changes this quarter, the filter should be 'year' (because 'month' is too short)
        - if the user asks for the the current weather, the filter should be 'day'
        - if the user asks for info on something that happened this quarter, the filter should be 'year'
        - if the user asks for something in the past 2 years, the filter should be 'none'
        - etc.

        Try to understand the user's intent and how that should be reflected by the search. 
        For example, if the user is looking for '2025 top movies', then even though it says 2025, we don't want to filter on 'year' because there are likely interesting search results from the time before those movies were released.
        On the other hand, if the user is looking for 'movie reviews written in 2025', then we do want to filter on 'year' because the user doesn't want older results.
        
        Sometimes you will have to use the current date and time to calculate the number of minutes.

        ################
        Examples:
        - Query: "Event timeline of WW3"
        - Output: {{"time_range": None, "cache_duration_minutes": 131400}}
        - Reason: 
            - time_range: A historic event like WW3 is well documented throughout time, and we don't want to restrict ourselves to only the most recent point of views on this topic, so we use None as the time range.
            - cache_duration_minutes: A historic event like WW3 is well documented, and that documentation isn't expected to change frequently, so we can cache it for a long time.

        - Query: "Main themes in the 2024 movie Trap"        
        - Context: "The current date and time is 2025-03-01T11:59:55.576288+00:00"
        - Output: {{"time_range": None, "cache_duration_minutes": 14400}}
        - Reason: 
            - time_range: When finding generic information about a movie, we don't want to restrict ourselves to a specific time frame.
            - cache_duration_minutes: When searching for a movie, we will likely want to capture the IMDB rating for the user. That score changes over time, so we can't cache the result for many months.

        - Query: "Climate change"
        - Output: {{"time_range": None, "cache_duration_minutes": 131400}}        
        - Reason:
            - time_range: When finding generic information about a topic like climate change, we don't want to restrict ourselves to a specific time frame.
            - cache_duration_minutes: When searching for a broad topic like climate change, the results will be valid for a long time so we can cache for many months.
        

        - Query: "Today's weather"
        - Context: "The current date and time is 2025-03-01T11:59:55.576288+00:00"
        - Output: {{"time_range": "day", "cache_duration_minutes": 720}}
        - Reason: 
            - time_range: When we're searching for information that happened today, like today's weather, we can limit the time_range to "day".
            - cache_duration_minutes: Given the current date and time, we calculate how many minutes until the next day so that the user can get fresh results when rerunning this query the next day.
        
        - Query: "Latest news"
        - Context: "The current date and time is 2025-03-01T08:23:45.562211+00:00"        
        - Output: {{"time_range": "week", "cache_duration_minutes": 360}}
        - Reason: 
            - time_range: The user intent when searching for something like 'latest news' is usually to find information in the past week or so, so we set time_range to "week".
            - cache_duration_minutes: The latest news changes frequently, so we don't want to cache it longer than a few hours.

        - Query: "Last month's stock price for company X"
        - Context: "The current date and time is 2025-03-01T12:05:12.610879+00:00"        
        - Reason: Last months stock price is relative to the current month, so we can cache until the end of the month, making sure the user gets fresh results when rerunning this query next month.

        - Query: "Current NVIDIA stock price"
        - Context: "The current date and time is 2025-03-01T12:05:12.610879+00:00"        
        - Output: {{"time_range": "month", "cache_duration_minutes": 60}}
        - Reason: 
            - time_range: The user is asking for the current stock price, but might be interested in how it changed over the recent weeks, so we set time_range to "month"
            - cache_duration_minutes: The user is asking for the current stock price. Stock prices fluctuate constantly, so any result wouldn't be valid for longer than an hour or so.

        - Query: "NVIDIA stock price"
        - Context: "The current date and time is 2025-03-01T12:05:12.610879+00:00"        
        - Output: {{"time_range": None, "cache_duration_minutes": 60}}
        - Reason: 
            - time_range: The user is asking for a stock price but didn't specify if they mean the 'current' stock price so they might be interested in the historic prices too. We set time_range to None.
            - cache_duration_minutes: The user is asking for the stock price. Stock prices fluctuate constantly, so any result wouldn't be valid for longer than an hour or so.

        - Query: "Tips to work from home"
        - Context: "The current date and time is 2025-03-01T12:05:12.610879+00:00"        
        - Output: {{"time_range": None, "cache_duration_minutes": 60}}
        - Reason: 
            - time_range: The user is asking about a generic topic for which we will find interesting search results throughout time, so we set time_range to None.
            - cache_duration_minutes: The user is asking a generic question the answer of which doesn't change over time, so we can safely cache for a long time.

        - Query: "Nike competitors"
        - Context: "The current date and time is 2025-03-01T12:05:12.610879+00:00"
        - Output: {{"time_range": None, "cache_duration_minutes": 131400}}
        - Reason: 
            - time_range: The user is asking about a generic topic for which we will find interesting search results throughout time, so we set time_range to None.
            - cache_duration_minutes: The main competitors of a company are unlikely to quickly change, so we can safely cache for a long time.

        - Query: "Bitcoin price prediction for 2025"        
        - Output: {{"time_range": "month", "cache_duration_minutes": 43800}}
        - Reason: 
            - time_range: The user is looking for bitcoin price predictions, but is probably most interested in the most recent predictions, so we set time_range to "month".
            - cache_duration_minutes: The price prediction for a full year of an asset like Bitcoin doesn't constantly change, but also isn't valid for many months, so we can safely cache for about a month.

        - Query: "Who won the 2024 US presidential election?"
        - Context: "The current date and time is 2025-03-01T12:05:12.610879+00:00"        
        - Output: {{"time_range": None, "cache_duration_minutes": 131400}}
        - Reason: 
            - time_range: We don't need to specificy a time_range filter here because we're not dealing with a very recent event and want to make sure we find all relevant results.
            - cache_duration_minutes: Given the current date and time, the 2024 presidential elections happened months ago. That means the results are stable and won't change anymore, so we can safely cache for a long time.

        - Query: "Best programming languages to learn in 2025"
        - Context: "The current date and time is 2025-03-01T12:05:12.610879+00:00"
        - Output: {{"time_range": "year", "cache_duration_minutes": 131400}}
        - Reason: 
            - time_range: The user is asking for information about 2025, so given the current date we assume we'll find content about that in the last 12 months and set time_range to "year".
            - cache_duration_minutes: Although the user specifies a year (2025), the question is generic and the answer to the question is unlikely to change within a few months, so we can cache for a long time.

        - Query: "Apple Q4 earnings report 2024"
        - Context: "The current date and time is 2025-03-01T12:05:12.610879+00:00"        
        - Output: {{"time_range": "year", "cache_duration_minutes": 131400}}
        - Reason: 
            - time_range: The user is explicitely asking for information about something that happened in the past few months, so we set time_range to "year". 
            - cache_duration_minutes: Q4 2024 is over, and the earnings report is available given we're months later now. So the results stay valid for a very long time.

        - Query: "Best Michelin-star restaurants in Paris 2025"
        - Output: {{"time_range": "year", "cache_duration_minutes": 131400}}
        - Reason: 
            - time_range: The user is asking for information about 2025, so given the current date we assume we'll find content about that in the last 12 months and set time_range to "year".
            - cache_duration_minutes: The list of top rated restaurants doesn't change frequently so can be cached safely for several months

        - Query: "GDP growth rate of the United States in 2022"        
        - Output: {{"time_range": None, "cache_duration_minutes": 131400}}
        - Reason: 
            - time_range: The user is asking about information from years ago, so we set time_range to None.
            - cache_duration_minutes: The date provided by the user is months in the past, so the GDP growth rate for that date is known and won't change anymore, so we can safely cache for a long time.

        - Query: "Latest GDP numbers for Germany"
        - Output: {{"time_range": "year", "cache_duration_minutes": 131400}}
        - Reason: 
            - time_range: Although the user is looking for the 'latest' information, GDP numbers are often released only once per year. So we set time_range to "year".
            - cache_duration_minutes: As GDP numbers are published very infrequently, it's safe to cache them for a few months.
        
        - Query: "Recent advancements in AI research"
        - Output: 43800
        - Output: {{"time_range": "year", "cache_duration_minutes": 43800}}
        - Reason: 
            - time_range: The user is asking for 'recent' advancements. If we would set the time_range to month that might be too restrictive, but None would include everything, so we set time_range to "year".
            - cache_duration_minutes: Although the user asks for 'recent advancements', when searching for something like AI research, the user means 'months' or 'weeks' with 'recent', so we can safely cache for several weeks.

        - Query: "Vincent Spruyt"
        - Output: 43800
        - Output: {{"time_range": None, "cache_duration_minutes": 43800}}
        - Reason: 
            - time_range: When searching information about a person, the user is likely interested in all information we can find so we set time_range to None.
            - cache_duration_minutes: When searching information about a person, we can assume that the information doesn't change rapidly over time, so we can cache for a long time.            
        
        ################
        
        The current date and time for you to use in your calculation is {datetime.datetime.now(datetime.UTC).isoformat()}.
        The user's search query is '{query}'.        

        Not caching long enough is expensive, because we have to pay for every web search.
        But caching for too long is expensive too because our users will stop paying for our app if we don't provide up to date results.
        Use the current date and time information that I have provided above, to interpret the user's query and to make a decision.
        
        Think step by step about this question and make sure you have a valid reason why you decide to cache for a specific number of minutes and why you would potentially restrict the search to a specific time_range.
        Now output the your response in the correct JSON format. ONLY output the JSON, nothing else."""
    
        messages = [            
            ("human", prompt),
        ]

        class SearchParameters(TypedDict):
            """Represents search filters for a web search."""
            time_range: Annotated[Literal["day", "week", "month", "year", None], 
                                  "A time range filter for the web search, where None means that we don't restrict the time range during the search"]
            cache_duration_minutes: Annotated[int, "The number of minutes we want to cache the search result"]


        result = self.llm.with_structured_output(SearchParameters).invoke(messages)        

        if result["time_range"]:
           if result["time_range"] not in ["day", "week", "month", "year"] :
               result["time_range"] = None

        # Cache the result for future use
        def cache_result(cur):
            logger.info(f"[CACHE STORE] Storing search parameters for query '{query}': time_range={result['time_range']}, cache_duration={result['cache_duration_minutes']} minutes")
            cur.execute("""
                INSERT INTO search_cache_duration 
                (id, query, embedding, time_range, cache_duration_minutes, creation_date, expires_after_minutes)
                VALUES (%s, %s, %s::vector, %s, %s, %s, %s)
                ON CONFLICT (query) DO UPDATE
                SET embedding = EXCLUDED.embedding,
                    time_range = EXCLUDED.time_range,
                    cache_duration_minutes = EXCLUDED.cache_duration_minutes,
                    creation_date = EXCLUDED.creation_date,
                    expires_after_minutes = EXCLUDED.expires_after_minutes
            """, (
                uuid.uuid4(),
                query,
                query_embedding,
                result["time_range"],
                result["cache_duration_minutes"],
                datetime.datetime.now(),
                self.CACHE_EXPIRY_MINUTES
            ))
        
        # Store the result in cache
        self._execute_with_connection(cache_result)
        
        return result