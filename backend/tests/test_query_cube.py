import json
import unittest

from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.cube.client import CubeAPIError
from app.cube.projection import (
    QueryResultProjectionInput,
    SemanticResponseProjector,
)
from app.cube.query import (
    MAX_MCP_CUBE_BLEND_QUERIES,
    bounded_mcp_cube_query,
    cube_api_error_detail,
    normalize_cube_query_payload,
    sentinel_mcp_cube_query,
)
from app.routers.mcp.query_cube import query_cube

projector = SemanticResponseProjector()


class BoundedCubeQueryTests(unittest.TestCase):
    def test_cube_error_omits_duplicate_and_raw_payload_representations(self):
        detail = cube_api_error_detail(
            CubeAPIError(
                "Unknown member",
                status_code=422,
                payload={"error": "Unknown member", "stack": "x" * 10_000},
            )
        )

        self.assertEqual(
            {"message": "Unknown member", "retryable": False},
            detail,
        )

    def test_default_limit_is_added_without_mutating_the_input(self):
        query = {"measures": ["orders.count"]}

        bounded = bounded_mcp_cube_query(query)

        self.assertEqual(100, bounded["limit"])
        self.assertNotIn("limit", query)

    def test_each_blending_query_is_bounded(self):
        bounded = bounded_mcp_cube_query(
            [
                {"measures": ["orders.count"]},
                {"measures": ["payments.total"], "limit": 25},
            ]
        )

        self.assertEqual([100, 25], [item["limit"] for item in bounded])

    def test_blending_array_is_bounded_and_not_independent_batching(self):
        with self.assertRaisesRegex(HTTPException, "one Cube blending request"):
            normalize_cube_query_payload(
                [{"measures": ["orders.count"]}] * (MAX_MCP_CUBE_BLEND_QUERIES + 1)
            )

    def test_each_blending_item_must_be_a_valid_cube_query(self):
        with self.assertRaisesRegex(HTTPException, "Expected Cube query JSON"):
            normalize_cube_query_payload(
                [
                    {"measures": ["orders.count"]},
                    {"arbitrary": "not a Cube query"},
                ]
            )

    def test_limit_above_the_cap_is_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            bounded_mcp_cube_query({"measures": ["orders.count"], "limit": 501})

        self.assertEqual(422, raised.exception.status_code)

    def test_sentinel_query_requests_one_extra_row(self):
        executable, limit, offset = sentinel_mcp_cube_query(
            {
                "dimensions": ["orders.id"],
                "limit": 500,
                "offset": 1000,
            }
        )

        self.assertEqual(501, executable["limit"])
        self.assertEqual(500, limit)
        self.assertEqual(1000, offset)

    def test_sentinel_query_rejects_invalid_offset(self):
        for offset in (-1, True, "10"):
            with self.subTest(offset=offset):
                with self.assertRaises(HTTPException) as raised:
                    sentinel_mcp_cube_query(
                        {
                            "dimensions": ["orders.id"],
                            "offset": offset,
                        }
                    )

                self.assertEqual(422, raised.exception.status_code)

    def test_compact_result_contains_rows_once(self):
        rows = [{"orders.status": "completed", "orders.count": 3}]
        legacy_response = {
            "ok": True,
            "query": {"measures": ["orders.count"]},
            "cube": {
                "query": {"measures": ["orders.count"], "rowLimit": 100},
                "annotation": {"measures": {"orders.count": {"type": "number"}}},
                "lastRefreshTime": "2026-07-03T00:00:00.000",
                "data": rows,
                "total": 1,
            },
            "data": rows,
            "result": rows,
        }

        result = projector.query_result(
            QueryResultProjectionInput(response=legacy_response)
        )
        serialized = json.dumps(result, separators=(",", ":"))

        self.assertEqual({"data": rows, "row_count": 1, "total": 1}, result)
        self.assertEqual(1, serialized.count("orders.status"))
        self.assertNotIn("query", result)
        self.assertNotIn("cube", result)
        self.assertNotIn("result", result)

    def test_query_result_normalizes_annotated_decimal_strings(self):
        result = projector.query_result(
            QueryResultProjectionInput(
                response={
                    "query": {
                        "measures": [
                            "orders.total",
                            "orders.balance",
                            "orders.precise_ratio",
                        ],
                        "dimensions": ["orders.customer_id"],
                    },
                    "cube": {
                        "annotation": {
                            "measures": {
                                "orders.total": {"type": "number"},
                                "orders.balance": {"type": "number"},
                                "orders.precise_ratio": {"type": "number"},
                            },
                            "dimensions": {
                                "orders.customer_id": {"type": "string"},
                            },
                        }
                    },
                    "data": [
                        {
                            "orders.customer_id": "00123",
                            "orders.total": "499.0000000000000000",
                            "orders.balance": "0.00000000000000000000",
                            "orders.precise_ratio": "0.12500000000000000000",
                        }
                    ],
                }
            )
        )

        self.assertEqual(
            {
                "orders.customer_id": "00123",
                "orders.total": 499,
                "orders.balance": 0,
                "orders.precise_ratio": 0.125,
            },
            result["data"][0],
        )

    def test_query_result_renders_date_only_members_as_neutral_dates(self):
        result = projector.query_result(
            QueryResultProjectionInput(
                response={
                    "query": {
                        "dimensions": ["renewals.renewal_date"],
                        "timezone": "America/New_York",
                    },
                    "cube": {
                        "annotation": {
                            "dimensions": {
                                "renewals.renewal_date": {
                                    "type": "time",
                                    "meta": {
                                        "settra": {"semantic_type": "business_date"}
                                    },
                                },
                                "renewals.created_at": {"type": "time"},
                            },
                        }
                    },
                    "data": [
                        {
                            "renewals.renewal_date": "2026-07-14T20:00:00.000",
                            "renewals.created_at": "2026-07-15T00:00:00.000Z",
                        }
                    ],
                }
            )
        )

        self.assertEqual("2026-07-15", result["data"][0]["renewals.renewal_date"])
        self.assertEqual(
            "2026-07-15T00:00:00.000Z",
            result["data"][0]["renewals.created_at"],
        )

    def test_query_result_renders_time_granularity_buckets_as_dates(self):
        result = projector.query_result(
            QueryResultProjectionInput(
                response={
                    "query": {
                        "timeDimensions": [
                            {
                                "dimension": "orders.created_at",
                                "granularity": "day",
                            }
                        ],
                        "timezone": "America/New_York",
                    },
                    "cube": {
                        "annotation": {
                            "dimensions": {
                                "orders.created_at.day": {"type": "time"},
                            },
                        }
                    },
                    "data": [{"orders.created_at.day": "2026-07-15T00:00:00.000Z"}],
                }
            )
        )

        self.assertEqual("2026-07-15", result["data"][0]["orders.created_at.day"])


class QueryCubeToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_rejects_arrays_instead_of_treating_them_as_blending(self):
        with self.assertRaisesRegex(ValueError, "use separate tool calls"):
            await query_cube(
                [
                    {"dimensions": ["orders.status"]},
                    {"measures": ["orders.count"]},
                ]
            )

    async def test_tool_returns_compact_data_and_submits_the_bounded_query(self):
        rows = [{"orders.count": 3}]
        load_query = AsyncMock(
            return_value={
                "data": rows,
                "query": {"measures": ["orders.count"], "rowLimit": 100},
                "annotation": {"measures": {"orders.count": {"type": "number"}}},
                "lastRefreshTime": "2026-07-03T00:00:00.000",
            }
        )

        with patch("app.cube.query.load_cube_query", new=load_query):
            result = await query_cube({"measures": ["orders.count"]})

        self.assertEqual(
            {
                "data": rows,
                "row_count": 1,
                "has_more": False,
                "limit": 100,
                "offset": 0,
                "next_offset": None,
            },
            result,
        )
        self.assertEqual(101, load_query.await_args.args[0]["limit"])
        self.assertNotIn("total", load_query.await_args.args[0])

    async def test_tool_trims_the_sentinel_row_and_returns_next_offset(self):
        rows = [
            {"orders.id": "order_1"},
            {"orders.id": "order_2"},
            {"orders.id": "order_3"},
        ]
        load_query = AsyncMock(return_value={"data": rows})

        with patch("app.cube.query.load_cube_query", new=load_query):
            result = await query_cube(
                {
                    "dimensions": ["orders.id"],
                    "limit": 2,
                    "offset": 4,
                    "order": {"orders.id": "asc"},
                }
            )

        self.assertEqual(rows[:2], result["data"])
        self.assertEqual(2, result["row_count"])
        self.assertEqual(True, result["has_more"])
        self.assertEqual(2, result["limit"])
        self.assertEqual(4, result["offset"])
        self.assertEqual(6, result["next_offset"])
        self.assertEqual(3, load_query.await_args.args[0]["limit"])
        self.assertEqual(4, load_query.await_args.args[0]["offset"])

    async def test_tool_preserves_an_explicit_cube_total(self):
        load_query = AsyncMock(
            return_value={
                "data": [{"orders.id": "order_5"}],
                "total": 5,
            }
        )

        with patch("app.cube.query.load_cube_query", new=load_query):
            result = await query_cube(
                {
                    "dimensions": ["orders.id"],
                    "limit": 2,
                    "offset": 4,
                    "total": True,
                }
            )

        self.assertEqual(5, result["total"])
        self.assertEqual(False, result["has_more"])
        self.assertIsNone(result["next_offset"])
        self.assertEqual(True, load_query.await_args.args[0]["total"])

    async def test_tool_surfaces_the_limit_cap_as_an_mcp_value_error(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 500"):
            await query_cube({"measures": ["orders.count"], "limit": 501})

    async def test_tool_surfaces_actionable_permission_denial(self):
        load_query = AsyncMock(
            side_effect=CubeAPIError(
                "Google Sheets returned 403 Forbidden: missing required scope "
                "spreadsheets.readonly",
                # Cube may wrap a provider 403 in its own 500 response.
                status_code=500,
            )
        )

        with (
            patch("app.cube.query.load_cube_query", new=load_query),
            self.assertRaises(ValueError) as raised,
        ):
            await query_cube(
                {
                    "measures": ["sales_pipeline.rows"],
                    "filters": [
                        {
                            "member": "account_lookup.industry",
                            "operator": "set",
                        }
                    ],
                }
            )

        detail = json.loads(str(raised.exception))

        self.assertEqual("cube_access_denied", detail["code"])
        self.assertEqual(
            ["account_lookup", "sales_pipeline"],
            detail["cubes"],
        )
        self.assertFalse(detail["retryable"])
        self.assertIn("spreadsheets.readonly", detail["source_error"])
        self.assertIn("Tell the user", detail["agent_action"])

    async def test_tool_distinguishes_retryable_cube_unavailability(self):
        load_query = AsyncMock(
            side_effect=CubeAPIError(
                "Could not reach the provider",
                status_code=503,
            )
        )

        with (
            patch("app.cube.query.load_cube_query", new=load_query),
            self.assertRaises(ValueError) as raised,
        ):
            await query_cube(
                {
                    "dimensions": ["orders.status"],
                    "timeDimensions": [
                        {"dimension": "orders.created", "granularity": "day"}
                    ],
                }
            )

        detail = json.loads(str(raised.exception))

        self.assertEqual("cube_temporarily_unavailable", detail["code"])
        self.assertEqual(["orders"], detail["cubes"])
        self.assertTrue(detail["retryable"])

    async def test_tool_distinguishes_invalid_members_from_access_denials(self):
        load_query = AsyncMock(
            side_effect=CubeAPIError(
                "Unknown member 'accounts.missing'",
                status_code=400,
            )
        )

        with (
            patch("app.cube.query.load_cube_query", new=load_query),
            self.assertRaises(ValueError) as raised,
        ):
            await query_cube({"dimensions": ["accounts.missing"]})

        detail = json.loads(str(raised.exception))

        self.assertEqual("invalid_cube_query", detail["code"])
        self.assertEqual(["accounts"], detail["cubes"])
        self.assertIn("get_cube", detail["agent_action"])


if __name__ == "__main__":
    unittest.main()
