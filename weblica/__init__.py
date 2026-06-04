"""
Weblica - Intelligent Web Application Cloning & Replaying Tool

A tool powered by CloakBrowser (stealth Playwright) to intelligently clone
web application frontends and replay them locally.
"""

__version__ = "0.1.0"
__author__ = "Weblica Team"

from .cloner import WebCloner
from .replayer import WebReplayer
from .browser import CloakBrowser

__all__ = ["WebCloner", "WebReplayer", "CloakBrowser"]
