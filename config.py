"""
Central configuration for The Poneglyph System.
Override these values via environment variables before launching api.py.
"""

import os

# HTTP server
HOST = os.environ.get("PONEGLYPH_HOST", "0.0.0.0")
PORT = int(os.environ.get("PONEGLYPH_PORT", "8000"))

# File system
STATIC_DIR    = "static"
SITES_DIR     = "sites"
TEMPLATES_DIR = "templates"
