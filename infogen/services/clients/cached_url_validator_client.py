import requests
from typing import Dict, Optional
from urllib.parse import urlparse, quote
import re
from langchain.tools import StructuredTool
import warnings
from urllib3.exceptions import InsecureRequestWarning
from infogen.core.logging_config import get_logger
import psycopg2
from psycopg2.extras import Json, register_uuid
from psycopg2.pool import ThreadedConnectionPool
import uuid
from datetime import datetime
import os
import threading

# Configure logging
logger = get_logger(__name__)

# Disable SSL verification warnings
warnings.filterwarnings('ignore', category=InsecureRequestWarning)

class URLValidatorClient:
    # Common browser headers to avoid 403 errors
    DEFAULT_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Cache-Control': 'max-age=0',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Sec-Ch-Ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"macOS"',
        'Referer': 'https://www.google.com/'
    }

    # Status codes that indicate the URL is technically valid even if not accessible
    VALID_BUT_RESTRICTED_CODES = {
        401,  # Unauthorized but exists
        403,  # Forbidden but exists
        405,  # Method not allowed but exists
        451,  # Unavailable for legal reasons but exists
        999,  # LinkedIn and others custom "denied" code
    }
    
    # Configuration constants
    CACHE_EXPIRY_MINUTES = 14400  # 10 days by default
    _instance_lock = threading.Lock()
    _connection_pools = {}  # Dictionary to store connection pools per process

    def __init__(self, db_connection_string: Optional[str] = None, min_connections: int = 1, max_connections: int = 20):
        """
        Initialize the URL validator client with optional caching support.
        
        Args:
            db_connection_string: PostgreSQL connection string for caching. If None, caching is disabled.
            min_connections: Minimum number of database connections in the pool
            max_connections: Maximum number of database connections in the pool
        """
        logger.debug("Initializing URLValidatorClient")
        
        self.use_cache = db_connection_string is not None
        
        if self.use_cache:
            # Register UUID type adapter
            register_uuid()
            
            # Create a unique key for this process's connection pool
            self._process_key = os.getpid()
            self._thread_id = threading.get_ident()
            logger.info(f"[INIT] Initializing URLValidatorClient with caching for process {self._process_key}, thread {self._thread_id}")
            
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
        else:
            logger.info("Initializing URLValidatorClient without caching")

    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        
    def close(self):
        """Close all connections and clean up resources for this process"""
        if not self.use_cache:
            return
            
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
        if not self.use_cache:
            raise ValueError("Cannot execute database operations when caching is disabled")
            
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

    def _get_session(self) -> requests.Session:
        """
        Creates a new session with proper headers.
        Thread-safe as it creates a new session each time.
        """
        logger.debug("Creating new requests session with custom headers")
        session = requests.Session()
        session.headers.update(self.DEFAULT_HEADERS)
        return session

    @staticmethod
    def _clean_url(url: str) -> str:
        """
        Clean and normalize the URL by:
        - Removing leading/trailing whitespace
        - Ensuring proper encoding of special characters
        - Handling common URL formatting issues
        """
        logger.debug(f"Cleaning URL: {url}")
        url = url.strip()
        url_parts = url.split('#', 1)
        base_url = url_parts[0]
        anchor = f"#{url_parts[1]}" if len(url_parts) > 1 else ""
        safe_chars = ':/?=&%@+,;'
        base_url = quote(base_url, safe=safe_chars)
        cleaned_url = base_url + anchor
        logger.debug(f"Cleaned URL: {cleaned_url}")
        return cleaned_url
    
    @staticmethod
    def _validate_image(session: requests.Session, url: str) -> bool:
        """
        Performs additional validation for image URLs by checking the actual content.
        """
        logger.debug(f"Performing image validation for URL: {url}")
        try:
            response = session.get(url, timeout=10, stream=True)
            content = next(response.iter_content(32))
            response.close()
            signatures = {
                b'\xFF\xD8\xFF': 'jpeg',
                b'\x89PNG\r\n\x1a\n': 'png',
                b'GIF87a': 'gif',
                b'GIF89a': 'gif',
                b'RIFF': 'webp'
            }
            is_valid = any(content.startswith(sig) for sig in signatures.keys())
            logger.debug(f"Image validation result for {url}: {is_valid}")
            return is_valid
        except Exception as e:
            logger.error(f"Error during image validation for {url}: {str(e)}")
            return False

    def _check_cache(self, url: str) -> Optional[bool]:
        """
        Check if the URL validation result is in the cache.
        
        Args:
            url: The URL to check
            
        Returns:
            bool or None: The cached validation result, or None if not in cache
        """
        if not self.use_cache:
            return None
            
        def check_cache_internal(cur):
            cur.execute("""
                SELECT is_valid
                FROM url_validation_cache
                WHERE url = %s
                    AND CURRENT_TIMESTAMP < creation_date + (expires_after_minutes * interval '1 minute')
                LIMIT 1
            """, (url,))
            
            result = cur.fetchone()
            return result[0] if result else None
            
        try:
            return self._execute_with_connection(check_cache_internal)
        except Exception as e:
            logger.error(f"Error checking cache for URL {url}: {str(e)}")
            return None
            
    def _cache_result(self, url: str, is_valid: bool) -> None:
        """
        Cache the URL validation result.
        
        Args:
            url: The URL that was validated
            is_valid: Whether the URL is valid
        """
        if not self.use_cache:
            return
            
        def cache_result_internal(cur):
            cur.execute("""
                INSERT INTO url_validation_cache 
                (id, url, is_valid, creation_date, expires_after_minutes)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (url) DO UPDATE
                SET is_valid = EXCLUDED.is_valid,
                    creation_date = EXCLUDED.creation_date,
                    expires_after_minutes = EXCLUDED.expires_after_minutes
            """, (
                uuid.uuid4(),
                url,
                is_valid,
                datetime.now(),
                self.CACHE_EXPIRY_MINUTES
            ))
            
        try:
            self._execute_with_connection(cache_result_internal)
            logger.debug(f"Cached validation result for URL {url}: {is_valid}")
        except Exception as e:
            logger.error(f"Error caching result for URL {url}: {str(e)}")

    def validate_url(self, url: str) -> bool:
        """
        Validates a URL by checking its accessibility and content.
        Uses caching if enabled to avoid repeated validation of the same URL.
        
        Args:
            url: The URL to validate
            
        Returns:
            bool: True if the URL is valid and accessible, False otherwise
        """
        logger.info(f"Validating URL: {url}")
        
        # Clean the URL first
        url = self._clean_url(url)
        
        # Check cache first if enabled
        if self.use_cache:
            cached_result = self._check_cache(url)
            if cached_result is not None:
                logger.info(f"[CACHE HIT] Found cached validation result for URL: {url} (valid: {cached_result})")
                return cached_result
            logger.debug(f"[CACHE MISS] No cached validation result for URL: {url}")
        
        # Validate URL format
        try:
            parsed = urlparse(url)
            if not all([parsed.scheme, parsed.netloc]):
                logger.warning(f"Invalid URL format: {url}")
                if self.use_cache:
                    self._cache_result(url, False)
                return False
        except Exception as e:
            logger.error(f"URL parsing error: {str(e)}")
            if self.use_cache:
                self._cache_result(url, False)
            return False

        def try_request(session: requests.Session, with_custom_headers: bool, verify_ssl: bool = True) -> tuple[bool, requests.Response | None]:
            """Helper function to try a request with or without custom headers and SSL verification"""
            try:
                if with_custom_headers:
                    # Add site-specific headers
                    additional_headers = {
                        'Host': parsed.netloc,
                        'Origin': f"{parsed.scheme}://{parsed.netloc}",
                        'authority': parsed.netloc,
                        'pragma': 'no-cache',
                    }
                    session.headers.update(additional_headers)
                    # Set a lower max_redirects to fail faster on redirect loops
                    session.max_redirects = 5
                
                logger.debug(f"Attempting request to {url} with custom_headers={with_custom_headers}, verify_ssl={verify_ssl}")
                response = session.get(url, allow_redirects=True, timeout=10, verify=verify_ssl)
                
                # If we got redirected, log the final URL for debugging
                if response.history:
                    logger.debug(f"URL was redirected: {url} -> {response.url}")
                
                content_type = response.headers.get('content-type', '').lower()
                
                # URL is valid if:
                # 1. It returns a success code (200-399)
                # 2. It returns a restricted code (401, 403, etc.) - means the URL exists but is protected
                is_valid = 200 <= response.status_code < 400 or response.status_code in self.VALID_BUT_RESTRICTED_CODES
                
                logger.debug(f"Response status: {response.status_code}, content-type: {content_type}, is_valid: {is_valid}")
                
                # For images, perform additional validation only if we have full access
                if is_valid and 'image' in content_type and response.status_code == 200:
                    is_valid = self._validate_image(session, response.url)  # Use final URL after redirects
                    if not is_valid:
                        logger.warning("Image validation failed: Invalid image format or corrupted data")
                
                return is_valid, response
                
            except requests.exceptions.SSLError as e:
                if verify_ssl:
                    # If SSL verification failed, return None to indicate we should retry without verification
                    logger.warning(f"SSL verification failed for {url}, will retry without verification")
                    return None, None
                else:
                    logger.error(f"SSL error for {url} even without verification: {str(e)}")
                    return False, None
            except requests.RequestException as e:
                logger.error(f"Request error for {url} {'with' if with_custom_headers else 'without'} custom headers: {str(e)}")
                return False, None
            except Exception as e:
                logger.error(f"Unexpected error while validating {url}: {str(e)}")
                return False, None
        
        # Try to access the URL using a new session
        session = None
        response = None
        try:
            # First try with custom headers and SSL verification
            session = self._get_session()
            is_valid, response = try_request(session, with_custom_headers=True, verify_ssl=True)
            
            # If we got None back, it means SSL failed - retry without verification
            if is_valid is None:
                if session:
                    session.close()
                session = self._get_session()
                is_valid, response = try_request(session, with_custom_headers=True, verify_ssl=False)
                if is_valid:
                    logger.info(f"URL {url} is valid (with custom headers, without SSL verification)")
                    if self.use_cache:
                        self._cache_result(url, True)
                    return True
            elif is_valid:
                logger.info(f"URL {url} is valid (with custom headers and SSL verification)")
                if self.use_cache:
                    self._cache_result(url, True)
                return True
                
            # If that failed, try without custom headers
            if session:
                session.close()
            session = self._get_session()
            is_valid, response = try_request(session, with_custom_headers=False, verify_ssl=False)
            
            if is_valid:
                logger.info(f"URL {url} is valid (without custom headers, without SSL verification)")
            else:
                logger.warning(f"URL {url} is invalid (all validation attempts failed)")
            
            # Cache the result if caching is enabled
            if self.use_cache:
                self._cache_result(url, is_valid)
                
            return is_valid
            
        finally:
            if response:
                response.close()
            if session:
                session.close()

    @classmethod
    def get_url_validator_tool(cls, db_connection_string: Optional[str] = None) -> StructuredTool:
        """
        Returns a StructuredTool for use with LangGraph agents that validates URLs.
        
        Args:
            db_connection_string: Optional PostgreSQL connection string for caching
            
        Returns:
            StructuredTool: A tool that can be used by LangGraph agents to validate URLs
        """
        logger.debug("Creating URL validator tool for LangGraph agents")
        validator = cls(db_connection_string=db_connection_string)
        return StructuredTool.from_function(
            func=validator.validate_url,
            name="validate_url",
            description="Use this tool to validate a URL and check if it is accessible. Returns True if the URL is valid and accessible, False otherwise."
        ) 