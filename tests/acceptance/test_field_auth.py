"""Field-level authorization tests.

Covers TODO section 7 (Field-Level Authorization).
"""

from __future__ import annotations

import httpx
import pytest

from tests.acceptance.conftest import COLLECTION_ID, create_feature, make_test_feature

pytestmark = pytest.mark.acceptance


class TestFieldLevelAuth:
    """Field-level write restrictions by role."""

    # ── Editor can modify geometry + properties ─────────────────────

    def test_editor_can_modify_properties(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Editor can PUT with updated geometry and properties."""
        fid, etag = create_feature(editor_client, test_run_id, name="Field Auth Test")

        body = make_test_feature(
            test_run_id,
            name="Updated Name",
            depth_m=300.0,
            lon=-115.0,
            lat=44.5,
        )
        resp = editor_client.put(
            f"/collections/{COLLECTION_ID}/items/{fid}",
            json=body,
            headers={"If-Match": etag},
        )
        assert resp.status_code == 200
        assert resp.json()["properties"]["name"] == "Updated Name"
        assert resp.json()["properties"]["depth_m"] == 300.0

    def test_editor_can_patch_properties(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Editor can PATCH geometry and properties."""
        fid, etag = create_feature(editor_client, test_run_id, name="Field Patch Test")

        resp = editor_client.patch(
            f"/collections/{COLLECTION_ID}/items/{fid}",
            json={
                "properties": {"depth_m": 400.0},
                "geometry": {"type": "Point", "coordinates": [-114.0, 43.0]},
            },
            headers={
                "If-Match": etag,
                "Content-Type": "application/merge-patch+json",
            },
        )
        assert resp.status_code == 200

    # ── Editor cannot modify visibility ─────────────────────────────

    def test_editor_cannot_set_visibility_on_create(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Editor cannot set visibility when creating a feature."""
        body = make_test_feature(test_run_id, name="Vis Create Test", visibility="restricted")
        resp = editor_client.post(
            f"/collections/{COLLECTION_ID}/items",
            json=body,
        )
        assert resp.status_code == 403

    def test_editor_cannot_change_visibility_via_patch(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Editor cannot change visibility via PATCH."""
        fid, etag = create_feature(editor_client, test_run_id, name="Vis Patch Test")

        resp = editor_client.patch(
            f"/collections/{COLLECTION_ID}/items/{fid}",
            json={"properties": {"visibility": "restricted"}},
            headers={
                "If-Match": etag,
                "Content-Type": "application/merge-patch+json",
            },
        )
        assert resp.status_code == 403

    # ── Admin can modify visibility ─────────────────────────────────

    def test_admin_can_set_visibility_on_create(
        self,
        admin_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Admin can set visibility when creating a feature."""
        body = make_test_feature(test_run_id, name="Admin Vis Create", visibility="restricted")
        resp = admin_client.post(
            f"/collections/{COLLECTION_ID}/items",
            json=body,
        )
        assert resp.status_code == 201
        assert resp.json()["properties"].get("visibility") == "restricted"

    def test_admin_can_change_visibility_via_patch(
        self,
        admin_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Admin can change visibility via PATCH."""
        body = make_test_feature(test_run_id, name="Admin Vis Patch", visibility="public")
        resp = admin_client.post(
            f"/collections/{COLLECTION_ID}/items",
            json=body,
        )
        assert resp.status_code == 201
        fid = resp.json()["id"]
        etag = resp.headers["etag"]

        resp = admin_client.patch(
            f"/collections/{COLLECTION_ID}/items/{fid}",
            json={"properties": {"visibility": "members"}},
            headers={
                "If-Match": etag,
                "Content-Type": "application/merge-patch+json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["properties"].get("visibility") == "members"

    # ── Admin cannot modify organization ────────────────────────────

    def test_admin_cannot_change_org_via_patch(
        self,
        admin_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Admin cannot change organization via PATCH — it's immutable."""
        body = make_test_feature(test_run_id, name="Admin Org Patch")
        resp = admin_client.post(
            f"/collections/{COLLECTION_ID}/items",
            json=body,
        )
        assert resp.status_code == 201
        fid = resp.json()["id"]
        etag = resp.headers["etag"]

        resp = admin_client.patch(
            f"/collections/{COLLECTION_ID}/items/{fid}",
            json={"properties": {"organization": "SomeOtherOrg"}},
            headers={
                "If-Match": etag,
                "Content-Type": "application/merge-patch+json",
            },
        )
        assert resp.status_code in (403, 422)

    # ── Viewer cannot write at all ──────────────────────────────────

    def test_viewer_cannot_create(
        self,
        viewer_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Viewer cannot POST (create) features."""
        body = make_test_feature(test_run_id, name="Viewer Create Test")
        resp = viewer_client.post(
            f"/collections/{COLLECTION_ID}/items",
            json=body,
        )
        assert resp.status_code == 403

    def test_viewer_cannot_put(
        self,
        editor_client: httpx.Client,
        viewer_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Viewer cannot PUT (replace) features."""
        fid, etag = create_feature(editor_client, test_run_id, name="Viewer PUT Test")

        body = make_test_feature(test_run_id, name="Viewer Updated")
        resp = viewer_client.put(
            f"/collections/{COLLECTION_ID}/items/{fid}",
            json=body,
            headers={"If-Match": etag},
        )
        assert resp.status_code == 403

    def test_viewer_cannot_delete(
        self,
        editor_client: httpx.Client,
        viewer_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Viewer cannot DELETE features."""
        fid, etag = create_feature(editor_client, test_run_id, name="Viewer DEL Test")

        resp = viewer_client.delete(
            f"/collections/{COLLECTION_ID}/items/{fid}",
            headers={"If-Match": etag},
        )
        assert resp.status_code == 403
