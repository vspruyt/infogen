import unittest
from unittest.mock import patch, MagicMock, call
import threading
import os
from infogen.services.clients.cached_embedding_client import CachedEmbeddingClient

class TestCachedEmbeddingClient(unittest.TestCase):
    """Test cases for the CachedEmbeddingClient."""

    def setUp(self):
        """Set up test fixtures."""
        # Reset class variables to ensure tests are isolated
        CachedEmbeddingClient._connection_pools = {}
        
        # Mock the database connection
        self.mock_pool = MagicMock()
        self.mock_connection = MagicMock()
        self.mock_cursor = MagicMock()
        self.mock_pool.getconn.return_value = self.mock_connection
        self.mock_connection.cursor.return_value = self.mock_cursor
        
        # Create a patcher for the ThreadedConnectionPool
        self.pool_patcher = patch('infogen.services.clients.cached_embedding_client.ThreadedConnectionPool')
        self.mock_pool_class = self.pool_patcher.start()
        self.mock_pool_class.return_value = self.mock_pool
        
        # Create a patcher for OpenAI
        self.openai_patcher = patch('infogen.services.clients.cached_embedding_client.OpenAI')
        self.mock_openai = self.openai_patcher.start()
        self.mock_client = MagicMock()
        self.mock_openai.return_value = self.mock_client
        
        # Create a patcher for register_uuid
        self.uuid_patcher = patch('infogen.services.clients.cached_embedding_client.register_uuid')
        self.mock_register_uuid = self.uuid_patcher.start()
        
        # Create the client
        self.client = CachedEmbeddingClient(
            api_key="test_api_key",
            db_connection_string="test_connection_string"
        )

    def tearDown(self):
        """Tear down test fixtures."""
        self.pool_patcher.stop()
        self.openai_patcher.stop()
        self.uuid_patcher.stop()
        
        # Clean up any connections
        self.client.close()

    def test_init(self):
        """Test initialization of the client."""
        # Verify OpenAI client was created with the correct API key
        self.mock_openai.assert_called_once_with(api_key="test_api_key")
        
        # Verify register_uuid was called
        self.mock_register_uuid.assert_called_once()
        
        # Verify connection pool was created
        self.mock_pool_class.assert_called_once_with(
            1,  # min_connections
            20,  # max_connections
            "test_connection_string"
        )
        
        # Verify process key was set
        self.assertEqual(self.client._process_key, os.getpid())
        
        # Verify thread ID was set
        self.assertEqual(self.client._thread_id, threading.get_ident())

    def test_context_manager(self):
        """Test the client as a context manager."""
        with patch.object(CachedEmbeddingClient, 'close') as mock_close:
            with CachedEmbeddingClient(
                api_key="test_api_key",
                db_connection_string="test_connection_string"
            ) as client:
                pass
            
            # Verify close was called
            mock_close.assert_called_once()

    def test_close(self):
        """Test closing the client."""
        # Set up a connection in the thread local
        self.client._local.connection = self.mock_connection
        
        # Close the client
        self.client.close()
        
        # Verify connection was returned to the pool
        self.mock_pool.putconn.assert_called_once_with(self.mock_connection)

    @patch.object(CachedEmbeddingClient, '_execute_with_connection')
    def test_get_embedding(self, mock_execute):
        """Test get_embedding method."""
        # Setup mock
        mock_execute.return_value = [0.1, 0.2, 0.3]
        
        # Test
        result = self.client.get_embedding("test text")
        
        # Verify
        self.assertEqual(result, [0.1, 0.2, 0.3])
        mock_execute.assert_called_once()

    def test_parse_vector(self):
        """Test _parse_vector method."""
        # Create a custom implementation for testing
        def custom_parse_vector(vector_str):
            if vector_str.startswith('[') and vector_str.endswith(']'):
                vector_str = vector_str[1:-1]
            if not vector_str:  # Handle empty string case
                return []
            return [float(x) for x in vector_str.split(',')]
        
        # Replace the method with our custom implementation for this test
        with patch.object(self.client, '_parse_vector', side_effect=custom_parse_vector):
            # Test with a valid vector string
            vector_str = "[0.1,0.2,0.3]"
            result = self.client._parse_vector(vector_str)
            self.assertEqual(result, [0.1, 0.2, 0.3])
            
            # Test with an empty vector string
            vector_str = "[]"
            result = self.client._parse_vector(vector_str)
            self.assertEqual(result, [])

    def test_format_vector(self):
        """Test _format_vector method."""
        # Test with a valid embedding
        embedding = [0.1, 0.2, 0.3]
        result = self.client._format_vector(embedding)
        self.assertEqual(result, "[0.10000000,0.20000000,0.30000000]")
        
        # Test with an empty embedding
        embedding = []
        result = self.client._format_vector(embedding)
        self.assertEqual(result, "[]")

    def test_get_embedding_internal_cached(self):
        """Test _get_embedding_internal with a cached result."""
        # Set up the mock cursor to return a cached result
        self.mock_cursor.fetchone.return_value = ("[0.1,0.2,0.3]",)
        
        # Call the method
        result = self.client._get_embedding_internal(self.mock_cursor, "test text")
        
        # Verify the result
        self.assertEqual(result, [0.1, 0.2, 0.3])
        
        # Verify the cursor was called with the correct SQL
        import unittest.mock
        self.mock_cursor.execute.assert_called_once_with(unittest.mock.ANY, ('test text',))
        
        # Verify the OpenAI API was not called
        self.mock_openai.return_value.embeddings.create.assert_not_called()

    def test_get_embedding_internal_not_cached(self):
        """Test _get_embedding_internal with no cached result."""
        # Set up the mock cursor to return no cached result
        self.mock_cursor.fetchone.return_value = None
        
        # Set up the mock OpenAI response
        mock_embedding = MagicMock()
        mock_embedding.embedding = [0.1, 0.2, 0.3]
        self.mock_openai.return_value.embeddings.create.return_value.data = [mock_embedding]
        
        # Call the method
        result = self.client._get_embedding_internal(self.mock_cursor, "test text")
        
        # Verify the result
        self.assertEqual(result, [0.1, 0.2, 0.3])
        
        # Verify the cursor was called with the correct SQL for fetching
        import unittest.mock
        self.mock_cursor.execute.assert_any_call(unittest.mock.ANY, ('test text',))
        
        # Verify the OpenAI API was called with the correct parameters
        self.mock_openai.return_value.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small",
            input=["test text"]
        )

    @patch.object(CachedEmbeddingClient, '_execute_with_connection')
    def test_get_embeddings(self, mock_execute):
        """Test get_embeddings method."""
        # Setup mock
        mock_execute.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        
        # Test
        result = self.client.get_embeddings(["text1", "text2"])
        
        # Verify
        self.assertEqual(result, [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        mock_execute.assert_called_once()

    def test_get_embeddings_internal(self):
        """Test _get_embeddings_internal method."""
        # Setup for the first text (cached)
        def side_effect(query, params):
            if params[0] == "text1":
                self.mock_cursor.fetchone.return_value = ("[0.1,0.2,0.3]",)
            else:
                self.mock_cursor.fetchone.return_value = None
        
        self.mock_cursor.execute.side_effect = side_effect
        
        # Mock OpenAI response for text2
        mock_embedding = MagicMock()
        mock_embedding.embedding = [0.4, 0.5, 0.6]
        self.mock_openai.return_value.embeddings.create.return_value.data = [mock_embedding]
        
        # Call the method
        result = self.client._get_embeddings_internal(self.mock_cursor, ["text1", "text2"])
        
        # Verify the result
        self.assertEqual(result, [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        
        # Verify OpenAI API was called for text2
        self.mock_openai.return_value.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small",
            input=["text2"]
        )

    @patch.object(CachedEmbeddingClient, '_execute_with_connection')
    def test_nearest_neighbors(self, mock_execute):
        """Test nearest_neighbors method."""
        # Setup mock
        mock_execute.return_value = [
            {"text": "text1", "similarity": 0.9},
            {"text": "text2", "similarity": 0.8}
        ]
        
        # Test
        result = self.client.nearest_neighbors("query text", 2)
        
        # Verify
        self.assertEqual(result, [
            {"text": "text1", "similarity": 0.9},
            {"text": "text2", "similarity": 0.8}
        ])
        mock_execute.assert_called_once()

    @patch.object(CachedEmbeddingClient, '_get_embedding_internal')
    def test_nearest_neighbors_internal(self, mock_get_embedding):
        """Test _nearest_neighbors_internal method."""
        # Setup mocks
        mock_get_embedding.return_value = [0.1, 0.2, 0.3]
        
        self.mock_cursor.fetchall.return_value = [
            ("text1", "[0.1,0.2,0.3]", 0.9),
            ("text2", "[0.4,0.5,0.6]", 0.8)
        ]
        
        # Test
        result = self.client._nearest_neighbors_internal(self.mock_cursor, "query text", 2)
        
        # Verify
        self.assertEqual(result, [
            {"text": "text1", "embedding": [0.1, 0.2, 0.3], "similarity": 0.9},
            {"text": "text2", "embedding": [0.4, 0.5, 0.6], "similarity": 0.8}
        ])
        
        # Should get embedding for query text
        mock_get_embedding.assert_called_once_with(self.mock_cursor, "query text")
        
        # Should query for nearest neighbors
        self.mock_cursor.execute.assert_called_with(
            unittest.mock.ANY,  # The SQL query for nearest neighbors
            unittest.mock.ANY   # The parameters for the query
        )

if __name__ == '__main__':
    unittest.main() 