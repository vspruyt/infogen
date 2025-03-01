"""
Configuration file for pytest.

This file is automatically loaded by pytest and can be used to define fixtures,
hooks, and other test configuration.
"""

import os
import sys
from pathlib import Path

# Add the project root directory to the Python path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root)) 