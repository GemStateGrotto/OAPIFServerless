"""Smoke test to verify the test harness works."""

import pytest


@pytest.mark.unit
def test_import_oapif() -> None:
    """Verify the oapif package is importable."""
    import oapif

    assert oapif.__version__ == "0.1.0"


@pytest.mark.unit
def test_runtime_config_from_env(lambda_env: dict[str, str]) -> None:
    """Verify RuntimeConfig loads from environment variables."""
    from oapif.config import RuntimeConfig

    config = RuntimeConfig.from_env()
    assert config.features_table == "oapif-test-features"
    assert config.changes_table == "oapif-test-changes"
    assert config.config_table == "oapif-test-config"
    assert config.environment == "test"
    assert config.log_level == "DEBUG"
