"""OIDC / PKCE authentication for AWS Cognito — pure Python.

Implements the Authorization Code flow with PKCE (RFC 7636) for
public Cognito app clients.  No PyQGIS or AWS SDK dependency.

Flow:
  1. Discover endpoints via ``.well-known/openid-configuration``
  2. Generate ``code_verifier`` / ``code_challenge`` (S256)
  3. Build authorization URL and open in the system browser
  4. Listen on a localhost ephemeral port for the redirect callback
  5. Exchange the authorization code for tokens
  6. Parse and cache tokens; refresh before expiry

Token storage uses the ``keyring`` library if available (platform
keychain), with a JSON file fallback.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# OIDC discovery
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OidcConfig:
    """Parsed OpenID Connect discovery document (subset)."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str
    jwks_uri: str
    end_session_endpoint: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OidcConfig:
        return cls(
            issuer=data["issuer"],
            authorization_endpoint=data["authorization_endpoint"],
            token_endpoint=data["token_endpoint"],
            userinfo_endpoint=data.get("userinfo_endpoint", ""),
            jwks_uri=data.get("jwks_uri", ""),
            end_session_endpoint=data.get("end_session_endpoint", ""),
        )


def discover_oidc(cognito_domain: str) -> OidcConfig:
    """Fetch and parse the OIDC discovery document.

    Parameters
    ----------
    cognito_domain:
        The Cognito User Pool domain URL, e.g.
        ``https://mypool.auth.us-west-2.amazoncognito.com``.
    """
    url = f"{cognito_domain.rstrip('/')}/.well-known/openid-configuration"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data: dict[str, Any] = json.loads(resp.read())
    return OidcConfig.from_dict(data)


# ---------------------------------------------------------------------------
# PKCE helpers (RFC 7636)
# ---------------------------------------------------------------------------


def generate_code_verifier(length: int = 64) -> str:
    """Generate a cryptographically random code verifier (43-128 chars)."""
    if not 43 <= length <= 128:
        msg = f"code_verifier length must be 43-128, got {length}"
        raise ValueError(msg)
    return secrets.token_urlsafe(length)[:length]


