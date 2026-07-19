"""Configuration loader for the drafting module.

Loads environment variables from a local ``.env`` file when present.
Safe to call multiple times (idempotent).
"""

from __future__ import annotations


def load_config() -> None:
    """Load environment variables from the project ``.env`` file.

    Searches the project root directory.  Silently ignores a missing file
    (production / CI environments use real environment variables instead).
    """
    from pathlib import Path

    try:
        from dotenv import load_dotenv as _load

        # Resolve project root relative to this file
        project_root = Path(__file__).resolve().parents[2]
        dotenv_path = project_root / ".env"
        if dotenv_path.exists():
            _load(dotenv_path=dotenv_path)
    except ImportError:
        # python-dotenv is optional; environment variables may be set directly
        pass


# Auto-load on first import so that all downstream modules see the values
load_config()