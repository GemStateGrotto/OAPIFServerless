"""Unit tests for plugin configuration.

Pure Python — no QGIS dependency.  Validates serialization,
deserialization, defaults, and edge cases.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugin.config import (
    CollectionSelection,
    PluginConfig,
    ServerConnection,
    load_config,
    save_config,
)

# ---------------------------------------------------------------------------
# ServerConnection
# ---------------------------------------------------------------------------


@pytest.mark.qgis_unit
class TestServerConnection:
    """Server connection config validation and serialization."""

    def test_valid_connection(self) -> None:
        conn = ServerConnection(
            name="prod",
            base_url="https://api.example.com",
            cognito_domain="https://auth.example.com",
            client_id="abc123",
        )
        assert conn.validate() == []

    def test_missing_name(self) -> None:
        conn = ServerConnection(name="", base_url="https://api.example.com")
        errors = conn.validate()
        assert any("name" in e.lower() for e in errors)

    def test_missing_base_url(self) -> None:
        conn = ServerConnection(name="test", base_url="")
        errors = conn.validate()
        assert any("url" in e.lower() for e in errors)

    def test_invalid_base_url_scheme(self) -> None:
        conn = ServerConnection(name="test", base_url="ftp://example.com")
        errors = conn.validate()
        assert any("http" in e.lower() for e in errors)

    def test_invalid_cognito_domain_scheme(self) -> None:
        conn = ServerConnection(
            name="test",
            base_url="https://api.example.com",
            cognito_domain="ftp://auth.example.com",
        )
        errors = conn.validate()
        assert any("cognito" in e.lower() for e in errors)

    def test_http_base_url_accepted(self) -> None:
        conn = ServerConnection(name="local", base_url="http://localhost:8080")
        assert conn.validate() == []

    def test_roundtrip_dict(self) -> None:
        conn = ServerConnection(
            name="prod",
            base_url="https://api.example.com",
            cognito_domain="https://auth.example.com",
            client_id="abc123",
        )
        d = conn.to_dict()
        conn2 = ServerConnection.from_dict(d)
        assert conn2.name == conn.name
        assert conn2.base_url == conn.base_url
        assert conn2.cognito_domain == conn.cognito_domain
        assert conn2.client_id == conn.client_id

    def test_from_dict_strips_trailing_slashes(self) -> None:
        conn = ServerConnection.from_dict(
            {
                "name": "test",
                "base_url": "https://api.example.com/",
                "cognito_domain": "https://auth.example.com/",
            }
        )
        assert not conn.base_url.endswith("/")
        assert not conn.cognito_domain.endswith("/")

    def test_from_dict_defaults(self) -> None:
        conn = ServerConnection.from_dict({"name": "minimal"})
        assert conn.base_url == ""
        assert conn.cognito_domain == ""
        assert conn.client_id == ""


# ---------------------------------------------------------------------------
# CollectionSelection
# ---------------------------------------------------------------------------


@pytest.mark.qgis_unit
class TestCollectionSelection:
    """Collection selection state."""

    def test_roundtrip_dict(self) -> None:
        sel = CollectionSelection(
            connection_name="prod", selected_ids=["caves", "springs"]
        )
        d = sel.to_dict()
        sel2 = CollectionSelection.from_dict(d)
        assert sel2.connection_name == "prod"
        assert sel2.selected_ids == ["caves", "springs"]


# ---------------------------------------------------------------------------
# PluginConfig
# ---------------------------------------------------------------------------


@pytest.mark.qgis_unit
class TestPluginConfig:
    """Top-level plugin config management."""

    def test_defaults(self) -> None:
        cfg = PluginConfig()
        assert cfg.connections == []
        assert cfg.active_connection == ""
        assert cfg.default_limit == 100
        assert cfg.auto_refresh_tokens is True

    def test_add_connection(self) -> None:
        cfg = PluginConfig()
        conn = ServerConnection(name="prod", base_url="https://api.example.com")
        cfg.add_connection(conn)
        assert len(cfg.connections) == 1
        assert cfg.get_connection("prod") is not None

    def test_add_connection_replaces_existing(self) -> None:
        cfg = PluginConfig()
        conn1 = ServerConnection(name="prod", base_url="https://old.example.com")
        conn2 = ServerConnection(name="prod", base_url="https://new.example.com")
        cfg.add_connection(conn1)
        cfg.add_connection(conn2)
        assert len(cfg.connections) == 1
        fetched = cfg.get_connection("prod")
        assert fetched is not None
        assert fetched.base_url == "https://new.example.com"

    def test_remove_connection(self) -> None:
        cfg = PluginConfig()
        cfg.add_connection(
            ServerConnection(name="prod", base_url="https://api.example.com")
        )
        cfg.active_connection = "prod"
        cfg.set_selected_collections("prod", ["caves"])

        removed = cfg.remove_connection("prod")
        assert removed is True
        assert cfg.get_connection("prod") is None
        assert cfg.active_connection == ""
        assert cfg.get_selected_collections("prod") == []

    def test_remove_nonexistent_connection(self) -> None:
        cfg = PluginConfig()
        assert cfg.remove_connection("nope") is False

    def test_active_connection(self) -> None:
        cfg = PluginConfig()
        conn = ServerConnection(name="prod", base_url="https://api.example.com")
        cfg.add_connection(conn)
        cfg.active_connection = "prod"
        assert cfg.get_active_connection() is not None
        assert cfg.get_active_connection() == conn

    def test_active_connection_none(self) -> None:
        cfg = PluginConfig()
        assert cfg.get_active_connection() is None

    def test_collection_selections(self) -> None:
        cfg = PluginConfig()
        cfg.set_selected_collections("prod", ["caves", "springs"])
        assert cfg.get_selected_collections("prod") == ["caves", "springs"]
        assert cfg.get_selected_collections("nope") == []

    def test_collection_selections_replace(self) -> None:
        cfg = PluginConfig()
        cfg.set_selected_collections("prod", ["caves"])
        cfg.set_selected_collections("prod", ["springs"])
        assert cfg.get_selected_collections("prod") == ["springs"]

    def test_collection_selections_clear(self) -> None:
        cfg = PluginConfig()
        cfg.set_selected_collections("prod", ["caves"])
        cfg.set_selected_collections("prod", [])
        assert cfg.get_selected_collections("prod") == []

    def test_roundtrip_dict(self) -> None:
        cfg = PluginConfig()
        cfg.add_connection(
            ServerConnection(
                name="prod", base_url="https://api.example.com", client_id="abc"
            )
        )
        cfg.add_connection(
            ServerConnection(name="dev", base_url="http://localhost:8080")
        )
        cfg.active_connection = "prod"
        cfg.set_selected_collections("prod", ["caves"])
        cfg.default_limit = 50
        cfg.auto_refresh_tokens = False

        d = cfg.to_dict()
        cfg2 = PluginConfig.from_dict(d)

        assert len(cfg2.connections) == 2
        assert cfg2.active_connection == "prod"
        assert cfg2.get_selected_collections("prod") == ["caves"]
        assert cfg2.default_limit == 50
        assert cfg2.auto_refresh_tokens is False


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


@pytest.mark.qgis_unit
class TestConfigPersistence:
    """Save and load config from disk."""

    def test_save_and_load(self, tmp_path: Path) -> None:
        cfg = PluginConfig()
        cfg.add_connection(
            ServerConnection(name="test", base_url="https://api.example.com")
        )
        cfg.active_connection = "test"
        cfg.default_limit = 42

        config_file = tmp_path / "config.json"
        save_config(cfg, path=config_file)
        loaded = load_config(path=config_file)

        assert loaded.active_connection == "test"
        assert loaded.default_limit == 42
        assert len(loaded.connections) == 1
        assert loaded.connections[0].name == "test"

    def test_load_missing_file(self, tmp_path: Path) -> None:
        config_file = tmp_path / "nope.json"
        loaded = load_config(path=config_file)
        assert loaded.connections == []
        assert loaded.default_limit == 100

    def test_load_invalid_json(self, tmp_path: Path) -> None:
        config_file = tmp_path / "bad.json"
        config_file.write_text("not valid json!!!", encoding="utf-8")
        loaded = load_config(path=config_file)
        assert loaded.connections == []

    def test_load_missing_fields(self, tmp_path: Path) -> None:
        config_file = tmp_path / "partial.json"
        config_file.write_text('{"active_connection": "foo"}', encoding="utf-8")
        loaded = load_config(path=config_file)
        assert loaded.active_connection == "foo"
        assert loaded.connections == []
        assert loaded.default_limit == 100
