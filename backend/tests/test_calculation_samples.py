import unittest

from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.calculations.aggregate import AggregateExecution
from app.calculations.executor import execute_definition
from app.calculations.graph import validate_graph
from app.calculations.parser import parse_calculation
from app.calculations.parameters import resolve_calculation_parameters
from app.calculations.service import validate_calculation
from app.errors import InvalidInputError, InvalidOperationError

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "calculations"
FINANCE_CUBE = "finance_bank_transactions"
CUSTOMER_CUBE = "o1_settra_customer_success_demo_settra_customer_success_demo"
SALES_CUBE = "o1_sample_sales_orders_parquet_sample_sales_orders"
SAMPLE_NAMES = (
    "monthly_cash_flow_variance.yaml",
    "customer_renewal_risk_rate.yaml",
    "sales_orders_per_customer.yaml",
    "sales_order_status_breakdown.yaml",
    "paid_average_order_value.yaml",
    "revenue_by_region.yaml",
    "parameterized_renewal_risk_rate.yaml",
)


def load_sample(name: str):
    return parse_calculation((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def cube_response(query, rows):
    return {
        "ok": True,
        "query": query,
        "cube": {},
        "data": rows,
    }


async def sample_cube_query(payload, *, allowed_names):
    query = payload["query"]
    measures = query.get("measures", [])
    filters = query.get("filters", [])

    if f"{FINANCE_CUBE}.net_amount" in measures:
        source = filters[0]["values"][0]
        value = -4545.35 if source == "december_2025_bank" else -12345.35
        return cube_response(query, [{f"{FINANCE_CUBE}.net_amount": value}])

    if f"{FINANCE_CUBE}.debit_amount" in measures:
        source = filters[0]["values"][0]
        value = -10845.35 if source == "december_2025_bank" else -18645.35
        return cube_response(query, [{f"{FINANCE_CUBE}.debit_amount": value}])

    if f"{SALES_CUBE}.row_count" in measures and f"{SALES_CUBE}.status" in query.get(
        "dimensions", []
    ):
        return cube_response(
            query,
            [
                {f"{SALES_CUBE}.status": "paid", f"{SALES_CUBE}.row_count": 10},
                {
                    f"{SALES_CUBE}.status": "refunded",
                    f"{SALES_CUBE}.row_count": 5,
                },
                {
                    f"{SALES_CUBE}.status": "pending",
                    f"{SALES_CUBE}.row_count": 5,
                },
            ],
        )

    if f"{SALES_CUBE}.row_count" in measures:
        return cube_response(query, [{f"{SALES_CUBE}.row_count": 20}])

    if f"{CUSTOMER_CUBE}.row_count" in measures:
        high_risk = any(
            item.get("member") == f"{CUSTOMER_CUBE}.renewal_risk"
            and item.get("values") == ["High"]
            for item in filters
        )
        value = 2 if high_risk else 10
        return cube_response(query, [{f"{CUSTOMER_CUBE}.row_count": value}])

    raise AssertionError(f"Unexpected sample query: {query}")


async def sample_aggregate_query(
    node,
    *,
    organization_id,
    allowed_connection_ids,
):
    if node.id == "paid_revenue":
        rows = [{"total_paid_revenue": 2500}]
    elif node.id == "paid_orders":
        rows = [{"paid_order_count": 10}]
    elif node.id == "regional_revenue":
        rows = [
            {"region": "Asia Pacific", "total_revenue": 900, "order_count": 4},
            {"region": "Europe", "total_revenue": 1600, "order_count": 8},
        ]
    else:
        raise AssertionError(f"Unexpected aggregate sample node: {node.id}")

    return AggregateExecution(
        columns=[*node.group_by, *(measure.name for measure in node.measures)],
        rows=rows,
        row_count=len(rows),
        has_more=node.id == "regional_revenue",
        limit=node.limit,
    )


class CalculationYamlSampleTests(unittest.IsolatedAsyncioTestCase):
    def test_every_sample_is_a_valid_complete_graph(self):
        for name in SAMPLE_NAMES:
            with self.subTest(name=name):
                validate_graph(load_sample(name))

    async def test_monthly_cash_flow_sample_executes_output_and_secondary_target(self):
        definition = load_sample("monthly_cash_flow_variance.yaml")

        with patch(
            "app.calculations.executor.execute_cube_query_payload",
            new=sample_cube_query,
        ):
            output = await execute_definition(
                definition,
                allowed_cube_names={FINANCE_CUBE},
            )
            outflow = await execute_definition(
                definition,
                allowed_cube_names={FINANCE_CUBE},
                target_node_id="outflow_increase_percent",
            )

        self.assertEqual(
            -7800,
            output["outputs"]["net_cash_change"]["result"]["value"],
        )
        self.assertAlmostEqual(
            71.9202238747,
            float(output["outputs"]["outflow_increase_percent"]["result"]["value"]),
        )
        self.assertAlmostEqual(71.9202238747, float(outflow["result"]["value"]))
        self.assertIn("december_debits", output["execution_order"])
        self.assertNotIn("december_net", outflow["execution_order"])

    async def test_customer_renewal_risk_sample_executes(self):
        definition = load_sample("customer_renewal_risk_rate.yaml")

        with patch(
            "app.calculations.executor.execute_cube_query_payload",
            new=sample_cube_query,
        ):
            result = await execute_definition(
                definition,
                allowed_cube_names={CUSTOMER_CUBE},
            )

        self.assertEqual(
            20,
            result["outputs"]["high_risk_rate"]["result"]["value"],
        )

    async def test_parameterized_renewal_risk_sample_executes(self):
        definition = load_sample("parameterized_renewal_risk_rate.yaml")
        resolved = resolve_calculation_parameters(
            definition,
            {
                "cubes": [
                    {
                        "name": CUSTOMER_CUBE,
                        "dimensions": [
                            {
                                "name": f"{CUSTOMER_CUBE}.renewal_risk",
                                "title": "Renewal Risk",
                                "type": "string",
                            }
                        ],
                    }
                ]
            },
        )

        with patch(
            "app.calculations.executor.execute_cube_query_payload",
            new=sample_cube_query,
        ):
            result = await execute_definition(
                definition,
                allowed_cube_names={CUSTOMER_CUBE},
                parameter_values={"risk": "High"},
                resolved_parameters=resolved,
            )

        self.assertEqual(
            20,
            result["outputs"]["matching_rate"]["result"]["value"],
        )

    async def test_cross_source_sample_executes(self):
        definition = load_sample("sales_orders_per_customer.yaml")

        with patch(
            "app.calculations.executor.execute_cube_query_payload",
            new=sample_cube_query,
        ):
            result = await execute_definition(
                definition,
                allowed_cube_names={CUSTOMER_CUBE, SALES_CUBE},
            )

        self.assertEqual(
            2,
            result["outputs"]["orders_per_customer"]["result"]["value"],
        )
        self.assertEqual(
            ["total_orders", "total_customer_accounts", "orders_per_customer"],
            result["execution_order"],
        )

    async def test_table_sample_is_bounded_and_reports_more_rows(self):
        definition = load_sample("sales_order_status_breakdown.yaml")

        with patch(
            "app.calculations.executor.execute_cube_query_payload",
            new=sample_cube_query,
        ):
            result = await execute_definition(
                definition,
                allowed_cube_names={SALES_CUBE},
            )

        table = result["outputs"]["status_breakdown"]["result"]
        self.assertEqual("table", table["kind"])
        self.assertEqual(2, table["row_count"])
        self.assertTrue(table["has_more"])
        self.assertEqual("paid", table["rows"][0][f"{SALES_CUBE}.status"])

    async def test_paid_average_order_value_uses_aggregate_scalars(self):
        definition = load_sample("paid_average_order_value.yaml")

        with patch(
            "app.calculations.executor.execute_aggregate_query",
            new=sample_aggregate_query,
        ):
            result = await execute_definition(
                definition,
                allowed_cube_names=set(),
                organization_id=1,
                allowed_connection_ids={11},
            )

        self.assertEqual(
            250,
            result["outputs"]["average_paid_order_value"]["result"]["value"],
        )
        self.assertEqual(
            ["paid_revenue", "paid_orders", "average_paid_order_value"],
            result["execution_order"],
        )

    async def test_revenue_by_region_returns_a_bounded_aggregate_table(self):
        definition = load_sample("revenue_by_region.yaml")

        with patch(
            "app.calculations.executor.execute_aggregate_query",
            new=sample_aggregate_query,
        ):
            result = await execute_definition(
                definition,
                allowed_cube_names=set(),
                organization_id=1,
                allowed_connection_ids={11},
            )

        table = result["outputs"]["regional_revenue"]["result"]
        self.assertEqual("table", table["kind"])
        self.assertEqual(2, table["row_count"])
        self.assertTrue(table["has_more"])
        self.assertEqual(900, table["rows"][0]["total_revenue"])

    async def test_scalar_sample_rejects_a_missing_result_member(self):
        definition = load_sample("customer_renewal_risk_rate.yaml")

        async def missing_member(payload, *, allowed_names):
            return cube_response(payload["query"], [{"wrong.member": 10}])

        with patch(
            "app.calculations.executor.execute_cube_query_payload",
            new=missing_member,
        ):
            with self.assertRaises(InvalidOperationError) as raised:
                await execute_definition(
                    definition,
                    allowed_cube_names={CUSTOMER_CUBE},
                )

        self.assertIn("does not contain member", raised.exception.message)

    async def test_sample_formula_reports_division_by_zero(self):
        content = """\
version: 1
name: division_by_zero
nodes:
  - id: numerator
    type: value
    value: 10
  - id: denominator
    type: value
    value: 0
  - id: ratio
    type: formula
    inputs: {left: numerator, right: denominator}
    expression: left / right
outputs:
  ratio: ratio
"""

        with self.assertRaises(InvalidOperationError) as raised:
            await execute_definition(
                parse_calculation(content),
                allowed_cube_names=set(),
            )

        self.assertIn("division by zero", raised.exception.message)

    async def test_sample_validation_rejects_an_oversized_table_query(self):
        content = """\
version: 1
name: oversized_table
nodes:
  - id: rows
    type: cube_query
    query:
      dimensions: [sales.region]
      limit: 501
outputs:
  rows: rows
"""

        with (
            patch(
                "app.calculations.service.get_calculation",
                new=AsyncMock(
                    return_value={"id": 7, "collection_id": 3, "content": content}
                ),
            ),
            patch(
                "app.calculations.service.get_collection",
                new=AsyncMock(
                    return_value={"id": 3, "cube_names": ["sales"], "pipe_ids": []}
                ),
            ),
        ):
            with self.assertRaises(InvalidInputError) as raised:
                await validate_calculation(7)

        self.assertIn("limit must be between 1 and 200", raised.exception.message)


if __name__ == "__main__":
    unittest.main()
