import logging
import sys
from typing import Optional

def configure_logging(level: int = logging.INFO, 
                     log_format: str = '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                     log_file: Optional[str] = None) -> logging.Logger:
    """
    Configure logging for the entire application.
    
    This function sets up a hierarchical logging structure where:
    - The root logger (affecting third-party libraries) is set to WARNING level
    - The application's logger (infogen) is set to the specified level
    
    Args:
        level: The logging level for the application code (default: INFO)
        log_format: The format string for log messages
        log_file: Optional path to a log file. If provided, logs will be written to this file
                 in addition to the console.
    
    Returns:
        The configured application root logger
    """
    # Create handlers
    handlers = [logging.StreamHandler(sys.stdout)]
    
    # Add file handler if log_file is specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(log_format))
        handlers.append(file_handler)
    
    # Configure root logger (third-party libraries) to WARNING level
    logging.basicConfig(
        level=logging.WARNING,  # Higher level for third-party libraries
        format=log_format,
        handlers=handlers
    )
    
    # Configure application's logger to the specified level
    app_logger = logging.getLogger("infogen")  # Application's root package name
    app_logger.setLevel(level)
    
    # Ensure propagation is enabled
    app_logger.propagate = True
    
    return app_logger

def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a specific module.
    
    This is a convenience function to get a logger with the correct naming convention.
    It should be used in each module like:
        logger = get_logger(__name__)
    
    Args:
        name: The name for the logger, typically __name__
        
    Returns:
        A configured logger instance
    """
    return logging.getLogger(name) 