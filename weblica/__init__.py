"""
Weblica - Intelligent Web Application Exploration & Replaying Tool

A tool powered by CloakBrowser (CloakHQ patched Chromium) with automatic
fallback to Playwright + JS evasion. Intelligently explores web applications
frontends and replays them locally.

CloakBrowser integration:
- Automatically uses real CloakBrowser when the patched binary is available
- Falls back to Playwright + anti-detection scripts otherwise
- Human-like behavior (mouse, keyboard, scroll) via --humanize (default)
- Download binary: python -m weblica.browser --download
"""

__version__ = "0.1.0"
__author__ = "Weblica Team"

from .explorer import WebExplorer
from .replayer import WebReplayer
from .browser import CloakBrowser
from .session_manager import SessionManager, ExplorationSession

__all__ = ["WebExplorer", "WebReplayer", "CloakBrowser", "SessionManager", "ExplorationSession"]
