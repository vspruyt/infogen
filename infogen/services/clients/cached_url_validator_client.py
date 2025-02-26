import requests
from typing import Dict, Optional
from urllib.parse import urlparse, quote
import re
from langchain.tools import StructuredTool
import warnings
from urllib3.exceptions import InsecureRequestWarning

# Disable SSL verification warnings
warnings.filterwarnings('ignore', category=InsecureRequestWarning)

class URLValidatorClient:
    # Common browser headers to avoid 403 errors
    DEFAULT_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Cache-Control': 'max-age=0',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Sec-Ch-Ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"macOS"',
        'Referer': 'https://www.google.com/'
    }

    # Known domains that use paywalls/subscriptions
    SUBSCRIPTION_DOMAINS = {
        'nytimes.com',
        'wsj.com',
        'ft.com',
        'economist.com',
        'bloomberg.com',
        'washingtonpost.com',
        'newyorker.com',
        'medium.com',
        'forbes.com',
        'reuters.com'
    }

    # Status codes that indicate the URL is technically valid even if not accessible
    VALID_BUT_RESTRICTED_CODES = {
        401,  # Unauthorized but exists
        403,  # Forbidden but exists
        405,  # Method not allowed but exists
        451,  # Unavailable for legal reasons but exists
        999,  # LinkedIn and others custom "denied" code
    }

    def __init__(self):
        """Initialize the URL validator client."""
        pass

    @staticmethod
    def _is_subscription_site(url: str) -> bool:
        """
        Check if the URL belongs to a known subscription/paywall site.
        """
        try:
            domain = urlparse(url).netloc.lower()
            return any(domain.endswith(sub_domain) for sub_domain in URLValidatorClient.SUBSCRIPTION_DOMAINS)
        except:
            return False

    def _get_session(self) -> requests.Session:
        """
        Creates a new session with proper headers.
        Thread-safe as it creates a new session each time.
        """
        session = requests.Session()
        session.headers.update(self.DEFAULT_HEADERS)
        return session

    @staticmethod
    def _clean_url(url: str) -> str:
        """
        Clean and normalize the URL by:
        - Removing leading/trailing whitespace
        - Ensuring proper encoding of special characters
        - Handling common URL formatting issues
        """
        url = url.strip()
        url_parts = url.split('#', 1)
        base_url = url_parts[0]
        anchor = f"#{url_parts[1]}" if len(url_parts) > 1 else ""
        safe_chars = ':/?=&%@+,;'
        base_url = quote(base_url, safe=safe_chars)
        return base_url + anchor
    
    @staticmethod
    def _validate_image(session: requests.Session, url: str) -> bool:
        """
        Performs additional validation for image URLs by checking the actual content.
        """
        try:
            response = session.get(url, timeout=10, stream=True)
            content = next(response.iter_content(32))
            response.close()
            signatures = {
                b'\xFF\xD8\xFF': 'jpeg',
                b'\x89PNG\r\n\x1a\n': 'png',
                b'GIF87a': 'gif',
                b'GIF89a': 'gif',
                b'RIFF': 'webp'
            }
            return any(content.startswith(sig) for sig in signatures.keys())
        except:
            return False

    @staticmethod
    def _ensure_www_prefix(url: str) -> str:
        """
        Ensures the URL has a www prefix if needed.
        """
        parsed = urlparse(url)
        if parsed.netloc and not parsed.netloc.startswith('www.'):
            netloc = 'www.' + parsed.netloc
            return parsed._replace(netloc=netloc).geturl()
        return url

    def validate_url(self, url: str) -> bool:
        """
        Validates a URL by checking its accessibility and content.
        
        Args:
            url: The URL to validate
            
        Returns:
            bool: True if the URL is valid and accessible, False otherwise
        """
        # Clean the URL first
        url = self._clean_url(url)
        
        # Validate URL format
        try:
            parsed = urlparse(url)
            if not all([parsed.scheme, parsed.netloc]):
                print(f"Invalid URL format: {url}")
                return False
        except Exception as e:
            print(f"URL parsing error: {str(e)}")
            return False

        def try_request(session: requests.Session, with_custom_headers: bool, verify_ssl: bool = True) -> tuple[bool, requests.Response | None]:
            """Helper function to try a request with or without custom headers and SSL verification"""
            try:
                if with_custom_headers:
                    # Add site-specific headers
                    additional_headers = {
                        'Host': parsed.netloc,
                        'Origin': f"{parsed.scheme}://{parsed.netloc}",
                        'authority': parsed.netloc,
                        'pragma': 'no-cache',
                    }
                    session.headers.update(additional_headers)
                    # Set a lower max_redirects to fail faster on redirect loops
                    session.max_redirects = 5
                
                response = session.get(url, allow_redirects=True, timeout=10, verify=verify_ssl)
                
                # If we got redirected, log the final URL for debugging
                if response.history:
                    print(f"URL was redirected: {url} -> {response.url}")
                
                content_type = response.headers.get('content-type', '').lower()
                
                # URL is valid if:
                # 1. It returns a success code (200-399)
                # 2. It returns a restricted code (401, 403, etc.) - means the URL exists but is protected
                is_valid = 200 <= response.status_code < 400 or response.status_code in self.VALID_BUT_RESTRICTED_CODES
                
                # For images, perform additional validation only if we have full access
                if is_valid and 'image' in content_type and response.status_code == 200:
                    is_valid = self._validate_image(session, response.url)  # Use final URL after redirects
                    if not is_valid:
                        print("Image validation failed: Invalid image format or corrupted data")
                
                return is_valid, response
                
            except requests.exceptions.SSLError as e:
                if verify_ssl:
                    # If SSL verification failed, return None to indicate we should retry without verification
                    print(f"SSL verification failed for {url}, will retry without verification")
                    return None, None
                else:
                    print(f"SSL error for {url} even without verification: {str(e)}")
                    return False, None
            except requests.RequestException as e:
                print(f"Request error for {url} {'with' if with_custom_headers else 'without'} custom headers: {str(e)}")
                return False, None
            except Exception as e:
                print(f"Unexpected error while validating {url}: {str(e)}")
                return False, None
        
        # Try to access the URL using a new session
        session = None
        response = None
        try:
            # First try with custom headers and SSL verification
            session = self._get_session()
            is_valid, response = try_request(session, with_custom_headers=True, verify_ssl=True)
            
            # If we got None back, it means SSL failed - retry without verification
            if is_valid is None:
                if session:
                    session.close()
                session = self._get_session()
                is_valid, response = try_request(session, with_custom_headers=True, verify_ssl=False)
                if is_valid:
                    return True
            elif is_valid:
                return True
                
            # If that failed, try without custom headers
            if session:
                session.close()
            session = self._get_session()
            is_valid, response = try_request(session, with_custom_headers=False, verify_ssl=False)
            return is_valid
            
        finally:
            if response:
                response.close()
            if session:
                session.close()

    @classmethod
    def get_url_validator_tool(cls) -> StructuredTool:
        """
        Returns a StructuredTool for use with LangGraph agents that validates URLs.
        """
        validator = cls()
        return StructuredTool.from_function(
            func=validator.validate_url,
            name="validate_url",
            description="Use this tool to validate a URL and check if it is accessible. Returns True if the URL is valid and accessible, False otherwise."
        ) 