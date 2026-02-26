"""Plugin configuration — server connections and user preferences.

Pure Python, no PyQGIS dependency.  Configuration is persisted as JSON
in the user's config directory.  When running inside QGIS, a QSettings
adapter can be used instead (Phase P4).

Configuration hierarchy:
  - ``ServerConnection``: base URL, Cognito domain, client ID
  - ``PluginConfig``: list of connections, active connection, preferences
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Server connection
# ---------------------------------------------------------------------------


@dataclass
class ServerConnection:
    """Configuration for a single OAPIF server."""

    name: str
    base_url: str
    cognito_domain: str = ""
    client_id: str = ""

    def validate(self) -> list[str]:
        """Return a list of validation errors (empty = valid)."""
        errors: list[str] = []
        if not self.name.strip():
            errors.append("Connection name is required")
        if not self.base_url.strip():
            errors.append("Base URL is required")
        if self.base_url and not (
            self.base_url.startswith("http://") or self.base_url.startswith("https://")
        ):
            errors.append("Base URL must start with http:// or https://")
        if self.cognito_domain and not (
            self.cognito_domain.startswith("http://")
            or self.cognito_domain.startswith("https://")
        ):
            errors.append("Cognito domain must start with http:// or https://")
        return errors

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServerConnection:
        return cls(
            name=data.get("name", ""),
            base_url=data.get("base_url", "").rstrip("/"),
            cognito_domain=data.get("cognito_domain", "").rstrip("/"),
            client_id=data.get("client_id", ""),
        )

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Collection selection
# ---------------------------------------------------------------------------


@dataclass
class CollectionSelection:
    """Tracks which collections are selected for a server connection."""

    connection_name: str
    selected_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CollectionSelection:
        return cls(
            connection_name=data.get("connection_name", ""),
            selected_ids=data.get("selected_ids", []),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Plugin config
# ---------------------------------------------------------------------------


@dataclass
class PluginConfig:
    """Top-level plugin configuration.

    Stores server connections, collection selections, and user preferences.
    """

    connections: list[ServerConnection] = field(default_factory=list)
    active_connection: str = ""
    collection_selections: list[CollectionSelection] = field(default_factory=list)

    # Preferences
    default_limit: int = 100
    auto_refresh_tokens: bool = True

    def get_connection(self, name: str) -> ServerConnection | None:
        """Find a connection by name."""
        for conn in self.connections:
            if conn.name == name:
                return conn
        return None

    def add_connection(self, conn: ServerConnection) -> None:
        """Add or replace a connection by name."""
        self.connections = [c for c in self.connections if c.name != conn.name]
        self.connections.append(conn)

    def remove_connection(self, name: str) -> bool:
        """Remove a connection by name. Returns True if found."""
        before = len(self.connections)
        self.connections = [c for c in self.connections if c.name != name]
        if self.active_connection == name:
            self.active_connection = ""
        self.collection_selections = [
            s for s in self.collection_selections if s.connection_name != name
        ]
        return len(self.connections) < before

    def get_active_connection(self) -> ServerConnection | None:
        """Return the currently active connection, or None."""
        if self.active_connection:
            return self.get_connection(self.active_connection)
        return None

    def set_selected_collections(
        self, connection_name: str, collection_ids: list[str]
    ) -> None:
        """Update the selected collections for a connection."""
        self.collection_selections = [
            s
            for s in self.collection_selections
            if s.connection_name != connection_name
        ]
        if collection_ids:
            self.collection_selections.append(
                CollectionSelection(
                    connection_name=connection_name, selected_ids=collection_ids
                )
            )

    def get_selected_collections(self, connection_name: str) -> list[str]:
        """Return selected collection IDs for a connection."""
        for sel in self.collection_selections:
            if sel.connection_name == connection_name:
                return list(sel.selected_ids)
        return []

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginConfig:
        return cls(
            connections=[
                ServerConnection.from_dict(c) for c in data.get("connections", [])
            ],
            active_connection=data.get("active_connection", ""),
            collection_selections=[
                CollectionSelection.from_dict(s)
                for s in data.get("collection_selections", [])
            ],
            default_limit=data.get("default_limit", 100),
            auto_refresh_tokens=data.get("auto_refresh_tokens", True),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "connections": [c.to_dict() for c in self.connections],
            "active_connection": self.active_connection,
            "collection_selections": [s.to_dict() for s in self.collection_selections],
            "default_limit": self.default_limit,
            "auto_refresh_tokens": self.auto_refresh_tokens,
        }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _config_file_path() -> Path:
    """Return the path to the plugin config file."""
    config_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_dir / "oapif-qgis-plugin" / "config.json"


def save_config(config: PluginConfig, *, path: Path | None = None) -> None:
    """Save the plugin config to disk.

    Parameters
    ----------
    config:
        The configuration to save.
    path:
        Override the default config file path (for testing).
    """
    if path is None:
        path = _config_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")


def load_config(*, path: Path | None = None) -> PluginConfig:
    """Load the plugin config from disk.

    Returns a default config if the file doesn't exist or is invalid.

    Parameters
    ----------
    path:
        Override the default config file path (for testing).
    """
    if path is None:
        path = _config_file_path()
    if not path.is_file():
        return PluginConfig()
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return PluginConfig.from_dict(data)
    except (json.JSONDecodeError, KeyError, TypeError):
        return PluginConfig()
