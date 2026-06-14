import re


def sanitize_sql(sql: str) -> str:
    cleaned = sql.strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:sql)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    cleaned = cleaned.strip().rstrip(";").strip()

    if ";" in cleaned:
        raise ValueError("Generated SQL contained multiple statements.")
    if not re.match(r"^(select|with)\b", cleaned, flags=re.IGNORECASE):
        raise ValueError("Generated SQL was not a read-only SELECT query.")
    if re.search(
        (
            r"\b(insert|update|delete|drop|alter|create|truncate|grant|"
            r"revoke|copy|call|do|execute|merge)\b"
        ),
        cleaned,
        flags=re.IGNORECASE,
    ):
        raise ValueError("Generated SQL contained a disallowed keyword.")

    return cleaned
