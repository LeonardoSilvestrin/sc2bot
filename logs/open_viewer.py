"""Open the log viewer HTML page in the default browser."""

from __future__ import annotations

import webbrowser
from pathlib import Path

if __name__ == "__main__":
    path = Path(__file__).resolve().parent / "viewer.html"
    webbrowser.open(path.as_uri())
