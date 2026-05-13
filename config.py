"""
Central configuration for The Poneglyph System.
Override these values via environment variables before launching api.py.
"""

import os

# HTTP server
HOST = os.environ.get("PONEGLYPH_HOST", "0.0.0.0")
PORT = int(os.environ.get("PONEGLYPH_PORT", "8000"))

# Simulation engine
SIM_TICK_INTERVAL_S  = 0.1   # seconds between physics ticks
SIM_HEARTBEAT_MS     = 100.0 # milliseconds between heartbeat frames
SIM_MIN_SPEED        = 0.01
SIM_MAX_SPEED        = 100.0

# File system
STATIC_DIR    = "static"
SITES_DIR     = "sites"
TEMPLATES_DIR = "templates"
