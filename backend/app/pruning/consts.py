RELATIONSHIP_INTROSPECTION_COLUMN_LIMIT = 80
METRIC_INTROSPECTION_COLUMN_LIMIT = 100
METRIC_SAMPLE_FIELD_LIMIT = 32
SEMANTIC_PROMPT_COLUMN_LIMIT = 120
SEMANTIC_WORKSPACE_VALUE_LIMIT = 280
QUERY_WORKSPACE_COLUMN_LIMIT = 48
QUERY_WORKSPACE_SAMPLE_ROW_LIMIT = 6
QUERY_WORKSPACE_VALUE_LIMIT = 160

GENERIC_TOKENS = frozenset(
    {
        "a",
        "an",
        "and",
        "app",
        "data",
        "db",
        "google",
        "googlesheets",
        "hubspot",
        "id",
        "name",
        "object",
        "record",
        "sheet",
        "sheets",
        "sp",
        "stripe",
        "table",
        "the",
    }
)

RELATIONSHIP_NAME_HINTS = frozenset(
    {
        "account",
        "company",
        "contact",
        "customer",
        "deal",
        "domain",
        "email",
        "guid",
        "key",
        "lead",
        "org",
        "organization",
        "owner",
        "parent",
        "tenant",
        "user",
        "uuid",
        "workspace",
    }
)

METRIC_NAME_HINTS = frozenset(
    {
        "amount",
        "arr",
        "balance",
        "count",
        "created",
        "currency",
        "date",
        "discount",
        "duration",
        "fee",
        "mrr",
        "price",
        "quantity",
        "rate",
        "revenue",
        "score",
        "status",
        "time",
        "total",
        "updated",
        "value",
    }
)

QUERY_WORKSPACE_COLUMN_HINTS = frozenset(
    {
        "age",
        "amount",
        "city",
        "company",
        "country",
        "created",
        "customer",
        "date",
        "domain",
        "email",
        "first",
        "id",
        "last",
        "name",
        "phone",
        "status",
        "title",
        "total",
        "updated",
        "website",
    }
)

SEMANTIC_WORKSPACE_KEYS_BY_TYPE = {
    "table": (
        "connection_id",
        "connection",
        "plugin",
        "table",
        "status",
        "table_type",
        "grain",
        "primary_time_column",
        "description",
    ),
    "column": (
        "connection_id",
        "connection",
        "plugin",
        "table",
        "column",
        "status",
        "label",
        "description",
        "data_type",
        "semantic_type",
        "expression",
        "unit",
        "roles",
    ),
    "relationship": (
        "from_connection_id",
        "to_connection_id",
        "from",
        "to",
        "status",
        "relationship_type",
        "match_type",
        "confidence",
        "validation_status",
        "validation_note",
    ),
    "metric": (
        "connection_id",
        "connection",
        "plugin",
        "table",
        "name",
        "status",
        "expression",
        "filters",
        "time_column",
        "unit",
    ),
    "warning": (
        "warning_type",
        "connection_id",
        "connection",
        "plugin",
        "table",
        "validation_status",
        "validation_note",
        "notes",
        "caveats",
    ),
}
