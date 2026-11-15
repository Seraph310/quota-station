"""Stable packaged entry point; app remains an importable module for smoke tests."""
import sys

if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--apply-update':
        from updater_core import apply_job
        raise SystemExit(apply_job(sys.argv[2]))
    from app import main
    raise SystemExit(main())
