#!/usr/bin/env python3
"""Run the exporter bundled with the skill (the single source of truth)."""

import runpy
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "skill" / "export-search-console" / "scripts" / "search_console_export.py"

if __name__ == "__main__":
    runpy.run_path(str(SCRIPT), run_name="__main__")
