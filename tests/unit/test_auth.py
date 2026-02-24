"""Unit tests for authentication and authorization middleware.

Tests cover:
- JWT claim extraction from API Gateway v2 events
- Cognito group parsing (lists, space-delimited strings, JSON arrays)
- Organization extraction from org:* groups
- Role extraction from group memberships
- Visibility filter construction
- Unauthenticated path: require organization param, restrict to public
- Authenticated path: derive org from JWT, validate org param match
- AuthError handling for missing org, org mismatch, no org group
"""

from __future__ import annotations

from typing import Any

import pytest

from oapif.auth import (
    AuthContext,
    AuthError,
    _build_visibility_filter,
    _extract_groups_from_claims,
    _extract_jwt_claims,
    _extract_organization,
    _extract_roles,
    resolve_auth_context,
)

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    *,
    query: dict[str, str] | None = None,
    claims: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal API Gateway HTTP API v2 event with optional JWT claims."""
    event: dict[str, Any] = {
        "rawPath": "/collections/caves/items",
        "requestContext": {
            "domainName": "api.example.com",
            "stage": "$default",
            "http": {"method": "GET", "path": "/collections/caves/items"},
        },
        "queryStringParameters": query,
    }
    if claims is not None:
        event["requestContext"]["authorizer"] = {
            "jwt": {
                "claims": claims,
            }
        }
    return event


def _make_claims(
    *,
    sub: str = "abc-123",
    email: str = "user@example.com",
    groups: str | list[str] = "",
) -> dict[str, Any]:
    """Build Cognito JWT claims."""
    claims: dict[str, Any] = {
        "sub": sub,
        "email": email,
    }
    if groups:
        claims["cognito:groups"] = groups
    return claims


# ===================================================================
# JWT claim extraction
# ===================================================================


class TestExtractJwtClaims:
    """Tests for _extract_jwt_claims."""

    def test_no_authorizer_returns_none(self) -> None:
        event = _make_event()
        assert _extract_jwt_claims(event) is None

    def test_empty_authorizer_returns_none(self) -> None:
        event = _make_event()
        event["requestContext"]["authorizer"] = {}
        assert _extract_jwt_claims(event) is None

    def test_jwt_claims_present(self) -> None:
        claims = _make_claims(sub="user-1", email="u@test.com")
        event = _make_event(claims=claims)
        result = _extract_jwt_claims(event)
        assert result is not None
        assert result["sub"] == "user-1"
        assert result["email"] == "u@test.com"

    def test_empty_claims_returns_none(self) -> None:
        event = _make_event()
        event["requestContext"]["authorizer"] = {"jwt": {"claims": {}}}
        assert _extract_jwt_claims(event) is None

    def test_missing_request_context(self) -> None:
        event: dict[str, Any] = {}
        assert _extract_jwt_claims(event) is None


# ===================================================================
# Group extraction
# ===================================================================


class TestExtractGroups:
    """Tests for _extract_groups_from_claims."""

    def test_no_groups_claim(self) -> None:
        claims: dict[str, Any] = {"sub": "x"}
        assert _extract_groups_from_claims(claims) == frozenset()

    def test_groups_as_list(self) -> None:
        claims = _make_claims(groups=["org:MyOrg", "editor", "MyOrg:members"])
        groups = _extract_groups_from_claims(claims)
        assert groups == frozenset({"org:MyOrg", "editor", "MyOrg:members"})

    def test_groups_as_space_delimited_string(self) -> None:
        claims = _make_claims(groups="org:MyOrg editor MyOrg:members")
        groups = _extract_groups_from_claims(claims)
        assert groups == frozenset({"org:MyOrg", "editor", "MyOrg:members"})

    def test_groups_as_json_array_string(self) -> None:
        claims = _make_claims(groups='["org:MyOrg", "editor"]')
        groups = _extract_groups_from_claims(claims)
        assert groups == frozenset({"org:MyOrg", "editor"})

    def test_empty_string(self) -> None:
        claims = _make_claims(groups="")
        assert _extract_groups_from_claims(claims) == frozenset()

    def test_single_group(self) -> None:
        claims = _make_claims(groups="org:TestOrg")
        groups = _extract_groups_from_claims(claims)
        assert groups == frozenset({"org:TestOrg"})

    def test_invalid_json_falls_back_to_split(self) -> None:
        claims = _make_claims(groups="[invalid json")
        groups = _extract_groups_from_claims(claims)
        # Falls back to space-delimited, so the entire string is one group
        assert groups == frozenset({"[invalid", "json"})


# ===================================================================
# Organization extraction
# ===================================================================


class TestExtractOrganization:
    """Tests for _extract_organization."""

    def test_no_org_group(self) -> None:
        groups = frozenset({"editor", "viewer"})
        assert _extract_organization(groups) == ""

    def test_single_org_group(self) -> None:
        groups = frozenset({"org:GemStateGrotto", "editor"})
        assert _extract_organization(groups) == "GemStateGrotto"

    def test_multiple_org_groups_picks_first_alphabetically(self) -> None:
        groups = frozenset({"org:Zeta", "org:Alpha"})
        assert _extract_organization(groups) == "Alpha"

    def test_org_prefix_only(self) -> None:
        """Edge case: group is exactly 'org:' with no name."""
        groups = frozenset({"org:"})
        assert _extract_organization(groups) == ""

    def test_mixed_groups(self) -> None:
        groups = frozenset({"org:TestOrg", "TestOrg:members", "admin"})
        assert _extract_organization(groups) == "TestOrg"


# ===================================================================
# Role extraction
# ===================================================================


class TestExtractRoles:
    """Tests for _extract_roles."""

    def test_no_roles(self) -> None:
        groups = frozenset({"org:Test"})
        assert _extract_roles(groups) == frozenset()

    def test_global_roles(self) -> None:
        groups = frozenset({"admin", "editor", "viewer"})
        assert _extract_roles(groups) == frozenset({"admin", "editor", "viewer"})

    def test_collection_scoped_role(self) -> None:
        groups = frozenset({"caves:editor", "mines:admin"})
        assert _extract_roles(groups) == frozenset({"editor", "admin"})

    def test_non_role_group_ignored(self) -> None:
        groups = frozenset({"org:Test", "Test:members", "random"})
        assert _extract_roles(groups) == frozenset()

    def test_mixed(self) -> None:
        groups = frozenset({"admin", "caves:editor", "org:Test"})
        roles = _extract_roles(groups)
        assert "admin" in roles
        assert "editor" in roles


# ===================================================================
# Visibility filter construction
# ===================================================================


class TestBuildVisibilityFilter:
    """Tests for _build_visibility_filter."""

    def test_no_visibility_groups(self) -> None:
        groups = frozenset({"org:Test"})
        result = _build_visibility_filter(groups, "Test")
        assert result == frozenset({"public"})

    def test_members_group(self) -> None:
        groups = frozenset({"org:Test", "Test:members"})
        result = _build_visibility_filter(groups, "Test")
        assert "public" in result
        assert "members" in result
        assert "restricted" not in result

    def test_restricted_group(self) -> None:
        groups = frozenset({"org:Test", "Test:restricted"})
        result = _build_visibility_filter(groups, "Test")
        assert "restricted" in result

    def test_all_visibility_groups(self) -> None:
        groups = frozenset({"org:Test", "Test:public", "Test:members", "Test:restricted"})
        result = _build_visibility_filter(groups, "Test")
        assert result == frozenset({"public", "members", "restricted"})

    def test_admin_sees_all(self) -> None:
        groups = frozenset({"org:Test", "admin"})
        result = _build_visibility_filter(groups, "Test")
        assert result == frozenset({"public", "members", "restricted"})

    def test_editor_sees_public_and_members(self) -> None:
        groups = frozenset({"org:Test", "editor"})
        result = _build_visibility_filter(groups, "Test")
        assert "public" in result
        assert "members" in result
        assert "restricted" not in result

    def test_viewer_only_sees_public(self) -> None:
        groups = frozenset({"org:Test", "viewer"})
        result = _build_visibility_filter(groups, "Test")
        assert result == frozenset({"public"})

    def test_editor_with_restricted_group(self) -> None:
        """Editor + explicit restricted group → sees all three."""
        groups = frozenset({"org:Test", "editor", "Test:restricted"})
        result = _build_visibility_filter(groups, "Test")
        assert result == frozenset({"public", "members", "restricted"})


# ===================================================================
# resolve_auth_context — unauthenticated path
# ===================================================================


class TestResolveAuthUnauthenticated:
    """Tests for resolve_auth_context with no JWT (unauthenticated)."""

    def test_unauthenticated_with_org_param(self) -> None:
        event = _make_event(query={"organization": "TestOrg"})
        ctx = resolve_auth_context(event)
        assert ctx.authenticated is False
        assert ctx.organization == "TestOrg"
        assert ctx.visibility_filter == frozenset({"public"})
        assert ctx.groups == frozenset()
        assert ctx.roles == frozenset()
        assert ctx.sub == ""

    def test_unauthenticated_missing_org_raises(self) -> None:
        event = _make_event(query={})
        with pytest.raises(AuthError) as exc_info:
            resolve_auth_context(event)
        assert exc_info.value.status_code == 400
        assert "organization" in exc_info.value.detail.lower()

    def test_unauthenticated_no_query_params_raises(self) -> None:
        event = _make_event()
        with pytest.raises(AuthError) as exc_info:
            resolve_auth_context(event)
        assert exc_info.value.status_code == 400

    def test_unauthenticated_explicit_query_params(self) -> None:
        """Test passing query_params explicitly."""
        event = _make_event()
        ctx = resolve_auth_context(event, query_params={"organization": "Explicit"})
        assert ctx.authenticated is False
        assert ctx.organization == "Explicit"


# ===================================================================
# resolve_auth_context — authenticated path
# ===================================================================


class TestResolveAuthAuthenticated:
    """Tests for resolve_auth_context with a valid JWT."""

    def test_authenticated_basic(self) -> None:
        claims = _make_claims(
            sub="user-42",
            email="alice@example.com",
            groups=["org:GemStateGrotto", "editor", "GemStateGrotto:members"],
        )
        event = _make_event(claims=claims)
        ctx = resolve_auth_context(event)
        assert ctx.authenticated is True
        assert ctx.sub == "user-42"
        assert ctx.email == "alice@example.com"
        assert ctx.organization == "GemStateGrotto"
        assert "editor" in ctx.roles
        assert "public" in ctx.visibility_filter
        assert "members" in ctx.visibility_filter

    def test_authenticated_admin(self) -> None:
        claims = _make_claims(groups=["org:TestOrg", "admin"])
        event = _make_event(claims=claims)
        ctx = resolve_auth_context(event)
        assert ctx.authenticated is True
        assert ctx.organization == "TestOrg"
        assert "admin" in ctx.roles
        assert ctx.visibility_filter == frozenset({"public", "members", "restricted"})

    def test_authenticated_no_org_group_raises(self) -> None:
        claims = _make_claims(groups=["editor"])
        event = _make_event(claims=claims)
        with pytest.raises(AuthError) as exc_info:
            resolve_auth_context(event)
        assert exc_info.value.status_code == 403
        assert "organization group" in exc_info.value.detail.lower()

    def test_authenticated_org_param_matches(self) -> None:
        """org query param matching JWT org is allowed."""
        claims = _make_claims(groups=["org:MyOrg", "viewer"])
        event = _make_event(
            query={"organization": "MyOrg"},
            claims=claims,
        )
        ctx = resolve_auth_context(event)
        assert ctx.organization == "MyOrg"

    def test_authenticated_org_param_mismatch_raises(self) -> None:
        """org query param not matching JWT org is rejected."""
        claims = _make_claims(groups=["org:MyOrg", "viewer"])
        event = _make_event(
            query={"organization": "DifferentOrg"},
            claims=claims,
        )
        with pytest.raises(AuthError) as exc_info:
            resolve_auth_context(event)
        assert exc_info.value.status_code == 403
        assert "does not match" in exc_info.value.detail.lower()

    def test_authenticated_no_org_param_ok(self) -> None:
        """Authenticated requests don't need org query param."""
        claims = _make_claims(groups=["org:MyOrg", "editor"])
        event = _make_event(claims=claims)
        ctx = resolve_auth_context(event)
        assert ctx.organization == "MyOrg"

    def test_authenticated_viewer_only_public(self) -> None:
        """Viewer with no extra visibility groups → only public."""
        claims = _make_claims(groups=["org:TestOrg", "viewer"])
        event = _make_event(claims=claims)
        ctx = resolve_auth_context(event)
        assert ctx.visibility_filter == frozenset({"public"})

    def test_authenticated_groups_preserved(self) -> None:
        claims = _make_claims(groups=["org:X", "admin", "X:restricted"])
        event = _make_event(claims=claims)
        ctx = resolve_auth_context(event)
        assert "org:X" in ctx.groups
        assert "admin" in ctx.groups
        assert "X:restricted" in ctx.groups


# ===================================================================
# AuthError
# ===================================================================


class TestAuthError:
    """Tests for the AuthError exception."""

    def test_attributes(self) -> None:
        err = AuthError(status_code=403, message="Forbidden", detail="Not allowed")
        assert err.status_code == 403
        assert err.message == "Forbidden"
        assert err.detail == "Not allowed"
        assert str(err) == "Forbidden"

    def test_default_detail(self) -> None:
        err = AuthError(status_code=400, message="Bad Request")
        assert err.detail == ""


# ===================================================================
# AuthContext dataclass
# ===================================================================


class TestAuthContext:
    """Tests for the AuthContext dataclass."""

    def test_defaults(self) -> None:
        ctx = AuthContext()
        assert ctx.authenticated is False
        assert ctx.sub == ""
        assert ctx.email == ""
        assert ctx.groups == frozenset()
        assert ctx.organization == ""
        assert ctx.visibility_filter == frozenset({"public"})
        assert ctx.roles == frozenset()

    def test_frozen(self) -> None:
        ctx = AuthContext(authenticated=True, organization="X")
        with pytest.raises(AttributeError):
            ctx.organization = "Y"  # type: ignore[misc]
