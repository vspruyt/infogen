import threading
from typing import Dict, Optional, List, Union
import psycopg2
from psycopg2.extras import Json, register_uuid
from psycopg2.pool import ThreadedConnectionPool
import uuid
from datetime import datetime
import os
import asyncio
from olclient.openlibrary import OpenLibrary
import olclient.common as common
import json

class CachedOpenLibraryClient:
    # Configuration constants
    CACHE_EXPIRY_MINUTES = 14400  # 10 days by default
    _instance_lock = threading.Lock()
    _connection_pools = {}  # Dictionary to store connection pools per process
    
    def __init__(self, db_connection_string: str, min_connections: int = 1, max_connections: int = 20):
        """
        Initialize the CachedOpenLibraryClient with connection pooling support.
        
        Args:
            db_connection_string: PostgreSQL connection string
            min_connections: Minimum number of database connections in the pool
            max_connections: Maximum number of database connections in the pool
        """
        # Register UUID type adapter
        register_uuid()
        
        # Create a unique key for this process's connection pool
        self._process_key = os.getpid()
        self._thread_id = threading.get_ident()
        print(f"[INIT] Initializing CachedOpenLibraryClient for process {self._process_key}, thread {self._thread_id}")
        
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
        self.ol = OpenLibrary()
        
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

    def search_multi(self, api_search_query: str, media_type: str) -> Dict:
        """
        Search for authors or books using OpenLibrary's search endpoints, with caching support.
        
        Args:
            api_search_query: The search query string
            media_type: Type of media to search for ("author" or "book")
            
        Returns:
            Dict containing search results, or None if no results found
        """
        if media_type not in ["author", "book"]:
            raise ValueError('media_type must be one of "author" or "book"')
            
        return self._execute_with_connection(lambda cur: self._search_multi_internal(cur, api_search_query, media_type))

    def _search_multi_internal(self, cur, api_search_query: str, media_type: str) -> Dict:
        # Check cache first
        cur.execute("""
            SELECT api_response 
            FROM openlibrary_search_cache 
            WHERE query = %s AND media_type = %s
                AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
        """, (api_search_query, media_type))
        
        cache_result = cur.fetchone()                        
        
        if cache_result:
            print(f"Found Cached result for {media_type} query: {api_search_query}")
            return cache_result[0]
            
        # If not in cache, call API
        print(f"Calling OpenLibrary API: search for {media_type} with query '{api_search_query}'")
        
        if media_type == "author":
            response = self.ol.Author.search(api_search_query, limit=10)
            if not response:
                response = None
        else:  # book
            response = self.ol.Work.search(api_search_query)
            if response and hasattr(response, 'identifiers'):
                if 'olid' in response.identifiers and response.identifiers['olid'] and len(response.identifiers['olid']) > 0:
                    response = response.identifiers['olid'][0]
                else:
                    response = None
            else:
                response = None
        
        # Cache the results (even if None, to avoid repeated API calls for empty results)
        cur.execute("""
            INSERT INTO openlibrary_search_cache 
            (id, query, media_type, api_response, creation_date, expires_after_minutes)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (query, media_type) DO UPDATE
            SET api_response = EXCLUDED.api_response,
                creation_date = EXCLUDED.creation_date,
                expires_after_minutes = EXCLUDED.expires_after_minutes
        """, (
            uuid.uuid4(),
            api_search_query,
            media_type,
            Json(response),
            datetime.now(),
            self.CACHE_EXPIRY_MINUTES
        ))
        return response

    def get_author_details(self, key: str) -> Dict:
        """
        Get detailed author information from OpenLibrary API, with caching support.
        
        Args:
            key: The OpenLibrary author key
            
        Returns:
            Dict containing author details
        """
        return self._execute_with_connection(lambda cur: self._get_author_details_internal(cur, key))

    def _get_author_details_internal(self, cur, key: str) -> Dict:
        cur.execute("""
            SELECT api_response 
            FROM openlibrary_author_cache 
            WHERE author_key = %s
                AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
        """, (key,))
        
        cache_result = cur.fetchone()
        
        if cache_result:
            print(f"Found Cached result for author key: {key}")
            return cache_result[0]
            
        # If not in cache, call API
        print(f"Calling OpenLibrary API: Author.get for key {key}")
        response = self.ol.Author.get(key)
        
        if response:
            response = response.json()
        
            # Cache the results
            cur.execute("""
                INSERT INTO openlibrary_author_cache 
                (author_key, api_response, creation_date, expires_after_minutes)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (author_key) DO UPDATE
                SET api_response = EXCLUDED.api_response,
                    creation_date = EXCLUDED.creation_date,
                    expires_after_minutes = EXCLUDED.expires_after_minutes
            """, (
                key,
                Json(response),
                datetime.now(),
                self.CACHE_EXPIRY_MINUTES
            ))
        
        return response

    def get_author_works(self, author) -> Dict:
        """
        Get works by an author from OpenLibrary API, with caching support.
        
        Args:
            author: The OpenLibrary Author object
            
        Returns:
            Dict containing author's works
        """
        return self._execute_with_connection(lambda cur: self._get_author_works_internal(cur, author))

    def _get_author_works_internal(self, cur, author) -> Dict:
        cur.execute("""
            SELECT api_response 
            FROM openlibrary_author_works_cache 
            WHERE author_key = %s
                AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
        """, (author.olid,))
        
        cache_result = cur.fetchone()
        
        if cache_result:
            print(f"Found Cached result for author works: {author.olid}")
            return cache_result[0]
            
        # If not in cache, call API
        print(f"Calling OpenLibrary API: author.works for author {author.olid}")
        response = author.works(limit=100)
        
        # Cache the results
        cur.execute("""
            INSERT INTO openlibrary_author_works_cache 
            (author_key, api_response, creation_date, expires_after_minutes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (author_key) DO UPDATE
            SET api_response = EXCLUDED.api_response,
                creation_date = EXCLUDED.creation_date,
                expires_after_minutes = EXCLUDED.expires_after_minutes
        """, (
            author.olid,
            Json(response),
            datetime.now(),
            self.CACHE_EXPIRY_MINUTES
        ))
        
        return response

    def get_work_details(self, ol_id: str) -> Dict:
        """
        Get detailed work information from OpenLibrary API, with caching support.
        
        Args:
            ol_id: The OpenLibrary work ID
            
        Returns:
            Dict containing work details
        """
        return self._execute_with_connection(lambda cur: self._get_work_details_internal(cur, ol_id))

    def _get_work_details_internal(self, cur, ol_id: str) -> Dict:
        cur.execute("""
            SELECT api_response 
            FROM openlibrary_work_cache 
            WHERE work_key = %s
                AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
        """, (ol_id,))
        
        cache_result = cur.fetchone()
        
        if cache_result:
            print(f"Found Cached result for work: {ol_id}")
            return cache_result[0]
            
        # If not in cache, call API
        print(f"Calling OpenLibrary API: Work.get for work {ol_id}")
        response = self.ol.Work.get(ol_id)
        if response:
            response = response.json()
        
            # Cache the results
            cur.execute("""
                INSERT INTO openlibrary_work_cache 
                (work_key, api_response, creation_date, expires_after_minutes)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (work_key) DO UPDATE
                SET api_response = EXCLUDED.api_response,
                    creation_date = EXCLUDED.creation_date,
                    expires_after_minutes = EXCLUDED.expires_after_minutes
            """, (
                ol_id,
                Json(response),
                datetime.now(),
                self.CACHE_EXPIRY_MINUTES
            ))
        
        return response

    def get_edition_details(self, work) -> Dict:
        """
        Get editions of a work from OpenLibrary API, with caching support.
        
        Args:
            work: The OpenLibrary Work object
            
        Returns:
            Dict containing work editions
        """
        return self._execute_with_connection(lambda cur: self._get_edition_details_internal(cur, work))

    def _get_edition_details_internal(self, cur, work) -> Dict:
        cur.execute("""
            SELECT api_response 
            FROM openlibrary_editions_cache 
            WHERE work_key = %s
                AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
        """, (work.olid,))
        
        cache_result = cur.fetchone()
        
        if cache_result:
            print(f"Found Cached result for work editions: {work.olid}")
            return cache_result[0]
            
        # If not in cache, call API
        print(f"Calling OpenLibrary API: work.editions for work {work.olid}")
        response = work.editions

        if response:
            # Convert each edition object to a dict for caching
            editions_data = [edition.json() if hasattr(edition, 'json') else edition for edition in response]
        
            # Cache the results
            cur.execute("""
                INSERT INTO openlibrary_editions_cache 
                (work_key, api_response, creation_date, expires_after_minutes)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (work_key) DO UPDATE
                SET api_response = EXCLUDED.api_response,
                    creation_date = EXCLUDED.creation_date,
                    expires_after_minutes = EXCLUDED.expires_after_minutes
            """, (
                work.olid,
                Json(editions_data),
                datetime.now(),
                self.CACHE_EXPIRY_MINUTES
            ))
            
            return editions_data
        
        return []

    def _json_to_author(self, author_data: Union[Dict, str]) -> common.Author:
        """
        Convert JSON author data into an OpenLibrary Author object.
        
        Args:
            author_data: Either a dict containing author data or a string with the author's name
            
        Returns:
            olclient.openlibrary.OpenLibrary.Author object
        """
        if isinstance(author_data, str):
            # For string input, create an Author with no olid
            return self.ol.Author(None, author_data)
            
        # Make a copy to avoid modifying the original
        data = author_data.copy()
        
        # Extract required fields
        name = data.pop('name', '')
        
        # Extract OLID from key (e.g., /authors/OL1234567A) or olid field
        olid = data.pop('key', '').replace('/authors/', '')
        if not olid:
            olid = data.pop('olid', '')
        
        # Create OpenLibrary Author with all remaining fields as kwargs
        return self.ol.Author(olid, name, **data)

    def _json_to_authors(self, authors_data: List[Union[Dict, str]]) -> List[common.Author]:
        """
        Convert a list of JSON author data into a list of OpenLibrary Author objects.
        
        Args:
            authors_data: List of either dicts containing author data or strings with author names
            
        Returns:
            List of common.Author objects
        """
        return [self._json_to_author(author_data) for author_data in authors_data]

    def _json_to_work(self, work_data: Dict) -> OpenLibrary.Work:
        """
        Convert JSON work data into an OpenLibrary Work object.
        
        Args:
            work_data: Dict containing work data
            
        Returns:
            olclient.openlibrary.OpenLibrary.Work object
        """
        # Make a copy to avoid modifying the original
        data = work_data.copy()
        
        # Extract and format the OLID - it could be in the key (e.g., /works/OL1234567W) or in an olid field
        olid = data.pop('key', '').replace('/works/', '')
        if not olid:
            olid = data.pop('olid', '')
        
        # Create Work object with all fields passed as kwargs
        return self.ol.Work(olid, **data)

    def _json_to_edition(self, edition_data: Dict) -> OpenLibrary.Edition:
        """
        Convert JSON edition data into an OpenLibrary Edition object.
        
        Args:
            edition_data: Dict containing edition data
            
        Returns:
            olclient.openlibrary.OpenLibrary.Edition object
        """
        # Make a copy to avoid modifying the original
        data = edition_data.copy()
        
        # Extract OLID from key (e.g., /books/OL1234567M) or olid field
        edition_olid = data.pop('key', '').replace('/books/', '')
        if not edition_olid:
            edition_olid = data.pop('olid', '')
            
        # Extract work OLID from works reference
        works = data.pop('works', [{}])
        work_olid = None
        if works and isinstance(works, list) and len(works) > 0:
            work_olid = works[0].get('key', '').replace('/works/', '')
        
        if not work_olid:
            # Try other possible fields
            work_olid = data.pop('work_olid', None) or data.pop('work_key', '')
            if isinstance(work_olid, str):
                work_olid = work_olid.replace('/works/', '')
            
        # Convert author references if present
        if 'authors' in data:
            data['authors'] = self._json_to_authors(data.pop('authors'))
            
        # Create Edition object with all remaining fields passed as kwargs
        return self.ol.Edition(edition_olid=edition_olid, work_olid=work_olid, **data)

    def create_work_from_json(self, json_data: Union[str, Dict]) -> common.Book:
        """
        Create an OpenLibrary Work object from JSON data.
        
        Args:
            json_data: Either a JSON string or a dict containing work data
            
        Returns:
            olclient.openlibrary.OpenLibrary.Work object
        """
        if isinstance(json_data, str):
            data = json.loads(json_data)
        else:
            data = json_data
            
        return self._json_to_work(data)

    def create_author_from_json(self, json_data: Union[str, Dict]) -> common.Author:
        """
        Create an OpenLibrary Author object from JSON data.
        
        Args:
            json_data: Either a JSON string or a dict containing author data
            
        Returns:
            olclient.openlibrary.OpenLibrary.Author object
        """
        if isinstance(json_data, str):
            data = json.loads(json_data)
        else:
            data = json_data
            
        return self._json_to_author(data)

    def create_edition_from_json(self, json_data: Union[str, Dict]) -> OpenLibrary.Edition:
        """
        Create an OpenLibrary Edition object from JSON data.
        
        Args:
            json_data: Either a JSON string or a dict containing edition data
            
        Returns:
            olclient.openlibrary.OpenLibrary.Edition object
        """
        if isinstance(json_data, str):
            data = json.loads(json_data)
        else:
            data = json_data
            
        return self._json_to_edition(data)
