"""Authentication and token tests.

Covers TODO section 2 (Authentication & Token Lifecycle).
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

pytestmark = pytest.mark.acceptance


class TestAuthentication:
    """Verify JWT authentication flow works end-to-end."""

    def test_editor_token_has_groups_claim(self, editor_token: str) -> None:
        """The editor's ID token contains cognito:groups claim."""
        # Decode JWT payload (second segment, base64url)
        payload_b64 = editor_token.split(".")[1]
        # Add padding
        padded = payload_b64 + "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        groups = payload.get("cognito:groups", [])
        assert "org:GemStateGrotto" in groups
        assert "editor" in groups

    def test_admin_token_has_admin_role(self, admin_token: str) -> None:
        """The admin's ID token has admin role group."""
        payload_b64 = admin_token.split(".")[1]
        padded = payload_b64 + "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        groups = payload.get("cognito:groups", [])
        assert "admin" in groups
        assert "org:GemStateGrotto" in groups

    def test_authenticated_collections_same_shape(
        self,
        anon_client: httpx.Client,
        editor_client: httpx.Client,
    ) -> None:
        """Authenticated and unauthenticated /collections have the same shape."""
        anon_body = anon_client.get("/collections").json()
        auth_body = editor_client.get("/collections").json()
        assert "collections" in anon_body
        assert "collections" in auth_body
        # Both should have the same collection IDs
        anon_ids = sorted(c["id"] for c in anon_body["collections"])
        auth_ids = sorted(c["id"] for c in auth_body["collections"])
        assert anon_ids == auth_ids

    def test_invalid_token_401(self, base_url: str) -> None:
        """Request with garbage Bearer token gets 401."""
        client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": "Bearer invalidtoken.garbage.here"},
            timeout=30.0,
        )
        try:
            resp = client.post(
                "/collections/acceptance-caves/items",
                json={"type": "Feature", "geometry": None, "properties": {"name": "x"}},
            )
            assert resp.status_code == 401
        finally:
            client.close()
