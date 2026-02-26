"""Main QGIS plugin class — OAPIFServerless.

This is a stub implementation for Phase P1. GUI integration (menus,
toolbars, dialogs) will be added in Phase P4.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qgis.gui import QgisInterface


class OapifPlugin:
    """OAPIFServerless QGIS plugin.

    Manages the plugin lifecycle: init, GUI setup, and cleanup.
    Actual functionality (auth, layer loading, editing) is delegated
    to the core modules (`client`, `auth`, `config`).
    """

    def __init__(self, iface: QgisInterface) -> None:
        self.iface = iface

    def initGui(self) -> None:  # noqa: N802
        """Create GUI elements (menus, toolbar buttons).

        Called by QGIS when the plugin is activated. Stub for now —
        GUI widgets will be added in Phase P4.
        """

    def unload(self) -> None:
        """Remove GUI elements and clean up resources.

        Called by QGIS when the plugin is deactivated.
        """
