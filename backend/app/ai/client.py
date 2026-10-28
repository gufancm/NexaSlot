"""LLM client boundary: mock by default, OpenAI-compatible when configured."""

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import httpx

from app.ai.mock import parse_booking_message
from app.ai.prompts import EXTRACTION_SCHEMA, build_messages
from app.ai.schemas import BookingExtraction
from app.core.config import settings

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class LLMUnavailableError(Exception):
    """Provider is disabled, misconfigured or temporarily unusable."""


class LLMClient(Protocol):
    def extract(
        self, message: str, *, reference_now: datetime, timezone: str
    ) -> BookingExtraction: ...


class MockLLMClient:
    """Deterministic local parser; follows the same contract as a provider."""

    def extract(
        self, message: str, *, reference_now: datetime, timezone: str
    ) -> BookingExtraction:
        return parse_booking_message(
            message, reference_now=reference_now, timezone=timezone
        )


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float
    max_output_tokens: int
    max_retries: int


class OpenAICompatibleLLMClient:
    def __init__(self, config: OpenAICompatibleConfig) -> None:
        self.config = config
        self.url = config.base_url.rstrip("/") + "/chat/completions"

    def extract(
        self, message: str, *, reference_now: datetime, timezone: str
    ) -> BookingExtraction:
        messages = build_messages(
            message, reference_now=reference_now, timezone=timezone
        )
        attempts = max(1, self.config.max_retries + 1)
        attempt = 0
        use_json_schema = True
        while attempt < attempts:
            payload: dict[str, Any] = {
                "model": self.config.model,
                "messages": messages,
                "temperature": 0,
                "max_tokens": self.config.max_output_tokens,
            }
            if use_json_schema:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "booking_extraction",
                        "strict": True,
                        "schema": EXTRACTION_SCHEMA,
                    },
                }
            else:
                payload["response_format"] = {"type": "json_object"}

            started = time.monotonic()
            try:
                response = httpx.post(
                    self.url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.config.api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=self.config.timeout_seconds,
                )
            except httpx.HTTPError:
                logger.warning("llm request failed: category=transport")
                attempt += 1
                continue

            if response.status_code == 400 and use_json_schema:
                # Some compatible providers do not implement json_schema.
                use_json_schema = False
                continue
            if response.status_code in RETRYABLE_STATUS:
                logger.warning(
                    "llm request failed: category=provider_retryable status=%s",
                    response.status_code,
                )
                attempt += 1
                if attempt < attempts:
                    time.sleep(0.2 * attempt)
                continue
            if response.status_code >= 400:
                logger.warning(
                    "llm request failed: category=provider_rejected status=%s",
                    response.status_code,
                )
                raise LLMUnavailableError("LLM provider rejected the request")

            try:
                data = response.json()
                extraction = BookingExtraction.model_validate(
                    _extract_json_payload(data)
                )
            except KeyError, IndexError, TypeError, ValueError:
                logger.warning("llm request failed: category=invalid_response")
                attempt += 1
                if attempt < attempts:
                    time.sleep(0.2 * attempt)
                continue

            usage = data.get("usage") or {}
            logger.info(
                "llm extraction ok provider=openai latency_ms=%s prompt_tokens=%s completion_tokens=%s",
                int((time.monotonic() - started) * 1000),
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
            )
            return extraction

        raise LLMUnavailableError("LLM provider is unavailable")


def _extract_json_payload(data: dict[str, Any]) -> dict[str, Any]:
    content = data["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    if not isinstance(content, str) or not content.strip():
        raise ValueError("empty LLM content")
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("LLM response must be a JSON object")
    return parsed


def get_llm_client() -> LLMClient | None:
    if not settings.AI_ENABLED:
        return None
    if settings.LLM_PROVIDER == "mock":
        return MockLLMClient()
    if not settings.LLM_API_KEY:
        return None
    return OpenAICompatibleLLMClient(
        OpenAICompatibleConfig(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            model=settings.LLM_MODEL,
            timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
            max_output_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
            max_retries=settings.LLM_MAX_RETRIES,
        )
    )
