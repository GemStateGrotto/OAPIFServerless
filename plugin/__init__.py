"""OAPIFServerless QGIS Plugin.

Connects QGIS to an OGC API - Features backend deployed on AWS,
providing authentication, layer loading, and feature editing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qgis.gui import QgisInterface


def classFactory(iface: QgisInterface) -> object:  # noqa: N802
    """QGIS plugin entry point — called by QGIS on plugin load.

    Parameters
    ----------
    iface:
        The QGIS application interface.

    Returns
    -------
    The plugin instance.
    """
    from plugin.plugin import OapifPlugin

    return OapifPlugin(iface)
