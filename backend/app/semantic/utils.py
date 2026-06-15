import re
import json

from app.semantic.consts import (
    BOOLEAN_DATA_TYPES,
    NUMERIC_DATA_TYPES,
    TEXT_DATA_TYPES,
)


def is_ignored_column(column_name: str, ignored_column_postfixes: list[str]) -> bool:
    lname = column_name.lower()
    return any(
        lname.endswith(postfix.lower())
        for postfix in ignored_column_postfixes
        if postfix.strip()
    )


def normalized_data_type(data_type: str | None) -> str:
    return str(data_type or "").strip().lower()


def is_text_data_type(data_type: str | None) -> bool:
    dtype = normalized_data_type(data_type)
    return dtype in TEXT_DATA_TYPES or "char" in dtype


def is_boolean_data_type(data_type: str | None) -> bool:
    return normalized_data_type(data_type) in BOOLEAN_DATA_TYPES


def is_json_data_type(data_type: str | None) -> bool:
    return "json" in normalized_data_type(data_type)


def is_numeric_data_type(data_type: str | None) -> bool:
    dtype = normalized_data_type(data_type)
    return dtype in NUMERIC_DATA_TYPES or any(
        token in dtype for token in ("int", "numeric", "decimal", "double", "real")
    )


def is_time_data_type(data_type: str | None) -> bool:
    dtype = normalized_data_type(data_type)
    return dtype == "date" or "time" in dtype


def humanize(name: str) -> str:
    cleaned = re.sub(r"[_\-]+", " ", name).strip()
    return cleaned.title()


def infer_table_semantics(table_name: str, columns: list[dict]) -> dict:
    column_names = {c["name"].lower() for c in columns}

    primary_time_column = None
    for candidate in [
        "created",
        "created_at",
        "create_time",
        "date",
        "timestamp",
        "updated_at",
    ]:
        if candidate in column_names:
            primary_time_column = candidate
            break

    table_type = "dimension"
    if any(
        word in table_name.lower()
        for word in [
            "charge",
            "payment",
            "invoice",
            "deal",
            "transaction",
            "event",
            "order",
        ]
    ):
        table_type = "fact"

    grain_col = "id" if "id" in column_names else None
    grain = f"one row per {humanize(table_name)}"
    if grain_col:
        grain = f"one row per {humanize(table_name)} id"

    return {
        "label": humanize(table_name),
        "description": f"{humanize(table_name)} table",
        "table_type": table_type,
        "grain": grain,
        "primary_time_column": primary_time_column,
        "hidden": table_name.startswith("_"),
    }


def infer_column_semantics(column: dict) -> dict:
    name = column["name"]
    lname = name.lower()
    dtype = str(column.get("type", "")).lower()

    semantic_type = "text"
    unit = None
    expression = None

    text_like = is_text_data_type(dtype)
    boolean_type = is_boolean_data_type(dtype)
    json_type = is_json_data_type(dtype)
    numeric_type = is_numeric_data_type(dtype)
    time_type = is_time_data_type(dtype)
    predicate_name = lname.startswith(("is_", "has_", "can_", "should_", "enable_"))

    is_id = (lname in {"id", "uuid"} or lname.endswith("_id")) and not boolean_type
    is_fk = not boolean_type and (
        lname.endswith("_id")
        or lname
        in {
            "customer",
            "subscription",
            "invoice",
            "company",
            "contact",
        }
    )
    is_time_name = any(
        x in lname for x in ["date", "time", "created", "updated", "timestamp"]
    )
    is_time = (time_type or (is_time_name and not is_id and not is_fk)) and not (
        boolean_type or json_type
    )
    is_money = any(
        x in lname for x in ["amount", "revenue", "price", "cost", "total", "subtotal"]
    ) and not (boolean_type or json_type)
    is_email = text_like and not predicate_name and "email" in lname
    is_domain = (
        text_like
        and not predicate_name
        and (
            lname in {"domain", "website", "url"}
            or lname.endswith("_domain")
            or lname.endswith("_url")
        )
    )

    if boolean_type:
        semantic_type = "boolean"
    elif json_type:
        semantic_type = "json"
    elif numeric_type:
        semantic_type = "number"

    if is_id:
        semantic_type = "id"
    if is_fk:
        semantic_type = "foreign_key"
    if is_time:
        semantic_type = "timestamp"
    if is_money:
        semantic_type = "money"
        unit = "currency"
    if is_email:
        semantic_type = "email"
    if is_domain:
        semantic_type = "domain"

    # Stripe-style fields are often minor units.
    if is_money and "integer" in dtype:
        semantic_type = "money_minor_units"
        expression = f"{name} / 100.0"

    hidden = lname in {"metadata", "raw", "json", "payload"} or lname.endswith("_json")

    return {
        "label": humanize(name),
        "semantic_type": semantic_type,
        "expression": expression,
        "unit": unit,
        "is_dimension": semantic_type
        in {"text", "category", "email", "domain", "id", "foreign_key", "boolean"},
        "is_measure": semantic_type in {"money", "money_minor_units", "number"},
        "is_time": is_time,
        "is_id": is_id,
        "is_foreign_key": is_fk,
        "hidden": hidden,
    }


