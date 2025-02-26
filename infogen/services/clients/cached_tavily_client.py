import asyncio
from datetime import datetime, timedelta, timezone
import asyncpg
from tavily import AsyncTavilyClient, TavilyClient
from typing import List, Dict, Optional
import traceback
from urllib.parse import urlparse
from langchain_core.callbacks.manager import adispatch_custom_event
from ..message_types import LogLevel, ProgressPhase, WorkflowMessage

class CachedTavilyClient:
    def __init__(self, api_key: str):
        self.tavily_client = AsyncTavilyClient(api_key=api_key)
        self.pool = None
        
    async def _get_db_pool(self) -> asyncpg.Pool:
        """Lazy initialization of the connection pool"""
        try:
            if self.pool is None:                
                self.pool = await asyncpg.create_pool(
                    user='postgres',
                    password='localtest',
                    database='postgres',
                    host='localhost',
                    port=5432
                )
                await adispatch_custom_event(
                        "web_searcher",
                        {"message": WorkflowMessage.log(level=LogLevel.INFO, 
                        message=f"Database connection established",)}
                        )
            return self.pool
        except Exception as e:
            await adispatch_custom_event(
                        "web_searcher",
                        {"message": WorkflowMessage.log(level=LogLevel.ERROR, 
                        message=f"❌ Database connection error: {str(e)}",
                        data={"exception":e})}
                        )                                
            raise
        
    async def _get_cached_urls(self, query: str, enhanced_query: Optional[str] = None, enhanced_query_embedding: Optional[List[float]] = None, max_results: int = 5) -> List[Dict]:
        """Get cached URLs for a query if they exist and are not stale"""
        try:
            pool = await self._get_db_pool()            
            
            async with pool.acquire() as conn:                

                # Convert embedding list to PostgreSQL vector format if it exists
                embedding_vector = None
                if enhanced_query_embedding:
                    # Format to match pgvector's expected format exactly: [1,2,3]
                    vector_values = ','.join(str(x) for x in enhanced_query_embedding)
                    embedding_vector = f'[{vector_values}]'
                    
                sql = """
                    SELECT DISTINCT on (url_cache.url)
                    url_cache.url, 1-(url_cache.enhanced_query_embedding <-> $1::vector) cosine_similarity
                    FROM url_cache                     
                    WHERE 1-(url_cache.enhanced_query_embedding <-> $1::vector) >= 0.2                    
                    AND CURRENT_TIMESTAMP < url_cache.created_at + (url_cache.expires_after_days * interval '1 day')
                    ORDER BY url_cache.url, cosine_similarity DESC
                    LIMIT $2
                """
                
                rows = await conn.fetch(sql, embedding_vector, max_results)
                                

                await adispatch_custom_event(
                        "web_searcher",
                        {"message": WorkflowMessage.log(level=LogLevel.INFO, 
                                                            message=f"Found {len(rows)} cached URL results for query {enhanced_query or query}",
                                )}
                        )
                    
                return [{'url': row['url']} for row in rows]
        except Exception as e:
            await adispatch_custom_event(
                        "web_searcher",
                        {"message": WorkflowMessage.log(level=LogLevel.ERROR, 
                        message=f"❌ Error fetching cached URLs: {str(e)}",
                        data={"exception":e})}
                        )                     
            raise

    async def update_url_cache(self, query: str, enhanced_query: Optional[str], url: str, enhanced_query_embedding: Optional[List[float]] = None, expires_after_days: int = 30):
        """Update the URL cache table with new search results"""
        pool = await self._get_db_pool()
        async with pool.acquire() as conn:
            embedding_vector = None
            if enhanced_query_embedding:
                vector_values = ','.join(str(x) for x in enhanced_query_embedding)
                embedding_vector = f'[{vector_values}]'
            
            sql = """
                INSERT INTO url_cache (query, enhanced_query, url, enhanced_query_embedding, expires_after_days, created_at, last_updated)
                VALUES ($1, $2, $3, $4::vector, $5, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT DO NOTHING
            """
            await conn.execute(sql, query, enhanced_query, url, embedding_vector, expires_after_days)

    async def update_content_cache(self, url: str, raw_content: str, expires_after_days: int = 30):
        """Update the content cache table with new content"""
        pool = await self._get_db_pool()
        async with pool.acquire() as conn:
            sql = """
                INSERT INTO content_cache (url, raw_content, expires_after_days, created_at, last_updated)
                VALUES ($1, $2, $3, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (url) DO UPDATE 
                SET raw_content = EXCLUDED.raw_content,
                    expires_after_days = EXCLUDED.expires_after_days,
                    last_updated = CURRENT_TIMESTAMP
            """
            await conn.execute(sql, url, raw_content, expires_after_days)

    async def _upsert_query_log(self, query: str, enhanced_query: str, enhanced_query_embedding: Optional[List[float]] = None):
        """Upsert the query_log table - increment counter if exists, otherwise insert new row"""
        try:
            pool = await self._get_db_pool()
            async with pool.acquire() as conn:
                # Convert embedding to vector format
                embedding_vector = None
                if enhanced_query_embedding:
                    vector_values = ','.join(str(x) for x in enhanced_query_embedding)
                    embedding_vector = f'[{vector_values}]'

                sql = """
                    INSERT INTO query_log (query, enhanced_query, enhanced_query_embedding, counter)
                    VALUES ($1, $2, $3::vector, 1)
                    ON CONFLICT (enhanced_query) DO UPDATE 
                    SET counter = query_log.counter + 1                        
                """
                await conn.execute(sql, query, enhanced_query, embedding_vector)
        except Exception as e:
            await adispatch_custom_event(
                        "web_searcher",
                        {"message": WorkflowMessage.log(level=LogLevel.ERROR, 
                        message=f"❌ Error upserting query log: {str(e)}",
                        data={"exception":e})}
                        )                     
            # Don't raise the error as this is not critical for the main functionality

    async def search(self, query: str, min_required_results: int = 1, enhanced_query: Optional[str] = None, enhanced_query_embedding: Optional[List[float]] = None, exclude_domains: Optional[List[str]] = None, max_results: int = 5, **kwargs) -> Dict:
        """Search with caching support"""                
        
        try:
            # Log the query first
            if enhanced_query:  # Only log if we have an enhanced query
                await self._upsert_query_log(query, enhanced_query, enhanced_query_embedding)
            
            # Try to get cached results first
            cached_results = await self._get_cached_urls(query, enhanced_query, enhanced_query_embedding, max_results)
            
            # Filter out excluded domains from cached results
            if exclude_domains:
                cached_results = [
                    result for result in cached_results 
                    if urlparse(result['url']).netloc not in exclude_domains
                ]
            
            if len(cached_results) >= min_required_results:
                await adispatch_custom_event(
                        "web_searcher",
                        {"message": WorkflowMessage.log(level=LogLevel.INFO, 
                                                            message=f"Using {len(cached_results)} cached URLs for query: {enhanced_query}"
                                                            )}
                        )                
                return {
                    'results': [
                        {
                            'url': result['url'],
                            'score': -1
                            # 'raw_content': result['raw_content']
                        } for result in cached_results
                    ]
                }
            
            # If not enough cached results, perform actual search
            await adispatch_custom_event(
                        "web_searcher",
                        {"message": WorkflowMessage.log(level=LogLevel.INFO, 
                                                            message=f"Performing fresh search for query: {enhanced_query or query}"
                                                            )}
                        )
            
            # Add exclude_domains to kwargs if provided
            if exclude_domains:
                kwargs['exclude_domains'] = exclude_domains

                await adispatch_custom_event(
                    "web_searcher",
                    {"message": WorkflowMessage.progress(phase=ProgressPhase.WEB_SEARCH, 
                                                        message=f"👉 Excluding {len(exclude_domains)} domains from search: {exclude_domains}",
                                                        data={"exluded_domains": exclude_domains})}
                )
                

            if not exclude_domains:
                kwargs['exclude_domains']=[]
            kwargs['exclude_domains'].extend(['facebook.com', 'tiktok.com', 'youtube.com'])

            kwargs['max_results']=max_results                        
            
            results = await self.tavily_client.search(query=enhanced_query, **kwargs)                                    

            return results
            
        except Exception as e:
            await adispatch_custom_event(
                    "web_searcher",
                    {"message": WorkflowMessage.log(level=LogLevel.ERROR, 
                            message=f"❌ Unexpected error in search method: {str(e)}",
                            data={"exception":e})}
                    )       
            raise

    async def extract(self, urls: List[str], query: Optional[str] = None, enhanced_query: Optional[str] = None, expires_after_days: int = 30, **kwargs) -> Dict:
        """Extract content with caching support"""
        try:
            pool = await self._get_db_pool()            
            
            # Try to get cached content first
            async with pool.acquire() as conn:
                sql = """
                    SELECT url, raw_content
                    FROM content_cache
                    WHERE url = ANY($1)
                    AND CURRENT_TIMESTAMP < content_cache.created_at + (content_cache.expires_after_days * interval '1 day')                    
                """
                
                cached_contents = await conn.fetch(sql, urls)
                cached_urls = {row['url']: row['raw_content'] for row in cached_contents}
                
                await adispatch_custom_event(
                        "web_searcher",
                        {"message": WorkflowMessage.log(level=LogLevel.INFO, 
                                                            message=f"Found {len(cached_urls)} cached website contents ({list(cached_urls.keys())})",
                                )}
                        )

                # Find URLs that need fresh extraction
                urls_to_extract = [url for url in urls if url not in cached_urls]
                
                if urls_to_extract:
                    await adispatch_custom_event(
                                "web_searcher",
                                {"message": WorkflowMessage.log(level=LogLevel.INFO, 
                                                                    message=f"Extracting fresh content for {urls_to_extract}",
                                                                    data={"urls":urls_to_extract})}
                                )
                    fresh_results = await self.tavily_client.extract(urls=urls_to_extract, **kwargs)                    
                                                            

                    if fresh_results and 'results' in fresh_results:
                        # Add failed fetches to the list to be handled by the agent
                        for failure in fresh_results['failed_results']:                            
                            url = failure['url']
                            cached_urls[url] = ''
                            await adispatch_custom_event(
                                "web_searcher",
                                {"message": WorkflowMessage.log(level=LogLevel.INFO, 
                                                                    message=f"Failed to scrape {failure['url']}: {failure['error']}",
                                                                    data={"urls":urls_to_extract})}
                                )
                            

                        for result in fresh_results['results']:
                            raw_content = result.get('raw_content', '')
                            url = result['url']                            
                            cached_urls[url] = raw_content
                            
                            # Cache the new content with expiration days
                            try:
                                await adispatch_custom_event(
                                "web_searcher",
                                {"message": WorkflowMessage.log(level=LogLevel.INFO, 
                                                                    message=f"Caching content for {url}",
                                                                    data={"url":url})}
                                )
                                
                                await self.update_content_cache(url, raw_content, expires_after_days)                                


                            except Exception as e:
                                await adispatch_custom_event(
                                "web_searcher",
                                {"message": WorkflowMessage.log(level=LogLevel.ERROR, 
                                                                    message=f"❌ Error caching content for {url}: {str(e)}",
                                                                    data={"exception":e})}
                                )                                
                                # Continue even if caching fails
            
            # Combine cached and fresh results
            return {
                'results': [
                    {
                        'url': url,
                        'raw_content': content
                    } for url, content in cached_urls.items()
                ]
            }
        except Exception as e:            
            await adispatch_custom_event(
                "web_searcher",
                {"message": WorkflowMessage.log(level=LogLevel.ERROR, 
                            message=f"❌ Unexpected error while scraping website: {str(e)}",
                            data={"exception":e})}
                )
            
            raise

    async def close(self):
        """Close the database connection pool"""
        if self.pool:
            try:
                await self.pool.close()                
                await adispatch_custom_event(
                "web_searcher",
                {"message": WorkflowMessage.log(level=LogLevel.INFO, 
                    message=f"Database connection closed",
                    )}
                )
            except Exception as e:
                await adispatch_custom_event(
                "web_searcher",
                {"message": WorkflowMessage.log(level=LogLevel.ERROR, 
                            message=f"❌ Unexpected error while closing database connection: {str(e)}",
                            data={"exception":e})}
                )                
                raise 

    