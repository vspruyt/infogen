import unittest
from unittest.mock import patch, MagicMock, call, ANY
import json
import datetime
import uuid
from infogen.services.clients.cached_tmdb_client import CachedTMDBClient

class TestCachedTMDBClient(unittest.TestCase):
    """Test cases for the CachedTMDBClient."""

    def setUp(self):
        """Set up test fixtures."""
        # Mock tmdb module
        self.mock_tmdb = MagicMock()
        self.mock_search = MagicMock()
        self.mock_tmdb.Search.return_value = self.mock_search
        self.tmdb_patcher = patch('infogen.services.clients.cached_tmdb_client.tmdb', self.mock_tmdb)
        self.tmdb_patcher.start()
        
        # Mock UUID
        self.mock_uuid = MagicMock(return_value="test-uuid")
        self.uuid_patcher = patch('uuid.uuid4', self.mock_uuid)
        self.uuid_patcher.start()
        
        # Mock ThreadedConnectionPool
        self.mock_pool = MagicMock()
        self.mock_pool_class = MagicMock(return_value=self.mock_pool)
        self.pool_patcher = patch('infogen.services.clients.cached_tmdb_client.ThreadedConnectionPool', self.mock_pool_class)
        self.pool_patcher.start()
        
        # Mock cursor and connection
        self.mock_cursor = MagicMock()
        self.mock_connection = MagicMock()
        self.mock_connection.cursor.return_value = self.mock_cursor
        self.mock_pool.getconn.return_value = self.mock_connection
        
        # Clear the connection pools dictionary to ensure a new pool is created
        CachedTMDBClient._connection_pools = {}
        
        # Create client
        self.client = CachedTMDBClient(
            api_key="test_api_key",
            db_connection_string="test_connection_string"
        )

    def tearDown(self):
        """Tear down test fixtures."""
        self.tmdb_patcher.stop()
        self.uuid_patcher.stop()
        self.pool_patcher.stop()

    def test_init(self):
        """Test initialization of the client."""
        # Verify connection pool was created with the correct parameters
        self.mock_pool_class.assert_called_once_with(
            1,  # min_connections
            20,  # max_connections
            "test_connection_string"
        )

    def test_close(self):
        """Test closing the client."""
        # Set up a connection in the thread local
        self.client._local.connection = self.mock_connection
        
        # Close the client
        self.client.close()
        
        # Verify connection was returned to the pool
        self.mock_pool.putconn.assert_called_once_with(self.mock_connection)

    def test_context_manager(self):
        """Test the client as a context manager."""
        # Use client as context manager
        with patch.object(CachedTMDBClient, 'close') as mock_close:
            with self.client:
                pass
            
            # Verify close was called
            mock_close.assert_called_once()

    def test_search_multi_cached_result(self):
        """Test search_multi method with a cached result."""
        # Setup mock result
        mock_result = {
            "results": [{"title": "Test Movie", "media_type": "movie"}]
        }
        self.mock_cursor.fetchone.return_value = (mock_result,)
        
        # Test
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.search_multi("test query")
            
            # Verify result
            self.assertEqual(result, mock_result)
            
            # Verify SQL query was executed
            self.mock_cursor.execute.assert_called_once()
            self.assertIn("SELECT api_response", self.mock_cursor.execute.call_args[0][0])
            self.assertIn("FROM tmdb_search_cache", self.mock_cursor.execute.call_args[0][0])

    def test_search_multi_no_cached_result(self):
        """Test search_multi method with no cached result."""
        # Setup mock result
        self.mock_cursor.fetchone.return_value = None
        mock_api_response = {
            "results": [{"title": "Test Movie", "media_type": "movie"}]
        }
        self.mock_search.multi.return_value = mock_api_response
        
        # Test
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.search_multi("test query")
            
            # Verify API was called
            self.mock_search.multi.assert_called_once_with(query="test query", include_adult=False)
            
            # Verify result
            self.assertEqual(result, mock_api_response)
            
            # Verify result was cached
            self.assertEqual(self.mock_cursor.execute.call_count, 2)
            self.assertIn("INSERT INTO tmdb_search_cache", self.mock_cursor.execute.call_args_list[1][0][0])

    def test_get_movie_info_cached_result(self):
        """Test get_movie_info method with a cached result."""
        # Setup mock result
        mock_result = {
            "id": 123,
            "title": "Test Movie",
            "overview": "Test overview"
        }
        self.mock_cursor.fetchone.return_value = (mock_result,)
        
        # Test
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.get_movie_info(123)
            
            # Verify result
            self.assertEqual(result, mock_result)
            
            # Verify SQL query was executed
            self.mock_cursor.execute.assert_called_once()
            self.assertIn("SELECT api_response", self.mock_cursor.execute.call_args[0][0])
            self.assertIn("FROM tmdb_movie_cache", self.mock_cursor.execute.call_args[0][0])

    def test_get_movie_info_no_cached_result(self):
        """Test get_movie_info method with no cached result."""
        # Setup mock result
        self.mock_cursor.fetchone.return_value = None
        mock_api_response = {
            "id": 123,
            "title": "Test Movie",
            "overview": "Test overview"
        }
        self.mock_tmdb.Movies.return_value.info.return_value = mock_api_response
        
        # Test
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.get_movie_info(123)
            
            # Verify API was called
            self.mock_tmdb.Movies.assert_called_once_with(123)
            self.mock_tmdb.Movies.return_value.info.assert_called_once()
            
            # Verify result
            self.assertEqual(result, mock_api_response)
            
            # Verify result was cached
            self.assertEqual(self.mock_cursor.execute.call_count, 2)
            self.assertIn("INSERT INTO tmdb_movie_cache", self.mock_cursor.execute.call_args_list[1][0][0])

    def test_get_tv_info_cached_result(self):
        """Test get_tv_info method with a cached result."""
        # Setup mock result
        mock_result = {
            "id": 123,
            "name": "Test TV Show",
            "overview": "Test overview"
        }
        self.mock_cursor.fetchone.return_value = (mock_result,)
        
        # Test
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.get_tv_info(123)
            
            # Verify result
            self.assertEqual(result, mock_result)
            
            # Verify SQL query was executed
            self.mock_cursor.execute.assert_called_once()
            self.assertIn("SELECT api_response", self.mock_cursor.execute.call_args[0][0])
            self.assertIn("FROM tmdb_tv_cache", self.mock_cursor.execute.call_args[0][0])

    def test_get_popular_list(self):
        """Test get_popular_list method."""
        # Setup mock result
        mock_result = {
            "results": [{"title": "Popular Movie", "id": 123}]
        }
        self.mock_cursor.fetchone.return_value = (mock_result,)
        
        # Test
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.get_popular_list("movie")
            
            # Verify result
            self.assertEqual(result, mock_result)
            
            # Verify SQL query was executed
            self.mock_cursor.execute.assert_called_once()
            self.assertIn("SELECT api_response", self.mock_cursor.execute.call_args[0][0])
            self.assertIn("FROM tmdb_popular_movies_cache", self.mock_cursor.execute.call_args[0][0])

if __name__ == '__main__':
    unittest.main() 