"""Visible desktop entry point. No auto-start or autostart-registration code."""

import sys
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo))

from control_panel.app import main  # noqa: E402

if __name__ == "__main__":
    main(repo)
