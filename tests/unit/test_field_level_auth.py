"""Unit tests for Phase 7: Field-Level Authorization.

Tests cover:
- Permission model: viewer cannot write, editor can modify geometry/properties,
  admin can modify visibility (organization is always immutable)
- Auth function unit tests for require_write_role and check_field_permissions_*
- End-to-end handler tests for POST, PUT, PATCH, DELETE with different roles
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from oapif.auth import (
    AuthContext,
    AuthError,
    check_field_permissions_for_create,
    check_field_permissions_for_replace,
    check_field_permissions_for_update,
    require_write_role,
)
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

ORG = "TestOrg"
COLLECTION = "caves"


def _point_feature(lon: float = -116.0, lat: float = 43.0, **extra_props: Any) -> dict[str, Any]:
    """Build a minimal GeoJSON Feature dict for testing."""
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"name": "Test Feature", **extra_props},
    }


def _make_event(
    *,
    method: str = "GET",
    path: str = "/",
    body: dict[str, Any] | None = None,
    query: dict[str, str] | None = None,
    claims: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
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
        "headers": headers or {},
    }
    if body is not None:
        event["body"] = json.dumps(body)
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


def _editor_claims() -> dict[str, Any]:
    """JWT claims for an editor in ORG."""
    return _make_claims(groups=[f"org:{ORG}", "editor", f"{ORG}:members"])


def _admin_claims() -> dict[str, Any]:
    """JWT claims for an admin in ORG."""
    return _make_claims(groups=[f"org:{ORG}", "admin"])


def _viewer_claims() -> dict[str, Any]:
    """JWT claims for a viewer in ORG."""
    return _make_claims(groups=[f"org:{ORG}", "viewer"])


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
# Auth function unit tests: require_write_role
# ======================================================================


class TestRequireWriteRole:
    """Unit tests for require_write_role function."""

    def test_editor_passes(self) -> None:
        auth = AuthContext(
            authenticated=True,
            organization=ORG,
            roles=frozenset({"editor"}),
        )
        require_write_role(auth)  # Should not raise

    def test_admin_passes(self) -> None:
        auth = AuthContext(
            authenticated=True,
            organization=ORG,
            roles=frozenset({"admin"}),
        )
        require_write_role(auth)  # Should not raise

    def test_viewer_rejected(self) -> None:
        auth = AuthContext(
            authenticated=True,
            organization=ORG,
            roles=frozenset({"viewer"}),
        )
        with pytest.raises(AuthError) as exc_info:
            require_write_role(auth)
        assert exc_info.value.status_code == 403

    def test_no_roles_rejected(self) -> None:
        auth = AuthContext(
            authenticated=True,
            organization=ORG,
            roles=frozenset(),
        )
        with pytest.raises(AuthError) as exc_info:
            require_write_role(auth)
        assert exc_info.value.status_code == 403


# ======================================================================
# Auth function unit tests: check_field_permissions_for_create
# ======================================================================


class TestCheckFieldPermissionsCreate:
    """Unit tests for field-level permissions on feature creation (POST)."""

    def test_admin_can_set_visibility(self) -> None:
        auth = AuthContext(
            authenticated=True,
            organization=ORG,
            roles=frozenset({"admin"}),
        )
        body = _point_feature(visibility="restricted")
        check_field_permissions_for_create(auth, body)  # Should not raise

    def test_editor_cannot_set_visibility(self) -> None:
        auth = AuthContext(
            authenticated=True,
            organization=ORG,
            roles=frozenset({"editor"}),
        )
        body = _point_feature(visibility="restricted")
        with pytest.raises(AuthError) as exc_info:
            check_field_permissions_for_create(auth, body)
        assert exc_info.value.status_code == 403
        assert "visibility" in exc_info.value.detail

    def test_editor_can_omit_visibility(self) -> None:
        auth = AuthContext(
            authenticated=True,
            organization=ORG,
            roles=frozenset({"editor"}),
        )
        body = _point_feature()  # No visibility field
        check_field_permissions_for_create(auth, body)  # Should not raise


# ======================================================================
# Auth function unit tests: check_field_permissions_for_replace
# ======================================================================


class TestCheckFieldPermissionsReplace:
    """Unit tests for field-level permissions on feature replacement (PUT)."""

    def test_admin_can_change_visibility(self) -> None:
        auth = AuthContext(
            authenticated=True,
            organization=ORG,
            roles=frozenset({"admin"}),
        )
        body = {"properties": {"name": "Updated", "visibility": "restricted"}}
        check_field_permissions_for_replace(auth, body, "public")  # Should not raise

    def test_editor_cannot_change_visibility(self) -> None:
        auth = AuthContext(
            authenticated=True,
            organization=ORG,
            roles=frozenset({"editor"}),
        )
        body = {"properties": {"name": "Updated", "visibility": "restricted"}}
        with pytest.raises(AuthError) as exc_info:
            check_field_permissions_for_replace(auth, body, "public")
        assert exc_info.value.status_code == 403
        assert "visibility" in exc_info.value.detail

    def test_editor_can_send_same_visibility(self) -> None:
        """Editor can include visibility if the value hasn't changed."""
        auth = AuthContext(
            authenticated=True,
            organization=ORG,
            roles=frozenset({"editor"}),
        )
        body = {"properties": {"name": "Updated", "visibility": "public"}}
        check_field_permissions_for_replace(auth, body, "public")  # Should not raise

    def test_editor_can_omit_visibility(self) -> None:
        """Editor can omit visibility entirely (defaults to current)."""
        auth = AuthContext(
            authenticated=True,
            organization=ORG,
            roles=frozenset({"editor"}),
        )
        body = {"properties": {"name": "Updated"}}
        check_field_permissions_for_replace(auth, body, "members")  # Should not raise


