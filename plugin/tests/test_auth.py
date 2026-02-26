"""Unit tests for OIDC/PKCE authentication.

Pure Python — no QGIS dependency.  Mocks Cognito discovery and token
exchange, validates PKCE challenge/verifier generation, and tests
the token lifecycle (expiry detection, refresh flow, storage).
"""

from __future__ import annotations

import json
import time
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from plugin.auth import (
    AuthenticationError,
    AuthManager,
    OidcConfig,
    TokenSet,
    build_auth_url,
    clear_tokens,
    compute_code_challenge,
    discover_oidc,
    exchange_code_for_tokens,
    generate_code_verifier,
    load_tokens,
    refresh_tokens,
    store_tokens,
)

# ---------------------------------------------------------------------------
# PKCE
# ---------------------------------------------------------------------------


@pytest.mark.qgis_unit
class TestPkce:
    """PKCE code_verifier / code_challenge generation."""

    def test_verifier_length(self) -> None:
        v = generate_code_verifier(64)
        assert len(v) == 64

    def test_verifier_min_length(self) -> None:
        v = generate_code_verifier(43)
        assert len(v) == 43

    def test_verifier_max_length(self) -> None:
        v = generate_code_verifier(128)
        assert len(v) == 128

    def test_verifier_invalid_short(self) -> None:
        with pytest.raises(ValueError, match="43-128"):
            generate_code_verifier(42)

    def test_verifier_invalid_long(self) -> None:
        with pytest.raises(ValueError, match="43-128"):
            generate_code_verifier(129)

    def test_verifier_is_url_safe(self) -> None:
        v = generate_code_verifier()
        # URL-safe base64 chars only
        allowed = set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        )
        assert all(c in allowed for c in v)

    def test_challenge_is_deterministic(self) -> None:
        v = "test_verifier_string_that_is_long_enough_for_pkce"
        c1 = compute_code_challenge(v)
        c2 = compute_code_challenge(v)
        assert c1 == c2

    def test_challenge_is_base64url_no_padding(self) -> None:
        v = generate_code_verifier()
        c = compute_code_challenge(v)
        assert "=" not in c
        assert "+" not in c
        assert "/" not in c

    def test_different_verifiers_different_challenges(self) -> None:
        v1 = generate_code_verifier()
        v2 = generate_code_verifier()
        assert v1 != v2
        assert compute_code_challenge(v1) != compute_code_challenge(v2)


# ---------------------------------------------------------------------------
# OIDC discovery
# ---------------------------------------------------------------------------


@pytest.mark.qgis_unit
class TestOidcDiscovery:
    """OIDC .well-known/openid-configuration fetch."""

    @patch("plugin.auth.urllib.request.urlopen")
    def test_discover_oidc(self, mock_urlopen: MagicMock) -> None:
        discovery_doc = {
            "issuer": "https://cognito-idp.us-west-2.amazonaws.com/us-west-2_abc123",
            "authorization_endpoint": "https://mypool.auth.us-west-2.amazoncognito.com/oauth2/authorize",
            "token_endpoint": "https://mypool.auth.us-west-2.amazoncognito.com/oauth2/token",
            "userinfo_endpoint": "https://mypool.auth.us-west-2.amazoncognito.com/oauth2/userInfo",
            "jwks_uri": "https://cognito-idp.us-west-2.amazonaws.com/us-west-2_abc123/.well-known/jwks.json",
            "end_session_endpoint": "https://mypool.auth.us-west-2.amazoncognito.com/logout",
        }
        resp = MagicMock()
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        resp.read.return_value = json.dumps(discovery_doc).encode("utf-8")
        mock_urlopen.return_value = resp

        config = discover_oidc("https://mypool.auth.us-west-2.amazoncognito.com")

        assert isinstance(config, OidcConfig)
        assert config.issuer == discovery_doc["issuer"]
        assert config.authorization_endpoint == discovery_doc["authorization_endpoint"]
        assert config.token_endpoint == discovery_doc["token_endpoint"]

        # Verify URL construction
        req = mock_urlopen.call_args[0][0]
        assert (
            req.full_url
            == "https://mypool.auth.us-west-2.amazoncognito.com/.well-known/openid-configuration"
        )


# ---------------------------------------------------------------------------
# Authorization URL
# ---------------------------------------------------------------------------


