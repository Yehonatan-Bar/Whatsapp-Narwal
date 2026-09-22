"""Make the repo-root modules importable from tests/ (pytest prepends this dir because the root
conftest lives here)."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
