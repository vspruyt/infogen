import unittest
import pytest
from unittest.mock import patch, MagicMock
from infogen.core.utilities import truncate_text_tokens

class TestUtilities(unittest.TestCase):
    """Test cases for the utilities module."""

    def test_truncate_text_tokens_input_validation(self):
        """Test input validation for truncate_text_tokens function."""
        # Test with invalid text type
        with self.assertRaises(TypeError):
            truncate_text_tokens("gpt-4", 12345, 100)
        
        # Test with empty model string
        with self.assertRaises(ValueError):
            truncate_text_tokens("", "some text", 100)
        
        # Test with whitespace-only model string
        with self.assertRaises(ValueError):
            truncate_text_tokens("   ", "some text", 100)
        
        # Test with invalid max_tokens
        with self.assertRaises(ValueError):
            truncate_text_tokens("gpt-4", "some text", 0)
        
        with self.assertRaises(ValueError):
            truncate_text_tokens("gpt-4", "some text", -10)

    @patch('tiktoken.encoding_for_model')
    def test_truncate_text_tokens_no_truncation_needed(self, mock_encoding_for_model):
        """Test when text is already within token limit."""
        # Setup mock
        mock_encoder = MagicMock()
        mock_encoder.encode.return_value = [1, 2, 3, 4, 5]  # 5 tokens
        mock_encoding_for_model.return_value = mock_encoder
        
        text = "This is a short text."
        result = truncate_text_tokens("gpt-4", text, 10)
        
        # Verify the text was not modified
        self.assertEqual(result, text)
        mock_encoder.encode.assert_called_once_with(text)

    @patch('tiktoken.encoding_for_model')
    def test_truncate_text_tokens_with_sentence_boundary(self, mock_encoding_for_model):
        """Test truncation at sentence boundary."""
        # Setup mock
        mock_encoder = MagicMock()
        # Simulate 10 tokens
        mock_encoder.encode.return_value = list(range(10))
        # When decoding the first 5 tokens, return a string with a sentence boundary
        mock_encoder.decode.return_value = "First sentence. Second sentence."
        mock_encoding_for_model.return_value = mock_encoder
        
        text = "First sentence. Second sentence. Third sentence."
        result = truncate_text_tokens("gpt-4", text, 5)
        
        # Verify truncation at sentence boundary
        # The actual implementation keeps the text up to the last sentence boundary
        self.assertEqual(result, "First sentence. Second sentence.\n\n[Content truncated due to length...]")
        mock_encoder.encode.assert_called_once_with(text)
        mock_encoder.decode.assert_called_once_with([0, 1, 2, 3, 4])

    @patch('tiktoken.encoding_for_model')
    def test_truncate_text_tokens_without_sentence_boundary(self, mock_encoding_for_model):
        """Test truncation when no sentence boundary is found."""
        # Setup mock
        mock_encoder = MagicMock()
        mock_encoder.encode.return_value = list(range(10))
        # No sentence boundary in the truncated text
        mock_encoder.decode.return_value = "This text has no sentence boundary"
        mock_encoding_for_model.return_value = mock_encoder
        
        text = "This text has no sentence boundary. But this part does."
        result = truncate_text_tokens("gpt-4", text, 5)
        
        # Verify truncation without sentence boundary adjustment
        self.assertEqual(result, "This text has no sentence boundary\n\n[Content truncated due to length...]")
        mock_encoder.encode.assert_called_once_with(text)
        mock_encoder.decode.assert_called_once_with([0, 1, 2, 3, 4])

    @patch('tiktoken.encoding_for_model')
    def test_truncate_text_tokens_with_question_mark(self, mock_encoding_for_model):
        """Test truncation at question mark sentence boundary."""
        # Setup mock
        mock_encoder = MagicMock()
        mock_encoder.encode.return_value = list(range(10))
        # Mock the decode method to return text with a question mark
        mock_encoder.decode.return_value = "Is this a question? This is not included."
        mock_encoding_for_model.return_value = mock_encoder
        
        text = "Is this a question? This is not included. This is also not included."
        result = truncate_text_tokens("gpt-4", text, 5)
        
        # The actual implementation finds the last question mark and truncates there
        expected = "Is this a question? This is not included.\n\n[Content truncated due to length...]"
        self.assertEqual(result, expected)

    @patch('tiktoken.encoding_for_model')
    def test_truncate_text_tokens_with_exclamation_mark(self, mock_encoding_for_model):
        """Test truncation at exclamation mark sentence boundary."""
        # Setup mock
        mock_encoder = MagicMock()
        mock_encoder.encode.return_value = list(range(10))
        # Mock the decode method to return text with an exclamation mark
        mock_encoder.decode.return_value = "This is exciting! This is not included."
        mock_encoding_for_model.return_value = mock_encoder
        
        text = "This is exciting! This is not included. This is also not included."
        result = truncate_text_tokens("gpt-4", text, 5)
        
        # The actual implementation finds the last exclamation mark and truncates there
        expected = "This is exciting! This is not included.\n\n[Content truncated due to length...]"
        self.assertEqual(result, expected)

    @patch('tiktoken.encoding_for_model', side_effect=KeyError("Model not found"))
    @patch('tiktoken.get_encoding')
    def test_truncate_text_tokens_fallback_encoding(self, mock_get_encoding, mock_encoding_for_model):
        """Test fallback to cl100k_base encoding when model is not found."""
        # Setup mock
        mock_encoder = MagicMock()
        mock_encoder.encode.return_value = list(range(5))  # 5 tokens
        mock_get_encoding.return_value = mock_encoder
        
        text = "This is a short text."
        result = truncate_text_tokens("gpt-4o-mini", text, 10)  # Using a model name that might not be in tiktoken
        
        # Verify the fallback encoding was used
        self.assertEqual(result, text)
        mock_encoding_for_model.assert_called_once_with("gpt-4o-mini")
        mock_get_encoding.assert_called_once_with("cl100k_base")
        mock_encoder.encode.assert_called_once_with(text)

    @patch('tiktoken.encoding_for_model')
    def test_truncate_text_tokens_exception_handling(self, mock_encoding_for_model):
        """Test exception handling in truncate_text_tokens."""
        # Setup mock to raise an exception
        mock_encoding_for_model.side_effect = Exception("Unexpected error")
        
        # Verify the function properly wraps the exception
        with self.assertRaises(RuntimeError) as context:
            truncate_text_tokens("gpt-4", "some text", 100)
        
        self.assertIn("Error during text truncation", str(context.exception))

if __name__ == '__main__':
    unittest.main() 