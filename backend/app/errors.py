from typing import Any


class ApplicationError(Exception):
    """Base error for expected failures independent of any transport."""

    default_code = "application_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code
        self.context = context or {}


class InvalidOperationError(ApplicationError):
    default_code = "invalid_operation"


class InvalidInputError(ApplicationError):
    default_code = "invalid_input"


class ResourceNotFoundError(ApplicationError):
    default_code = "not_found"


class ResourceConflictError(ApplicationError):
    default_code = "conflict"


class AccessDeniedError(ApplicationError):
    default_code = "access_denied"
