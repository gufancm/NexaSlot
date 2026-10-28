"""Evaluate the V3 booking parser against the frozen fixture set.

The default Mock provider is a deterministic contract baseline, not a claim
about real LLM accuracy. Use ``--provider openai`` only with a configured key
when you intentionally want to measure a real model.
"""

import argparse
import json
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app.ai.client import (
    LLMUnavailableError,
    MockLLMClient,
    OpenAICompatibleConfig,
    OpenAICompatibleLLMClient,
)
from app.ai.schemas import BookingExtraction
from app.core.config import settings

FIXTURES = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "ai_booking_cases.json"
)


def _normalized(field: str, value: Any) -> Any:
    if field == "date":
        return value.isoformat() if value is not None else None
    if field in {"time_window_start", "time_window_end"}:
        return value.strftime("%H:%M") if value is not None else None
    return value


def _build_client(provider: str):
    if provider == "mock":
        return MockLLMClient()
    if not settings.LLM_API_KEY:
        raise SystemExit("LLM_API_KEY is required for --provider openai")
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


def evaluate(provider: str) -> dict[str, Any]:
    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))
    client = _build_client(provider)
    field_total = 0
    field_matches = 0
    intent_matches = 0
    pydantic_valid = 0
    latencies: list[float] = []
    failures: list[dict[str, Any]] = []

    for case in cases:
        reference_now = datetime.fromisoformat(case["reference_now"])
        started = time.perf_counter()
        try:
            extraction = client.extract(
                case["message"],
                reference_now=reference_now,
                timezone="Asia/Shanghai",
            )
        except LLMUnavailableError:
            failures.append({"id": case["id"], "error": "LLM unavailable"})
            field_total += len(case["expect"])
            continue
        latencies.append((time.perf_counter() - started) * 1000)

        try:
            BookingExtraction.model_validate(extraction.model_dump())
            pydantic_valid += 1
        except ValueError:
            failures.append({"id": case["id"], "error": "invalid extraction model"})

        expected_intent = case["expect"].get("is_booking_request")
        if (
            expected_intent is not None
            and extraction.is_booking_request == expected_intent
        ):
            intent_matches += 1
        for field, expected in case["expect"].items():
            field_total += 1
            actual = _normalized(field, getattr(extraction, field))
            if actual == expected:
                field_matches += 1
            else:
                failures.append(
                    {
                        "id": case["id"],
                        "field": field,
                        "expected": expected,
                        "actual": actual,
                    }
                )

    return {
        "provider": provider,
        "cases": len(cases),
        "intent_accuracy": round(intent_matches / len(cases), 4),
        "field_accuracy": round(field_matches / max(field_total, 1), 4),
        "pydantic_valid_rate": round(pydantic_valid / len(cases), 4),
        "avg_latency_ms": round(statistics.mean(latencies), 3) if latencies else None,
        "p95_latency_ms": round(statistics.quantiles(latencies, n=20)[-1], 3)
        if len(latencies) >= 20
        else None,
        "field_checks": field_total,
        "failures": failures[:20],
        "note": (
            "Mock 结果是确定性契约基线，不代表真实 LLM 准确率；"
            "真实模型需单独配置 Key 后手动评测。"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("mock", "openai"), default="mock")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    report = evaluate(args.provider)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
