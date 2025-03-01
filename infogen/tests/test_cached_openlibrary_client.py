import unittest
from unittest.mock import patch, MagicMock, call, ANY
import json
import datetime
import uuid
from infogen.services.clients.cached_openlibrary_client import CachedOpenLibraryClient

class TestCachedOpenLibraryClient(unittest.TestCase):
    """Test cases for the CachedOpenLibraryClient."""

    def setUp(self):
        """Set up test fixtures."""
        # Mock OpenLibrary
        self.mock_ol = MagicMock()
        self.mock_openlibrary = MagicMock(return_value=self.mock_ol)
        self.openlibrary_patcher = patch('infogen.services.clients.cached_openlibrary_client.OpenLibrary', self.mock_openlibrary)
        self.openlibrary_patcher.start()
        
        # Mock UUID
        self.mock_uuid = MagicMock(return_value="test-uuid")
        self.uuid_patcher = patch('uuid.uuid4', self.mock_uuid)
        self.uuid_patcher.start()
        
        # Mock ThreadedConnectionPool
        self.mock_pool = MagicMock()
        self.mock_pool_class = MagicMock(return_value=self.mock_pool)
        self.pool_patcher = patch('infogen.services.clients.cached_openlibrary_client.ThreadedConnectionPool', self.mock_pool_class)
        self.pool_patcher.start()
        
        # Mock cursor and connection
        self.mock_cursor = MagicMock()
        self.mock_connection = MagicMock()
        self.mock_connection.cursor.return_value = self.mock_cursor
        self.mock_pool.getconn.return_value = self.mock_connection
        
        # Clear the connection pools dictionary to ensure a new pool is created
        CachedOpenLibraryClient._connection_pools = {}
        
        # Create client
        self.client = CachedOpenLibraryClient(
            db_connection_string="test_connection_string"
        )

    def tearDown(self):
        """Tear down test fixtures."""
        self.openlibrary_patcher.stop()
        self.uuid_patcher.stop()
        self.pool_patcher.stop()

    def test_init(self):
        """Test initialization of the client."""
        # Verify OpenLibrary was initialized
        self.mock_openlibrary.assert_called_once()
        
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
        with patch.object(CachedOpenLibraryClient, 'close') as mock_close:
            with self.client:
                pass
            
            # Verify close was called
            mock_close.assert_called_once()

    def test_search_multi_cached_result(self):
        """Test search_multi method with a cached result."""
        # Setup mock result
        mock_result = [{"name": "Test Author", "key": "/authors/OL123456A"}]
        self.mock_cursor.fetchone.return_value = (mock_result,)
        
        # Test
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.search_multi("test query", "author")
            
            # Verify result
            self.assertEqual(result, mock_result)
            
            # Verify SQL query was executed
            self.mock_cursor.execute.assert_called_once()
            self.assertIn("SELECT api_response", self.mock_cursor.execute.call_args[0][0])
            self.assertIn("FROM openlibrary_search_cache", self.mock_cursor.execute.call_args[0][0])

    def test_search_multi_no_cached_result_author(self):
        """Test search_multi method with no cached result for author."""
        # Setup mock result
        self.mock_cursor.fetchone.return_value = None
        mock_api_response = [{"name": "Test Author", "key": "/authors/OL123456A"}]
        self.mock_ol.Author.search.return_value = mock_api_response
        
        # Test
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.search_multi("test query", "author")
            
            # Verify API was called
            self.mock_ol.Author.search.assert_called_once_with("test query", limit=10)
            
            # Verify result
            self.assertEqual(result, mock_api_response)
            
            # Verify result was cached
            self.assertEqual(self.mock_cursor.execute.call_count, 2)
            self.assertIn("INSERT INTO openlibrary_search_cache", self.mock_cursor.execute.call_args_list[1][0][0])

    def test_search_multi_no_cached_result_book(self):
        """Test search_multi method with no cached result for book."""
        # Setup mock result
        self.mock_cursor.fetchone.return_value = None
        mock_work = MagicMock()
        mock_work.identifiers = {"olid": ["OL123456W"]}
        self.mock_ol.Work.search.return_value = mock_work
        
        # Test
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.search_multi("test query", "book")
            
            # Verify API was called
            self.mock_ol.Work.search.assert_called_once_with("test query")
            
            # Verify result
            self.assertEqual(result, "OL123456W")
            
            # Verify result was cached
            self.assertEqual(self.mock_cursor.execute.call_count, 2)
            self.assertIn("INSERT INTO openlibrary_search_cache", self.mock_cursor.execute.call_args_list[1][0][0])

    def test_get_author_details_cached_result(self):
        """Test get_author_details method with a cached result."""
        # Setup mock result
        mock_result = {
            "name": "Test Author",
            "birth_date": "1970-01-01"
        }
        self.mock_cursor.fetchone.return_value = (mock_result,)
        
        # Test
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.get_author_details("OL123456A")
            
            # Verify result
            self.assertEqual(result, mock_result)
            
            # Verify SQL query was executed
            self.mock_cursor.execute.assert_called_once()
            self.assertIn("SELECT api_response", self.mock_cursor.execute.call_args[0][0])
            self.assertIn("FROM openlibrary_author_cache", self.mock_cursor.execute.call_args[0][0])

    def test_get_author_details_no_cached_result(self):
        """Test get_author_details method with no cached result."""
        # Setup mock result
        self.mock_cursor.fetchone.return_value = None
        mock_author = MagicMock()
        mock_author.json.return_value = {
            "name": "Test Author",
            "birth_date": "1970-01-01"
        }
        self.mock_ol.Author.get.return_value = mock_author
        
        # Test
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.get_author_details("OL123456A")
            
            # Verify API was called
            self.mock_ol.Author.get.assert_called_once_with("OL123456A")
            
            # Verify result
            self.assertEqual(result, mock_author.json())
            
            # Verify result was cached
            self.assertEqual(self.mock_cursor.execute.call_count, 2)
            self.assertIn("INSERT INTO openlibrary_author_cache", self.mock_cursor.execute.call_args_list[1][0][0])

    def test_get_work_details_cached_result(self):
        """Test get_work_details method with a cached result."""
        # Setup mock result
        mock_result = {
            "title": "Test Book",
            "key": "/works/OL123456W"
        }
        self.mock_cursor.fetchone.return_value = (mock_result,)
        
        # Test
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.get_work_details("OL123456W")
            
            # Verify result
            self.assertEqual(result, mock_result)
            
            # Verify SQL query was executed
            self.mock_cursor.execute.assert_called_once()
            self.assertIn("SELECT api_response", self.mock_cursor.execute.call_args[0][0])
            self.assertIn("FROM openlibrary_work_cache", self.mock_cursor.execute.call_args[0][0])

    def test_get_work_details_no_cached_result(self):
        """Test get_work_details method with no cached result."""
        # Setup mock result
        self.mock_cursor.fetchone.return_value = None
        mock_work = MagicMock()
        mock_work.json.return_value = {
            "title": "Test Book",
            "key": "/works/OL123456W"
        }
        self.mock_ol.Work.get.return_value = mock_work
        
        # Test
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.get_work_details("OL123456W")
            
            # Verify API was called
            self.mock_ol.Work.get.assert_called_once_with("OL123456W")
            
            # Verify result
            self.assertEqual(result, mock_work.json())
            
            # Verify result was cached
            self.assertEqual(self.mock_cursor.execute.call_count, 2)
            self.assertIn("INSERT INTO openlibrary_work_cache", self.mock_cursor.execute.call_args_list[1][0][0])

    def test_get_edition_details_cached_result(self):
        """Test get_edition_details method with a cached result."""
        # Setup mock result
        mock_result = [
            {"title": "Test Edition", "key": "/books/OL123456M"}
        ]
        self.mock_cursor.fetchone.return_value = (mock_result,)
        
        # Test
        mock_work = MagicMock()
        mock_work.olid = "OL123456W"
        
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.get_edition_details(mock_work)
            
            # Verify result
            self.assertEqual(result, mock_result)
            
            # Verify SQL query was executed
            self.mock_cursor.execute.assert_called_once()
            self.assertIn("SELECT api_response", self.mock_cursor.execute.call_args[0][0])
            self.assertIn("FROM openlibrary_editions_cache", self.mock_cursor.execute.call_args[0][0])

    def test_json_to_author(self):
        """Test _json_to_author method."""
        # Test with string input
        author_name = "Test Author"
        mock_author = MagicMock()
        self.mock_ol.Author.return_value = mock_author
        
        result = self.client._json_to_author(author_name)
        self.mock_ol.Author.assert_called_with(None, author_name)
        self.assertEqual(result, mock_author)
        
        # Test with dict input
        author_data = {
            "name": "Test Author",
            "key": "/authors/OL123456A"
        }
        self.mock_ol.Author.reset_mock()
        self.mock_ol.Author.return_value = mock_author
        
        result = self.client._json_to_author(author_data)
        self.mock_ol.Author.assert_called_with("OL123456A", "Test Author")
        self.assertEqual(result, mock_author)

    def test_create_work_from_json(self):
        """Test create_work_from_json method."""
        # Test with string input
        work_json = '{"title": "Test Book", "key": "/works/OL123456W"}'
        mock_work = MagicMock()
        
        with patch.object(self.client, '_json_to_work', return_value=mock_work) as mock_json_to_work:
            result = self.client.create_work_from_json(work_json)
            
            # Verify _json_to_work was called with parsed JSON
            mock_json_to_work.assert_called_once()
            self.assertEqual(mock_json_to_work.call_args[0][0]["title"], "Test Book")
            self.assertEqual(result, mock_work)
        
        # Test with dict input
        work_data = {
            "title": "Test Book",
            "key": "/works/OL123456W"
        }
        
        with patch.object(self.client, '_json_to_work', return_value=mock_work) as mock_json_to_work:
            result = self.client.create_work_from_json(work_data)
            
            # Verify _json_to_work was called with the dict
            mock_json_to_work.assert_called_once_with(work_data)
            self.assertEqual(result, mock_work)

if __name__ == '__main__':
    unittest.main() 