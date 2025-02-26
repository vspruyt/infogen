import musicbrainzngs
from typing import Dict, Optional
import psycopg2
from psycopg2.extras import Json, register_uuid
from psycopg2.pool import ThreadedConnectionPool
import uuid
from datetime import datetime, timedelta
import os
import threading
import pylast

class CachedMusicBrainzClient:
    # Configuration constants
    CACHE_EXPIRY_MINUTES = 14400  # 10 days by default
    _instance_lock = threading.Lock()
    _connection_pools = {}  # Dictionary to store connection pools per process
    
    def __init__(self, app_name: str, app_version: str, app_contact: str, db_connection_string: str, min_connections: int = 1, max_connections: int = 20):
        """
        Initialize the CachedMusicBrainzClient with connection pooling support.
        
        Args:
            app_name: Name of your application
            app_version: Version of your application
            app_contact: Contact information (email)
            db_connection_string: PostgreSQL connection string
            min_connections: Minimum number of database connections in the pool
            max_connections: Maximum number of database connections in the pool
        """
        # Set up MusicBrainz API
        musicbrainzngs.set_useragent(app_name, app_version, app_contact)
        
        # Register UUID type adapter
        register_uuid()
        
        # Create a unique key for this process's connection pool
        self._process_key = os.getpid()
        self._thread_id = threading.get_ident()
        print(f"[INIT] Initializing CachedMusicBrainzClient for process {self._process_key}, thread {self._thread_id}")
        
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
        
    def _get_connection(self):
        """Get a connection from the pool"""
        thread_id = threading.get_ident()
        process_key = os.getpid()
        
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            print(f"[CONN] Getting new connection for process {process_key}, thread {thread_id}")
            try:
                self._local.connection = self._db_pool.getconn()
                print(f"[CONN] Got connection for process {process_key}, thread {thread_id}. Pool status: used={len(self._db_pool._used)}, idle={len(self._db_pool._pool)}")
            except Exception as e:
                print(f"[ERROR] Error getting connection for process {process_key}, thread {thread_id}: {str(e)}")
                raise
        return self._local.connection
        
    def _put_connection(self, conn):
        """Return a connection to the pool"""
        thread_id = threading.get_ident()
        process_key = os.getpid()
        
        if hasattr(self._local, 'connection') and self._local.connection is not None:
            try:
                print(f"[CONN] Returning connection for process {process_key}, thread {thread_id}")
                self._db_pool.putconn(self._local.connection)
                self._local.connection = None
                print(f"[CONN] Returned connection. Pool status: used={len(self._db_pool._used)}, idle={len(self._db_pool._pool)}")
            except Exception as e:
                print(f"[ERROR] Error returning connection for process {process_key}, thread {thread_id}: {str(e)}")
                raise
                
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

    def _execute_with_connection_async(self, operation):
        """Execute an operation with proper connection handling for async operations"""
        thread_id = threading.get_ident()
        process_key = os.getpid()
        
        # Get a fresh connection for the async operation
        print(f"[CONN] Getting new connection for async operation in process {process_key}, thread {thread_id}")
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
            print(f"[CONN] Returning connection for async operation in process {process_key}, thread {thread_id}")
            self._db_pool.putconn(conn)

    def search_multi(self, api_search_query: str, media_type: str, artist_name: Optional[str] = None) -> Dict:
        """
        Search for artists, albums, or songs using MusicBrainz API, with caching support.
        
        Args:
            api_search_query: The search query string
            media_type: Type of media to search for ("artist", "album", or "song")
            artist_name: Optional artist name for filtering album and song searches
            
        Returns:
            Dict containing search results
        """
        if media_type not in ["artist", "album", "song"]:
            raise ValueError('media_type must be one of "artist", "album", or "song"')
            
        return self._execute_with_connection(lambda cur: self._search_multi_internal(cur, api_search_query, media_type, artist_name))

    def _search_multi_internal(self, cur, api_search_query: str, media_type: str, artist_name: Optional[str] = None) -> Dict:
        # Check cache first
        cur.execute("""
            SELECT api_response 
            FROM musicbrainz_search_cache 
            WHERE query = %s AND media_type = %s AND (artist_name = %s OR %s IS NULL)
                AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
        """, (api_search_query, media_type, artist_name, artist_name))
        
        cache_result = cur.fetchone()
        
        if cache_result:
            print(f"Found Cached result for {media_type} query: {api_search_query}")
            return cache_result[0]
            
        # If not in cache, call appropriate API based on media type
        print(f"Calling MusicBrainz API: search_{media_type}s for query '{api_search_query}'")
        
        if media_type == "artist":
            response = musicbrainzngs.search_artists(query=api_search_query, limit=10)
        elif media_type == "album":
            response = musicbrainzngs.search_release_groups(
                query=api_search_query,
                strict=True,
                limit=10,
                artistname=artist_name,
                type="Album",
                primarytype="Album"
            )
        else:  # song
            response = musicbrainzngs.search_recordings(
                query=api_search_query,
                strict=True,
                limit=5,
                artistname=artist_name
            )
        
        # Cache the results
        cur.execute("""
            INSERT INTO musicbrainz_search_cache 
            (id, query, media_type, artist_name, api_response, creation_date, expires_after_minutes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (query, media_type, artist_name) DO UPDATE
            SET api_response = EXCLUDED.api_response,
                creation_date = EXCLUDED.creation_date,
                expires_after_minutes = EXCLUDED.expires_after_minutes
        """, (
            uuid.uuid4(),
            api_search_query,
            media_type,
            artist_name,
            Json(response),
            datetime.now(),
            self.CACHE_EXPIRY_MINUTES
        ))
        return response

    def get_release_info_from_album(self, album_release_list: list) -> Dict:
        """Helper function to get the most relevant release from an album's release list"""
        if not album_release_list:
            return None
            
        # Find the most important release
        found_release = []
        
        # international standard version
        
        # First, let's try to find an international release
        for release in album_release_list:
            if 'disambiguation' in release and release['disambiguation']=="international standard version":
                found_release.append(release)
        
        # Otherwise, let's try to find a standard version
        if len(found_release)==0:
            for release in album_release_list:
                if 'disambiguation' in release and "standard" in release['disambiguation']:
                    found_release.append(release)
        
        
        # Otherwise, let's try to find a release in the US, where 'disambiguation' is None (so that it's not a special edition)
        if len(found_release)==0:
            for release in album_release_list:
                if 'country' in release and release['country']=='US' and release.get('disambiguation') is None:
                    found_release.append(release)
        
        # Otherwise, try to find the releases in the US
        if len(found_release)==0:
            for release in album_release_list:
                if 'country' in release and release['country']=='US':
                    found_release.append(release)
        
        # Otherwise, try to find the releases in the English and non-special editions
        if len(found_release)==0:
            for release in album_release_list:
                if release.get('disambiguation') is None and 'text-representation' in release and 'language' in release['text-representation'] and release['text-representation']['language']=='eng':
                    found_release.append(release)
        
        # Otherwise, try to find the releases in the English
        if len(found_release)==0:
            for release in album_release_list:
                if 'text-representation' in release and 'language' in release['text-representation'] and release['text-representation']['language']=='eng':
                    found_release.append(release)
        
        # Otherwise, try to find non-special editions
        if len(found_release)==0:
            for release in album_release_list:
                if release.get('disambiguation') is None:
                    found_release.append(release)
        
        # Otherwise, add the all to the list
        if len(found_release)==0:
            found_release = album_release_list
        
        # Now we sort the list by date, assuming the oldest date was the original release
        found_release.sort(key=lambda x: x['date'])
                    
        main_release_id = found_release[0]['id']
        
        return self._execute_with_connection(lambda cur: self._get_release_info_internal(cur, main_release_id))

    def _get_release_info_internal(self, cur, main_release_id: str) -> Dict:
        cur.execute("""
            SELECT api_response 
            FROM musicbrainz_release_cache 
            WHERE mbid = %s
                AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
        """, (main_release_id,))
        
        cache_result = cur.fetchone()
        
        if cache_result:
            print(f"Found Cached result for release MBID: {main_release_id}")
            return cache_result[0]

        # If not in cache, call API
        print(f"Calling MusicBrainz API: get_release_by_id for MBID {main_release_id}")
        response = musicbrainzngs.get_release_by_id(main_release_id, includes=["recordings"])
        
        # Cache the results
        cur.execute("""
            INSERT INTO musicbrainz_release_cache 
            (mbid, api_response, creation_date, expires_after_minutes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (mbid) DO UPDATE
            SET api_response = EXCLUDED.api_response,
                creation_date = EXCLUDED.creation_date,
                expires_after_minutes = EXCLUDED.expires_after_minutes
        """, (
            main_release_id,
            Json(response),
            datetime.now(),
            self.CACHE_EXPIRY_MINUTES
        ))
        
        return response

    def get_music_details(self, mbid: str, media_type: str) -> Dict:
        """
        Get detailed music information from MusicBrainz API, with caching support.
        
        Args:
            mbid: The MusicBrainz ID
            media_type: Type of media ("artist", "album", or "song")
            
        Returns:
            Dict containing details including related information and relationships
        """
        if media_type not in ["artist", "album", "song"]:
            raise ValueError('media_type must be one of "artist", "album", or "song"')
            
        # Use the async-safe version for this method since it's called in an async context
        return self._execute_with_connection_async(lambda cur: self._get_music_details_internal(cur, mbid, media_type))

    def _get_music_details_internal(self, cur, mbid: str, media_type: str) -> Dict:
        # Map media types to their corresponding cache tables
        cache_table_map = {
            "artist": "musicbrainz_artist_cache",
            "album": "musicbrainz_album_cache",
            "song": "musicbrainz_song_cache"
        }
            
        cur.execute(f"""
            SELECT api_response 
            FROM {cache_table_map[media_type]} 
            WHERE mbid = %s
                AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
        """, (mbid,))
        
        cache_result = cur.fetchone()
        
        if cache_result:
            print(f"Found Cached result for {media_type} MBID: {mbid}")
            return cache_result[0]
            
        # If not in cache, call appropriate API based on media type
        print(f"Calling MusicBrainz API: get_{media_type} for MBID {mbid}")
        
        if media_type == "artist":
            response = musicbrainzngs.get_artist_by_id(
                mbid,
                includes=["recordings", "release-groups", "aliases", "url-rels"]
            )
        elif media_type == "album":
            response = musicbrainzngs.get_release_group_by_id(
                mbid,
                includes=["artists", "releases", "discids", "media", "artist-credits",
                         "annotation", "aliases", "tags", "ratings", "url-rels"]
            )
            
            # Get additional release information if available
            if 'release-list' in response['release-group']:
                release = self.get_release_info_from_album(response['release-group']['release-list'])
                if release:                        
                    response['main release']={
                        "description": "This is the main release which contains the tracks/songs that can be shown to the user. (Don't call it 'main release' in your report though!)",
                        "release info": release
                    }
        else:  # song
            response = musicbrainzngs.get_recording_by_id(
                mbid,
                includes=["artists", "releases", "artist-credits", "work-level-rels",
                         "tags", "ratings", "url-rels"]
            )
        
        # Cache the results
        cur.execute(f"""
            INSERT INTO {cache_table_map[media_type]} 
            (mbid, api_response, creation_date, expires_after_minutes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (mbid) DO UPDATE
            SET api_response = EXCLUDED.api_response,
                creation_date = EXCLUDED.creation_date,
                expires_after_minutes = EXCLUDED.expires_after_minutes
        """, (
            mbid,
            Json(response),
            datetime.now(),
            self.CACHE_EXPIRY_MINUTES
        ))
        
        return response

    def get_artist_bio(self, mbid: str) -> Optional[Dict]:
        """
        Get artist biography from LastFM API, with caching support.
        
        Args:
            mbid: The MusicBrainz ID of the artist
            
        Returns:
            Dict containing the artist's biography and related information, or None if not found
        """
        return self._execute_with_connection(lambda cur: self._get_artist_bio_internal(cur, mbid))

    def _get_artist_bio_internal(self, cur, mbid: str) -> Optional[Dict]:
        cur.execute("""
            SELECT api_response 
            FROM lastfm_artist_bio_cache 
            WHERE mbid = %s
                AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
        """, (mbid,))
        
        cache_result = cur.fetchone()
        
        if cache_result:
            print(f"Found Cached result for artist bio MBID: {mbid}")
            return cache_result[0]
            
        # If not in cache, call LastFM API
        print(f"Calling LastFM API: get_artist_bio for MBID {mbid}")
        
        # Initialize LastFM API
        lastfm_network = pylast.LastFMNetwork(
            api_key=os.getenv("LAST_FM_API_KEY"),
            api_secret=os.getenv("LAST_FM_API_SECRET")
        )
        
        # Get artist bio
        last_fm_artist = lastfm_network.get_artist_by_mbid(mbid)
        if not last_fm_artist:
            print(f"No LastFM artist found for MBID: {mbid}")
            return None
            
        bio = last_fm_artist.get_bio_content()
        if not bio:
            print(f"No biography found for artist MBID: {mbid}")
            return None
            
        # Prepare response
        response = {
            "bio": bio,
            "source": "last.fm",
            "mbid": mbid,
            "artist_name": last_fm_artist.get_name()
        }
        
        # Cache the results
        cur.execute("""
            INSERT INTO lastfm_artist_bio_cache 
            (mbid, api_response, creation_date, expires_after_minutes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (mbid) DO UPDATE
            SET api_response = EXCLUDED.api_response,
                creation_date = EXCLUDED.creation_date,
                expires_after_minutes = EXCLUDED.expires_after_minutes
        """, (
            mbid,
            Json(response),
            datetime.now(),
            self.CACHE_EXPIRY_MINUTES
        ))
        
        return response 