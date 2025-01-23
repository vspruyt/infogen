import asyncio
from datetime import datetime, timedelta, timezone
import asyncpg
from tavily import AsyncTavilyClient
from typing import List, Dict, Optional
import traceback
from urllib.parse import urlparse

# Constants
CACHE_MAX_AGE_DAYS = 30

class CachedTavilyClient:
    def __init__(self, api_key: str):
        self.tavily_client = AsyncTavilyClient(api_key=api_key)
        self.pool = None
        
    async def _get_db_pool(self) -> asyncpg.Pool:
        """Lazy initialization of the connection pool"""
        try:
            if self.pool is None:
                print("\n🔌 Connecting to database...")
                self.pool = await asyncpg.create_pool(
                    user='postgres',
                    password='localtest',
                    database='postgres',
                    host='localhost',
                    port=5432
                )
                print("✅ Database connection established")
            return self.pool
        except Exception as e:
            print(f"\n❌ Database connection error: {str(e)}")
            print(f"Error type: {type(e)}")
            print(f"Traceback:\n{traceback.format_exc()}")
            raise
        
    async def _get_cached_urls(self, query: str, enhanced_query: Optional[str] = None, enhanced_query_embedding: Optional[List[float]] = None) -> List[Dict]:
        """Get cached URLs for a query if they exist and are not stale"""
        try:
            pool = await self._get_db_pool()
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=CACHE_MAX_AGE_DAYS)
            
            async with pool.acquire() as conn:
                print(f"\n🔍 Checking cache for query: {enhanced_query or query}")

                # Convert embedding list to PostgreSQL vector format if it exists
                embedding_vector = None
                if enhanced_query_embedding:
                    # Format to match pgvector's expected format exactly: [1,2,3]
                    vector_values = ','.join(str(x) for x in enhanced_query_embedding)
                    embedding_vector = f'[{vector_values}]'
                    
                sql = """
                    SELECT DISTINCT url_cache.url, url_cache.enhanced_query, content_cache.raw_content, url_cache.created_at
                    FROM url_cache 
                    JOIN content_cache ON url_cache.url = content_cache.url
                    WHERE  1-(url_cache.enhanced_query_embedding <-> $2::vector) >= 0.2
                    AND url_cache.created_at > $1
                    ORDER BY url_cache.created_at DESC
                """
                # print(f"\n📝 Executing SQL:\n{sql}")
                # print(f"Parameters: enhanced_query='{enhanced_query or query}', cutoff_date='{cutoff_date}'")
                
                rows = await conn.fetch(sql, cutoff_date, embedding_vector)
                
                print(f"✅ Found {len(rows)} cached results")
                for row in rows:
                    print(row['enhanced_query'])
                    
                return [{'url': row['url'], 'raw_content': row['raw_content']} for row in rows]
        except Exception as e:
            print(f"\n❌ Error fetching cached URLs: {str(e)}")
            print(f"Error type: {type(e)}")
            print(f"Traceback:\n{traceback.format_exc()}")
            raise

    async def _cache_search_results(self, query: str, enhanced_query: Optional[str], results: List[Dict], enhanced_query_embedding: Optional[List[float]] = None):
        """Cache search results in both tables"""
        try:
            pool = await self._get_db_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    print(f"\n💾 Caching {len(results)} search results")
                    
                    # First ensure content is cached if available
                    for result in results:
                        if result.get('raw_content'):  # Only cache content if it exists
                            try:
                                sql = """
                                    INSERT INTO content_cache (url, query, enhanced_query, raw_content)
                                    VALUES ($1, $2, $3, $4)
                                    ON CONFLICT (url) DO UPDATE 
                                    SET raw_content = EXCLUDED.raw_content,
                                        last_updated = CURRENT_TIMESTAMP
                                """
                                await conn.execute(sql, result['url'], query, enhanced_query, result['raw_content'])
                            except Exception as e:
                                print(f"\n❌ Error caching content for URL {result['url']}: {str(e)}")
                                continue

                    # Then cache URL references
                    for result in results:
                        try:
                            # Convert embedding list to PostgreSQL vector format if it exists
                            embedding_vector = None
                            if enhanced_query_embedding:
                                # Format to match pgvector's expected format exactly: [1,2,3]
                                vector_values = ','.join(str(x) for x in enhanced_query_embedding)
                                embedding_vector = f'[{vector_values}]'
                            
                            sql = """
                                INSERT INTO url_cache (query, enhanced_query, url, enhanced_query_embedding)
                                VALUES ($1, $2, $3, $4::vector)
                                ON CONFLICT DO NOTHING
                            """
                            await conn.execute(sql, query, enhanced_query, result['url'], embedding_vector)
                        except Exception as e:
                            print(f"\n❌ Error caching URL {result['url']}: {str(e)}")
                            continue
                            
                    print("✅ Successfully cached results")
        except Exception as e:
            print(f"\n❌ Error caching search results: {str(e)}")
            print(f"Error type: {type(e)}")
            print(f"Traceback:\n{traceback.format_exc()}")
            raise

    async def search(self, query: str, min_required_results: int = 1, enhanced_query: Optional[str] = None, enhanced_query_embedding: Optional[List[float]] = None, exclude_domains: Optional[List[str]] = None, **kwargs) -> Dict:
        """Search with caching support"""                
        
        try:
            # Try to get cached results first
            cached_results = await self._get_cached_urls(query, enhanced_query, enhanced_query_embedding)
            
            # Filter out excluded domains from cached results
            if exclude_domains:
                cached_results = [
                    result for result in cached_results 
                    if urlparse(result['url']).netloc not in exclude_domains
                ]
            
            if len(cached_results) >= min_required_results:
                print(f"\n📂 Using {len(cached_results)} cached results for query: {query}")
                return {
                    'results': [
                        {
                            'url': result['url'],
                            'raw_content': result['raw_content']
                        } for result in cached_results
                    ]
                }
            
            # If not enough cached results, perform actual search
            print(f"\n🌐 Performing fresh search for query: {enhanced_query or query}")
            
            # Add exclude_domains to kwargs if provided
            if exclude_domains:
                kwargs['exclude_domains'] = exclude_domains
                print(f"\n🚫 Excluding domains: {exclude_domains}")
                
            results = await self.tavily_client.search(query=query, **kwargs)
            
            # Cache the new results
            if results and 'results' in results:
                await self._cache_search_results(query, enhanced_query, results['results'], enhanced_query_embedding)
                
            return results
        except Exception as e:
            print(f"\n❌ Error in search method: {str(e)}")
            print(f"Error type: {type(e)}")
            print(f"Traceback:\n{traceback.format_exc()}")
            raise

    async def extract(self, urls: List[str], query: Optional[str] = None, enhanced_query: Optional[str] = None, **kwargs) -> Dict:
        """Extract content with caching support"""
        try:
            pool = await self._get_db_pool()
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=CACHE_MAX_AGE_DAYS)
            
            # Try to get cached content first
            async with pool.acquire() as conn:
                sql = """
                    SELECT url, raw_content
                    FROM content_cache
                    WHERE url = ANY($1)
                    AND created_at > $2
                """
                # print(f"\n📝 Executing SQL:\n{sql}")
                # print(f"Parameters: urls={urls}, cutoff_date='{cutoff_date}'")
                
                cached_contents = await conn.fetch(sql, urls, cutoff_date)
                
                cached_urls = {row['url']: row['raw_content'] for row in cached_contents}
                
                # Find URLs that need fresh extraction
                urls_to_extract = [url for url in urls if url not in cached_urls]
                
                if urls_to_extract:
                    print(f"\n🌐 Extracting fresh content for {urls_to_extract}")
                    fresh_results = await self.tavily_client.extract(urls=urls_to_extract, **kwargs)
                    
                    if fresh_results and 'results' in fresh_results:
                        # Cache the new results
                        for result in fresh_results['results']:
                            sql = """
                                INSERT INTO content_cache (url, query, enhanced_query, raw_content)
                                VALUES ($1, $2, $3, $4)
                                ON CONFLICT (url) DO UPDATE 
                                SET raw_content = EXCLUDED.raw_content,
                                    query = EXCLUDED.query,
                                    enhanced_query = EXCLUDED.enhanced_query,
                                    last_updated = CURRENT_TIMESTAMP
                            """
                            # print(f"\n📝 Executing SQL:\n{sql}")
                            # print(f"Parameters: url='{result['url']}', query='{query or ''}', enhanced_query='{enhanced_query}', raw_content_length={len(result.get('raw_content', ''))}")
                            
                            await conn.execute(sql, result['url'], query or '', enhanced_query, result.get('raw_content', ''))
                            cached_urls[result['url']] = result.get('raw_content', '')
            
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
            print(f"\n❌ Error in extract method: {str(e)}")
            print(f"Error type: {type(e)}")
            print(f"Traceback:\n{traceback.format_exc()}")
            raise

    async def close(self):
        """Close the database connection pool"""
        if self.pool:
            try:
                await self.pool.close()
                print("\n✅ Database connection closed")
            except Exception as e:
                print(f"\n❌ Error closing database connection: {str(e)}")
                print(f"Error type: {type(e)}")
                print(f"Traceback:\n{traceback.format_exc()}")
                raise 

    async def delete_from_cache(self, url: str):
        """Delete a URL from both cache tables"""
        try:
            pool = await self._get_db_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    print(f"\n🗑️  Removing invalid URL from cache: {url}")
                    
                    # Delete from url_cache first due to foreign key constraint
                    sql = "DELETE FROM url_cache WHERE url = $1"
                    # print(f"\n📝 Executing SQL:\n{sql}")
                    # print(f"Parameters: url='{url}'")
                    await conn.execute(sql, url)
                    
                    # Then delete from content_cache
                    sql = "DELETE FROM content_cache WHERE url = $1"
                    # print(f"\n📝 Executing SQL:\n{sql}")
                    # print(f"Parameters: url='{url}'")
                    await conn.execute(sql, url)
                    
                    print("✅ URL removed from cache")
        except Exception as e:
            print(f"\n❌ Error deleting URL from cache: {str(e)}")
            print(f"Error type: {type(e)}")
            print(f"Traceback:\n{traceback.format_exc()}")
            raise 