# ======================================================================
# Auth function unit tests: check_field_permissions_for_update
# ======================================================================


class TestCheckFieldPermissionsUpdate:
    """Unit tests for field-level permissions on feature update (PATCH)."""

    def test_admin_can_patch_visibility(self) -> None:
        auth = AuthContext(
            authenticated=True,
            organization=ORG,
            roles=frozenset({"admin"}),
        )
        patch: dict[str, Any] = {"properties": {"visibility": "restricted"}}
        check_field_permissions_for_update(auth, patch)  # Should not raise

    def test_editor_cannot_patch_visibility(self) -> None:
        auth = AuthContext(
            authenticated=True,
            organization=ORG,
            roles=frozenset({"editor"}),
        )
        patch: dict[str, Any] = {"properties": {"visibility": "restricted"}}
        with pytest.raises(AuthError) as exc_info:
            check_field_permissions_for_update(auth, patch)
        assert exc_info.value.status_code == 403
        assert "visibility" in exc_info.value.detail

    def test_editor_can_patch_geometry(self) -> None:
        auth = AuthContext(
            authenticated=True,
            organization=ORG,
            roles=frozenset({"editor"}),
        )
        patch: dict[str, Any] = {"geometry": {"type": "Point", "coordinates": [-115.0, 44.0]}}
        check_field_permissions_for_update(auth, patch)  # Should not raise

    def test_editor_can_patch_properties_without_visibility(self) -> None:
        auth = AuthContext(
            authenticated=True,
            organization=ORG,
            roles=frozenset({"editor"}),
        )
        patch: dict[str, Any] = {"properties": {"name": "New Name", "depth_m": 100}}
        check_field_permissions_for_update(auth, patch)  # Should not raise


# ======================================================================
# Handler-level field-level auth — POST (create)
# ======================================================================


