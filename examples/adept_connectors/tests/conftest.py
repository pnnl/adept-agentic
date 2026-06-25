"""Root conftest — adds subdirectory conftest modules to sys.path for direct import.

The chatgpt test files use `from conftest import create_mock_facade` which requires
the chatgpt conftest directory to be on sys.path BEFORE the generic conftest directory.
"""

import sys
from pathlib import Path

# chatgpt conftest must come first (it defines create_mock_facade)
_chatgpt_dir = str(Path(__file__).parent / "connectors" / "chatgpt")
if _chatgpt_dir not in sys.path:
    sys.path.insert(0, _chatgpt_dir)
