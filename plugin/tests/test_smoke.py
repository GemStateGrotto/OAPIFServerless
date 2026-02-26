"""Smoke test — verify QGIS environment is functional.

Starts QgsApplication, checks that the OAPIF (WFS3) provider is registered
in QgsProviderRegistry, and exits. This validates the test container is
correctly set up before running real tests.
"""

from __future__ import annotations

import pytest


@pytest.mark.qgis_headless
def test_qgis_application_starts(qgis_app: object) -> None:
    """QgsApplication initializes successfully."""
    from qgis.core import QgsApplication

    assert qgis_app is not None
    assert isinstance(qgis_app, QgsApplication)


@pytest.mark.qgis_headless
def test_oapif_provider_registered(qgis_app: object) -> None:
    """QGIS has the OAPIF (WFS3) data provider available."""
    from qgis.core import QgsProviderRegistry

    registry = QgsProviderRegistry.instance()
    providers = registry.providerList()

    # The built-in OAPIF provider is registered as "OAPIF" or "WFS3"
    # depending on QGIS version. Check for either.
    has_oapif = "OAPIF" in providers or "WFS3" in providers
    assert has_oapif, (
        f"Neither 'OAPIF' nor 'WFS3' provider found. Available providers: {providers}"
    )