@pytest.mark.qgis_unit
class TestAuthUrl:
    """Authorization URL construction."""

    def test_build_auth_url_contains_params(self) -> None:
        url = build_auth_url(
            "https://auth.example.com/oauth2/authorize",
            "client123",
            "http://localhost:8765/callback",
            "challenge_value",
            state="my-state",
            nonce="my-nonce",
        )
        assert "response_type=code" in url
        assert "client_id=client123" in url
        assert "redirect_uri=" in url
        assert "code_challenge=challenge_value" in url
        assert "code_challenge_method=S256" in url
        assert "state=my-state" in url
        assert "nonce=my-nonce" in url
        assert "scope=openid+profile+email" in url

    def test_auto_generates_state_and_nonce(self) -> None:
        url = build_auth_url(
            "https://auth.example.com/oauth2/authorize",
            "client123",
            "http://localhost:8765/callback",
            "challenge_value",
        )
        assert "state=" in url
        assert "nonce=" in url


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------


@pytest.mark.qgis_unit
class TestTokenExchange:
    """Token endpoint interactions."""

    @patch("plugin.auth.urllib.request.urlopen")
    def test_exchange_code_for_tokens(self, mock_urlopen: MagicMock) -> None:
        token_response = {
            "access_token": "access-abc",
            "id_token": "id-abc",
            "refresh_token": "refresh-abc",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        resp = MagicMock()
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        resp.read.return_value = json.dumps(token_response).encode("utf-8")
        mock_urlopen.return_value = resp

        result = exchange_code_for_tokens(
            "https://auth.example.com/oauth2/token",
            "client123",
            "auth-code-xyz",
            "http://localhost:8765/callback",
            "verifier123",
        )

        assert isinstance(result, TokenSet)
        assert result.access_token == "access-abc"
        assert result.id_token == "id-abc"
        assert result.refresh_token == "refresh-abc"
        assert result.expires_in == 3600

        # Verify POST body
        req = mock_urlopen.call_args[0][0]
        assert req.method == "POST"
        body = req.data.decode("utf-8")
        assert "grant_type=authorization_code" in body
        assert "code=auth-code-xyz" in body
        assert "code_verifier=verifier123" in body

    @patch("plugin.auth.urllib.request.urlopen")
    def test_exchange_failure_raises(self, mock_urlopen: MagicMock) -> None:
        import urllib.error

        exc = urllib.error.HTTPError(
            url="https://auth.example.com/oauth2/token",
            code=400,
            msg="Bad Request",
            hdrs=None,  # type: ignore[arg-type]
            fp=BytesIO(b'{"error":"invalid_grant"}'),
        )
        mock_urlopen.side_effect = exc

        with pytest.raises(AuthenticationError, match="Token exchange failed"):
            exchange_code_for_tokens(
                "https://auth.example.com/oauth2/token",
                "client123",
                "bad-code",
                "http://localhost:8765/callback",
                "verifier",
            )


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------


@pytest.mark.qgis_unit
class TestTokenRefresh:
    """Refresh token flow."""

    @patch("plugin.auth.urllib.request.urlopen")
    def test_refresh_tokens(self, mock_urlopen: MagicMock) -> None:
        token_response = {
            "access_token": "new-access",
            "id_token": "new-id",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        resp = MagicMock()
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        resp.read.return_value = json.dumps(token_response).encode("utf-8")
        mock_urlopen.return_value = resp

        result = refresh_tokens(
            "https://auth.example.com/oauth2/token",
            "client123",
            "my-refresh-token",
        )

        assert result.access_token == "new-access"
        assert result.id_token == "new-id"
        # Cognito doesn't return a new refresh token; should preserve the original
        assert result.refresh_token == "my-refresh-token"

    @patch("plugin.auth.urllib.request.urlopen")
    def test_refresh_failure_raises(self, mock_urlopen: MagicMock) -> None:
        import urllib.error

        exc = urllib.error.HTTPError(
            url="https://auth.example.com/oauth2/token",
            code=400,
            msg="Bad Request",
            hdrs=None,  # type: ignore[arg-type]
            fp=BytesIO(b'{"error":"invalid_grant"}'),
        )
        mock_urlopen.side_effect = exc

        with pytest.raises(AuthenticationError, match="Token refresh failed"):
            refresh_tokens(
                "https://auth.example.com/oauth2/token",
                "client123",
                "expired-refresh",
            )


# ---------------------------------------------------------------------------
# TokenSet lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.qgis_unit
class TestTokenLifecycle:
    """Token expiry detection and refresh behavior."""

    def test_not_expired(self) -> None:
        ts = TokenSet(
            access_token="a", id_token="i", expires_in=3600, obtained_at=time.time()
        )
        assert not ts.is_expired()

    def test_expired(self) -> None:
        ts = TokenSet(
            access_token="a",
            id_token="i",
            expires_in=3600,
            obtained_at=time.time() - 7200,
        )
        assert ts.is_expired()

    def test_expires_within_buffer(self) -> None:
        ts = TokenSet(
            access_token="a",
            id_token="i",
            expires_in=3600,
            obtained_at=time.time() - 3550,
        )
        assert ts.is_expired(buffer_seconds=60)

    def test_to_from_dict_roundtrip(self) -> None:
        ts = TokenSet(
            access_token="a",
            id_token="i",
            refresh_token="r",
            token_type="Bearer",
            expires_in=3600,
            obtained_at=1234567890.0,
        )
        d = ts.to_dict()
        ts2 = TokenSet.from_dict(d)
        assert ts2.access_token == ts.access_token
        assert ts2.id_token == ts.id_token
        assert ts2.refresh_token == ts.refresh_token
        assert ts2.expires_in == ts.expires_in


# ---------------------------------------------------------------------------
# Token storage
# ---------------------------------------------------------------------------


@pytest.mark.qgis_unit
class TestTokenStorage:
    """Token persistence (file fallback, no keyring in test env)."""

    def test_store_and_load_tokens(self, tmp_path: Any) -> None:
        ts = TokenSet(
            access_token="a", id_token="i", refresh_token="r", expires_in=3600
        )

        with (
            patch("plugin.auth._keyring_available", return_value=False),
            patch(
                "plugin.auth._token_file_path", return_value=tmp_path / "default.json"
            ),
        ):
            store_tokens(ts, profile="default")
            loaded = load_tokens(profile="default")

        assert loaded is not None
        assert loaded.access_token == "a"
        assert loaded.id_token == "i"
        assert loaded.refresh_token == "r"

    def test_load_tokens_missing(self, tmp_path: Any) -> None:
        with (
            patch("plugin.auth._keyring_available", return_value=False),
            patch("plugin.auth._token_file_path", return_value=tmp_path / "nope.json"),
        ):
            loaded = load_tokens(profile="nope")

        assert loaded is None

    def test_clear_tokens(self, tmp_path: Any) -> None:
        token_file = tmp_path / "default.json"
        ts = TokenSet(access_token="a", id_token="i", refresh_token="r")

        with (
            patch("plugin.auth._keyring_available", return_value=False),
            patch("plugin.auth._token_file_path", return_value=token_file),
        ):
            store_tokens(ts, profile="default")
            assert token_file.is_file()
            clear_tokens(profile="default")
            assert not token_file.is_file()


# ---------------------------------------------------------------------------
# AuthManager
# ---------------------------------------------------------------------------


@pytest.mark.qgis_unit
class TestAuthManager:
    """High-level auth manager."""

    def test_ensure_valid_token_not_authenticated(self) -> None:
        with patch("plugin.auth.load_tokens", return_value=None):
            mgr = AuthManager("https://auth.example.com", "client123")
            with pytest.raises(AuthenticationError, match="Not authenticated"):
                mgr.ensure_valid_token()

    def test_ensure_valid_token_returns_cached(self) -> None:
        ts = TokenSet(
            access_token="a", id_token="my-id-token", refresh_token="r", expires_in=3600
        )
        mgr = AuthManager("https://auth.example.com", "client123")
        mgr._tokens = ts

        result = mgr.ensure_valid_token()
        assert result == "my-id-token"

    @patch("plugin.auth.refresh_tokens")
    @patch("plugin.auth.discover_oidc")
    @patch("plugin.auth.store_tokens")
    def test_ensure_valid_token_refreshes_when_expired(
        self, mock_store: MagicMock, mock_discover: MagicMock, mock_refresh: MagicMock
    ) -> None:
        # Expired token
        ts = TokenSet(
            access_token="a",
            id_token="old-id",
            refresh_token="r",
            expires_in=3600,
            obtained_at=time.time() - 7200,
        )
        new_ts = TokenSet(
            access_token="b", id_token="new-id", refresh_token="r", expires_in=3600
        )

        mock_discover.return_value = OidcConfig(
            issuer="iss",
            authorization_endpoint="",
            token_endpoint="https://auth.example.com/oauth2/token",
            userinfo_endpoint="",
            jwks_uri="",
            end_session_endpoint="",
        )
        mock_refresh.return_value = new_ts

        mgr = AuthManager("https://auth.example.com", "client123")
        mgr._tokens = ts

        result = mgr.ensure_valid_token()
        assert result == "new-id"
        mock_refresh.assert_called_once()
        mock_store.assert_called_once()

    def test_logout_clears_tokens(self) -> None:
        ts = TokenSet(access_token="a", id_token="i", refresh_token="r")
        mgr = AuthManager("https://auth.example.com", "client123")
        mgr._tokens = ts

        with patch("plugin.auth.clear_tokens") as mock_clear:
            mgr.logout()
            mock_clear.assert_called_once()
        assert mgr._tokens is None
