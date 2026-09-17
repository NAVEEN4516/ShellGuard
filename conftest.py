import sys
import os
from pathlib import Path

# Ensure project root is on sys.path for test discovery
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

# Default disable auth in general test runs unless explicitly tested
os.environ.setdefault("SHELLGUARD_DISABLE_AUTH", "1")