def compute_code_challenge(verifier: str) -> str:
    """Compute the S256 code challenge from a verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ---------------------------------------------------------------------------
# Authorization URL
# ---------------------------------------------------------------------------


def build_auth_url(
    authorization_endpoint: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    *,
    scopes: list[str] | None = None,
    state: str | None = None,
    nonce: str | None = None,
) -> str:
    """Build the Cognito authorization URL with PKCE parameters.

    Parameters
    ----------
    authorization_endpoint:
        The ``authorization_endpoint`` from OIDC discovery.
    client_id:
        Cognito app client ID (public, no secret).
    redirect_uri:
        The localhost callback URI (e.g. ``http://localhost:8765/callback``).
    code_challenge:
        The S256 code challenge derived from the code verifier.
    scopes:
        OAuth scopes to request (default: ``openid profile email``).
    state:
        Anti-CSRF state parameter (auto-generated if omitted).
    nonce:
        OpenID nonce (auto-generated if omitted).
    """
    if scopes is None:
        scopes = ["openid", "profile", "email"]
    if state is None:
        state = secrets.token_urlsafe(32)
    if nonce is None:
        nonce = secrets.token_urlsafe(32)

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "nonce": nonce,
    }
    return f"{authorization_endpoint}?{urllib.parse.urlencode(params)}"


# ---------------------------------------------------------------------------
# Localhost redirect listener
# ---------------------------------------------------------------------------


@dataclass
class AuthorizationResult:
    """Result captured from the browser redirect callback."""

    code: str = ""
    state: str = ""
    error: str = ""
    error_description: str = ""


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler that captures the authorization code from the redirect."""

    result: AuthorizationResult

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        self.result = AuthorizationResult(
            code=params.get("code", [""])[0],
            state=params.get("state", [""])[0],
            error=params.get("error", [""])[0],
            error_description=params.get("error_description", [""])[0],
        )

        if self.result.code:
            body = b"<html><body><h1>Authentication successful</h1><p>You can close this window.</p></body></html>"
            self.send_response(200)
        else:
            body = (
                f"<html><body><h1>Authentication failed</h1>"
                f"<p>{self.result.error}: {self.result.error_description}</p></body></html>"
            ).encode()
            self.send_response(400)

        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default stderr logging."""


def listen_for_redirect(
    port: int = 0,
    timeout: float = 120.0,
) -> tuple[AuthorizationResult, int]:
    """Start a localhost HTTP server and wait for the authorization redirect.

    Parameters
    ----------
    port:
        Port to listen on (0 = ephemeral, OS-assigned).
    timeout:
        Maximum seconds to wait for the callback.

    Returns
    -------
    A tuple of (AuthorizationResult, port).  The port is returned so
    the caller knows which port was assigned when ``port=0``.
    """
    result = AuthorizationResult()

    server = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
    actual_port: int = server.server_address[1]
    server.timeout = timeout

    # Use class-level attribute to capture the result from the handler
    _CallbackHandler.result = result

    def _serve() -> None:
        server.handle_request()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    server.server_close()

    # Retrieve result from the class attribute
    captured = _CallbackHandler.result
    return captured, actual_port


# ---------------------------------------------------------------------------
# Token exchange and management
# ---------------------------------------------------------------------------


@dataclass
class TokenSet:
    """Parsed OAuth2 token response."""

    access_token: str = ""
    id_token: str = ""
    refresh_token: str = ""
    token_type: str = "Bearer"
    expires_in: int = 3600
    obtained_at: float = field(default_factory=time.time)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TokenSet:
        return cls(
            access_token=data.get("access_token", ""),
            id_token=data.get("id_token", ""),
            refresh_token=data.get("refresh_token", ""),
            token_type=data.get("token_type", "Bearer"),
            expires_in=data.get("expires_in", 3600),
            obtained_at=time.time(),
        )

    @property
    def expires_at(self) -> float:
        """Unix timestamp when the access token expires."""
        return self.obtained_at + self.expires_in

    def is_expired(self, buffer_seconds: int = 60) -> bool:
        """Check if the access token is expired or about to expire."""
        return time.time() >= (self.expires_at - buffer_seconds)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict for storage."""
        return {
            "access_token": self.access_token,
            "id_token": self.id_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expires_in": self.expires_in,
            "obtained_at": self.obtained_at,
        }


def exchange_code_for_tokens(
    token_endpoint: str,
    client_id: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> TokenSet:
    """Exchange an authorization code for tokens via the Cognito token endpoint.

    Parameters
    ----------
    token_endpoint:
        The ``token_endpoint`` from OIDC discovery.
    client_id:
        Cognito app client ID.
    code:
        The authorization code from the redirect callback.
    redirect_uri:
        Must match the redirect_uri used in the authorization request.
    code_verifier:
        The PKCE code verifier corresponding to the challenge.
    """
    data = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        token_endpoint,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return TokenSet.from_dict(json.loads(resp.read()))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        msg = f"Token exchange failed ({exc.code}): {body}"
        raise AuthenticationError(msg) from exc


def refresh_tokens(
    token_endpoint: str,
    client_id: str,
    refresh_token: str,
) -> TokenSet:
    """Use a refresh token to obtain new access/ID tokens.

    Parameters
    ----------
    token_endpoint:
        The ``token_endpoint`` from OIDC discovery.
    client_id:
        Cognito app client ID.
    refresh_token:
        The refresh token from a previous authentication.
    """
    data = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        token_endpoint,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            token_data: dict[str, Any] = json.loads(resp.read())
            # Cognito refresh response doesn't include a new refresh_token
            if not token_data.get("refresh_token"):
                token_data["refresh_token"] = refresh_token
            return TokenSet.from_dict(token_data)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        msg = f"Token refresh failed ({exc.code}): {body}"
        raise AuthenticationError(msg) from exc


class AuthenticationError(Exception):
    """Raised when authentication or token exchange fails."""


# ---------------------------------------------------------------------------
# Token storage
# ---------------------------------------------------------------------------


_KEYRING_SERVICE = "oapif-qgis-plugin"


def _keyring_available() -> bool:
    """Check if the keyring library is importable and functional."""
    try:
        import keyring

        # Smoke-test: some keyring backends fail silently
        keyring.get_keyring()
        return True
    except Exception:
        return False


def store_tokens(tokens: TokenSet, *, profile: str = "default") -> None:
    """Persist tokens securely.

    Uses the platform keyring if available, otherwise falls back to a
    JSON file in the user's config directory.
    """
    key = f"tokens-{profile}"
    payload = json.dumps(tokens.to_dict())

    if _keyring_available():
        import keyring

        keyring.set_password(_KEYRING_SERVICE, key, payload)
        return

    # Fallback: JSON file
    path = _token_file_path(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    # Restrict permissions (best effort on non-Unix)
    with contextlib.suppress(OSError):
        path.chmod(0o600)


def load_tokens(*, profile: str = "default") -> TokenSet | None:
    """Load persisted tokens.

    Returns ``None`` if no tokens are stored.
    """
    key = f"tokens-{profile}"

    if _keyring_available():
        import keyring

        payload = keyring.get_password(_KEYRING_SERVICE, key)
        if payload:
            return TokenSet.from_dict(json.loads(payload))
        return None

    # Fallback: JSON file
    path = _token_file_path(profile)
    if path.is_file():
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return TokenSet.from_dict(data)
    return None


def clear_tokens(*, profile: str = "default") -> None:
    """Remove persisted tokens for a profile."""
    key = f"tokens-{profile}"

    if _keyring_available():
        import keyring

        with contextlib.suppress(Exception):
            keyring.delete_password(_KEYRING_SERVICE, key)
        return

    path = _token_file_path(profile)
    if path.is_file():
        path.unlink()


def _token_file_path(profile: str) -> Path:
    """Return the path to the token storage file for a profile."""
    config_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_dir / "oapif-qgis-plugin" / f"{profile}.json"


# ---------------------------------------------------------------------------
# High-level auth manager
# ---------------------------------------------------------------------------


class AuthManager:
    """Manages the OIDC/PKCE authentication lifecycle.

    Handles token acquisition, refresh, and storage for a single
    server profile.

    Parameters
    ----------
    cognito_domain:
        The Cognito User Pool domain URL.
    client_id:
        The Cognito app client ID (public, no secret).
    profile:
        Named profile for token storage.
    redirect_port:
        Localhost port for the PKCE redirect listener (0 = ephemeral).
    """

    def __init__(
        self,
        cognito_domain: str,
        client_id: str,
        *,
        profile: str = "default",
        redirect_port: int = 0,
    ) -> None:
        self.cognito_domain = cognito_domain.rstrip("/")
        self.client_id = client_id
        self.profile = profile
        self.redirect_port = redirect_port
        self._tokens: TokenSet | None = None
        self._oidc_config: OidcConfig | None = None

    @property
    def oidc_config(self) -> OidcConfig:
        """Lazily discover the OIDC configuration."""
        if self._oidc_config is None:
            self._oidc_config = discover_oidc(self.cognito_domain)
        return self._oidc_config

    @property
    def tokens(self) -> TokenSet | None:
        """Current token set (may be None if not authenticated)."""
        return self._tokens

    @property
    def id_token(self) -> str | None:
        """Current ID token, or None if not authenticated/expired."""
        if self._tokens and not self._tokens.is_expired():
            return self._tokens.id_token
        return None

    def load_saved_tokens(self) -> bool:
        """Attempt to load tokens from storage. Returns True if found."""
        self._tokens = load_tokens(profile=self.profile)
        return self._tokens is not None

    def login(self, *, open_browser: bool = True) -> TokenSet:
        """Run the full OIDC/PKCE login flow.

        1. Generate PKCE verifier/challenge
        2. Build authorization URL
        3. Open browser (or return URL if ``open_browser=False``)
        4. Listen for the redirect callback
        5. Exchange code for tokens
        6. Store tokens

        Returns the obtained TokenSet.

        Raises
        ------
        AuthenticationError
            If login fails at any step.
        """
        oidc = self.oidc_config

        # PKCE
        verifier = generate_code_verifier()
        challenge = compute_code_challenge(verifier)

        # Start redirect listener
        state = secrets.token_urlsafe(32)
        # We need the port before building the URL
        server = http.server.HTTPServer(
            ("127.0.0.1", self.redirect_port), _CallbackHandler
        )
        actual_port = server.server_address[1]
        redirect_uri = f"http://localhost:{actual_port}/callback"

        auth_url = build_auth_url(
            oidc.authorization_endpoint,
            self.client_id,
            redirect_uri,
            challenge,
            state=state,
        )

        if open_browser:
            webbrowser.open(auth_url)

        # Wait for callback
        server.timeout = 120.0
        _CallbackHandler.result = AuthorizationResult()

        def _serve() -> None:
            server.handle_request()

        thread = threading.Thread(target=_serve, daemon=True)
        thread.start()
        thread.join(timeout=120.0)
        server.server_close()

        result = _CallbackHandler.result

        if result.error:
            raise AuthenticationError(
                f"Authorization failed: {result.error} — {result.error_description}"
            )
        if not result.code:
            raise AuthenticationError("No authorization code received (timeout?)")
        if result.state != state:
            raise AuthenticationError("State parameter mismatch — possible CSRF attack")

        # Exchange code for tokens
        self._tokens = exchange_code_for_tokens(
            oidc.token_endpoint,
            self.client_id,
            result.code,
            redirect_uri,
            verifier,
        )

        store_tokens(self._tokens, profile=self.profile)
        return self._tokens

    def ensure_valid_token(self) -> str:
        """Return a valid ID token, refreshing if necessary.

        Raises
        ------
        AuthenticationError
            If no tokens are available and refresh is impossible.
        """
        if self._tokens is None and not self.load_saved_tokens():
            raise AuthenticationError("Not authenticated \u2014 call login() first")

        assert self._tokens is not None  # for type checker

        if not self._tokens.is_expired():
            return self._tokens.id_token

        # Try refresh
        if not self._tokens.refresh_token:
            raise AuthenticationError("Token expired and no refresh token available")

        oidc = self.oidc_config
        self._tokens = refresh_tokens(
            oidc.token_endpoint,
            self.client_id,
            self._tokens.refresh_token,
        )
        store_tokens(self._tokens, profile=self.profile)
        return self._tokens.id_token

    def logout(self) -> None:
        """Clear stored tokens."""
        clear_tokens(profile=self.profile)
        self._tokens = None
