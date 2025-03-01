from openai import OpenAI
from typing import List, Dict
import psycopg2
from psycopg2.extras import Json, register_uuid
from psycopg2.pool import ThreadedConnectionPool
import uuid
from datetime import datetime
import os
import threading
from infogen.core.logging_config import get_logger

# Configure logging
logger = get_logger(__name__)

class CachedEmbeddingClient:
    _instance_lock = threading.Lock()
    _connection_pools = {}

    def __init__(self, api_key: str, db_connection_string: str, min_connections: int = 1, max_connections: int = 20):
        self.client = OpenAI(api_key=api_key)
        register_uuid()
        self._process_key = os.getpid()
        self._thread_id = threading.get_ident()
        logger.info(f"Initializing CachedEmbeddingClient for process {self._process_key}, thread {self._thread_id}")
        with self._instance_lock:
            if self._process_key not in self._connection_pools:
                logger.info(f"Creating new connection pool for process {self._process_key}")
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
        with self._instance_lock:
            if self._process_key in self._connection_pools:
                if hasattr(self._local, 'connection') and self._local.connection is not None:
                    try:
                        self._db_pool.putconn(self._local.connection)
                    except Exception as e:
                        logger.error(f"Error returning connection during close: {str(e)}")
                        pass
                    self._local.connection = None
                logger.info(f"Closing connection pool for process {self._process_key}")
                try:
                    self._connection_pools[self._process_key].closeall()
                except Exception as e:
                    logger.error(f"Error closing connection pool: {str(e)}")
                del self._connection_pools[self._process_key]

    def _execute_with_connection(self, operation):
        thread_id = threading.get_ident()
        process_key = os.getpid()
        logger.debug(f"Getting connection for process {process_key}, thread {thread_id}")
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
            logger.error(f"Error executing database operation: {str(e)}")
            conn.rollback()
            raise
        finally:
            logger.debug(f"Returning connection for process {process_key}, thread {thread_id}")
            self._db_pool.putconn(conn)

    def get_embedding(self, text: str) -> List[float]:
        logger.debug(f"Getting embedding for text: {text[:50]}...")
        return self._execute_with_connection(lambda cur: self._get_embedding_internal(cur, text))

    def _parse_vector(self, vector_str: str) -> List[float]:
        """Parse a PostgreSQL vector string into a list of floats"""
        # Remove brackets and split by commas
        if vector_str.startswith('[') and vector_str.endswith(']'):
            vector_str = vector_str[1:-1]
        return [float(x) for x in vector_str.split(',')]

    def _format_vector(self, embedding: List[float]) -> str:
        """Convert a list of floats to a PostgreSQL vector string format"""
        return f"[{','.join(f'{x:.8f}' for x in embedding)}]"

    def _get_embedding_internal(self, cur, text: str) -> List[float]:
        cur.execute("""
            SELECT embedding::text
            FROM embedding_cache 
            WHERE text = %s
        """, (text,))
        cache_result = cur.fetchone()
        if cache_result:
            logger.info(f"[CACHE HIT] Found embedding in cache for text: {text[:50]}...")
            # Parse vector string to list of floats
            return self._parse_vector(cache_result[0])
        logger.info(f"[API CALL] Fetching embedding from OpenAI API for text: {text[:50]}...")
        try:
            response = self.client.embeddings.create(model="text-embedding-3-small", input=[text])
            embedding = response.data[0].embedding
            logger.debug(f"Successfully received embedding from API (dimensions: {len(embedding)})")
            
            # Cache the embedding
            cur.execute("""
                INSERT INTO embedding_cache 
                (id, text, embedding, creation_date)
                VALUES (%s, %s, %s::vector, %s)
                ON CONFLICT (text) DO UPDATE
                SET embedding = EXCLUDED.embedding,
                    creation_date = EXCLUDED.creation_date
            """, (
                uuid.uuid4(),
                text,
                self._format_vector(embedding),
                datetime.now()
            ))
            logger.debug("Successfully cached embedding in database")
            return embedding
        except Exception as e:
            logger.error(f"Error getting embedding from OpenAI API: {str(e)}")
            raise

    def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        logger.debug(f"Getting embeddings for {len(texts)} texts")
        return self._execute_with_connection(lambda cur: self._get_embeddings_internal(cur, texts))

    def _get_embeddings_internal(self, cur, texts: List[str]) -> List[List[float]]:
        # First try to get all cached embeddings
        embeddings = []
        uncached_texts = []
        uncached_indices = []
        
        for i, text in enumerate(texts):
            cur.execute("""
                SELECT embedding::text
                FROM embedding_cache 
                WHERE text = %s
            """, (text,))
            cache_result = cur.fetchone()
            if cache_result:
                logger.debug(f"[CACHE HIT] Found embedding in cache for text {i}: {text[:50]}...")
                embeddings.append(self._parse_vector(cache_result[0]))
            else:
                logger.debug(f"[CACHE MISS] No cached embedding for text {i}: {text[:50]}...")
                uncached_texts.append(text)
                uncached_indices.append(i)
        
        # If we have any uncached texts, get them all at once from the API
        if uncached_texts:
            logger.info(f"[BATCH API CALL] Fetching {len(uncached_texts)} embeddings from OpenAI API...")
            try:
                response = self.client.embeddings.create(model="text-embedding-3-small", input=uncached_texts)
                new_embeddings = [embedding.embedding for embedding in response.data]
                logger.info(f"[BATCH API CALL] Successfully received {len(new_embeddings)} embeddings from API")
                
                # Cache all the new embeddings
                for text, embedding in zip(uncached_texts, new_embeddings):
                    cur.execute("""
                        INSERT INTO embedding_cache 
                        (id, text, embedding, creation_date)
                        VALUES (%s, %s, %s::vector, %s)
                        ON CONFLICT (text) DO UPDATE
                        SET embedding = EXCLUDED.embedding,
                            creation_date = EXCLUDED.creation_date
                    """, (
                        uuid.uuid4(),
                        text,
                        self._format_vector(embedding),
                        datetime.now()
                    ))
                logger.debug(f"Successfully cached {len(new_embeddings)} embeddings in database")
                
                # Insert new embeddings into the result list at their original positions
                for idx, embedding in zip(uncached_indices, new_embeddings):
                    while len(embeddings) <= idx:
                        embeddings.append(None)
                    embeddings[idx] = embedding
            except Exception as e:
                logger.error(f"Error getting batch embeddings from OpenAI API: {str(e)}")
                raise
        
        return embeddings

    def nearest_neighbors(self, text: str, k: int) -> List[Dict[str, any]]:
        """
        Find the k nearest neighbors in the cache based on embedding similarity.
        
        Args:
            text: The text to find similar matches for
            k: Number of nearest neighbors to return
            
        Returns:
            List of dictionaries containing the similar texts and their similarity scores
        """
        logger.info(f"Finding {k} nearest neighbors for text: {text[:50]}...")
        return self._execute_with_connection(lambda cur: self._nearest_neighbors_internal(cur, text, k))
        
    def _nearest_neighbors_internal(self, cur, text: str, k: int) -> List[Dict[str, any]]:
        # Get embedding for the text
        text_embedding = self.get_embedding(text)
        
        # Find k nearest neighbors using cosine similarity
        cur.execute("""
            SELECT 
                text,
                embedding::text,
                1 - (embedding <-> %s::vector) as similarity
            FROM embedding_cache 
            ORDER BY embedding <-> %s::vector ASC
            LIMIT %s
        """, (self._format_vector(text_embedding), self._format_vector(text_embedding), k))
        
        results = []
        for row in cur.fetchall():
            results.append({
                "text": row[0],
                "embedding": self._parse_vector(row[1]),
                "similarity": row[2]
            })
            
        if results:
            logger.info(f"[NEIGHBORS] Found {len(results)} similar texts")
            for i, r in enumerate(results):
                logger.debug(f"[NEIGHBORS] #{i+1}: Similarity {r['similarity']:.3f} for text: {r['text'][:100]}...")
        else:
            logger.warning(f"[NEIGHBORS] No similar texts found")
            
        return results 