"""Unit tests for Phase 5: Row-Level Access Control.

Tests cover:
- Organization tenant scoping (hard boundary, never cross-org)
- Unauthenticated users only see public features within specified org
- Authenticated users derive org from JWT and see visibility-appropriate features
- Visibility filtering at query time (public, members, restricted)
- Visibility filtering on single-feature retrieval (get_feature)
- Auto-population of organization on feature creation
- Rejection of organization changes on PUT/PATCH
- 404 (not 403) for visibility-denied features
- numberMatched reflects only visible features
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from oapif.dal.exceptions import FeatureNotFoundError, OrganizationImmutableError
from oapif.dal.features import FeatureDAL
from oapif.handlers.main import handler
from oapif.handlers.routes import (
    reset_singletons,
    set_collection_dal,
    set_feature_dal,
)

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_A = "OrgAlpha"
ORG_B = "OrgBeta"
COLLECTION = "caves"


def _point_feature(lon: float = -116.0, lat: float = 43.0, **extra_props: Any) -> dict[str, Any]:
    """Build a minimal GeoJSON-like feature dict for testing."""
    return {
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"name": "Test Feature", **extra_props},
    }


def _make_event(
    *,
    method: str = "GET",
    path: str = "/",
    query: dict[str, str] | None = None,
    claims: dict[str, Any] | None = None,
    domain: str = "api.example.com",
    stage: str = "$default",
) -> dict[str, Any]:
    """Build a minimal API Gateway HTTP API v2 event."""
    event: dict[str, Any] = {
        "rawPath": path,
        "requestContext": {
            "domainName": domain,
            "stage": stage,
            "http": {"method": method, "path": path},
        },
        "queryStringParameters": query,
    }
    if claims is not None:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": claims}}
    return event


def _make_claims(
    *,
    sub: str = "user-1",
    email: str = "user@example.com",
    groups: str | list[str] = "",
) -> dict[str, Any]:
    """Build Cognito JWT claims."""
    claims: dict[str, Any] = {"sub": sub, "email": email}
    if groups:
        claims["cognito:groups"] = groups
    return claims


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_handler_singletons() -> None:
    reset_singletons()


@pytest.fixture()
def _setup_dals(
    collection_dal: Any,
    dal: Any,
    lambda_env: dict[str, str],
) -> None:
    """Inject moto-backed DALs into handlers."""
    set_collection_dal(collection_dal)
    set_feature_dal(dal)


@pytest.fixture()
def _setup_with_collection(
    _setup_dals: None,
    collection_dal: Any,
    sample_collection_config: Any,
) -> None:
    """Set up DALs and seed a collection."""
    collection_dal.put_collection(sample_collection_config)


# ======================================================================
# Organization Tenant Scoping (DAL level)
# ======================================================================


class TestOrganizationScoping:
    """Organization is a hard boundary — no cross-org data access."""

    def test_features_isolated_by_org(self, dal: FeatureDAL) -> None:
        """Features in org A are invisible to org B."""
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="public")
        dal.create_feature(COLLECTION, _point_feature(), ORG_B, visibility="public")

        result_a = dal.query_features(COLLECTION, ORG_A, limit=10)
        result_b = dal.query_features(COLLECTION, ORG_B, limit=10)

        assert len(result_a.features) == 1
        assert result_a.features[0].organization == ORG_A
        assert len(result_b.features) == 1
        assert result_b.features[0].organization == ORG_B

    def test_get_feature_wrong_org_returns_not_found(self, dal: FeatureDAL) -> None:
        """Requesting a feature with the wrong org raises FeatureNotFoundError."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG_A)

        with pytest.raises(FeatureNotFoundError):
            dal.get_feature(COLLECTION, created.id, ORG_B)

    def test_cross_org_query_returns_empty(self, dal: FeatureDAL) -> None:
        """Querying with wrong org returns no results, not an error."""
        dal.create_feature(COLLECTION, _point_feature(), ORG_A)

        result = dal.query_features(COLLECTION, ORG_B, limit=10)
        assert result.features == []

    def test_replace_wrong_org_raises(self, dal: FeatureDAL) -> None:
        """Cannot replace a feature through a different org."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG_A)

        with pytest.raises(FeatureNotFoundError):
            dal.replace_feature(
                COLLECTION,
                created.id,
                _point_feature(),
                created.etag,
                ORG_B,
            )

    def test_update_wrong_org_raises(self, dal: FeatureDAL) -> None:
        """Cannot merge-patch a feature through a different org."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG_A)

        with pytest.raises(FeatureNotFoundError):
            dal.update_feature(
                COLLECTION,
                created.id,
                {"properties": {"name": "evil"}},
                created.etag,
                ORG_B,
            )

    def test_delete_wrong_org_raises(self, dal: FeatureDAL) -> None:
        """Cannot delete a feature through a different org."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG_A)

        with pytest.raises(FeatureNotFoundError):
            dal.delete_feature(COLLECTION, created.id, created.etag, ORG_B)


# ======================================================================
# Visibility Filtering (DAL level)
# ======================================================================


class TestVisibilityFiltering:
    """Visibility filtering in query_features and get_feature."""

    def test_query_public_only(self, dal: FeatureDAL) -> None:
        """Public-only filter returns only public features."""
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="public")
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="members")
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="restricted")

        result = dal.query_features(COLLECTION, ORG_A, limit=10, visibility_filter=["public"])
        assert len(result.features) == 1
        assert result.features[0].visibility == "public"

    def test_query_public_and_members(self, dal: FeatureDAL) -> None:
        """Members-level filter returns public + members."""
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="public")
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="members")
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="restricted")

        result = dal.query_features(COLLECTION, ORG_A, limit=10, visibility_filter=["public", "members"])
        assert len(result.features) == 2
        visibilities = {f.visibility for f in result.features}
        assert visibilities == {"public", "members"}

    def test_query_all_visibility(self, dal: FeatureDAL) -> None:
        """Admin-level filter returns all visibility levels."""
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="public")
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="members")
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="restricted")

        result = dal.query_features(
            COLLECTION,
            ORG_A,
            limit=10,
            visibility_filter=["public", "members", "restricted"],
        )
        assert len(result.features) == 3

    def test_get_feature_visibility_denied_returns_not_found(self, dal: FeatureDAL) -> None:
        """A feature the caller can't see raises FeatureNotFoundError (404)."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="restricted")

        # Caller only has public visibility
        with pytest.raises(FeatureNotFoundError):
            dal.get_feature(
                COLLECTION,
                created.id,
                ORG_A,
                visibility_filter=["public"],
            )

    def test_get_feature_visibility_allowed(self, dal: FeatureDAL) -> None:
        """A feature with matching visibility is returned normally."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="members")

        fetched = dal.get_feature(
            COLLECTION,
            created.id,
            ORG_A,
            visibility_filter=["public", "members"],
        )
        assert fetched.id == created.id
        assert fetched.visibility == "members"

    def test_get_feature_no_visibility_filter_returns_any(self, dal: FeatureDAL) -> None:
        """Without visibility_filter, any visibility level is returned (backward compat)."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="restricted")

        fetched = dal.get_feature(COLLECTION, created.id, ORG_A)
        assert fetched.id == created.id

    def test_get_feature_visibility_denied_same_404_as_not_found(self, dal: FeatureDAL) -> None:
        """Visibility denial raises the same error type as a missing feature.

        This ensures we return 404 (not 403), preventing information leakage
        about the existence of restricted features.
        """
        created = dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="restricted")

        # Visibility denied
        with pytest.raises(FeatureNotFoundError):
            dal.get_feature(COLLECTION, created.id, ORG_A, visibility_filter=["public"])

        # Truly not found
        with pytest.raises(FeatureNotFoundError):
            dal.get_feature(COLLECTION, "does-not-exist", ORG_A)


