"""Rebuild the file ownership of inspected code, defaults and source metadata."""

from pathlib import Path
import sys
from build_namespace import build

if __name__ == "__main__":
    build(*(Path(v).resolve() for v in sys.argv[1:]), hooks="source_observers")
