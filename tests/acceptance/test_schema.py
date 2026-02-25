"""Schema validation tests.

Covers TODO sections 5 (Schema Validation) and schema endpoint tests from §1.
"""

from __future__ import annotations

import httpx
import pytest

from tests.acceptance.conftest import COLLECTION_ID

pytestmark = pytest.mark.acceptance


class TestSchemaEndpoint:
    """GET /collections/{id}/schema — JSON Schema (Part 5)."""

    def test_schema_status(self, anon_client: httpx.Client) -> None:
        """GET schema endpoint returns 200."""
        resp = anon_client.get(f"/collections/{COLLECTION_ID}/schema")
        assert resp.status_code == 200

    def test_schema_is_valid_json_schema(self, anon_client: httpx.Client) -> None:
        """Response is a JSON Schema with expected keys."""
        body = anon_client.get(f"/collections/{COLLECTION_ID}/schema").json()
        # JSON Schema should have type and properties
        assert "type" in body or "$schema" in body or "properties" in body

    def test_schema_has_ogc_role(self, anon_client: httpx.Client) -> None:
        """Response includes x-ogc-role annotation."""
        body = anon_client.get(f"/collections/{COLLECTION_ID}/schema").json()
        # x-ogc-role should be present at top level or in properties
        has_role = "x-ogc-role" in body or any(
            "x-ogc-role" in v for v in body.get("properties", {}).values() if isinstance(v, dict)
        )
        assert has_role, f"Expected x-ogc-role in schema: {list(body.keys())}"

    def test_schema_receivable_variant(self, anon_client: httpx.Client) -> None:
        """Schema supports ?type=receivable variant."""
        resp = anon_client.get(f"/collections/{COLLECTION_ID}/schema?type=receivable")
        assert resp.status_code == 200

    def test_schema_nonexistent_collection_404(self, anon_client: httpx.Client) -> None:
        """Schema for nonexistent collection returns 404."""
        resp = anon_client.get("/collections/nonexistent-xyz/schema")
        assert resp.status_code == 404


class TestSchemaValidation:
    """POST/PUT with invalid bodies should be rejected (TODO §5)."""

    def test_post_missing_required_property_422(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """POST with missing required 'name' property returns 422."""
        body = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-114.5, 44.0]},
            "properties": {
                "depth_m": 50,
                "test_run_id": test_run_id,
                # 'name' is missing — required by the collection schema
            },
        }
        resp = editor_client.post(
            f"/collections/{COLLECTION_ID}/items",
            json=body,
        )
        assert resp.status_code == 422

    def test_post_wrong_property_type_422(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """POST with wrong property type returns 422."""
        body = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-114.5, 44.0]},
            "properties": {
                "name": "Type Test Feature",
                "depth_m": "not-a-number",  # should be number
                "test_run_id": test_run_id,
            },
        }
        resp = editor_client.post(
            f"/collections/{COLLECTION_ID}/items",
            json=body,
        )
        assert resp.status_code == 422

    def test_put_invalid_body_422(
        self,
        editor_client: httpx.Client,
        test_run_id: str,
    ) -> None:
        """PUT with schema-violating body returns 422."""
        from tests.acceptance.conftest import create_feature

        fid, etag = create_feature(editor_client, test_run_id, name="Schema PUT Test")

        invalid_body = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-114.5, 44.0]},
            "properties": {
                # missing required 'name'
                "depth_m": 100,
                "test_run_id": test_run_id,
            },
        }
        resp = editor_client.put(
            f"/collections/{COLLECTION_ID}/items/{fid}",
            json=invalid_body,
            headers={"If-Match": etag},
        )
        assert resp.status_code == 422