# ======================================================================
# numberMatched
# ======================================================================


class TestNumberMatched:
    """numberMatched reflects only visible features within the org."""

    def test_number_matched_all_visible(self, dal: FeatureDAL) -> None:
        col = "nm-all"
        for _ in range(5):
            dal.create_feature(col, _point_feature(), ORG_A, visibility="public")

        result = dal.query_features(col, ORG_A, limit=2, visibility_filter=["public"])
        assert result.number_matched == 5
        assert len(result.features) == 2

    def test_number_matched_filtered_by_visibility(self, dal: FeatureDAL) -> None:
        col = "nm-vis"
        for _ in range(3):
            dal.create_feature(col, _point_feature(), ORG_A, visibility="public")
        for _ in range(2):
            dal.create_feature(col, _point_feature(), ORG_A, visibility="members")
        for _ in range(1):
            dal.create_feature(col, _point_feature(), ORG_A, visibility="restricted")

        # Public only
        public_result = dal.query_features(col, ORG_A, limit=10, visibility_filter=["public"])
        assert public_result.number_matched == 3

        # Public + members
        members_result = dal.query_features(col, ORG_A, limit=10, visibility_filter=["public", "members"])
        assert members_result.number_matched == 5

    def test_number_matched_org_scoped(self, dal: FeatureDAL) -> None:
        col = "nm-org"
        for _ in range(3):
            dal.create_feature(col, _point_feature(), ORG_A, visibility="public")
        for _ in range(2):
            dal.create_feature(col, _point_feature(), ORG_B, visibility="public")

        result_a = dal.query_features(col, ORG_A, limit=10, visibility_filter=["public"])
        result_b = dal.query_features(col, ORG_B, limit=10, visibility_filter=["public"])

        assert result_a.number_matched == 3
        assert result_b.number_matched == 2

    def test_number_matched_excludes_deleted(self, dal: FeatureDAL) -> None:
        col = "nm-del"
        features = []
        for _ in range(4):
            f = dal.create_feature(col, _point_feature(), ORG_A, visibility="public")
            features.append(f)

        # Delete one
        dal.delete_feature(col, features[0].id, features[0].etag, ORG_A)

        result = dal.query_features(col, ORG_A, limit=10, visibility_filter=["public"])
        assert result.number_matched == 3

    def test_number_matched_none_for_bbox(self, dal: FeatureDAL) -> None:
        """With bbox filtering, numberMatched is None (can't accurately count)."""
        col = "nm-bbox"
        dal.create_feature(col, _point_feature(), ORG_A, visibility="public")

        result = dal.query_features(col, ORG_A, limit=10, bbox=(-117.0, 42.0, -115.0, 44.0))
        assert result.number_matched is None


