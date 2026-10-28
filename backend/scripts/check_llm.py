"""One-shot OpenAI-compatible connectivity check.

Usage:
    cd backend
    uv run python scripts/check_llm.py
    uv run python scripts/check_llm.py --message "明天下午3点，8个人，带投影仪，开两小时"

This sends exactly one request and is intended for verifying a real API key
without running the full 40-case evaluation.
"""

import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from app.ai.client import (
    LLMClient,
    LLMUnavailableError,
    MockLLMClient,
    OpenAICompatibleConfig,
    OpenAICompatibleLLMClient,
)
from app.core.config import settings

DEFAULT_MESSAGE = "明天下午3点，8个人，带投影仪，开两个小时"


def _build_client() -> LLMClient:
    if settings.LLM_PROVIDER == "mock":
        return MockLLMClient()
    if not settings.LLM_API_KEY:
        raise SystemExit(
            "LLM_API_KEY is empty. Fill it in the repository root .env and retry."
        )
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    args = parser.parse_args()

    client = _build_client()
    reference_now = datetime.now(ZoneInfo("Asia/Shanghai"))
    print(  # noqa: T201
        f"provider={settings.LLM_PROVIDER} model={settings.LLM_MODEL} "
        f"base_url={settings.LLM_BASE_URL}"
    )
    try:
        extraction = client.extract(
            args.message, reference_now=reference_now, timezone="Asia/Shanghai"
        )
    except LLMUnavailableError as exc:
        raise SystemExit(f"LLM check failed: {exc}") from exc
    print(json.dumps(extraction.model_dump(mode="json"), ensure_ascii=False, indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
