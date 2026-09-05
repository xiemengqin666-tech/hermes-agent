#!/usr/bin/env python3
"""Fast pre-run context for daily AI news cron.

Uses the latest Horizon summary plus live RSS, but does not run Horizon itself.
This keeps Hermes cron pre-run under the scheduler script timeout.
"""
import os
import sys
from pathlib import Path

TARGET = Path.home() / ".hermes" / "scripts" / "horizon_ai_news_context.py"
os.execv(sys.executable, [
    sys.executable,
    str(TARGET),
    "--skip-horizon",
    "--rss-timeout",
    "90",
])
