from typing import Any


def validation_cleanup_failed(cleanup: dict[str, Any]) -> bool:
    """Include disk and compiler confirmation in overall validation readiness."""
    if cleanup.get("error"):
        return True
    if cleanup.get("attempted") is not True:
        return False
    if cleanup.get("complete") is False or cleanup.get("removed") is not True:
        return True
    if "restored" in cleanup and cleanup["restored"] is not True:
        return True

    for key in ("cube", "removal"):
        status = cleanup.get(key)

        if isinstance(status, dict) and (
            status.get("error")
            or status.get("connected") is False
            or status.get("compiled") is False
            or status.get("removed") is False
        ):
            return True

    return False
