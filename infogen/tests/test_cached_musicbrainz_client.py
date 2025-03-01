import unittest
from unittest.mock import patch, MagicMock, call, ANY
import json
import datetime
import uuid
from infogen.services.clients.cached_musicbrainz_client import CachedMusicBrainzClient

class TestCachedMusicBrainzClient(unittest.TestCase):
    """Test cases for the CachedMusicBrainzClient."""

    def setUp(self):
        """Set up test fixtures."""
        # Mock musicbrainzngs module
        self.mock_musicbrainzngs = MagicMock()
        self.musicbrainzngs_patcher = patch('infogen.services.clients.cached_musicbrainz_client.musicbrainzngs', self.mock_musicbrainzngs)
        self.musicbrainzngs_patcher.start()
        
        # Mock pylast module
        self.mock_lastfm_network = MagicMock()
        self.mock_pylast = MagicMock()
        self.mock_pylast.LastFMNetwork.return_value = self.mock_lastfm_network
        self.pylast_patcher = patch('infogen.services.clients.cached_musicbrainz_client.pylast', self.mock_pylast)
        self.pylast_patcher.start()
        
        # Mock UUID
        self.mock_uuid = MagicMock(return_value="test-uuid")
        self.uuid_patcher = patch('uuid.uuid4', self.mock_uuid)
        self.uuid_patcher.start()
        
        # Mock ThreadedConnectionPool
        self.mock_pool = MagicMock()
        self.mock_pool_class = MagicMock(return_value=self.mock_pool)
        self.pool_patcher = patch('infogen.services.clients.cached_musicbrainz_client.ThreadedConnectionPool', self.mock_pool_class)
        self.pool_patcher.start()
        
        # Mock cursor and connection
        self.mock_cursor = MagicMock()
        self.mock_connection = MagicMock()
        self.mock_connection.cursor.return_value = self.mock_cursor
        self.mock_pool.getconn.return_value = self.mock_connection
        
        # Clear the connection pools dictionary to ensure a new pool is created
        CachedMusicBrainzClient._connection_pools = {}
        
        # Create client
        self.client = CachedMusicBrainzClient(
            app_name="test_app",
            app_version="1.0",
            app_contact="test@example.com",
            db_connection_string="test_connection_string"
        )

    def tearDown(self):
        """Tear down test fixtures."""
        self.musicbrainzngs_patcher.stop()
        self.pylast_patcher.stop()
        self.uuid_patcher.stop()
        self.pool_patcher.stop()

    def test_init(self):
        """Test initialization of the client."""
        # Verify MusicBrainz API was set up correctly
        self.mock_musicbrainzngs.set_useragent.assert_called_once_with(
            "test_app", "1.0", "test@example.com"
        )
        
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
        with patch.object(CachedMusicBrainzClient, 'close') as mock_close:
            with self.client:
                pass
            
            # Verify close was called
            mock_close.assert_called_once()

    def test_search_multi_cached_result(self):
        """Test search_multi method with a cached result."""
        # Setup mock result
        mock_result = {
            "artist-list": [{"name": "Test Artist", "id": "test-id"}]
        }
        self.mock_cursor.fetchone.return_value = (mock_result,)
        
        # Test
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.search_multi("test query", "artist")
            
            # Verify result
            self.assertEqual(result, mock_result)
            
            # Verify SQL query was executed
            self.mock_cursor.execute.assert_called_once()
            self.assertIn("SELECT api_response", self.mock_cursor.execute.call_args[0][0])
            self.assertIn("FROM musicbrainz_search_cache", self.mock_cursor.execute.call_args[0][0])

    def test_search_multi_no_cached_result_artist(self):
        """Test search_multi method with no cached result for artist."""
        # Setup mock result
        self.mock_cursor.fetchone.return_value = None
        mock_api_response = {
            "artist-list": [{"name": "Test Artist", "id": "test-id"}]
        }
        self.mock_musicbrainzngs.search_artists.return_value = mock_api_response
        
        # Test
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.search_multi("test query", "artist")
            
            # Verify API was called
            self.mock_musicbrainzngs.search_artists.assert_called_once_with(query="test query", limit=10)
            
            # Verify result
            self.assertEqual(result, mock_api_response)
            
            # Verify result was cached
            self.assertEqual(self.mock_cursor.execute.call_count, 2)
            self.assertIn("INSERT INTO musicbrainz_search_cache", self.mock_cursor.execute.call_args_list[1][0][0])

    def test_search_multi_no_cached_result_album(self):
        """Test search_multi method with no cached result for album."""
        # Setup mock result
        self.mock_cursor.fetchone.return_value = None
        mock_api_response = {
            "release-group-list": [{"title": "Test Album", "id": "test-id"}]
        }
        self.mock_musicbrainzngs.search_release_groups.return_value = mock_api_response
        
        # Test
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.search_multi("test query", "album", artist_name="Test Artist")
            
            # Verify API was called
            self.mock_musicbrainzngs.search_release_groups.assert_called_once_with(
                query="test query",
                strict=True,
                limit=10,
                artistname="Test Artist",
                type="Album",
                primarytype="Album"
            )
            
            # Verify result
            self.assertEqual(result, mock_api_response)
            
            # Verify result was cached
            self.assertEqual(self.mock_cursor.execute.call_count, 2)
            self.assertIn("INSERT INTO musicbrainz_search_cache", self.mock_cursor.execute.call_args_list[1][0][0])

    def test_get_music_details_cached_result(self):
        """Test get_music_details method with a cached result."""
        # Setup mock result
        mock_result = {
            "artist": {"name": "Test Artist", "id": "test-id"}
        }
        self.mock_cursor.fetchone.return_value = (mock_result,)
        
        # Test
        with patch.object(self.client, '_execute_with_connection_async', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.get_music_details("test-id", "artist")
            
            # Verify result
            self.assertEqual(result, mock_result)
            
            # Verify SQL query was executed
            self.mock_cursor.execute.assert_called_once()
            self.assertIn("SELECT api_response", self.mock_cursor.execute.call_args[0][0])
            self.assertIn("FROM musicbrainz_artist_cache", self.mock_cursor.execute.call_args[0][0])

    def test_get_music_details_no_cached_result_artist(self):
        """Test get_music_details method with no cached result for artist."""
        # Setup mock result
        self.mock_cursor.fetchone.return_value = None
        mock_api_response = {
            "artist": {"name": "Test Artist", "id": "test-id"}
        }
        self.mock_musicbrainzngs.get_artist_by_id.return_value = mock_api_response
        
        # Test
        with patch.object(self.client, '_execute_with_connection_async', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.get_music_details("test-id", "artist")
            
            # Verify API was called
            self.mock_musicbrainzngs.get_artist_by_id.assert_called_once_with(
                "test-id",
                includes=["recordings", "release-groups", "aliases", "url-rels"]
            )
            
            # Verify result
            self.assertEqual(result, mock_api_response)
            
            # Verify result was cached
            self.assertEqual(self.mock_cursor.execute.call_count, 2)
            self.assertIn("INSERT INTO musicbrainz_artist_cache", self.mock_cursor.execute.call_args_list[1][0][0])

    def test_get_artist_bio_cached_result(self):
        """Test get_artist_bio method with a cached result."""
        # Setup mock result
        mock_result = {
            "bio": "Test bio",
            "source": "last.fm",
            "mbid": "test-id",
            "artist_name": "Test Artist"
        }
        self.mock_cursor.fetchone.return_value = (mock_result,)
        
        # Test
        with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
            result = self.client.get_artist_bio("test-id")
            
            # Verify result
            self.assertEqual(result, mock_result)
            
            # Verify SQL query was executed
            self.mock_cursor.execute.assert_called_once()
            self.assertIn("SELECT api_response", self.mock_cursor.execute.call_args[0][0])
            self.assertIn("FROM lastfm_artist_bio_cache", self.mock_cursor.execute.call_args[0][0])

    def test_get_artist_bio_no_cached_result(self):
        """Test get_artist_bio method with no cached result."""
        # Setup mock result
        self.mock_cursor.fetchone.return_value = None
        mock_artist = MagicMock()
        mock_artist.get_bio_content.return_value = "Test bio"
        mock_artist.get_name.return_value = "Test Artist"
        self.mock_lastfm_network.get_artist_by_mbid.return_value = mock_artist
        
        # Mock environment variable
        with patch('os.getenv', return_value="test_api_key"):
            # Test
            with patch.object(self.client, '_execute_with_connection', side_effect=lambda x: x(self.mock_cursor)):
                result = self.client.get_artist_bio("test-id")
                
                # Verify API was called
                self.mock_lastfm_network.get_artist_by_mbid.assert_called_once_with("test-id")
                mock_artist.get_bio_content.assert_called_once()
                
                # Verify result
                self.assertEqual(result["bio"], "Test bio")
                self.assertEqual(result["source"], "last.fm")
                self.assertEqual(result["mbid"], "test-id")
                self.assertEqual(result["artist_name"], "Test Artist")
                
                # Verify result was cached
                self.assertEqual(self.mock_cursor.execute.call_count, 2)
                self.assertIn("INSERT INTO lastfm_artist_bio_cache", self.mock_cursor.execute.call_args_list[1][0][0])

if __name__ == '__main__':
    unittest.main() 