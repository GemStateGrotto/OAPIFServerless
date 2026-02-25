"""Row-level access control tests (org isolation + visibility filtering).

Covers TODO section 6 (Row-Level Access Control).
"""

from __future__ import annotations

import httpx
import pytest

from tests.acceptance.conftest import COLLECTION_ID, create_feature, make_test_feature

pytestmark = pytest.mark.acceptance


class TestAnonymousAccess:
    """Unauthenticated access — org param required, only public visible."""

    def test_anon_items_without_org_400(self, anon_client: httpx.Client) -> None:
        """GET /items without organization param returns 400."""
        resp = anon_client.get(f"/collections/{COLLECTION_ID}/items")
        assert resp.status_code == 400

    def test_anon_items_with_org_200(self, anon_client: httpx.Client) -> None:
        """GET /items?organization=TestOrgA returns 200."""
        resp = anon_client.get(
            f"/collections/{COLLECTION_ID}/items",
            params={"organization": "TestOrgA"},
        )
        assert resp.status_code == 200

    def test_anon_sees_only_public(
        self,
        admin_client: httpx.Client,
        anon_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Anonymous users only see 'public' features."""
        # Create features at each visibility level (admin can set visibility)
        for vis in ("public", "members", "restricted"):
            body = make_test_feature(
                test_run_id,
                name=f"Vis-{vis}",
                visibility=vis,
            )
            resp = admin_client.post(
                f"/collections/{COLLECTION_ID}/items",
                json=body,
            )
            assert resp.status_code == 201, f"Failed to create {vis} feature: {resp.text}"

        # Query as anonymous
        resp = anon_client.get(
            f"/collections/{COLLECTION_ID}/items",
            params={"organization": "TestOrgA", "limit": "100"},
        )
        assert resp.status_code == 200
        features = resp.json()["features"]
        our_features = [f for f in features if f["properties"].get("test_run_id") == test_run_id]

        for f in our_features:
            vis = f["properties"].get("visibility", "public")
            assert vis == "public", f"Anon user saw non-public feature: visibility={vis}"


class TestVisibilityByRole:
    """Authenticated visibility depends on group memberships."""

    @pytest.fixture(autouse=True)
    def _seed_visibility_features(
        self,
        admin_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Create one feature per visibility level (runs once per class)."""
        self._vis_tag = f"{test_run_id}-visrole"
        for vis in ("public", "members", "restricted"):
            body = make_test_feature(
                test_run_id,
                name=f"VisRole-{vis}",
                visibility=vis,
                extra_props={"vis_tag": self._vis_tag},
            )
            admin_client.post(
                f"/collections/{COLLECTION_ID}/items",
                json=body,
            )

    def _get_visible_levels(self, client: httpx.Client, tag: str) -> set[str]:
        """Return the set of visibility values this client can see."""
        resp = client.get(
            f"/collections/{COLLECTION_ID}/items",
            params={"limit": "100"},
        )
        assert resp.status_code == 200
        features = resp.json()["features"]
        return {f["properties"].get("visibility", "public") for f in features if f["properties"].get("vis_tag") == tag}

    def test_editor_sees_public_and_members(
        self,
        editor_client: httpx.Client,
    ) -> None:
        """Editor (members group) sees public + members, not restricted."""
        levels = self._get_visible_levels(editor_client, self._vis_tag)
        assert "public" in levels
        assert "members" in levels
        assert "restricted" not in levels

    def test_admin_sees_all_levels(
        self,
        admin_client: httpx.Client,
    ) -> None:
        """Admin (members + restricted groups) sees all visibility levels."""
        levels = self._get_visible_levels(admin_client, self._vis_tag)
        assert "public" in levels
        assert "members" in levels
        assert "restricted" in levels

    def test_viewer_sees_only_public(
        self,
        viewer_client: httpx.Client,
    ) -> None:
        """Viewer (no visibility groups) sees only public."""
        levels = self._get_visible_levels(viewer_client, self._vis_tag)
        assert "public" in levels
        assert "members" not in levels
        assert "restricted" not in levels


class TestOrgIsolation:
    """Cross-org isolation — TestOrgB must never see TestOrgA features."""

    def test_other_org_cannot_see_primary_org_features(
        self,
        editor_client: httpx.Client,
        other_org_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Features created by TestOrgA editor are invisible to TestOrgB."""
        # Create a feature as TestOrgA editor
        fid, _ = create_feature(editor_client, test_run_id, name="Org Isolation Test")

        # TestOrgB editor should not see it in their items
        resp = other_org_client.get(
            f"/collections/{COLLECTION_ID}/items",
            params={"limit": "100"},
        )
        assert resp.status_code == 200
        feature_ids = [f["id"] for f in resp.json()["features"]]
        assert fid not in feature_ids

    def test_other_org_cannot_get_primary_org_feature(
        self,
        editor_client: httpx.Client,
        other_org_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """Direct GET of a TestOrgA feature by TestOrgB returns 404."""
        fid, _ = create_feature(editor_client, test_run_id, name="Org GET Test")

        resp = other_org_client.get(f"/collections/{COLLECTION_ID}/items/{fid}")
        assert resp.status_code == 404


class TestOrganizationAutoPopulation:
    """Organization is auto-populated on creation and immutable."""

    def test_create_auto_populates_org(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """POST auto-populates organization from the JWT token."""
        fid, _ = create_feature(editor_client, test_run_id, name="AutoOrg Test")
        resp = editor_client.get(f"/collections/{COLLECTION_ID}/items/{fid}")
        assert resp.status_code == 200
        props = resp.json()["properties"]
        assert props.get("organization") == "TestOrgA"

    def test_put_cannot_change_org(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """PUT attempting to change organization is rejected."""
        fid, etag = create_feature(editor_client, test_run_id, name="Org Change Test")

        body = make_test_feature(test_run_id, name="Org Change Test")
        body["properties"]["organization"] = "SomeOtherOrg"
        resp = editor_client.put(
            f"/collections/{COLLECTION_ID}/items/{fid}",
            json=body,
            headers={"If-Match": etag},
        )
        # Should be rejected (422 for organization immutable or 403)
        assert resp.status_code in (403, 422), f"Expected 403 or 422, got {resp.status_code}"

    def test_patch_cannot_change_org(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """PATCH attempting to change organization is rejected."""
        fid, etag = create_feature(editor_client, test_run_id, name="Org Patch Test")

        resp = editor_client.patch(
            f"/collections/{COLLECTION_ID}/items/{fid}",
            json={"properties": {"organization": "SomeOtherOrg"}},
            headers={
                "If-Match": etag,
                "Content-Type": "application/merge-patch+json",
            },
        )
        assert resp.status_code in (403, 422), f"Expected 403 or 422, got {resp.status_code}"
