#!/usr/bin/env python3
"""
Test runner script for the infogen project.

This script discovers and runs all tests in the infogen/tests directory.
It provides a convenient way to run all tests with a single command.

Usage:
    python -m infogen.tests.run_tests
    
    # To run specific test modules:
    python -m infogen.tests.run_tests test_utilities test_url_validator_client
    
    # To run with verbose output:
    python -m infogen.tests.run_tests -v
"""

import unittest
import sys
import os
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

def run_tests():
    """Discover and run all tests in the infogen/tests directory."""
    # Get the directory of this script
    test_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Check if specific test modules were specified
    if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
        # Run specific test modules
        test_modules = [arg for arg in sys.argv[1:] if not arg.startswith('-')]
        test_suite = unittest.TestLoader().loadTestsFromNames(
            [f'infogen.tests.{module}' for module in test_modules]
        )
    else:
        # Discover and run all tests
        test_suite = unittest.defaultTestLoader.discover(test_dir)
    
    # Check for verbose flag
    verbosity = 2 if '-v' in sys.argv or '--verbose' in sys.argv else 1
    
    # Run the tests
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(test_suite)
    
    # Return non-zero exit code if tests failed
    return 0 if result.wasSuccessful() else 1

if __name__ == '__main__':
    sys.exit(run_tests()) 