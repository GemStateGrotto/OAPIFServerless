"""QGIS startup script for interactive plugin development.

Loaded via `qgis --code /plugin/scripts/startup.py` by the interactive
session launcher. Adds /plugin to the Python path and prints environment
info. Once the plugin has a proper entry point, this script will register
and enable it.
"""

from __future__ import annotations

import os
import sys

# Ensure /plugin is on the Python path
plugin_dir = "/plugin"
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)

# Print session info to the QGIS Python console
base_url = os.environ.get("OAPIF_BASE_URL", "(not set)")
has_token = "yes" if os.environ.get("OAPIF_ID_TOKEN") else "no"

print("OAPIFServerless plugin dev session")
print(f"  Base URL:  {base_url}")
print(f"  ID token:  {has_token}")
print(f"  Plugin dir on sys.path: {plugin_dir in sys.path}")