# ======================================================================
# Organization auto-population and immutability
# ======================================================================


class TestOrganizationAutoPopulation:
    """Organization is auto-populated on create and immutable after."""

    def test_create_auto_populates_org(self, dal: FeatureDAL) -> None:
        """Organization is set from the caller's org, not client data."""
        feature = dal.create_feature(COLLECTION, _point_feature(), ORG_A)
        assert feature.organization == ORG_A

    def test_create_ignores_client_org(self, dal: FeatureDAL) -> None:
        """Client-supplied organization in properties is ignored."""
        data = _point_feature(organization="evil-org")
        feature = dal.create_feature(COLLECTION, data, ORG_A)
        assert feature.organization == ORG_A
        assert "organization" not in feature.properties

    def test_replace_same_org_allowed(self, dal: FeatureDAL) -> None:
        """Supplying the same org on replace is harmless."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG_A)

        data: dict[str, Any] = {
            "geometry": {"type": "Point", "coordinates": [-117.0, 44.0]},
            "properties": {"name": "Updated", "organization": ORG_A},
        }
        replaced = dal.replace_feature(COLLECTION, created.id, data, created.etag, ORG_A)
        assert replaced.organization == ORG_A

    def test_replace_different_org_rejected(self, dal: FeatureDAL) -> None:
        """Attempting to change organization on replace raises error."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG_A)

        data: dict[str, Any] = {
            "geometry": {"type": "Point", "coordinates": [-117.0, 44.0]},
            "properties": {"name": "Updated", "organization": ORG_B},
        }
        with pytest.raises(OrganizationImmutableError):
            dal.replace_feature(COLLECTION, created.id, data, created.etag, ORG_A)

    def test_update_same_org_allowed(self, dal: FeatureDAL) -> None:
        """Supplying the same org in a patch is harmless."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG_A)

        patch: dict[str, Any] = {"properties": {"organization": ORG_A}}
        updated = dal.update_feature(COLLECTION, created.id, patch, created.etag, ORG_A)
        assert updated.organization == ORG_A

    def test_update_different_org_rejected(self, dal: FeatureDAL) -> None:
        """Attempting to change organization via patch raises error."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG_A)

        patch: dict[str, Any] = {"properties": {"organization": ORG_B}}
        with pytest.raises(OrganizationImmutableError):
            dal.update_feature(COLLECTION, created.id, patch, created.etag, ORG_A)

    def test_replace_no_org_field_allowed(self, dal: FeatureDAL) -> None:
        """Omitting organization from properties is fine (no change attempted)."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG_A)

        data: dict[str, Any] = {
            "geometry": {"type": "Point", "coordinates": [-117.0, 44.0]},
            "properties": {"name": "No org field"},
        }
        replaced = dal.replace_feature(COLLECTION, created.id, data, created.etag, ORG_A)
        assert replaced.organization == ORG_A

    def test_update_no_org_field_allowed(self, dal: FeatureDAL) -> None:
        """Omitting organization from patch is fine (no change attempted)."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG_A)

        patch: dict[str, Any] = {"properties": {"name": "New name"}}
        updated = dal.update_feature(COLLECTION, created.id, patch, created.etag, ORG_A)
        assert updated.organization == ORG_A


# ======================================================================
# Handler-level row-level access control (end-to-end through Lambda handler)
# ======================================================================