def format_semantic_contract(
    *,
    tables: list[dict],
    columns: list[dict],
    relationships: list[dict],
    metrics: list[dict],
    selected_connection_ids: list[int],
    rules: list[str] | None = None,
) -> dict:
    columns_by_table_id: dict[int, list[dict]] = {}

    for col in columns:
        columns_by_table_id.setdefault(col["semantic_table_id"], []).append(col)

    contract_tables = {}

    for table in tables:
        full_name = f'{table["schema_name"]}.{table["table_name"]}'

        contract_tables[full_name] = {
            "label": table.get("label"),
            "type": table.get("table_type"),
            "grain": table.get("grain"),
            "primary_time_column": table.get("primary_time_column"),
            "metadata": table_metadata(table),
            "columns": {
                col["column_name"]: {
                    "label": col.get("label"),
                    "type": col.get("semantic_type"),
                    "data_type": col.get("data_type"),
                    "expression": col.get("expression"),
                    "unit": col.get("unit"),
                    "is_dimension": bool(col.get("is_dimension")),
                    "is_measure": bool(col.get("is_measure")),
                    "is_time": bool(col.get("is_time")),
                    "is_id": bool(col.get("is_id")),
                    "is_foreign_key": bool(col.get("is_foreign_key")),
                }
                for col in columns_by_table_id.get(table["id"], [])
            },
        }

    contract_relationships = []

    for rel in relationships:
        contract_relationships.append(
            {
                "from": f'{rel["from_schema"]}.{rel["from_table"]}.{rel["from_column"]}',
                "to": f'{rel["to_schema"]}.{rel["to_table"]}.{rel["to_column"]}',
                "type": rel["relationship_type"],
                "match_type": rel["match_type"],
            }
        )

    contract_metrics = {}

    for metric in metrics:
        filters = metric.get("filters_json")
        if isinstance(filters, str) and filters:
            try:
                filters = json.loads(filters)
            except json.JSONDecodeError:
                pass

        contract_metrics[metric["name"]] = {
            "label": metric.get("label"),
            "table": f'{metric["schema_name"]}.{metric["table_name"]}',
            "expression": metric["expression"],
            "filters": filters,
            "time_column": metric.get("time_column"),
            "unit": metric.get("unit"),
        }

    return {
        "selected_connection_ids": selected_connection_ids,
        "tables": contract_tables,
        "confirmed_relationships": contract_relationships,
        "metrics": contract_metrics,
        "rules": semantic_rules(rules),
    }


def table_metadata(table: dict) -> dict:
    metadata = table.get("metadata")
    if isinstance(metadata, dict):
        return metadata

    raw = table.get("metadata_json")
    if not raw:
        return {}

    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def semantic_rules(extra_rules: list[str] | None = None) -> list[str]:
    rules = [
        "Treat this contract as approved semantic guidance, not an exhaustive permission list.",
        "Use tables and columns from the live context when the contract is incomplete.",
        "Prefer confirmed_relationships when they fit the question.",
        "When no confirmed relationship exists, exploratory joins may use compatible live context columns if the join assumption is stated.",
        "Do not invent table names, column names, or joins whose columns/entities are clearly incompatible.",
        "Respect table grain before aggregating.",
        "Use approved metric definitions when available.",
        "For columns with expression, use the expression instead of the raw column for calculations.",
        "Use primary_time_column for time grouping unless the user asks for a different date.",
        "Be transparent about unconfirmed joins in the query plan.",
    ]

    if extra_rules:
        rules.extend(extra_rules)

    return rules


def validate_sql_against_contract(sql: str, contract: dict) -> list[str]:
    """
    issues = validate_sql_against_contract(
        safe_sql,
        state.get("semantic_contract") or {},
    )

    if issues:
        return {
            "error": "SQL did not follow the selected semantic contract: " + "; ".join(issues),
            "sql": safe_sql,
            "needs_retry": True,
        }
    """
    issues = []

    allowed_tables = set(contract.get("tables", {}).keys())

    sql_lower = sql.lower()

    for table in allowed_tables:
        # table like stripe_prod.stripe_charge
        pass

    # Simple check: if SQL references schema.table not in contract, flag it.
    referenced = set(re.findall(r"\b([a-zA-Z_][\w]*\.[a-zA-Z_][\w]*)\b", sql))

    for ref in referenced:
        if ref not in allowed_tables and not any(
            ref.endswith("." + t.split(".")[-1]) for t in allowed_tables
        ):
            # this may catch aliases imperfectly, but it is useful for MVP
            issues.append(f"SQL references table not in semantic contract: {ref}")

    return issues
