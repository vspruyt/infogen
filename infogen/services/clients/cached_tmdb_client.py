import tmdbsimple as tmdb
from typing import Dict, Optional
import psycopg2
from psycopg2.extras import Json, register_uuid
from psycopg2.pool import ThreadedConnectionPool
import uuid
from datetime import datetime, timedelta
import os
from omdb import OMDB
import threading
import logging

logger = logging.getLogger(__name__)

class CachedTMDBClient:
    # Configuration constants
    CACHE_EXPIRY_MINUTES = 14400  # 10 days by default
    _instance_lock = threading.Lock()
    _connection_pools = {}  # Dictionary to store connection pools per process
    
    def __init__(self, api_key: str, db_connection_string: str, min_connections: int = 1, max_connections: int = 20):
        """
        Initialize the CachedTMDBClient with connection pooling support.
        
        Args:
            api_key: TMDB API key
            db_connection_string: PostgreSQL connection string
            min_connections: Minimum number of database connections in the pool
            max_connections: Maximum number of database connections in the pool
        """
        tmdb.API_KEY = api_key
        # Register UUID type adapter
        register_uuid()
        
        # Create a unique key for this process's connection pool
        self._process_key = os.getpid()
        self._thread_id = threading.get_ident()
        logger.info(f"Initializing CachedTMDBClient for process {self._process_key}, thread {self._thread_id}")
        
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
        """Close all connections and clean up resources for this process"""
        with self._instance_lock:
            if self._process_key in self._connection_pools:
                if hasattr(self._local, 'connection') and self._local.connection is not None:
                    try:
                        self._db_pool.putconn(self._local.connection)
                    except Exception:
                        pass  # Ignore errors during cleanup
                    self._local.connection = None
                
                logger.info(f"Closing connection pool for process {self._process_key}")
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
        logger.debug(f"Getting new connection for process {process_key}, thread {thread_id}")
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
            logger.debug(f"Returning connection for process {process_key}, thread {thread_id}")
            self._db_pool.putconn(conn)

    def search_multi(self, api_search_query: str) -> Dict:
        """
        Search for movies, TV shows and people using TMDB's multi-search endpoint, with caching support.
        
        Args:
            api_search_query: The search query string
            
        Returns:
            Dict containing search results
        """
        return self._execute_with_connection(lambda cur: self._search_multi_internal(cur, api_search_query))
        
    def get_movie_info(self, tmdb_id: int) -> Dict:
        """
        Get detailed movie information from TMDB API, with caching support.
        
        Args:
            tmdb_id: The TMDB ID of the movie (integer)
            
        Returns:
            Dict containing movie details including credits, external IDs, release dates, and watch providers
        """
        return self._execute_with_connection(lambda cur: self._get_movie_info_internal(cur, tmdb_id))
        
    def get_omdb_movie_info(self, imdb_id: str) -> Dict:
        """
        Get detailed movie information from OMDB API, with caching support.
        
        Args:
            imdb_id: The IMDB ID of the movie
            
        Returns:
            Dict containing movie details with full plot information
        """
        return self._execute_with_connection(lambda cur: self._get_omdb_movie_info_internal(cur, imdb_id))
        
    def get_collection_info(self, collection_id: int) -> Dict:
        """
        Get detailed collection information from TMDB API, with caching support.
        
        Args:
            collection_id: The TMDB Collection ID (integer)
            
        Returns:
            Dict containing collection details
        """
        return self._execute_with_connection(lambda cur: self._get_collection_info_internal(cur, collection_id))
        
    def get_tv_info(self, tmdb_id: int) -> Dict:
        """
        Get detailed TV show information from TMDB API, with caching support.
        
        Args:
            tmdb_id: The TMDB ID of the TV show (integer)
            
        Returns:
            Dict containing TV show details including credits, external IDs, content ratings, and watch providers
        """
        return self._execute_with_connection(lambda cur: self._get_tv_info_internal(cur, tmdb_id))
        
    def get_omdb_tv_info(self, imdb_id: str) -> Dict:
        """
        Get detailed TV show information from OMDB API, with caching support.
        
        Args:
            imdb_id: The IMDB ID of the TV show
            
        Returns:
            Dict containing TV show details with full plot information
        """
        return self._execute_with_connection(lambda cur: self._get_omdb_tv_info_internal(cur, imdb_id))
        
    def get_season_info(self, tmdb_id: int, season_number: int) -> Dict:
        """
        Get detailed TV season information from TMDB API, with caching support.
        
        Args:
            tmdb_id: The TMDB ID of the TV show (integer)
            season_number: The season number
            
        Returns:
            Dict containing season details including account states, credits, and external IDs
        """
        return self._execute_with_connection(lambda cur: self._get_season_info_internal(cur, tmdb_id, season_number))
        
    def get_people_info(self, tmdb_id: int) -> Dict:
        """
        Get detailed person information from TMDB API, with caching support.
        
        Args:
            tmdb_id: The TMDB ID of the person (integer)
            
        Returns:
            Dict containing person details including combined credits and external IDs
        """
        return self._execute_with_connection(lambda cur: self._get_people_info_internal(cur, tmdb_id))
        
    def get_popular_list(self, media_type: str) -> Dict:
        """
        Get popular list for movies, TV shows, or people from TMDB API, with caching support.
        
        Args:
            media_type: The type of media to get popular list for ("movie", "tv", or "person")
            
        Returns:
            Dict containing popular items of the specified type
            
        Raises:
            ValueError: If media_type is not one of "movie", "tv", or "person"
        """
        if media_type not in ["movie", "tv", "person"]:
            raise ValueError('media_type must be one of "movie", "tv", or "person"')
            
        return self._execute_with_connection(lambda cur: self._get_popular_list_internal(cur, media_type))
        
    def get_top_rated_list(self, media_type: str) -> Dict:
        """
        Get top rated list for movies or TV shows from TMDB API, with caching support.
        
        Args:
            media_type: The type of media to get top rated list for ("movie" or "tv")
            
        Returns:
            Dict containing top rated items of the specified type
            
        Raises:
            ValueError: If media_type is not one of "movie" or "tv"
        """
        if media_type not in ["movie", "tv"]:
            raise ValueError('media_type must be one of "movie" or "tv"')
            
        return self._execute_with_connection(lambda cur: self._get_top_rated_list_internal(cur, media_type))

    def _search_multi_internal(self, cur, api_search_query: str) -> Dict:
        # Check cache first
        cur.execute("""
            SELECT api_response 
            FROM tmdb_search_cache 
            WHERE query = %s
                AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
        """, (api_search_query,))
        
        cache_result = cur.fetchone()                        
        
        if cache_result:
            print("Found Cached result for query: ", api_search_query)
            return cache_result[0]
            
        # If not in cache, call API
        print(f"Calling TMDB API: search.multi for query '{api_search_query}'")
        search = tmdb.Search()
        response = search.multi(query=api_search_query)
        
        # Cache the results
        cur.execute("""
            INSERT INTO tmdb_search_cache 
            (id, query, api_response, creation_date, expires_after_minutes)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (query) DO UPDATE
            SET api_response = EXCLUDED.api_response,
                creation_date = EXCLUDED.creation_date,
                expires_after_minutes = EXCLUDED.expires_after_minutes
        """, (
            uuid.uuid4(),
            api_search_query,
            Json(response),
            datetime.now(),
            self.CACHE_EXPIRY_MINUTES
        ))
        return response

    def _get_movie_info_internal(self, cur, tmdb_id: int) -> Dict:
        # Check cache first
        cur.execute("""
            SELECT api_response 
            FROM tmdb_movie_cache 
            WHERE tmdb_id = %s
                AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
        """, (tmdb_id,))
        
        cache_result = cur.fetchone()
        
        if cache_result:
            print("Found Cached result for movie ID: ", tmdb_id)
            return cache_result[0]
            
        # If not in cache, call API
        print(f"Calling TMDB API: movie.info for movie ID {tmdb_id}")
        movie = tmdb.Movies(tmdb_id)
        response = movie.info(append_to_response="credits,external_ids,release_dates,watch/providers")
        
        # Cache the results
        cur.execute("""
            INSERT INTO tmdb_movie_cache 
            (tmdb_id, api_response, creation_date, expires_after_minutes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tmdb_id) DO UPDATE
            SET api_response = EXCLUDED.api_response,
                creation_date = EXCLUDED.creation_date,
                expires_after_minutes = EXCLUDED.expires_after_minutes
        """, (
            tmdb_id,
            Json(response),
            datetime.now(),
            self.CACHE_EXPIRY_MINUTES
        ))
        return response

    def _get_omdb_movie_info_internal(self, cur, imdb_id: str) -> Dict:
        # Check cache first
        cur.execute("""
            SELECT api_response 
            FROM omdb_movie_cache 
            WHERE imdb_id = %s
                AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
        """, (imdb_id,))
        
        cache_result = cur.fetchone()
        
        if cache_result:
            print("Found Cached result for IMDB ID: ", imdb_id)
            return cache_result[0]
            
        # If not in cache, call API
        print(f"Calling OMDB API: get_movie for IMDB ID {imdb_id}")
        omdb = OMDB(os.getenv("OMDB_API_KEY"))
        response = omdb.get_movie(imdbid=imdb_id, plot="full")
        
        # Cache the results
        cur.execute("""
            INSERT INTO omdb_movie_cache 
            (imdb_id, api_response, creation_date, expires_after_minutes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (imdb_id) DO UPDATE
            SET api_response = EXCLUDED.api_response,
                creation_date = EXCLUDED.creation_date,
                expires_after_minutes = EXCLUDED.expires_after_minutes
        """, (
            imdb_id,
            Json(response),
            datetime.now(),
            self.CACHE_EXPIRY_MINUTES
        ))
        return response

    def _get_collection_info_internal(self, cur, collection_id: int) -> Dict:
        # Check cache first
        cur.execute("""
            SELECT api_response 
            FROM tmdb_collection_cache 
            WHERE collection_id = %s
                AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
        """, (collection_id,))
        
        cache_result = cur.fetchone()
        
        if cache_result:
            print("Found Cached result for collection ID: ", collection_id)
            return cache_result[0]
            
        # If not in cache, call API
        print(f"Calling TMDB API: collection.info for collection ID {collection_id}")
        collection = tmdb.Collections(collection_id)
        response = collection.info()
        
        # Cache the results
        cur.execute("""
            INSERT INTO tmdb_collection_cache 
            (collection_id, api_response, creation_date, expires_after_minutes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (collection_id) DO UPDATE
            SET api_response = EXCLUDED.api_response,
                creation_date = EXCLUDED.creation_date,
                expires_after_minutes = EXCLUDED.expires_after_minutes
        """, (
            collection_id,
            Json(response),
            datetime.now(),
            self.CACHE_EXPIRY_MINUTES
        ))
        return response

    def _get_tv_info_internal(self, cur, tmdb_id: int) -> Dict:
        # Check cache first
        cur.execute("""
            SELECT api_response 
            FROM tmdb_tv_cache 
            WHERE tmdb_id = %s
                AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
        """, (tmdb_id,))
        
        cache_result = cur.fetchone()
        
        if cache_result:
            print("Found Cached result for TV show ID: ", tmdb_id)
            return cache_result[0]
            
        # If not in cache, call API
        print(f"Calling TMDB API: tv.info for TV show ID {tmdb_id}")
        tv = tmdb.TV(tmdb_id)
        response = tv.info(append_to_response="credits,external_ids,content_ratings,watch/providers")
        
        # Cache the results
        cur.execute("""
            INSERT INTO tmdb_tv_cache 
            (tmdb_id, api_response, creation_date, expires_after_minutes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tmdb_id) DO UPDATE
            SET api_response = EXCLUDED.api_response,
                creation_date = EXCLUDED.creation_date,
                expires_after_minutes = EXCLUDED.expires_after_minutes
        """, (
            tmdb_id,
            Json(response),
            datetime.now(),
            self.CACHE_EXPIRY_MINUTES
        ))
        return response

    def _get_omdb_tv_info_internal(self, cur, imdb_id: str) -> Dict:
        # Check cache first
        cur.execute("""
            SELECT api_response 
            FROM omdb_tv_cache 
            WHERE imdb_id = %s
                AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
        """, (imdb_id,))
        
        cache_result = cur.fetchone()
        
        if cache_result:
            print("Found Cached result for TV show IMDB ID: ", imdb_id)
            return cache_result[0]
            
        # If not in cache, call API
        print(f"Calling OMDB API: get_series for IMDB ID {imdb_id}")
        omdb = OMDB(os.getenv("OMDB_API_KEY"))
        response = omdb.get_series(imdbid=imdb_id, plot="full")
        
        # Cache the results
        cur.execute("""
            INSERT INTO omdb_tv_cache 
            (imdb_id, api_response, creation_date, expires_after_minutes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (imdb_id) DO UPDATE
            SET api_response = EXCLUDED.api_response,
                creation_date = EXCLUDED.creation_date,
                expires_after_minutes = EXCLUDED.expires_after_minutes
        """, (
            imdb_id,
            Json(response),
            datetime.now(),
            self.CACHE_EXPIRY_MINUTES
        ))
        return response

    def _get_season_info_internal(self, cur, tmdb_id: int, season_number: int) -> Dict:
        # Check cache first
        cur.execute("""
            SELECT api_response 
            FROM tmdb_season_cache 
            WHERE tmdb_id = %s AND season_number = %s
                AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
        """, (tmdb_id, season_number))
        
        cache_result = cur.fetchone()
        
        if cache_result:
            print(f"Found Cached result for TV show ID {tmdb_id}, season {season_number}")
            return cache_result[0]
            
        # If not in cache, call API
        print(f"Calling TMDB API: season.info for TV show ID {tmdb_id}, season {season_number}")
        season = tmdb.TV_Seasons(tmdb_id, season_number)
        response = season.info(append_to_response="account_states,credits,external_ids")
        
        # Cache the results
        cur.execute("""
            INSERT INTO tmdb_season_cache 
            (id, tmdb_id, season_number, api_response, creation_date, expires_after_minutes)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tmdb_id, season_number) DO UPDATE
            SET api_response = EXCLUDED.api_response,
                creation_date = EXCLUDED.creation_date,
                expires_after_minutes = EXCLUDED.expires_after_minutes
        """, (
            uuid.uuid4(),
            tmdb_id,
            season_number,
            Json(response),
            datetime.now(),
            self.CACHE_EXPIRY_MINUTES
        ))
        return response

    def _get_people_info_internal(self, cur, tmdb_id: int) -> Dict:
        # Check cache first
        cur.execute("""
            SELECT api_response 
            FROM tmdb_people_cache 
            WHERE tmdb_id = %s
                AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
        """, (tmdb_id,))
        
        cache_result = cur.fetchone()
        
        if cache_result:
            print("Found Cached result for person ID: ", tmdb_id)
            return cache_result[0]
            
        # If not in cache, call API
        print(f"Calling TMDB API: people.info for person ID {tmdb_id}")
        people = tmdb.People(tmdb_id)
        response = people.info(append_to_response="combined_credits,external_ids")
        
        # Cache the results
        cur.execute("""
            INSERT INTO tmdb_people_cache 
            (tmdb_id, api_response, creation_date, expires_after_minutes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tmdb_id) DO UPDATE
            SET api_response = EXCLUDED.api_response,
                creation_date = EXCLUDED.creation_date,
                expires_after_minutes = EXCLUDED.expires_after_minutes
        """, (
            tmdb_id,
            Json(response),
            datetime.now(),
            self.CACHE_EXPIRY_MINUTES
        ))
        return response

    def _get_popular_list_internal(self, cur, media_type: str) -> Dict:
        if media_type not in ["movie", "tv", "person"]:
            raise ValueError('media_type must be one of "movie", "tv", or "person"')
            
        # Map media types to their corresponding cache tables
        cache_table_map = {
            "movie": "tmdb_popular_movies_cache",
            "tv": "tmdb_popular_tv_cache",
            "person": "tmdb_popular_people_cache"
        }
            
        # Check cache first
        cur.execute(f"""
            SELECT api_response 
            FROM {cache_table_map[media_type]} 
            WHERE CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
            ORDER BY creation_date DESC
            LIMIT 1
        """)
        
        cache_result = cur.fetchone()
        
        if cache_result:
            print(f"Found Cached result for popular {media_type} list")
            return cache_result[0]
            
        # If not in cache, call API
        print(f"Calling TMDB API: {media_type}.popular()")
        if media_type == "movie":
            media_type_object = tmdb.Movies()
        elif media_type == "tv":
            media_type_object = tmdb.TV()
        else:  # person
            media_type_object = tmdb.People()
            
        response = media_type_object.popular()
        
        # Cache the results
        cur.execute(f"""
            INSERT INTO {cache_table_map[media_type]} 
            (id, api_response, creation_date, expires_after_minutes)
            VALUES (%s, %s, %s, %s)
        """, (
            uuid.uuid4(),
            Json(response),
            datetime.now(),
            self.CACHE_EXPIRY_MINUTES
        ))
        return response

    def _get_top_rated_list_internal(self, cur, media_type: str) -> Dict:
        if media_type not in ["movie", "tv"]:
            raise ValueError('media_type must be one of "movie" or "tv"')
            
        # Map media types to their corresponding cache tables
        cache_table_map = {
            "movie": "tmdb_top_rated_movies_cache",
            "tv": "tmdb_top_rated_tv_cache"
        }
            
        # Check cache first
        cur.execute(f"""
            SELECT api_response 
            FROM {cache_table_map[media_type]} 
            WHERE CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
            ORDER BY creation_date DESC
            LIMIT 1
        """)
        
        cache_result = cur.fetchone()
        
        if cache_result:
            print(f"Found Cached result for top rated {media_type} list")
            return cache_result[0]
            
        # If not in cache, call API
        print(f"Calling TMDB API: {media_type}.top_rated()")
        if media_type == "movie":
            media_type_object = tmdb.Movies()
        else:  # tv
            media_type_object = tmdb.TV()
            
        response = media_type_object.top_rated()
        
        # Cache the results
        cur.execute(f"""
            INSERT INTO {cache_table_map[media_type]} 
            (id, api_response, creation_date, expires_after_minutes)
            VALUES (%s, %s, %s, %s)
        """, (
            uuid.uuid4(),
            Json(response),
            datetime.now(),
            self.CACHE_EXPIRY_MINUTES
        ))
        return response 