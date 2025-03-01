import unittest
from unittest.mock import patch, MagicMock, call, ANY
import json
import datetime
import uuid
from infogen.services.clients.cached_tavily_client_v2 import CachedTavilyClient

class TestCachedTavilyClient(unittest.TestCase):
    """Test cases for the CachedTavilyClient."""

    def setUp(self):
        """Set up test fixtures."""
        # Mock TavilyClient
        self.mock_tavily_client = MagicMock()
        self.mock_tavily = MagicMock(return_value=self.mock_tavily_client)
        self.tavily_patcher = patch('infogen.services.clients.cached_tavily_client_v2.TavilyClient', self.mock_tavily)
        self.tavily_patcher.start()
        
        # Mock UUID
        self.mock_uuid = MagicMock(return_value="test-uuid")
        self.uuid_patcher = patch('uuid.uuid4', self.mock_uuid)
        self.uuid_patcher.start()
        
        # Mock ThreadedConnectionPool
        self.mock_pool = MagicMock()
        self.mock_pool_class = MagicMock(return_value=self.mock_pool)
        self.pool_patcher = patch('infogen.services.clients.cached_tavily_client_v2.ThreadedConnectionPool', self.mock_pool_class)
        self.pool_patcher.start()
        
        # Mock cursor and connection
        self.mock_cursor = MagicMock()
        self.mock_connection = MagicMock()
        self.mock_connection.cursor.return_value = self.mock_cursor
        self.mock_pool.getconn.return_value = self.mock_connection
        
        # Mock embedding client
        self.mock_embedding_client = MagicMock()
        self.mock_embedding_client.get_embedding.return_value = [0.1, 0.2, 0.3]
        
        # Clear the connection pools dictionary to ensure a new pool is created
        CachedTavilyClient._connection_pools = {}
        
        # Create client
        self.client = CachedTavilyClient(
            api_key="test_api_key",
            db_connection_string="test_connection_string",
            embedding_client=self.mock_embedding_client
        )

    def tearDown(self):
        """Tear down test fixtures."""
        self.tavily_patcher.stop()
        self.uuid_patcher.stop()
        self.pool_patcher.stop()

    def test_init(self):
        """Test initialization of the client."""
        # Verify TavilyClient was created with the correct API key
        self.mock_tavily.assert_called_once_with(api_key="test_api_key")
        
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
        with patch.object(CachedTavilyClient, 'close') as mock_close:
            with self.client:
                pass
            
            # Verify close was called
            mock_close.assert_called_once()

    def test_search_cached_result(self):
        """Test search method with a cached result."""
        # Setup mock result
        mock_result = {
            "query": "test query",
            "results": [{"title": "Test Result", "content": "Test content"}]
        }
        # Return a Python dictionary for the cached response, not a JSON string
        self.mock_cursor.fetchone.return_value = (mock_result, 10)
        
        # Test
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.search("test query")
            
            # Verify
            self.assertEqual(result, mock_result["results"])
            self.mock_cursor.execute.assert_called_with(ANY, ANY)
            self.mock_cursor.fetchone.assert_called_once()
            # Tavily API should not be called
            self.mock_tavily_client.search.assert_not_called()

    def test_search_no_cached_result(self):
        """Test search method with no cached result."""
        # Setup mock cursor to return no cached result
        self.mock_cursor.fetchone.return_value = None
        
        # Setup mock Tavily response
        mock_result = {
            "query": "test query",
            "results": [{"title": "Test Result", "content": "Test content"}]
        }
        self.mock_tavily_client.search.return_value = mock_result
        
        # Test
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.search("test query")
            
            # Verify
            self.assertEqual(result, mock_result["results"])
            self.mock_cursor.execute.assert_called()
            self.mock_cursor.fetchone.assert_called_once()
            
            # Tavily API should be called
            self.mock_tavily_client.search.assert_called_once()
            call_args = self.mock_tavily_client.search.call_args[1]
            self.assertEqual(call_args["query"], "test query")
            self.assertEqual(call_args["search_depth"], "advanced")
            self.assertEqual(call_args["max_results"], 5)
            self.assertFalse(call_args["include_answer"])
            self.assertFalse(call_args["include_raw_content"])
            self.assertFalse(call_args["include_images"])
            self.assertIsNone(call_args["exclude_domains"])
            self.assertIsNone(call_args["time_range"])

    def test_search_with_options(self):
        """Test search method with custom options."""
        # Setup mock cursor to return no cached result
        self.mock_cursor.fetchone.return_value = None
        
        # Setup mock Tavily response
        mock_result = {
            "query": "test query",
            "results": [{"title": "Test Result", "content": "Test content"}]
        }
        self.mock_tavily_client.search.return_value = mock_result
        
        # Test with custom options
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.search(
                query="test query",
                search_depth="basic",
                max_results=5,
                exclude_domains=["example.org"],
                time_range="day"
            )
            
            # Verify
            self.assertEqual(result, mock_result["results"])
            
            # Tavily API should be called with custom options
            self.mock_tavily_client.search.assert_called_once()
            call_args = self.mock_tavily_client.search.call_args[1]
            self.assertEqual(call_args["query"], "test query")
            self.assertEqual(call_args["search_depth"], "basic")
            self.assertEqual(call_args["max_results"], 5)
            self.assertEqual(call_args["exclude_domains"], ["example.org"])
            self.assertEqual(call_args["time_range"], "day")

    def test_search_api_error(self):
        """Test search method with an API error."""
        # Setup mock cursor to return no cached result
        self.mock_cursor.fetchone.return_value = None
        
        # Setup mock Tavily client to raise an exception
        self.mock_tavily_client.search.side_effect = Exception("API Error")
        
        # Test
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            with self.assertRaises(ValueError) as context:
                self.client.search("test query")
            
            # Verify exception message includes the API error
            self.assertEqual(str(context.exception), "Error calling Tavily API for advanced search: API Error")
            
            # Verify database operations
            self.mock_cursor.execute.assert_called()
            self.mock_cursor.fetchone.assert_called_once()
            
            # Verify API call
            self.mock_tavily_client.search.assert_called_once()

if __name__ == '__main__':
    unittest.main() 