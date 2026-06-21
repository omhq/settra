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
        from_ref = f'{rel["from_schema"]}.{rel["from_table"]}.{rel["from_column"]}'
        to_ref = f'{rel["to_schema"]}.{rel["to_table"]}.{rel["to_column"]}'
        from_sql = relationship_side_sql(rel, "from")
        to_sql = relationship_side_sql(rel, "to")

        contract_relationships.append(
            {
                "from": from_ref,
                "to": to_ref,
                "join_sql": f"{from_sql} = {to_sql}",
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


def relationship_side_sql(rel: dict, side: str) -> str:
    schema = str(rel.get(f"{side}_schema") or "")
    table = str(rel.get(f"{side}_table") or "")
    column = str(rel.get(f"{side}_column") or "")
    expression = str(rel.get(f"{side}_expression") or "").strip()
    qualified_column = f"{schema}.{table}.{column}"

    if not expression:
        return qualified_column

    return re.sub(rf"\b{re.escape(column)}\b", qualified_column, expression)


def semantic_rules(extra_rules: list[str] | None = None) -> list[str]:
    rules = [
        "Treat this contract as approved semantic guidance, not an exhaustive permission list.",
        "Use tables and columns from the live context when the contract is incomplete.",
        "Prefer confirmed_relationships when they fit the question.",
        "When no confirmed relationship exists, exploratory joins may use compatible live context columns if the join assumption is stated.",
        "Do not invent table names, column names, or joins whose columns/entities are clearly incompatible.",
        "Respect table grain before aggregating.",
        "Use approved metric definitions when available.",
        "For columns with expression, use the expression instead of the raw column in joins, filters, grouping, and calculations.",
        "When a relationship includes join_sql, use join_sql exactly unless the live schema makes it invalid.",
        "Use primary_time_column for time grouping unless the user asks for a different date.",
        (
            "Treat created/updated timestamps as record lifecycle dates; for "
            "business events, status changes, or interval calculations, prefer "
            "a more specific semantic date column when one is available."
        ),
        "Be transparent about unconfirmed joins in the query plan.",
    ]

    if extra_rules:
        rules.extend(extra_rules)

    return rules


def validate_sql_against_contract(sql: str, contract: dict) -> list[str]:
    issues = []

    aliases = _sql_table_aliases(sql)
    expression_columns = _expression_columns(contract)

    for table_name, columns in expression_columns.items():
        table_aliases = {
            alias
            for alias, aliased_table in aliases.items()
            if aliased_table == table_name
        }
        table_aliases.add(table_name.rsplit(".", 1)[-1])

        for column_name, expression in columns.items():
            raw_uses = _raw_expression_column_predicates(
                sql,
                table_name=table_name,
                table_aliases=table_aliases,
                column_name=column_name,
            )

            if raw_uses:
                issues.append(
                    f"SQL uses raw column {table_name}.{column_name} in a "
                    f"predicate/join; use expression {expression!r} instead."
                )

    return issues


def _expression_columns(contract: dict) -> dict[str, dict[str, str]]:
    tables = contract.get("tables")

    if not isinstance(tables, dict):
        return {}

    expression_columns: dict[str, dict[str, str]] = {}

    for table_name, table in tables.items():
        if not isinstance(table, dict):
            continue

        columns = table.get("columns")

        if not isinstance(columns, dict):
            continue

        for column_name, column in columns.items():
            if not isinstance(column, dict):
                continue

            expression = str(column.get("expression") or "").strip()

            if expression:
                expression_columns.setdefault(str(table_name), {})[
                    str(column_name)
                ] = expression

    return expression_columns


def _sql_table_aliases(sql: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    table_ref = r'"?([a-zA-Z_][\w]*)"?\."?([a-zA-Z_][\w]*)"?'
    reserved = (
        "JOIN|WHERE|ON|LEFT|RIGHT|INNER|FULL|CROSS|GROUP|ORDER|LIMIT|" "UNION|HAVING"
    )
    alias_ref = rf'(?:\s+(?:AS\s+)?(?!{reserved}\b)"?([a-zA-Z_][\w]*)"?)?'

    for match in re.finditer(
        rf"\b(?:FROM|JOIN)\s+{table_ref}{alias_ref}",
        sql,
        flags=re.IGNORECASE,
    ):
        table_name = f"{match.group(1)}.{match.group(2)}"
        alias = match.group(3)
        aliases[table_name] = table_name
        aliases[match.group(2)] = table_name

        if alias:
            aliases[alias] = table_name

    return aliases


def _raw_expression_column_predicates(
    sql: str,
    *,
    table_name: str,
    table_aliases: set[str],
    column_name: str,
) -> list[str]:
    uses = []
    referenced_table_count = len(set(_sql_table_aliases(sql).values()))

    for qualifier in sorted(table_aliases, key=len, reverse=True):
        qualified = rf"{_identifier_regex(qualifier)}\.{_identifier_regex(column_name)}"
        three_part = (
            rf"{_identifier_regex(table_name.rsplit('.', 1)[0])}\."
            rf"{_identifier_regex(table_name.rsplit('.', 1)[1])}\."
            rf"{_identifier_regex(column_name)}"
        )

        if _column_used_in_predicate(sql, qualified) or _column_used_in_predicate(
            sql,
            three_part,
        ):
            uses.append(f"{qualifier}.{column_name}")

    if referenced_table_count <= 2 and _column_used_in_predicate(
        sql,
        _identifier_regex(column_name),
    ):
        uses.append(column_name)

    return uses


def _column_used_in_predicate(sql: str, column_pattern: str) -> bool:
    operators = r"=|<>|!=|<=|>=|<|>|\bIN\b|\bLIKE\b|\bILIKE\b|\bIS\b"
    left = rf"\b{column_pattern}\b\s*(?:{operators})"
    right = rf"(?:{operators})\s*\b{column_pattern}\b"

    return bool(
        re.search(left, sql, flags=re.IGNORECASE)
        or re.search(right, sql, flags=re.IGNORECASE)
    )


def _identifier_regex(identifier: str) -> str:
    return rf'(?:"{re.escape(identifier)}"|{re.escape(identifier)})'
