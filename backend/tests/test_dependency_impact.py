import unittest

from contextlib import ExitStack
from unittest.mock import AsyncMock, Mock, patch

from app import dependency_impact_service as impact_service

COLLECTION = {
    "id": 3,
    "name": "Finance",
    "slug": "finance",
    "pipe_ids": [7],
    "pipes": [
        {
            "id": 7,
            "name": "Revenue source",
            "slug": "revenue_source",
            "storage_key": "o1_revenue_source",
            "destination_schema": "o1_revenue_source",
        }
    ],
    "cube_names": ["Revenue", "RevenueJoined", "RevenueView"],
}

DEFINITIONS = {
    "Revenue": {
        "path": "generated/connections/revenue.yaml",
        "definition": {
            "name": "Revenue",
            "sql_table": "o1_revenue_source.revenue",
            "meta": {"settra": {"connection_id": 7}},
        },
    },
    "RevenueJoined": {
        "path": "overlays/generated/organizations/1/collections/3/joined.yaml",
        "definition": {
            "name": "RevenueJoined",
            "joins": [{"name": "Revenue", "relationship": "many_to_one"}],
        },
    },
    "RevenueView": {
        "path": "overlays/generated/organizations/1/collections/3/view.yaml",
        "definition": {
            "name": "RevenueView",
            "cubes": [{"join_path": "RevenueJoined"}],
        },
    },
}

CALCULATIONS = [
    {
        "id": 10,
        "name": "Revenue total",
        "slug": "revenue_total",
        "content": """\
version: 1
name: Revenue total
nodes:
  - id: revenue
    type: cube_query
    query:
      measures: [Revenue.total]
    result:
      kind: scalar
      member: Revenue.total
  - id: doubled
    type: formula
    inputs:
      value: revenue
    expression: value * 2
outputs:
  total: doubled
""",
    },
    {
        "id": 11,
        "name": "Revenue forecast",
        "slug": "revenue_forecast",
        "content": """\
version: 1
name: Revenue forecast
nodes:
  - id: base
    type: calculation_output
    calculation: revenue_total
    output: total
    result:
      kind: scalar
  - id: forecast
    type: formula
    inputs:
      value: base
    expression: value * 1.1
outputs:
  forecast: forecast
""",
    },
]


