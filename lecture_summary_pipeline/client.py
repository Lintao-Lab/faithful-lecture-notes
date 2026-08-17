from __future__ import annotations

import json
import os
from typing import TypeVar
from urllib.parse import urlparse

from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel, ValidationError


T = TypeVar("T", bound=BaseModel)


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 180.0,
        max_retries: int = 3,
        max_parse_attempts: int = 3,
    ) -> None:
        resolved_api_key = (
            api_key
            or os.getenv("LLM_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )
        if not resolved_api_key:
            raise RuntimeError(
                "Missing API key. Pass --api-key or set one of the environment "
                "variables LLM_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY."
            )

        resolved_base_url = (
            base_url or os.getenv("LLM_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL")
        )
        if not resolved_base_url:
            resolved_base_url = "https://api.deepseek.com"

        self.max_parse_attempts = max_parse_attempts
        self._uses_official_deepseek = _is_official_deepseek_base_url(resolved_base_url)
        self._sync_client = OpenAI(
            api_key=resolved_api_key,
            base_url=resolved_base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )
        self._async_client = AsyncOpenAI(
            api_key=resolved_api_key,
            base_url=resolved_base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    def complete_text(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        enable_thinking: bool = False,
        json_object: bool = False,
        reasoning_effort: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        kwargs = {}
        if enable_thinking:
            kwargs.update(
                _thinking_kwargs(
                    official_deepseek=self._uses_official_deepseek,
                    reasoning_effort=reasoning_effort,
                )
            )
        if json_object:
            kwargs["response_format"] = {"type": "json_object"}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        response = self._sync_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            **kwargs,
        )
        return (response.choices[0].message.content or "").strip()

    async def acomplete_text(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        enable_thinking: bool = False,
        json_object: bool = False,
        reasoning_effort: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        kwargs = {}
        if enable_thinking:
            kwargs.update(
                _thinking_kwargs(
                    official_deepseek=self._uses_official_deepseek,
                    reasoning_effort=reasoning_effort,
                )
            )
        if json_object:
            kwargs["response_format"] = {"type": "json_object"}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        response = await self._async_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            **kwargs,
        )
        return (response.choices[0].message.content or "").strip()

    def complete_json(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        schema_type: type[T],
        enable_thinking: bool = False,
        json_object: bool = False,
        reasoning_effort: str | None = None,
        max_tokens: int | None = None,
    ) -> T:
        last_error: Exception | None = None
        last_raw = ""
        for _ in range(self.max_parse_attempts):
            try:
                raw = self.complete_text(
                    model=model,
                    messages=_json_retry_messages(messages, last_error),
                    temperature=temperature,
                    enable_thinking=enable_thinking,
                    json_object=json_object,
                    reasoning_effort=reasoning_effort,
                    max_tokens=max_tokens,
                )
                last_raw = raw
                return schema_type.model_validate(_coerce_json_payload(raw))
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
        snippet = last_raw[:500].replace("\n", "\\n")
        raise RuntimeError(
            f"Failed to parse structured model output: {last_error}. Raw snippet: {snippet}"
        ) from last_error


def _thinking_kwargs(
    *, official_deepseek: bool, reasoning_effort: str | None = None
) -> dict:
    if official_deepseek:
        return {
            "extra_body": {
                "thinking": {
                    "type": "enabled",
                    "reasoning_effort": reasoning_effort or "high",
                }
            },
        }
    return {"extra_body": {"enable_thinking": True}}


def _is_official_deepseek_base_url(base_url: str) -> bool:
    return (urlparse(base_url).hostname or "").lower() == "api.deepseek.com"


def _coerce_json_payload(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return _extract_first_json_object(text)


def _extract_first_json_object(text: str) -> dict:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise json.JSONDecodeError("No valid JSON object found in model output", text, 0)


def _json_retry_messages(
    messages: list[dict[str, str]],
    last_error: Exception | None,
) -> list[dict[str, str]]:
    if not last_error:
        return messages

    return [
        *messages,
        {
            "role": "user",
            "content": (
                "Your previous reply was not valid JSON for the required schema.\n"
                f"Validation error: {last_error}\n"
                "Return exactly one valid JSON object only.\n"
                "Do not use markdown fences.\n"
                "Do not include commentary before or after the JSON.\n"
                "If you need to revise the structure, output the corrected JSON object directly."
            ),
        },
    ]
