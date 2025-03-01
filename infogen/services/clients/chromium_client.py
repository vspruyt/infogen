from langchain_community.document_loaders import AsyncChromiumLoader
from langchain_community.document_transformers import Html2TextTransformer
from typing import Optional
import os
from infogen.core.logging_config import get_logger

# Configure logging
logger = get_logger(__name__)

def scrape_with_chromium(url: str) -> Optional[str]:
    """
    Scrapes content from a given URL using Chromium browser automation.
    
    Args:
        url (str): The URL to scrape content from.
        
    Returns:
        Optional[str]: The scraped and transformed text content.
                      Returns None if the URL is invalid or if scraping fails.
        
    Raises:
        ValueError: If the provided URL is invalid.
    """
    
    logger.info(f"Starting scraping process for URL: {url}")
    
    try:
        # Initialize the chromium loader with user agent
        user_agent = os.getenv("USER_AGENT")
        if not user_agent:
            logger.warning("USER_AGENT environment variable not set. This might affect scraping reliability.")
            
        logger.debug(f"Initializing AsyncChromiumLoader with user agent: {user_agent or 'default'}")
        loader = AsyncChromiumLoader([url], user_agent=user_agent)
        
        # Load HTML content
        logger.debug(f"Attempting to load content from {url}")
        html = loader.load()
        
        if not html:
            logger.warning(f"No HTML content loaded from {url}")
            return None
            
        logger.debug(f"Successfully loaded HTML content from {url} (size: {len(html[0].page_content) if html and len(html) > 0 else 0} bytes)")
        
        # Transform HTML to text
        logger.debug("Transforming HTML to text")
        html2text = Html2TextTransformer()
        docs_transformed = html2text.transform_documents(html)
        
        # Validate transformed content
        if (not docs_transformed or 
            len(docs_transformed) == 0 or 
            not docs_transformed[0].page_content or
            len(docs_transformed[0].page_content) < 10 or 
            'Error' in docs_transformed[0].page_content[0:10]):
            
            logger.error(f"Failed to extract valid content from {url}")
            return None
            
        content_length = len(docs_transformed[0].page_content)
        logger.debug(f"Successfully scraped content from {url} (content length: {content_length} characters)")
        
        # Log a snippet of the content for debugging
        content_preview = docs_transformed[0].page_content[:100].replace('\n', ' ').strip()
        logger.debug(f"Content preview: '{content_preview}...'")
        
        return docs_transformed[0].page_content
        
    except Exception as e:
        logger.error(f"Error while scraping {url}: {str(e)}", exc_info=True)
        return None
