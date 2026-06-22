import json
import logging

from typing import Any, Literal, TypeVar
from pydantic import BaseModel
from langchain_core.messages import HumanMessage

from app.agent.schemas import PromptMessage
from app.common.logging import env_flag
from app.utils import extract_json_object

logger = logging.getLogger(__name__)

StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)
StructuredOutputMethod = Literal["json_schema", "function_calling", "json_mode"]
STRUCTURED_OUTPUT_METHODS: tuple[StructuredOutputMethod, ...] = (
    "json_schema",
    "function_calling",
    "json_mode",
)


class StructuredOutputMixin:
    async def structured(
        self,
        messages: list[PromptMessage],
        schema: type[BaseModel],
        operation: str | None = None,
    ) -> dict[str, Any]:
        result = await self.structured_model(messages, schema, operation=operation)
        return result.model_dump(mode="json")

    async def structured_model(
        self,
        messages: list[PromptMessage],
        schema: type[StructuredModelT],
        operation: str | None = None,
    ) -> StructuredModelT:
        if self._llm is None:
            raise RuntimeError("No chat model is configured for this thread.")

        converted = self._to_langchain_messages(messages)
        op_name = operation or schema.__name__

        self._log_prompt("structured", op_name, messages)

        last_exc: Exception | None = None

        for method in STRUCTURED_OUTPUT_METHODS:
            trace = self._start_trace(
                "structured",
                op_name,
                messages,
                schema=schema.__name__,
                method=method,
            )

            try:
                result = await self._structured_with(
                    schema,
                    converted,
                    trace=trace,
                    method=method,
                )

                self._finish_trace(trace, "succeeded")
                logger.info(
                    f"LLM structured output succeeded operation={op_name} "
                    f"schema={schema.__name__} method={method}"
                )
                return result
            except Exception as exc:
                last_exc = exc
                self._finish_trace(trace, "failed", exc)
                logger.warning(
                    f"LLM structured output failed operation={op_name} "
                    f"schema={schema.__name__} method={method} "
                    f"error={self._exception_summary(exc)}",
                    exc_info=env_flag("AGENT_DEBUG"),
                )

                if _should_abort_structured_fallback(exc):
                    raise self._agent_error_from_exception(
                        exc,
                        operation=op_name,
                    ) from exc

        try:
            fallback_messages = _with_json_schema_instruction(messages, schema)
            content = await self.text(
                fallback_messages,
                operation=f"{op_name}:raw_json",
            )
            payload = extract_json_object(content)
            result = schema.model_validate(payload)

            logger.info(
                f"LLM raw JSON fallback succeeded operation={op_name} "
                f"schema={schema.__name__}"
            )
            return result
        except Exception as json_exc:
            if self._is_agent_error(json_exc):
                raise

            previous_error = self._exception_summary(last_exc) if last_exc else "none"
            logger.warning(
                f"LLM raw JSON fallback failed operation={op_name} "
                f"schema={schema.__name__} "
                f"previous_error={previous_error} "
                f"error={self._exception_summary(json_exc)}",
                exc_info=env_flag("AGENT_DEBUG"),
            )
            raise self._structured_parse_error(
                "The model returned a response that Settra could not parse into "
                "the expected structure. Try again or choose another model.",
                operation=op_name,
                original_summary=self._exception_summary(json_exc),
            ) from json_exc

    async def _structured_with(
        self,
        schema: type[StructuredModelT],
        messages: list,
        trace: dict[str, Any] | None = None,
        method: StructuredOutputMethod = "json_schema",
        **kwargs: Any,
    ) -> StructuredModelT:
        if method == "json_schema":
            kwargs.setdefault("strict", True)

        effective_messages = messages

        if method == "json_mode":
            # JSON mode constrains the provider to JSON, while Pydantic
            # still owns the schema contract and validation.
            effective_messages = _with_langchain_json_schema_instruction(
                messages,
                schema,
            )

        try:
            structured_llm = self._llm.with_structured_output(
                schema,
                include_raw=True,
                method=method,
                **kwargs,
            )
            include_raw = True
        except TypeError:
            structured_llm = self._llm.with_structured_output(
                schema,
                method=method,
                **kwargs,
            )
            include_raw = False

        if trace is not None:
            trace["include_raw"] = include_raw
            trace["json_schema_prompt_instruction"] = method == "json_mode"

        operation = (
            str(trace.get("operation"))
            if isinstance(trace, dict) and trace.get("operation")
            else schema.__name__
        )
        response = await self._ainvoke_with_visible_retries(
            lambda: structured_llm.ainvoke(effective_messages),
            operation=operation,
            call_type="structured",
            trace=trace,
            method=method,
        )

        if (
            isinstance(response, dict)
            and "raw" in response
            and ("parsed" in response or "parsing_error" in response)
        ):
            self._record_response_metadata(trace, response.get("raw"))

            if response.get("parsing_error"):
                raise response["parsing_error"]

            response = response.get("parsed")

        return _coerce_structured_model(schema, response)


def _with_json_schema_instruction(
    messages: list[PromptMessage],
    schema: type[BaseModel],
) -> list[PromptMessage]:
    return [
        *messages,
        {
            "role": "user",
            "content": _json_schema_instruction(schema),
        },
    ]


def _with_langchain_json_schema_instruction(
    messages: list,
    schema: type[BaseModel],
) -> list:
    return [
        *messages,
        HumanMessage(content=_json_schema_instruction(schema)),
    ]


def _json_schema_instruction(schema: type[BaseModel]) -> str:
    json_schema = json.dumps(
        schema.model_json_schema(),
        indent=2,
        sort_keys=True,
    )
    return (
        "Return only one valid JSON object that conforms to this Pydantic JSON "
        "schema. Use the JSON property names exactly. Do not include markdown "
        "fences, commentary, or extra keys.\n\n"
        f"{json_schema}"
    )


def _coerce_structured_model(
    schema: type[StructuredModelT],
    response: Any,
) -> StructuredModelT:
    if isinstance(response, schema):
        return response

    if isinstance(response, BaseModel):
        return schema.model_validate(response.model_dump(mode="json"))

    if isinstance(response, dict):
        return schema.model_validate(response)

    raise RuntimeError("Structured model response was not a dict or Pydantic model.")


def _should_abort_structured_fallback(exc: Exception) -> bool:
    message = str(exc).lower()

    return any(
        token in message
        for token in (
            "quota",
            "billing",
            "rate limit",
            "ratelimit",
            "429",
            "api key",
            "unauthorized",
            "authentication",
            "permission",
            "context length",
            "maximum context",
            "too many tokens",
            "token limit",
            "timeout",
            "timed out",
            "connection error",
            "internalservererror",
            "internal server error",
            "server error",
            "unavailable",
        )
    )
