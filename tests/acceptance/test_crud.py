"""Full CRUD lifecycle tests.

Covers TODO sections 3 (CRUD Lifecycle) and 4 (ETag / Optimistic Concurrency).
"""

from __future__ import annotations

import httpx
import pytest

from tests.acceptance.conftest import COLLECTION_ID, create_feature, make_test_feature

pytestmark = pytest.mark.acceptance


class TestCRUDLifecycle:
    """Create → Read → Update (PUT) → Patch → Delete → Verify deleted."""

    def test_full_lifecycle(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Complete CRUD lifecycle in a single test to ensure ordering."""
        # ── CREATE ──
        body = make_test_feature(test_run_id, name="Lifecycle Feature", depth_m=100.0)
        create_resp = editor_client.post(
            f"/collections/{COLLECTION_ID}/items",
            json=body,
        )
        assert create_resp.status_code == 201, create_resp.text
        assert "location" in create_resp.headers
        assert "etag" in create_resp.headers

        created = create_resp.json()
        feature_id = created["id"]
        etag = create_resp.headers["etag"]

        assert feature_id, "Feature should have an assigned ID"
        assert created["properties"]["name"] == "Lifecycle Feature"

        # ── READ ──
        get_resp = editor_client.get(f"/collections/{COLLECTION_ID}/items/{feature_id}")
        assert get_resp.status_code == 200
        assert "etag" in get_resp.headers
        fetched = get_resp.json()
        assert fetched["id"] == feature_id
        assert fetched["properties"]["name"] == "Lifecycle Feature"

        # ── REPLACE (PUT) ──
        put_body = make_test_feature(test_run_id, name="Updated Feature", depth_m=200.0)
        put_resp = editor_client.put(
            f"/collections/{COLLECTION_ID}/items/{feature_id}",
            json=put_body,
            headers={"If-Match": etag},
        )
        assert put_resp.status_code == 200, put_resp.text
        assert "etag" in put_resp.headers
        new_etag = put_resp.headers["etag"]
        assert new_etag != etag, "ETag should change after PUT"

        updated = put_resp.json()
        assert updated["properties"]["name"] == "Updated Feature"
        assert updated["properties"]["depth_m"] == 200.0

        # ── PATCH (JSON Merge Patch) ──
        patch_body = {"properties": {"depth_m": 250.0}}
        patch_resp = editor_client.patch(
            f"/collections/{COLLECTION_ID}/items/{feature_id}",
            json=patch_body,
            headers={
                "If-Match": new_etag,
                "Content-Type": "application/merge-patch+json",
            },
        )
        assert patch_resp.status_code == 200, patch_resp.text
        assert "etag" in patch_resp.headers
        patch_etag = patch_resp.headers["etag"]
        assert patch_etag != new_etag, "ETag should change after PATCH"

        patched = patch_resp.json()
        assert patched["properties"]["depth_m"] == 250.0
        # Name should be unchanged from PUT
        assert patched["properties"]["name"] == "Updated Feature"

        # ── DELETE ──
        del_resp = editor_client.delete(
            f"/collections/{COLLECTION_ID}/items/{feature_id}",
            headers={"If-Match": patch_etag},
        )
        assert del_resp.status_code == 204

        # ── VERIFY DELETED ──
        gone_resp = editor_client.get(f"/collections/{COLLECTION_ID}/items/{feature_id}")
        assert gone_resp.status_code == 404


class TestCreateFeature:
    """POST /collections/{id}/items — additional create scenarios."""

    def test_create_returns_location_header(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Location header points to the newly created feature."""
        body = make_test_feature(test_run_id, name="Location Test")
        resp = editor_client.post(
            f"/collections/{COLLECTION_ID}/items",
            json=body,
        )
        assert resp.status_code == 201
        location = resp.headers["location"]
        assert COLLECTION_ID in location
        assert resp.json()["id"] in location

    def test_create_returns_feature_with_id(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Response body contains the assigned feature ID."""
        fid, _ = create_feature(editor_client, test_run_id, name="ID Test")
        assert fid and len(fid) > 0

    def test_create_geojson_type(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Response body has type=Feature."""
        body = make_test_feature(test_run_id, name="Type Test")
        resp = editor_client.post(
            f"/collections/{COLLECTION_ID}/items",
            json=body,
        )
        assert resp.status_code == 201
        assert resp.json()["type"] == "Feature"


class TestETagConcurrency:
    """ETag / If-Match optimistic concurrency checks (TODO §4)."""

    def test_put_without_if_match_428(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """PUT without If-Match returns 428 Precondition Required."""
        fid, _ = create_feature(editor_client, test_run_id, name="ETag PUT Test")
        body = make_test_feature(test_run_id, name="No ETag")
        resp = editor_client.put(
            f"/collections/{COLLECTION_ID}/items/{fid}",
            json=body,
        )
        assert resp.status_code == 428

    def test_patch_without_if_match_428(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """PATCH without If-Match returns 428."""
        fid, _ = create_feature(editor_client, test_run_id, name="ETag PATCH Test")
        resp = editor_client.patch(
            f"/collections/{COLLECTION_ID}/items/{fid}",
            json={"properties": {"depth_m": 999}},
            headers={"Content-Type": "application/merge-patch+json"},
        )
        assert resp.status_code == 428

    def test_delete_without_if_match_428(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """DELETE without If-Match returns 428."""
        fid, _ = create_feature(editor_client, test_run_id, name="ETag DEL Test")
        resp = editor_client.delete(
            f"/collections/{COLLECTION_ID}/items/{fid}",
        )
        assert resp.status_code == 428

    def test_put_stale_etag_412(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """PUT with stale ETag returns 412 Precondition Failed."""
        fid, etag = create_feature(editor_client, test_run_id, name="Stale PUT")
        # First PUT to change the etag
        body = make_test_feature(test_run_id, name="Changed")
        editor_client.put(
            f"/collections/{COLLECTION_ID}/items/{fid}",
            json=body,
            headers={"If-Match": etag},
        )
        # Second PUT with the old stale etag
        resp = editor_client.put(
            f"/collections/{COLLECTION_ID}/items/{fid}",
            json=body,
            headers={"If-Match": etag},
        )
        assert resp.status_code == 412

    def test_patch_stale_etag_412(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """PATCH with stale ETag returns 412."""
        fid, etag = create_feature(editor_client, test_run_id, name="Stale PATCH")
        # First PATCH to change etag
        editor_client.patch(
            f"/collections/{COLLECTION_ID}/items/{fid}",
            json={"properties": {"depth_m": 1}},
            headers={"If-Match": etag, "Content-Type": "application/merge-patch+json"},
        )
        # Second PATCH with stale etag
        resp = editor_client.patch(
            f"/collections/{COLLECTION_ID}/items/{fid}",
            json={"properties": {"depth_m": 2}},
            headers={"If-Match": etag, "Content-Type": "application/merge-patch+json"},
        )
        assert resp.status_code == 412

    def test_delete_stale_etag_412(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """DELETE with stale ETag returns 412."""
        fid, etag = create_feature(editor_client, test_run_id, name="Stale DEL")
        # PATCH to change etag
        editor_client.patch(
            f"/collections/{COLLECTION_ID}/items/{fid}",
            json={"properties": {"depth_m": 1}},
            headers={"If-Match": etag, "Content-Type": "application/merge-patch+json"},
        )
        # DELETE with stale etag
        resp = editor_client.delete(
            f"/collections/{COLLECTION_ID}/items/{fid}",
            headers={"If-Match": etag},
        )
        assert resp.status_code == 412
