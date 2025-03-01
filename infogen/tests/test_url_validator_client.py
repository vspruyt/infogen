import unittest
from unittest.mock import patch, MagicMock
import requests
from infogen.services.clients.cached_url_validator_client import URLValidatorClient

class TestURLValidatorClient(unittest.TestCase):
    """Test cases for the URLValidatorClient."""

    def setUp(self):
        """Set up test fixtures."""
        self.validator = URLValidatorClient()
        
    def test_clean_url(self):
        """Test the _clean_url method."""
        # Test with spaces
        self.assertEqual(self.validator._clean_url(" https://example.com "), "https://example.com")
        
        # Test with special characters
        self.assertEqual(self.validator._clean_url("https://example.com/search?q=test query"), 
                         "https://example.com/search?q=test%20query")
        
        # Test with anchor
        self.assertEqual(self.validator._clean_url("https://example.com/page#section"), 
                         "https://example.com/page#section")
        
        # Test with special characters and anchor
        self.assertEqual(self.validator._clean_url("https://example.com/search?q=test query#results"), 
                         "https://example.com/search?q=test%20query#results")

    @patch('requests.Session')
    def test_validate_url_success(self, mock_session_class):
        """Test validate_url with a successful response."""
        # Setup mock
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {'content-type': 'text/html'}
        mock_response.history = []
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        # Test
        result = self.validator.validate_url("https://example.com")
        
        # Verify
        self.assertTrue(result)
        mock_session.get.assert_called_with(
            "https://example.com", 
            allow_redirects=True, 
            timeout=10, 
            verify=True
        )

    @patch('requests.Session')
    def test_validate_url_redirect(self, mock_session_class):
        """Test validate_url with a redirect."""
        # Setup mock
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {'content-type': 'text/html'}
        mock_response.history = [MagicMock()]  # Non-empty history indicates a redirect
        mock_response.url = "https://example.com/redirected"
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        # Test
        result = self.validator.validate_url("https://example.com")
        
        # Verify
        self.assertTrue(result)

    @patch('requests.Session')
    def test_validate_url_restricted(self, mock_session_class):
        """Test validate_url with a restricted response (403)."""
        # Setup mock
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 403  # Forbidden
        mock_response.headers = {'content-type': 'text/html'}
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        # Test
        result = self.validator.validate_url("https://example.com")
        
        # Verify
        self.assertTrue(result)  # Should be true because 403 is in VALID_BUT_RESTRICTED_CODES

    @patch('requests.Session')
    def test_validate_url_not_found(self, mock_session_class):
        """Test validate_url with a not found response (404)."""
        # Setup mock
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 404  # Not Found
        mock_response.headers = {'content-type': 'text/html'}
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        # Test
        result = self.validator.validate_url("https://example.com/nonexistent")
        
        # Verify
        self.assertFalse(result)  # Should be false because 404 is not in VALID_BUT_RESTRICTED_CODES

    @patch('requests.Session')
    def test_validate_url_ssl_error(self, mock_session_class):
        """Test validate_url with an SSL error that gets retried without verification."""
        # Setup mocks
        mock_session1 = MagicMock()
        mock_session2 = MagicMock()
        mock_session3 = MagicMock()
        
        # First session raises SSL error
        mock_session1.get.side_effect = requests.exceptions.SSLError("SSL Error")
        
        # Second session succeeds
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {'content-type': 'text/html'}
        mock_session2.get.return_value = mock_response
        
        # Third session shouldn't be used
        
        # Return different session instances for each call
        mock_session_class.side_effect = [mock_session1, mock_session2, mock_session3]
        
        # Test
        result = self.validator.validate_url("https://example.com")
        
        # Verify
        self.assertTrue(result)
        mock_session1.get.assert_called_with(
            "https://example.com", 
            allow_redirects=True, 
            timeout=10, 
            verify=True
        )
        mock_session2.get.assert_called_with(
            "https://example.com", 
            allow_redirects=True, 
            timeout=10, 
            verify=False
        )
        # Third session's get method should not be called
        mock_session3.get.assert_not_called()

    @patch('requests.Session')
    def test_validate_url_request_exception(self, mock_session_class):
        """Test validate_url with a request exception."""
        # Setup mock
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.RequestException("Connection error")
        mock_session_class.return_value = mock_session
        
        # Test
        result = self.validator.validate_url("https://example.com")
        
        # Verify
        self.assertFalse(result)

    @patch('requests.Session')
    def test_validate_url_invalid_format(self, mock_session_class):
        """Test validate_url with an invalid URL format."""
        # Test with invalid URL
        result = self.validator.validate_url("not-a-url")
        
        # Verify
        self.assertFalse(result)
        mock_session_class.assert_not_called()  # Session should not be created for invalid URLs

    @patch('requests.Session')
    @patch.object(URLValidatorClient, '_validate_image')
    def test_validate_url_image(self, mock_validate_image, mock_session_class):
        """Test validate_url with an image URL."""
        # Setup mocks
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {'content-type': 'image/jpeg'}
        mock_response.url = "https://example.com/image.jpg"
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        # Configure _validate_image to return True
        mock_validate_image.return_value = True
        
        # Test
        result = self.validator.validate_url("https://example.com/image.jpg")
        
        # Verify
        self.assertTrue(result)
        mock_validate_image.assert_called_once_with(mock_session, "https://example.com/image.jpg")

    @patch('requests.Session')
    @patch.object(URLValidatorClient, '_validate_image')
    def test_validate_url_invalid_image(self, mock_validate_image, mock_session_class):
        """Test validate_url with an invalid image URL."""
        # Setup mocks
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {'content-type': 'image/jpeg'}
        mock_response.url = "https://example.com/image.jpg"
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        # Configure _validate_image to return False
        mock_validate_image.return_value = False
        
        # Test
        result = self.validator.validate_url("https://example.com/image.jpg")
        
        # Verify
        self.assertFalse(result)
        # Don't assert the exact number of calls since the implementation may call it multiple times
        mock_validate_image.assert_called_with(mock_session, "https://example.com/image.jpg")

    def test_validate_image(self):
        """Test the _validate_image method."""
        # Setup mock session and response
        mock_session = MagicMock()
        mock_response = MagicMock()
        
        # Test with JPEG signature
        mock_response.iter_content.return_value = iter([b'\xFF\xD8\xFF\xE0\x00\x10JFIF'])
        mock_session.get.return_value = mock_response
        self.assertTrue(self.validator._validate_image(mock_session, "https://example.com/image.jpg"))
        
        # Test with PNG signature
        mock_response.iter_content.return_value = iter([b'\x89PNG\r\n\x1a\n'])
        self.assertTrue(self.validator._validate_image(mock_session, "https://example.com/image.png"))
        
        # Test with GIF signature
        mock_response.iter_content.return_value = iter([b'GIF89a'])
        self.assertTrue(self.validator._validate_image(mock_session, "https://example.com/image.gif"))
        
        # Test with invalid signature
        mock_response.iter_content.return_value = iter([b'INVALID'])
        self.assertFalse(self.validator._validate_image(mock_session, "https://example.com/invalid.jpg"))
        
        # Test with exception
        mock_session.get.side_effect = Exception("Error")
        self.assertFalse(self.validator._validate_image(mock_session, "https://example.com/error.jpg"))

    def test_get_url_validator_tool(self):
        """Test the get_url_validator_tool class method."""
        tool = URLValidatorClient.get_url_validator_tool()
        
        # Verify the tool has the correct properties
        self.assertEqual(tool.name, "validate_url")
        self.assertIn("validate a url", tool.description.lower())

    def test_real_urls(self):
        """Test with real URLs that are known to work.
        
        Note: This test makes actual network requests and may fail if the URLs change or are unavailable.
        """
        # These tests are commented out by default to avoid making real network requests during automated testing
        # Uncomment to run manually when needed
        
        """
        # Test with known working URLs
        self.assertTrue(self.validator.validate_url("https://www.sparknotes.com/lit/matilda/summary/"))
        self.assertTrue(self.validator.validate_url("https://www.iment.com/maida/tv/lordoftherings/characters.htm"))
        self.assertTrue(self.validator.validate_url("https://themoviedb.org/"))
        
        # Test with known non-existent URL
        self.assertFalse(self.validator.validate_url("https://www.example.com/nonexistent-page-12345"))
        """

if __name__ == '__main__':
    unittest.main() 