class DependencyImpactTests(unittest.IsolatedAsyncioTestCase):
    def impact_patches(self):
        repository = Mock()
        repository.list_files.return_value = [
            {
                "cube_names": ["Revenue", "RevenueJoined"],
                "view_names": ["RevenueView"],
            }
        ]
        return (
            patch.object(
                impact_service,
                "get_collection",
                new=AsyncMock(return_value=COLLECTION),
            ),
            patch.object(
                impact_service,
                "list_collections",
                new=AsyncMock(return_value=[COLLECTION]),
            ),
            patch.object(
                impact_service,
                "authored_definition_index",
                side_effect=lambda allowed_names=None: {
                    name: value
                    for name, value in DEFINITIONS.items()
                    if allowed_names is None or name in allowed_names
                },
            ),
            patch.object(impact_service, "model_repository", return_value=repository),
            patch.object(
                impact_service,
                "list_calculation_documents",
                new=AsyncMock(return_value=CALCULATIONS),
            ),
        )

    async def test_model_deletion_follows_models_relationships_and_outputs(self):
        with ExitStack() as stack:
            for active_patch in self.impact_patches():
                stack.enter_context(active_patch)
            stack.enter_context(
                patch.object(
                    impact_service,
                    "collection_model_file",
                    new=AsyncMock(
                        return_value={
                            "path": "overlays/generated/model.yaml",
                            "cube_names": ["Revenue"],
                            "view_names": [],
                        }
                    ),
                )
            )
            result = await impact_service.preview_model_deletion(
                3,
                "overlays/generated/model.yaml",
            )

        app_impact = result["apps"][0]
        self.assertEqual(
            ["Revenue", "RevenueJoined", "RevenueView"],
            [item["name"] for item in app_impact["affected"]["models"]],
        )
        self.assertEqual(1, app_impact["summary"]["relationship_count"])
        self.assertEqual(
            ["total"],
            app_impact["affected"]["calculations"][0]["outputs"],
        )
        self.assertEqual(
            ["forecast"],
            app_impact["affected"]["calculations"][1]["outputs"],
        )

    async def test_model_deletion_includes_other_apps_that_share_the_model(self):
        shared_app = {
            **COLLECTION,
            "id": 4,
            "name": "Shared finance",
            "slug": "shared-finance",
        }

        with ExitStack() as stack:
            for active_patch in self.impact_patches():
                stack.enter_context(active_patch)
            stack.enter_context(
                patch.object(
                    impact_service,
                    "list_collections",
                    new=AsyncMock(return_value=[COLLECTION, shared_app]),
                )
            )
            stack.enter_context(
                patch.object(
                    impact_service,
                    "collection_model_file",
                    new=AsyncMock(
                        return_value={
                            "path": "overlays/generated/model.yaml",
                            "cube_names": ["Revenue"],
                            "view_names": [],
                        }
                    ),
                )
            )
            result = await impact_service.preview_model_deletion(
                3,
                "overlays/generated/model.yaml",
            )

        self.assertEqual([3, 4], [item["app"]["id"] for item in result["apps"]])
        self.assertEqual(2, result["summary"]["app_count"])
        self.assertEqual(6, result["summary"]["model_count"])

    async def test_source_removal_marks_direct_and_transitive_dependencies(self):
        with ExitStack() as stack:
            for active_patch in self.impact_patches():
                stack.enter_context(active_patch)
            stack.enter_context(
                patch.object(
                    impact_service,
                    "allowed_cube_names_for_pipe_ids",
                    return_value=set(),
                )
            )
            result = await impact_service.preview_source_removal(3, 7)

        models = {item["name"]: item for item in result["affected"]["models"]}
        self.assertTrue(models["Revenue"]["direct"])
        self.assertFalse(models["RevenueJoined"]["direct"])
        self.assertEqual(3, result["summary"]["model_count"])
        self.assertEqual(2, result["summary"]["calculation_count"])
        self.assertEqual(2, result["summary"]["calculation_output_count"])

    async def test_schema_change_combines_every_app_using_the_source(self):
        first = {
            "has_impact": True,
            "summary": {
                "model_count": 3,
                "relationship_count": 1,
                "calculation_count": 2,
                "calculation_output_count": 2,
            },
        }
        second = {
            "has_impact": False,
            "summary": {
                "model_count": 0,
                "relationship_count": 0,
                "calculation_count": 0,
                "calculation_output_count": 0,
            },
        }

        with (
            patch.object(
                impact_service,
                "_source_record",
                new=AsyncMock(
                    return_value={"id": 7, "name": "Revenue", "slug": "revenue"}
                ),
            ),
            patch.object(
                impact_service,
                "list_collections",
                new=AsyncMock(
                    return_value=[
                        {"id": 3, "pipe_ids": [7]},
                        {"id": 4, "pipe_ids": [7]},
                        {"id": 5, "pipe_ids": [8]},
                    ]
                ),
            ),
            patch.object(
                impact_service,
                "preview_source_removal",
                new=AsyncMock(side_effect=[first, second]),
            ) as preview,
        ):
            result = await impact_service.preview_source_schema_change(7)

        self.assertEqual(2, preview.await_count)
        self.assertEqual(2, result["summary"]["app_count"])
        self.assertEqual(3, result["summary"]["model_count"])
        self.assertTrue(result["has_impact"])
        self.assertEqual("potential", result["certainty"])

    async def test_source_deletion_is_an_exact_cross_app_preview(self):
        with patch.object(
            impact_service,
            "_preview_source_across_apps",
            new=AsyncMock(return_value={"certainty": "exact"}),
        ) as preview:
            result = await impact_service.preview_source_deletion(7)

        preview.assert_awaited_once_with(
            7,
            action="delete_source",
            certainty="exact",
            message="Deleting this source makes these App dependencies unavailable.",
            collection_id=None,
        )
        self.assertEqual("exact", result["certainty"])


class CalculationDocumentTests(unittest.IsolatedAsyncioTestCase):
    async def test_documents_are_scoped_to_the_app_and_organization(self):
        class Database:
            query = ""
            args = ()

            async def fetch(self, query, *args):
                self.query = query
                self.args = args
                return []

        database = Database()

        class Context:
            async def __aenter__(self):
                return database

            async def __aexit__(self, *_args):
                return None

        from app import calculation_service

        with (
            patch.object(calculation_service, "db_connection", return_value=Context()),
            patch.object(
                calculation_service,
                "current_organization_id",
                return_value=41,
            ),
        ):
            result = await calculation_service.list_calculation_documents(3)

        self.assertEqual([], result)
        self.assertIn("collection_id = $1", database.query)
        self.assertIn("organization_id = $2", database.query)
        self.assertEqual((3, 41), database.args)
