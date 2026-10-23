from __future__ import annotations

import argparse
from pathlib import Path

from .client import OpenAICompatibleClient
from .pipeline import LectureSummaryPipeline, PipelineConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate proportionate, source-faithful lecture study notes."
    )
    parser.add_argument(
        "--transcript",
        required=True,
        help="Lecture transcript: .md/.markdown/.txt, or .pdf/.docx (converted automatically)",
    )
    parser.add_argument(
        "--slides",
        help="Lecture slides: .md/.markdown/.txt, or .pdf/.pptx/.docx (converted automatically)",
    )
    parser.add_argument(
        "--output-dir", required=True, help="New directory for this run"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume only when the existing run manifest exactly matches",
    )
    parser.add_argument(
        "--api-key",
        help="OpenAI-compatible API key; env LLM_API_KEY also honoured",
    )
    parser.add_argument(
        "--base-url",
        help="OpenAI-compatible endpoint; env LLM_BASE_URL also honoured",
    )
    parser.add_argument("--architect-model", default="deepseek-v4-pro")
    parser.add_argument("--assembler-model", default="deepseek-v4-pro")
    parser.add_argument("--architect-temperature", type=float, default=0.5)
    parser.add_argument("--assembler-temperature", type=float, default=0.2)
    parser.add_argument(
        "--architect-reasoning-effort", choices=["high", "max"], default="max"
    )
    parser.add_argument(
        "--assembler-reasoning-effort", choices=["high", "max"], default="max"
    )
    parser.add_argument("--architect-max-tokens", type=int, default=65536)
    parser.add_argument("--assembler-max-tokens", type=int, default=65536)
    parser.add_argument("--parallelism", type=int, default=50)
    parser.add_argument(
        "--assembler-prime-delay-seconds",
        type=float,
        default=20.0,
        help=(
            "Cache-priming stagger for the Assembler fan-out: the first section "
            "is dispatched alone, then the remaining sections after this delay "
            "so sibling calls hit the provider's prefix cache; 0 dispatches "
            "everything at once"
        ),
    )
    parser.add_argument(
        "--max-retries", type=int, default=3, help="SDK and JSON-parse retries"
    )
    parser.add_argument("--node-retry-attempts", type=int, default=10)
    parser.add_argument("--node-retry-delay-seconds", type=float, default=3.0)
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--disable-architect-thinking", action="store_true")
    parser.add_argument("--disable-assembler-thinking", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = PipelineConfig(
        architect_model=args.architect_model,
        assembler_model=args.assembler_model,
        architect_temperature=args.architect_temperature,
        assembler_temperature=args.assembler_temperature,
        architect_reasoning_effort=args.architect_reasoning_effort,
        assembler_reasoning_effort=args.assembler_reasoning_effort,
        architect_max_tokens=args.architect_max_tokens,
        assembler_max_tokens=args.assembler_max_tokens,
        parallelism=args.parallelism,
        node_retry_attempts=args.node_retry_attempts,
        node_retry_delay_seconds=args.node_retry_delay_seconds,
        assembler_prime_delay_seconds=args.assembler_prime_delay_seconds,
        architect_enable_thinking=not args.disable_architect_thinking,
        assembler_enable_thinking=not args.disable_assembler_thinking,
        resume=args.resume,
    )
    client = OpenAICompatibleClient(
        api_key=args.api_key,
        base_url=args.base_url,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        max_parse_attempts=args.max_retries,
    )
    result = LectureSummaryPipeline(client=client, config=config).run(
        transcript_path=args.transcript,
        slides_path=args.slides,
        output_dir=args.output_dir,
    )

    output_dir = Path(result.output_dir)
    print(f"Final notes: {output_dir / '04_final' / 'lecture_summary.md'}")
    print(f"Audit report: {output_dir / '05_audit.json'}")
    print(f"Audit passed: {result.audit.passed}")
    if not result.audit.passed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
