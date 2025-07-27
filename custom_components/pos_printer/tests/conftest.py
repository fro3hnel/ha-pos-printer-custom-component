import sys
from pathlib import Path

# Ensure repository root is on sys.path so 'custom_components' can be imported
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
