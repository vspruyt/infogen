from fastapi import FastAPI
from infogen.core.logging_config import configure_logging
import logging
import argparse
import sys
import os

def parse_args():
    """Parse command line arguments for the application."""
    parser = argparse.ArgumentParser(description="InfoGen API Server")
    parser.add_argument(
        "--log-level", 
        type=str, 
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level"
    )
    parser.add_argument(
        "--log-file",
        type=str,
        help="Optional log file path"
    )
    return parser.parse_args()

def main():
    # Parse command line arguments
    args = parse_args()
    
    # Convert string log level to logging constant
    log_level = getattr(logging, args.log_level)
    
    # Configure application logging
    app_logger = configure_logging(
        level=log_level,
        log_file=args.log_file
    )
    
    app_logger.info(f"Starting InfoGen application with log level: {args.log_level}")
    app_logger.debug("Debug logging is enabled")
    
    # Create the FastAPI app instance
    infogen = FastAPI()
    
    # Define a simple route
    @infogen.get("/")
    def read_root():
        app_logger.debug("Root endpoint accessed")
        return {"message": "Hello, World reloaded!"}
    
    # Return the FastAPI app
    return infogen

# Create the FastAPI app instance
infogen = main()

# For direct execution
if __name__ == "__main__":
    import uvicorn
    
    # Get the port from environment or use default
    port = int(os.environ.get("PORT", 8000))
    
    # Run the application
    uvicorn.run(
        "main:infogen", 
        host="0.0.0.0", 
        port=port, 
        reload=True
    )

