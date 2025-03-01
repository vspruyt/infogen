import unittest
from unittest.mock import patch, MagicMock
import os
from infogen.services.clients.chromium_client import scrape_with_chromium

class TestChromiumClient(unittest.TestCase):
    """Test cases for the chromium client."""

    @patch('infogen.services.clients.chromium_client.AsyncChromiumLoader')
    @patch('infogen.services.clients.chromium_client.Html2TextTransformer')
    @patch.dict(os.environ, {"USER_AGENT": "Mozilla/5.0 Test User Agent"})
    def test_scrape_with_chromium_success(self, mock_transformer_class, mock_loader_class):
        """Test successful scraping with chromium."""
        # Setup mocks
        mock_loader = MagicMock()
        mock_loader.load.return_value = [MagicMock(page_content="<html><body><h1>Test Page</h1><p>Test content</p></body></html>")]
        mock_loader_class.return_value = mock_loader
        
        mock_transformer = MagicMock()
        mock_transformer.transform_documents.return_value = [MagicMock(page_content="Test Page\nTest content")]
        mock_transformer_class.return_value = mock_transformer
        
        # Test
        result = scrape_with_chromium("https://example.com")
        
        # Verify
        self.assertEqual(result, "Test Page\nTest content")
        mock_loader_class.assert_called_once_with(["https://example.com"], user_agent="Mozilla/5.0 Test User Agent")
        mock_loader.load.assert_called_once()
        mock_transformer_class.assert_called_once()
        mock_transformer.transform_documents.assert_called_once()

    @patch('infogen.services.clients.chromium_client.AsyncChromiumLoader')
    @patch('infogen.services.clients.chromium_client.Html2TextTransformer')
    def test_scrape_with_chromium_no_user_agent(self, mock_transformer_class, mock_loader_class):
        """Test scraping with no user agent environment variable."""
        # Setup mocks
        mock_loader = MagicMock()
        mock_loader.load.return_value = [MagicMock(page_content="<html><body><h1>Test Page</h1><p>Test content</p></body></html>")]
        mock_loader_class.return_value = mock_loader
        
        mock_transformer = MagicMock()
        mock_transformer.transform_documents.return_value = [MagicMock(page_content="Test Page\nTest content")]
        mock_transformer_class.return_value = mock_transformer
        
        # Test with no USER_AGENT in environment
        with patch.dict(os.environ, {}, clear=True):
            result = scrape_with_chromium("https://example.com")
        
        # Verify
        self.assertEqual(result, "Test Page\nTest content")
        mock_loader_class.assert_called_once_with(["https://example.com"], user_agent=None)

    @patch('infogen.services.clients.chromium_client.AsyncChromiumLoader')
    def test_scrape_with_chromium_no_html(self, mock_loader_class):
        """Test scraping with no HTML returned."""
        # Setup mock
        mock_loader = MagicMock()
        mock_loader.load.return_value = []  # Empty list
        mock_loader_class.return_value = mock_loader
        
        # Test
        result = scrape_with_chromium("https://example.com")
        
        # Verify
        self.assertIsNone(result)
        mock_loader_class.assert_called_once()
        mock_loader.load.assert_called_once()

    @patch('infogen.services.clients.chromium_client.AsyncChromiumLoader')
    @patch('infogen.services.clients.chromium_client.Html2TextTransformer')
    def test_scrape_with_chromium_empty_content(self, mock_transformer_class, mock_loader_class):
        """Test scraping with empty content after transformation."""
        # Setup mocks
        mock_loader = MagicMock()
        mock_loader.load.return_value = [MagicMock(page_content="<html><body></body></html>")]
        mock_loader_class.return_value = mock_loader
        
        mock_transformer = MagicMock()
        mock_transformer.transform_documents.return_value = [MagicMock(page_content="")]
        mock_transformer_class.return_value = mock_transformer
        
        # Test
        result = scrape_with_chromium("https://example.com")
        
        # Verify
        self.assertIsNone(result)

    @patch('infogen.services.clients.chromium_client.AsyncChromiumLoader')
    @patch('infogen.services.clients.chromium_client.Html2TextTransformer')
    def test_scrape_with_chromium_error_content(self, mock_transformer_class, mock_loader_class):
        """Test scraping with error content."""
        # Setup mocks
        mock_loader = MagicMock()
        mock_loader.load.return_value = [MagicMock(page_content="<html><body><h1>Error</h1></body></html>")]
        mock_loader_class.return_value = mock_loader
        
        mock_transformer = MagicMock()
        mock_transformer.transform_documents.return_value = [MagicMock(page_content="Error: Page not found")]
        mock_transformer_class.return_value = mock_transformer
        
        # Test
        result = scrape_with_chromium("https://example.com")
        
        # Verify
        self.assertIsNone(result)

    @patch('infogen.services.clients.chromium_client.AsyncChromiumLoader')
    def test_scrape_with_chromium_exception(self, mock_loader_class):
        """Test scraping with an exception."""
        # Setup mock
        mock_loader = MagicMock()
        mock_loader.load.side_effect = Exception("Test exception")
        mock_loader_class.return_value = mock_loader
        
        # Test
        result = scrape_with_chromium("https://example.com")
        
        # Verify
        self.assertIsNone(result)
        mock_loader_class.assert_called_once()
        mock_loader.load.assert_called_once()

if __name__ == '__main__':
    unittest.main() 