class TestHandlerCreateFieldAuth:
    """End-to-end tests for field-level auth on POST /collections/{id}/items."""

    def test_viewer_cannot_create(self, _setup_with_collection: None) -> None:
        """Viewer role is rejected on POST."""
        event = _make_event(
            method="POST",
            path=f"/collections/{COLLECTION}/items",
            body=_point_feature(),
            claims=_viewer_claims(),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 403

    def test_editor_can_create_without_visibility(self, _setup_with_collection: None) -> None:
        """Editor can create a feature (defaults to public visibility)."""
        event = _make_event(
            method="POST",
            path=f"/collections/{COLLECTION}/items",
            body=_point_feature(),
            claims=_editor_claims(),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 201
        body = json.loads(resp["body"])
        assert body["properties"]["visibility"] == "public"

    def test_editor_cannot_create_with_visibility(self, _setup_with_collection: None) -> None:
        """Editor cannot set visibility on creation."""
        event = _make_event(
            method="POST",
            path=f"/collections/{COLLECTION}/items",
            body=_point_feature(visibility="restricted"),
            claims=_editor_claims(),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 403
        body = json.loads(resp["body"])
        assert "visibility" in body.get("detail", "")

    def test_admin_can_create_with_visibility(self, _setup_with_collection: None) -> None:
        """Admin can set visibility on creation."""
        event = _make_event(
            method="POST",
            path=f"/collections/{COLLECTION}/items",
            body=_point_feature(visibility="restricted"),
            claims=_admin_claims(),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 201
        body = json.loads(resp["body"])
        assert body["properties"]["visibility"] == "restricted"

    def test_unauthenticated_cannot_create(self, _setup_with_collection: None) -> None:
        """Unauthenticated user is rejected on POST."""
        event = _make_event(
            method="POST",
            path=f"/collections/{COLLECTION}/items",
            body=_point_feature(),
            query={"organization": ORG},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 401


# ======================================================================
# Handler-level field-level auth — PUT (replace)
# ======================================================================


class TestHandlerReplaceFieldAuth:
    """End-to-end tests for field-level auth on PUT /collections/{id}/items/{fid}."""

    def test_editor_can_change_geometry(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Editor can replace geometry."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG)
        new_body = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-115.0, 44.0]},
            "properties": {"name": "Moved"},
        }
        event = _make_event(
            method="PUT",
            path=f"/collections/{COLLECTION}/items/{created.id}",
            body=new_body,
            claims=_editor_claims(),
            headers={"if-match": f'"{created.etag}"'},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["geometry"]["coordinates"] == [-115.0, 44.0]

    def test_editor_cannot_change_visibility(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Editor cannot change visibility via PUT."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG, visibility="public")
        new_body = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-116.0, 43.0]},
            "properties": {"name": "Same", "visibility": "restricted"},
        }
        event = _make_event(
            method="PUT",
            path=f"/collections/{COLLECTION}/items/{created.id}",
            body=new_body,
            claims=_editor_claims(),
            headers={"if-match": f'"{created.etag}"'},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 403
        body = json.loads(resp["body"])
        assert "visibility" in body.get("detail", "")

    def test_editor_can_send_same_visibility(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Editor can include unchanged visibility in PUT body."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG, visibility="public")
        new_body = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-115.0, 44.0]},
            "properties": {"name": "Updated", "visibility": "public"},
        }
        event = _make_event(
            method="PUT",
            path=f"/collections/{COLLECTION}/items/{created.id}",
            body=new_body,
            claims=_editor_claims(),
            headers={"if-match": f'"{created.etag}"'},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 200

    def test_admin_can_change_visibility(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Admin can change visibility via PUT."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG, visibility="public")
        new_body = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-116.0, 43.0]},
            "properties": {"name": "Now restricted", "visibility": "restricted"},
        }
        event = _make_event(
            method="PUT",
            path=f"/collections/{COLLECTION}/items/{created.id}",
            body=new_body,
            claims=_admin_claims(),
            headers={"if-match": f'"{created.etag}"'},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["properties"]["visibility"] == "restricted"

    def test_admin_cannot_change_organization(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Even admin cannot change organization (always immutable)."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG)
        new_body = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-116.0, 43.0]},
            "properties": {"name": "Evil", "organization": "EvilOrg"},
        }
        event = _make_event(
            method="PUT",
            path=f"/collections/{COLLECTION}/items/{created.id}",
            body=new_body,
            claims=_admin_claims(),
            headers={"if-match": f'"{created.etag}"'},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 422
        body = json.loads(resp["body"])
        assert "organization" in body.get("detail", "").lower()

    def test_viewer_cannot_replace(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Viewer role is rejected on PUT."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG)
        event = _make_event(
            method="PUT",
            path=f"/collections/{COLLECTION}/items/{created.id}",
            body=_point_feature(),
            claims=_viewer_claims(),
            headers={"if-match": f'"{created.etag}"'},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 403


# ======================================================================
# Handler-level field-level auth — PATCH (update)
# ======================================================================


class TestHandlerUpdateFieldAuth:
    """End-to-end tests for field-level auth on PATCH /collections/{id}/items/{fid}."""

    def test_editor_can_patch_geometry(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Editor can modify geometry via PATCH."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG)
        patch: dict[str, Any] = {
            "geometry": {"type": "Point", "coordinates": [-115.0, 44.0]},
        }
        event = _make_event(
            method="PATCH",
            path=f"/collections/{COLLECTION}/items/{created.id}",
            body=patch,
            claims=_editor_claims(),
            headers={"if-match": f'"{created.etag}"'},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["geometry"]["coordinates"] == [-115.0, 44.0]

    def test_editor_can_patch_properties(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Editor can modify feature properties via PATCH."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG)
        patch: dict[str, Any] = {
            "properties": {"name": "Renamed Cave"},
        }
        event = _make_event(
            method="PATCH",
            path=f"/collections/{COLLECTION}/items/{created.id}",
            body=patch,
            claims=_editor_claims(),
            headers={"if-match": f'"{created.etag}"'},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["properties"]["name"] == "Renamed Cave"

    def test_editor_cannot_patch_visibility(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Editor cannot change visibility via PATCH."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG)
        patch: dict[str, Any] = {
            "properties": {"visibility": "restricted"},
        }
        event = _make_event(
            method="PATCH",
            path=f"/collections/{COLLECTION}/items/{created.id}",
            body=patch,
            claims=_editor_claims(),
            headers={"if-match": f'"{created.etag}"'},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 403
        body = json.loads(resp["body"])
        assert "visibility" in body.get("detail", "")

    def test_admin_can_patch_visibility(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Admin can change visibility via PATCH."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG)
        patch: dict[str, Any] = {
            "properties": {"visibility": "restricted"},
        }
        event = _make_event(
            method="PATCH",
            path=f"/collections/{COLLECTION}/items/{created.id}",
            body=patch,
            claims=_admin_claims(),
            headers={"if-match": f'"{created.etag}"'},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["properties"]["visibility"] == "restricted"

    def test_admin_cannot_patch_organization(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Even admin cannot change organization via PATCH."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG)
        patch: dict[str, Any] = {
            "properties": {"organization": "EvilOrg"},
        }
        event = _make_event(
            method="PATCH",
            path=f"/collections/{COLLECTION}/items/{created.id}",
            body=patch,
            claims=_admin_claims(),
            headers={"if-match": f'"{created.etag}"'},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 422
        body = json.loads(resp["body"])
        assert "organization" in body.get("detail", "").lower()

    def test_viewer_cannot_patch(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Viewer role is rejected on PATCH."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG)
        patch: dict[str, Any] = {"properties": {"name": "Nope"}}
        event = _make_event(
            method="PATCH",
            path=f"/collections/{COLLECTION}/items/{created.id}",
            body=patch,
            claims=_viewer_claims(),
            headers={"if-match": f'"{created.etag}"'},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 403


# ======================================================================
# Handler-level field-level auth — DELETE
# ======================================================================


class TestHandlerDeleteFieldAuth:
    """End-to-end tests for field-level auth on DELETE."""

    def test_editor_can_delete(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Editor can delete a feature."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG)
        event = _make_event(
            method="DELETE",
            path=f"/collections/{COLLECTION}/items/{created.id}",
            claims=_editor_claims(),
            headers={"if-match": f'"{created.etag}"'},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 204

    def test_admin_can_delete(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Admin can delete a feature."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG)
        event = _make_event(
            method="DELETE",
            path=f"/collections/{COLLECTION}/items/{created.id}",
            claims=_admin_claims(),
            headers={"if-match": f'"{created.etag}"'},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 204

    def test_viewer_cannot_delete(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Viewer role is rejected on DELETE."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG)
        event = _make_event(
            method="DELETE",
            path=f"/collections/{COLLECTION}/items/{created.id}",
            claims=_viewer_claims(),
            headers={"if-match": f'"{created.etag}"'},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 403

    def test_unauthenticated_cannot_delete(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Unauthenticated user is rejected on DELETE."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG)
        event = _make_event(
            method="DELETE",
            path=f"/collections/{COLLECTION}/items/{created.id}",
            query={"organization": ORG},
            headers={"if-match": f'"{created.etag}"'},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 401


# ======================================================================
# Combined role escalation scenarios
# ======================================================================


class TestFieldLevelEdgeCases:
    """Edge cases and combined scenarios."""

    def test_editor_full_replace_preserving_visibility(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Editor can do a full PUT as long as visibility doesn't change."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG, visibility="members")
        new_body = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-115.0, 44.0]},
            "properties": {
                "name": "Fully Replaced",
                "visibility": "members",  # same as current
            },
        }
        event = _make_event(
            method="PUT",
            path=f"/collections/{COLLECTION}/items/{created.id}",
            body=new_body,
            claims=_editor_claims(),
            headers={"if-match": f'"{created.etag}"'},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["properties"]["visibility"] == "members"
        assert body["geometry"]["coordinates"] == [-115.0, 44.0]

    def test_admin_can_do_everything_editors_can(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Admin has all editor capabilities plus visibility changes."""
        # Create
        event = _make_event(
            method="POST",
            path=f"/collections/{COLLECTION}/items",
            body=_point_feature(visibility="restricted"),
            claims=_admin_claims(),
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 201
        created_body = json.loads(resp["body"])
        feature_id = created_body["id"]
        etag = resp["headers"]["ETag"].strip('"')

        # Replace geometry + change visibility
        new_body = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-114.0, 45.0]},
            "properties": {"name": "Admin Updated", "visibility": "public"},
        }
        event = _make_event(
            method="PUT",
            path=f"/collections/{COLLECTION}/items/{feature_id}",
            body=new_body,
            claims=_admin_claims(),
            headers={"if-match": f'"{etag}"'},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["properties"]["visibility"] == "public"
        assert body["geometry"]["coordinates"] == [-114.0, 45.0]

    def test_editor_geometry_and_properties_update(self, _setup_with_collection: None, dal: FeatureDAL) -> None:
        """Editor can PATCH both geometry and properties simultaneously."""
        created = dal.create_feature(COLLECTION, _point_feature(), ORG)
        patch: dict[str, Any] = {
            "geometry": {"type": "Point", "coordinates": [-115.0, 44.0]},
            "properties": {"name": "New Name", "depth_m": 42},
        }
        event = _make_event(
            method="PATCH",
            path=f"/collections/{COLLECTION}/items/{created.id}",
            body=patch,
            claims=_editor_claims(),
            headers={"if-match": f'"{created.etag}"'},
        )
        resp = handler(event, None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["properties"]["name"] == "New Name"
        assert body["properties"]["depth_m"] == 42
        assert body["geometry"]["coordinates"] == [-115.0, 44.0]
