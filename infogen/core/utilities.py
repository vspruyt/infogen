import tiktoken
from typing import Optional
from infogen.core.logging_config import get_logger

# Configure logging
logger = get_logger(__name__)

def truncate_text_tokens(base_model_str: str, text: str, max_tokens: int = 100000) -> str:
    """Truncates text to fit within a specified token limit while preserving sentence boundaries.
    
    This function uses the tiktoken library to count tokens according to the specified model's
    tokenization scheme. It attempts to truncate at sentence boundaries for more natural results.
    
    Args:
        base_model_str (str): The name of the model to use for tokenization (e.g., 'gpt-4', 'gpt-4o').
        text (str): The input text to truncate.
        max_tokens (int, optional): Maximum number of tokens to keep. Defaults to 100000.
    
    Returns:
        str: The truncated text, ending at a sentence boundary if possible, with a note if truncated.
        
    Raises:
        ValueError: If max_tokens is less than 1 or if base_model_str is empty.
        TypeError: If inputs are of incorrect type.
    """
    logger.info(f"Truncating text for model '{base_model_str}' with max tokens: {max_tokens}")
    
    # Input validation
    if not isinstance(text, str):
        logger.error("TypeError: text must be a string")
        raise TypeError("text must be a string")
    if not isinstance(base_model_str, str) or not base_model_str.strip():
        logger.error("ValueError: base_model_str must be a non-empty string")
        raise ValueError("base_model_str must be a non-empty string")
    if not isinstance(max_tokens, int) or max_tokens < 1:
        logger.error(f"ValueError: max_tokens must be a positive integer, got {max_tokens}")
        raise ValueError("max_tokens must be a positive integer")
    
    # Log text length for debugging
    text_length = len(text)
    logger.debug(f"Input text length: {text_length} characters")
    
    try:
        logger.debug(f"Initializing tokenizer for model: {base_model_str}")
        # Initialize tokenizer
        try:
            encoding = tiktoken.encoding_for_model(base_model_str)
            logger.debug(f"Successfully initialized tokenizer for model: {base_model_str}")
        except KeyError:
            logger.warning(f"Model '{base_model_str}' not found in tiktoken. Falling back to cl100k_base encoding.")
            encoding = tiktoken.get_encoding("cl100k_base")
        
        # Get tokens for the text
        logger.debug("Tokenizing text...")
        tokens = encoding.encode(text)
        token_count = len(tokens)
        logger.debug(f"Text tokenized to {token_count} tokens")
        
        if token_count <= max_tokens:
            logger.debug(f"Text already within token limit ({token_count}/{max_tokens})")
            return text
            
        # Truncate tokens and decode
        logger.info(f"Truncating text from {token_count} to {max_tokens} tokens ({(max_tokens/token_count)*100:.1f}% of original)")
        truncated_tokens = tokens[:max_tokens]
        logger.debug("Decoding truncated tokens back to text")
        truncated_text = encoding.decode(truncated_tokens)
        
        # Try to end at a sentence boundary
        logger.debug("Looking for sentence boundary to improve truncation")
        last_period = truncated_text.rfind('.')
        last_question = truncated_text.rfind('?')
        last_exclamation = truncated_text.rfind('!')
        
        # Find the latest sentence boundary
        sentence_end = max(last_period, last_question, last_exclamation)
        
        if sentence_end > 0:
            logger.debug(f"Found sentence boundary at position {sentence_end}")
            original_length = len(truncated_text)
            # Extract the text up to and including the sentence boundary
            # This ensures we don't include partial sentences after the boundary
            truncated_text = truncated_text[:sentence_end + 1]
            
            # If there's any text after the sentence boundary, remove it
            # This handles cases where the sentence boundary is in the middle of a word
            if last_period == sentence_end:
                parts = truncated_text.rsplit('.', 1)
                if len(parts) > 1:
                    truncated_text = parts[0] + '.'
            elif last_question == sentence_end:
                parts = truncated_text.rsplit('?', 1)
                if len(parts) > 1:
                    truncated_text = parts[0] + '?'
            elif last_exclamation == sentence_end:
                parts = truncated_text.rsplit('!', 1)
                if len(parts) > 1:
                    truncated_text = parts[0] + '!'
                    
            logger.debug(f"Further truncated text from {original_length} to {len(truncated_text)} characters to end at sentence boundary")
        else:
            logger.debug("No suitable sentence boundary found for truncation")
        
        final_text = truncated_text.rstrip() + "\n\n[Content truncated due to length...]"
        logger.info(f"Truncation complete. Final text length: {len(final_text)} characters")
        return final_text
        
    except Exception as e:
        logger.exception(f"Error during text truncation: {str(e)}")
        raise RuntimeError(f"Error during text truncation: {str(e)}")