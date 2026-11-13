"""Stable packaged entry point; app remains an importable module for smoke tests."""
from app import main

if __name__ == '__main__':
    raise SystemExit(main())
