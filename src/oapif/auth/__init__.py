"""Authentication and authorization logic.

Handles JWT parsing, Cognito group extraction, organization scoping,
and visibility filtering.

API Gateway HTTP API v2 with a JWT authorizer passes decoded claims in
``event["requestContext"]["authorizer"]["jwt"]["claims"]`` and scopes
in ``event["requestContext"]["authorizer"]["jwt"]["scopes"]``.

When no authorizer is attached to a route (unauthenticated GET), these
fields are absent.  The Lambda handler must then require an
``organization`` query parameter and restrict visibility to ``public``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cognito group prefixes
# ---------------------------------------------------------------------------

ORG_GROUP_PREFIX = "org:"
"""Prefix for organization groups, e.g. ``org:GemStateGrotto``."""


# ---------------------------------------------------------------------------
# Auth context dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthContext:
    """Resolved authentication/authorization context for a request.

    Attributes
    ----------
    authenticated:
        True if the request carries a valid JWT.
    sub:
        Cognito ``sub`` (user ID) from the JWT, empty if unauthenticated.
    email:
        User's email from the JWT, empty if unauthenticated.
    groups:
        Set of Cognito groups the user belongs to.
    organization:
        Resolved organization name for this request.  For authenticated
        users this is derived from their ``org:*`` Cognito group.  For
        unauthenticated users it comes from the ``organization`` query
        parameter.
    visibility_filter:
        Set of visibility levels the caller is allowed to see.
        Unauthenticated → ``{"public"}``.
        Authenticated → determined by org visibility groups.
    roles:
        Set of role names extracted from Cognito groups
        (e.g. ``{"editor"}``, ``{"admin", "viewer"}``).
    """

    authenticated: bool = False
    sub: str = ""
    email: str = ""
    groups: frozenset[str] = field(default_factory=frozenset)
    organization: str = ""
    visibility_filter: frozenset[str] = field(default_factory=lambda: frozenset({"public"}))
    roles: frozenset[str] = field(default_factory=frozenset)


# Well-known role group names
_ROLE_GROUPS: frozenset[str] = frozenset({"admin", "editor", "viewer"})

# All standard visibility levels in order of increasing privilege
_ALL_VISIBILITY_LEVELS: list[str] = ["public", "members", "restricted"]


# ---------------------------------------------------------------------------
# JWT claim extraction
# ---------------------------------------------------------------------------


def _extract_jwt_claims(event: dict[str, Any]) -> dict[str, Any] | None:
    """Extract JWT claims from an API Gateway v2 event.

    Returns ``None`` if no JWT authorizer claims are present, indicating
    an unauthenticated request.
    """
    authorizer = event.get("requestContext", {}).get("authorizer", {})

    # API Gateway HTTP API v2 JWT authorizer format
    jwt_data = authorizer.get("jwt", {})
    claims = jwt_data.get("claims")
    if claims:
        return dict(claims)

    return None


def _extract_groups_from_claims(claims: dict[str, Any]) -> frozenset[str]:
    """Extract Cognito groups from JWT claims.

    Cognito stores groups in the ``cognito:groups`` claim.  When passed
    through API Gateway, this is typically a space-delimited string or
    may be a JSON-encoded list.
    """
    raw = claims.get("cognito:groups", "")

    if isinstance(raw, list):
        return frozenset(raw)

    if isinstance(raw, str) and raw:
        # API Gateway may pass groups as space-separated or comma-separated
        # Cognito ID tokens encode groups as a JSON array string
        stripped = raw.strip()
        if stripped.startswith("["):
            # JSON array string — parse manually
            import json

            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return frozenset(str(g) for g in parsed)
            except json.JSONDecodeError, TypeError:
                pass

        # Fall back to space-delimited
        return frozenset(stripped.split())

    return frozenset()


def _extract_organization(groups: frozenset[str]) -> str:
    """Derive the user's organization from their Cognito groups.

    Looks for a group matching ``org:<OrgName>`` and returns ``<OrgName>``.
    If no org group is found, returns an empty string.
    If multiple org groups exist, the first one (alphabetically) is used —
    users should belong to exactly one org group.
    """
    org_groups = sorted(g for g in groups if g.startswith(ORG_GROUP_PREFIX))
    if org_groups:
        return org_groups[0][len(ORG_GROUP_PREFIX) :]
    return ""


def _extract_roles(groups: frozenset[str]) -> frozenset[str]:
    """Extract role names from Cognito groups.

    Matches exact role names (``admin``, ``editor``, ``viewer``) as well
    as collection-scoped variants like ``caves:editor``.
    """
    roles: set[str] = set()
    for group in groups:
        # Exact match (global role)
        if group in _ROLE_GROUPS:
            roles.add(group)
        # Collection-scoped role: "<collection>:<role>"
        elif ":" in group:
            _, _, role_part = group.partition(":")
            if role_part in _ROLE_GROUPS:
                roles.add(role_part)
    return frozenset(roles)


def _build_visibility_filter(
    groups: frozenset[str],
    organization: str,
) -> frozenset[str]:
    """Build the set of visibility levels accessible to an authenticated user.

    All authenticated org members can see ``public`` features.
    Group ``<Org>:members`` grants ``members`` visibility.
    Group ``<Org>:restricted`` grants ``restricted`` visibility.
    Admins see everything regardless of explicit visibility groups.
    """
    levels: set[str] = {"public"}

    # Check for org-specific visibility groups
    if organization:
        for level in _ALL_VISIBILITY_LEVELS:
            group_name = f"{organization}:{level}"
            if group_name in groups:
                levels.add(level)

    # Admins and editors in the org see at least members-level
    roles = _extract_roles(groups)
    if "admin" in roles:
        # Admins see all visibility levels
        levels.update(_ALL_VISIBILITY_LEVELS)
    elif "editor" in roles:
        # Editors see public + members
        levels.add("members")

    return frozenset(levels)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_auth_context(
    event: dict[str, Any],
    query_params: dict[str, str] | None = None,
) -> AuthContext:
    """Resolve the authentication and authorization context for a request.

    For authenticated requests (JWT present):
    - Organization is derived from the ``org:*`` Cognito group.
    - If an ``organization`` query param is also provided, it must match
      the JWT-derived org (prevents cross-org queries).
    - Visibility filter is built from group memberships.

    For unauthenticated requests (no JWT):
    - ``organization`` query parameter is required.
    - Visibility is restricted to ``public``.

    Parameters
    ----------
    event:
        API Gateway HTTP API v2 event.
    query_params:
        Parsed query string parameters.  If None, extracted from event.

    Returns
    -------
    AuthContext
        Resolved context.

    Raises
    ------
    AuthError
        If the request fails authorization checks (missing org, org mismatch).
    """
    if query_params is None:
        query_params = event.get("queryStringParameters") or {}

    claims = _extract_jwt_claims(event)

    if claims is None:
        # Unauthenticated request
        org = query_params.get("organization", "")
        if not org:
            raise AuthError(
                status_code=400,
                message="Missing required parameter",
                detail="Query parameter 'organization' is required for unauthenticated requests.",
            )
        return AuthContext(
            authenticated=False,
            organization=org,
            visibility_filter=frozenset({"public"}),
        )

    # Authenticated request
    groups = _extract_groups_from_claims(claims)
    org = _extract_organization(groups)
    roles = _extract_roles(groups)
    sub = str(claims.get("sub", ""))
    email = str(claims.get("email", ""))

    if not org:
        raise AuthError(
            status_code=403,
            message="No organization group",
            detail="Authenticated user must belong to an organization group (org:<name>).",
        )

    # If organization query param is provided, it must match JWT org
    query_org = query_params.get("organization", "")
    if query_org and query_org != org:
        raise AuthError(
            status_code=403,
            message="Organization mismatch",
            detail=f"JWT organization '{org}' does not match query parameter '{query_org}'.",
        )

    visibility_filter = _build_visibility_filter(groups, org)

    return AuthContext(
        authenticated=True,
        sub=sub,
        email=email,
        groups=groups,
        organization=org,
        visibility_filter=visibility_filter,
        roles=roles,
    )


# ---------------------------------------------------------------------------
# Auth error
# ---------------------------------------------------------------------------


class AuthError(Exception):
    """Raised when an authorization check fails.

    Attributes
    ----------
    status_code:
        HTTP status code to return (400, 403, etc.).
    message:
        Short error title.
    detail:
        Longer description for the problem response.
    """

    def __init__(self, status_code: int, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.detail = detail


# ---------------------------------------------------------------------------
# Field-level authorization
# ---------------------------------------------------------------------------


def require_write_role(auth: AuthContext) -> None:
    """Verify the caller has a write-capable role (``editor`` or ``admin``).

    Viewers and users with no recognized role are rejected.

    Raises
    ------
    AuthError
        403 Forbidden if the caller lacks a write role.
    """
    if not auth.roles & {"editor", "admin"}:
        raise AuthError(
            status_code=403,
            message="Insufficient permissions",
            detail="Write operations require 'editor' or 'admin' role.",
        )


def check_field_permissions_for_create(
    auth: AuthContext,
    body: dict[str, Any],
) -> None:
    """Check field-level permissions for feature creation (POST).

    Editors can create features with default visibility.
    Only admins can explicitly set the ``visibility`` field.

    Raises
    ------
    AuthError
        403 Forbidden if the caller sets fields they are not authorized
        to modify.
    """
    if "admin" in auth.roles:
        return  # Admins can set any field

    props = body.get("properties") or {}
    if "visibility" in props:
        raise AuthError(
            status_code=403,
            message="Forbidden",
            detail="Setting 'visibility' requires admin role. Omit the field to use the default visibility.",
        )


def check_field_permissions_for_replace(
    auth: AuthContext,
    body: dict[str, Any],
    current_visibility: str,
) -> None:
    """Check field-level permissions for feature replacement (PUT).

    Editors can replace geometry and properties but cannot change
    ``visibility``.  Admins can change any field except ``organization``
    (which is enforced separately as always-immutable).

    Raises
    ------
    AuthError
        403 Forbidden if the caller modifies a field they are not
        authorized to change.
    """
    if "admin" in auth.roles:
        return

    props = body.get("properties") or {}
    new_visibility = props.get("visibility", current_visibility)
    if new_visibility != current_visibility:
        raise AuthError(
            status_code=403,
            message="Forbidden",
            detail="Changing 'visibility' requires admin role.",
        )


def check_field_permissions_for_update(
    auth: AuthContext,
    patch: dict[str, Any],
) -> None:
    """Check field-level permissions for feature update (PATCH).

    Editors can modify geometry and properties but cannot change
    ``visibility``.  Admins can change any field except ``organization``
    (which is enforced separately as always-immutable).

    Raises
    ------
    AuthError
        403 Forbidden if the patch includes fields the caller is not
        authorized to modify.
    """
    if "admin" in auth.roles:
        return

    props = patch.get("properties") or {}
    if "visibility" in props:
        raise AuthError(
            status_code=403,
            message="Forbidden",
            detail="Changing 'visibility' requires admin role.",
        )
