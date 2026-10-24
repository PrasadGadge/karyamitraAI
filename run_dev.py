"""Windows-safe development server entry point with focused reload watching."""
from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

PROJECT_DIR = Path(__file__).resolve().parent
# Uvicorn resolves these as working-directory-relative glob patterns.  The
# trailing wildcard is required for its Watchfiles filter to reject events
# reported with absolute paths.  Passing them here avoids PowerShell expansion.
RELOAD_EXCLUDES = (".venv/*", "evaluation_runs/*")


def run(port: int = 8000) -> None:
    """Run Uvicorn programmatically so PowerShell never expands glob patterns."""
    uvicorn.run(
        "app:app",
        host="127.0.0.1",
        port=port,
        reload=True,
        reload_dirs=[str(PROJECT_DIR)],
        reload_excludes=list(RELOAD_EXCLUDES),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run KaryaMitra AI with focused hot reload.")
    parser.add_argument("--port", type=int, default=8000)
    run(parser.parse_args().port)