class TestHandlerRowLevelAccess:
    """End-to-end tests through the Lambda handler for row-level access."""

    def test_unauthenticated_sees_only_public(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Unauthenticated user with organization=X sees only public items."""
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="public")
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="members")
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="restricted")

        event = _make_event(
            path=f"/collections/{COLLECTION}/items",
            query={"organization": ORG_A},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert len(body["features"]) == 1
        assert body["features"][0]["properties"]["visibility"] == "public"

    def test_unauthenticated_different_org_sees_nothing(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Unauthenticated user with org Y never sees org X features."""
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="public")

        event = _make_event(
            path=f"/collections/{COLLECTION}/items",
            query={"organization": ORG_B},
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert body["features"] == []

    def test_unauthenticated_missing_org_returns_400(self, _setup_with_collection: None) -> None:
        """Unauthenticated request without organization param returns 400."""
        event = _make_event(path=f"/collections/{COLLECTION}/items")
        resp = handler(event, None)
        assert resp["statusCode"] == 400

    def test_authenticated_editor_sees_public_and_members(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Authenticated editor sees public + members, not restricted."""
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="public")
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="members")
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="restricted")

        claims = _make_claims(groups=[f"org:{ORG_A}", "editor", f"{ORG_A}:members"])
        event = _make_event(
            path=f"/collections/{COLLECTION}/items",
            claims=claims,
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert len(body["features"]) == 2
        visibilities = {f["properties"]["visibility"] for f in body["features"]}
        assert visibilities == {"public", "members"}

    def test_authenticated_admin_sees_all(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Authenticated admin sees all visibility levels."""
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="public")
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="members")
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="restricted")

        claims = _make_claims(groups=[f"org:{ORG_A}", "admin"])
        event = _make_event(
            path=f"/collections/{COLLECTION}/items",
            claims=claims,
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert len(body["features"]) == 3

    def test_authenticated_viewer_sees_only_public(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Authenticated viewer without extra groups sees only public."""
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="public")
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="members")

        claims = _make_claims(groups=[f"org:{ORG_A}", "viewer"])
        event = _make_event(
            path=f"/collections/{COLLECTION}/items",
            claims=claims,
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert len(body["features"]) == 1
        assert body["features"][0]["properties"]["visibility"] == "public"

    def test_authenticated_user_org_x_never_sees_org_y(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """User in org X never sees org Y features, even with admin role."""
        dal.create_feature(COLLECTION, _point_feature(), ORG_B, visibility="public")

        claims = _make_claims(groups=[f"org:{ORG_A}", "admin"])
        event = _make_event(
            path=f"/collections/{COLLECTION}/items",
            claims=claims,
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert body["features"] == []

    def test_single_feature_visibility_denied_returns_404(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Requesting a restricted feature as unauthenticated returns 404."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="restricted")

        event = _make_event(
            path=f"/collections/{COLLECTION}/items/{created.id}",
            query={"organization": ORG_A},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 404

    def test_single_feature_visibility_allowed_returns_200(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Requesting a public feature as unauthenticated returns 200."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="public")

        event = _make_event(
            path=f"/collections/{COLLECTION}/items/{created.id}",
            query={"organization": ORG_A},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["id"] == created.id

    def test_single_feature_wrong_org_returns_404(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Requesting a feature with the wrong org returns 404."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="public")

        event = _make_event(
            path=f"/collections/{COLLECTION}/items/{created.id}",
            query={"organization": ORG_B},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 404

    def test_items_number_matched_reflects_visibility(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """numberMatched in the response reflects visibility-filtered count."""
        for _ in range(3):
            dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="public")
        for _ in range(2):
            dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="members")

        # Unauthenticated: should see 3 public
        event = _make_event(
            path=f"/collections/{COLLECTION}/items",
            query={"organization": ORG_A},
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert body.get("numberMatched") == 3
        assert body["numberReturned"] == 3

    def test_items_number_matched_org_scoped(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """numberMatched counts only features from the caller's org."""
        for _ in range(3):
            dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="public")
        for _ in range(2):
            dal.create_feature(COLLECTION, _point_feature(), ORG_B, visibility="public")

        event = _make_event(
            path=f"/collections/{COLLECTION}/items",
            query={"organization": ORG_A},
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert body.get("numberMatched") == 3

    def test_authenticated_org_mismatch_returns_403(self, _setup_with_collection: None) -> None:
        """JWT org doesn't match query org → 403."""
        claims = _make_claims(groups=[f"org:{ORG_A}", "viewer"])
        event = _make_event(
            path=f"/collections/{COLLECTION}/items",
            query={"organization": ORG_B},
            claims=claims,
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 403

    def test_authenticated_members_level_user(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """User with members visibility group sees public + members."""
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="public")
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="members")
        dal.create_feature(COLLECTION, _point_feature(), ORG_A, visibility="restricted")

        claims = _make_claims(groups=[f"org:{ORG_A}", "viewer", f"{ORG_A}:members"])
        event = _make_event(
            path=f"/collections/{COLLECTION}/items",
            claims=claims,
        )
        resp = handler(event, None)
        body = json.loads(resp["body"])
        assert len(body["features"]) == 2
        visibilities = {f["properties"]["visibility"] for f in body["features"]}
        assert visibilities == {"public", "members"}
