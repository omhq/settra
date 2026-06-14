import json
import time
import logging

from typing import Any
from datetime import datetime, timezone
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.common.logging import env_flag
from app.agent.schemas import PromptMessage
from app.agent.structured import StructuredOutputMixin
from app.utils import extract_json_object, jsonable

logger = logging.getLogger(__name__)


class AgentLLMError(RuntimeError):
    def __init__(
        self,
        user_message: str,
        *,
        operation: str,
        original_summary: str,
        retryable: bool = False,
    ):
        super().__init__(user_message)
        self.user_message = user_message
        self.operation = operation
        self.original_summary = original_summary
        self.retryable = retryable

    @classmethod
    def from_exception(
        cls,
        exc: Exception,
        *,
        operation: str,
    ) -> "AgentLLMError":
        if isinstance(exc, AgentLLMError):
            return exc

        return cls(
            _provider_user_message(exc),
            operation=operation,
            original_summary=_exception_summary(exc),
            retryable=_is_retryable_provider_error(exc),
        )


class AgentLLM(StructuredOutputMixin):
    def __init__(
        self,
        llm: BaseChatModel | None,
        diagnostics: list[dict[str, Any]] | None = None,
    ):
        self._llm = llm
        self._diagnostics = diagnostics

    @property
    def configured(self) -> bool:
        return self._llm is not None

    async def json(self, messages: list[PromptMessage]) -> dict[str, Any]:
        content = await self.text(messages)
        return extract_json_object(content)

    async def text(
        self,
        messages: list[PromptMessage],
        operation: str | None = None,
    ) -> str:
        if self._llm is None:
            raise RuntimeError("No chat model is configured for this thread.")

        op_name = operation or "text"
        self._log_prompt("text", op_name, messages)
        logger.info(f"LLM text call started operation={op_name}")
        trace = self._start_trace("text", op_name, messages)

        try:
            response = await self._llm.ainvoke(_to_langchain_messages(messages))
        except Exception as exc:
            self._finish_trace(trace, "failed", exc)

            llm_error = AgentLLMError.from_exception(exc, operation=op_name)

            logger.warning(
                f"LLM text call failed operation={op_name} "
                f"error={llm_error.original_summary} "
                f"user_message={llm_error.user_message}",
                exc_info=env_flag("AGENT_DEBUG"),
            )
            raise llm_error from exc

        _record_response_metadata(trace, response)
        self._finish_trace(trace, "succeeded")

        content = response.content

        logger.info(
            f"LLM text call completed operation={op_name} "
            f"response_type={type(content).__name__}"
        )

        if isinstance(content, str):
            return content

        return json.dumps(content)

    def _log_prompt(
        self,
        call_type: str,
        operation: str,
        messages: list[PromptMessage],
    ) -> None:
        roles = [message.get("role", "unknown") for message in messages]
        char_count = sum(len(message.get("content", "")) for message in messages)

        logger.info(
            f"LLM {call_type} call operation={operation} model={_model_name(self._llm)} "
            f"messages={roles} chars={char_count}"
        )

        if not env_flag("AGENT_LOG_PROMPTS"):
            return

        for index, message in enumerate(messages):
            logger.debug(
                f"LLM prompt preview operation={operation} message={index} "
                f"role={message.get('role', 'unknown')} "
                f"content={message.get('content', '')[:2000]!r}"
            )

    def _start_trace(
        self,
        call_type: str,
        operation: str,
        messages: list[PromptMessage],
        **extra: Any,
    ) -> dict[str, Any]:
        trace = {
            "call_type": call_type,
            "operation": operation,
            "model": _model_name(self._llm),
            "message_roles": [message.get("role", "unknown") for message in messages],
            "message_count": len(messages),
            "prompt_chars": sum(
                len(message.get("content", "")) for message in messages
            ),
            "started_at": _utc_now(),
            **extra,
        }
        trace["_started_perf"] = time.perf_counter()

        if self._diagnostics is not None:
            self._diagnostics.append(trace)

        return trace

    def _finish_trace(
        self,
        trace: dict[str, Any],
        status: str,
        exc: Exception | None = None,
    ) -> None:
        started = trace.pop("_started_perf", None)
        trace["status"] = status
        trace["finished_at"] = _utc_now()

        if started is not None:
            trace["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)

        if exc is not None:
            trace["error"] = _exception_summary(exc)

    def _to_langchain_messages(self, messages: list[PromptMessage]):
        return _to_langchain_messages(messages)

    def _record_response_metadata(
        self,
        trace: dict[str, Any] | None,
        response: Any,
    ) -> None:
        _record_response_metadata(trace, response)

    def _agent_error_from_exception(
        self,
        exc: Exception,
        *,
        operation: str,
    ) -> AgentLLMError:
        return AgentLLMError.from_exception(exc, operation=operation)

    def _structured_parse_error(
        self,
        user_message: str,
        *,
        operation: str,
        original_summary: str,
    ) -> AgentLLMError:
        return AgentLLMError(
            user_message,
            operation=operation,
            original_summary=original_summary,
            retryable=False,
        )

    def _is_agent_error(self, exc: Exception) -> bool:
        return isinstance(exc, AgentLLMError)

    def _exception_summary(self, exc: Exception) -> str:
        return _exception_summary(exc)


def _to_langchain_messages(messages: list[PromptMessage]):
    converted = []

    for message in messages:
        role = message["role"]
        content = message["content"]

        if role == "system":
            converted.append(SystemMessage(content=content))
        elif role == "assistant":
            converted.append(AIMessage(content=content))
        else:
            converted.append(HumanMessage(content=content))

    return converted


def _record_response_metadata(
    trace: dict[str, Any] | None,
    response: Any,
) -> None:
    if trace is None or response is None:
        return

    usage_metadata = _safe_jsonable(getattr(response, "usage_metadata", None))
    response_metadata = _safe_jsonable(getattr(response, "response_metadata", None))
    additional_kwargs = _safe_jsonable(getattr(response, "additional_kwargs", None))

    if usage_metadata:
        trace["usage_metadata"] = usage_metadata
    if response_metadata:
        trace["response_metadata"] = response_metadata
    if additional_kwargs:
        trace["additional_kwargs"] = additional_kwargs

    token_usage = _normalise_token_usage(usage_metadata, response_metadata)

    if token_usage:
        trace["token_usage"] = token_usage


def _normalise_token_usage(*sources: Any) -> dict[str, int]:
    usage: dict[str, int] = {}

    for source in sources:
        if not isinstance(source, dict):
            continue

        candidates = [
            source,
            source.get("token_usage"),
            source.get("usage"),
            source.get("usage_metadata"),
        ]

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue

            input_tokens = _first_int(
                candidate,
                "input_tokens",
                "prompt_tokens",
                "prompt_token_count",
            )
            output_tokens = _first_int(
                candidate,
                "output_tokens",
                "completion_tokens",
                "completion_token_count",
            )
            total_tokens = _first_int(
                candidate,
                "total_tokens",
                "total_token_count",
            )

            if input_tokens is not None:
                usage["input_tokens"] = input_tokens
            if output_tokens is not None:
                usage["output_tokens"] = output_tokens
            if total_tokens is not None:
                usage["total_tokens"] = total_tokens

            if usage:
                if "total_tokens" not in usage and (
                    "input_tokens" in usage or "output_tokens" in usage
                ):
                    usage["total_tokens"] = usage.get("input_tokens", 0) + usage.get(
                        "output_tokens",
                        0,
                    )
                return usage

    return usage


def _first_int(source: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = source.get(key)

        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue

    return None


def _safe_jsonable(value: Any) -> Any:
    if value in (None, {}, []):
        return None

    try:
        return jsonable(value)
    except Exception:
        return str(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _model_name(llm: BaseChatModel | None) -> str:
    if llm is None:
        return "none"

    return str(
        getattr(llm, "model", None)
        or getattr(llm, "model_name", None)
        or llm.__class__.__name__
    )


def _exception_summary(exc: Exception) -> str:
    message = str(exc).replace("\n", " ")

    if len(message) > 600:
        message = f"{message[:600]}..."

    return f"{exc.__class__.__name__}: {message}"


def _provider_user_message(exc: Exception) -> str:
    message = str(exc).lower()

    if "quota" in message or "billing" in message:
        return (
            "The model provider quota or billing limit was reached. "
            "Check the selected model provider account or choose another model."
        )
    if "rate limit" in message or "ratelimit" in message or "429" in message:
        return (
            "The model provider rate limit was reached. "
            "Try again shortly or choose another model."
        )
    if (
        "api key" in message
        or "unauthorized" in message
        or "authentication" in message
        or "permission" in message
    ):
        return (
            "The model provider rejected the configured credentials. "
            "Check the model API key and permissions."
        )
    if (
        "context length" in message
        or "maximum context" in message
        or "too many tokens" in message
        or "token limit" in message
    ):
        return (
            "The request was too large for the selected model context window. "
            "Try a narrower question or choose a model with a larger context window."
        )
    if "timeout" in message or "timed out" in message:
        return (
            "The model provider request timed out. "
            "Try again or choose another model."
        )
    if (
        "connection error" in message
        or "internalservererror" in message
        or "internal server error" in message
        or "server error" in message
        or "unavailable" in message
    ):
        return (
            "The model provider request failed with a connection or server error. "
            "Try again shortly or choose another model."
        )

    return "The model provider failed while generating a response."


def _is_retryable_provider_error(exc: Exception) -> bool:
    message = str(exc).lower()

    if (
        "quota" in message
        or "billing" in message
        or "api key" in message
        or "unauthorized" in message
        or "authentication" in message
        or "permission" in message
        or "context length" in message
        or "maximum context" in message
        or "too many tokens" in message
        or "token limit" in message
    ):
        return False

    return any(
        token in message
        for token in (
            "rate limit",
            "ratelimit",
            "429",
            "timeout",
            "timed out",
            "connection error",
            "temporarily",
            "overloaded",
            "server error",
            "unavailable",
        )
    )
