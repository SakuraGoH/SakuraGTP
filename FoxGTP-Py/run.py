"""Convenience launcher: python run.py"""

import os
import sys

if not getattr(sys, "frozen", False):
    root = os.path.dirname(os.path.abspath(__file__))
    if root not in sys.path:
        sys.path.insert(0, root)

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
