#!/usr/bin/env python3
"""Smoke tests for token_receipt.py visual and pricing behavior."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "token_receipt.py"


def run_case(*args: str) -> str:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.rstrip("\n")


def assert_receipt(text: str, width: int, must_contain: list[str]) -> None:
    lines = text.splitlines()
    assert lines, "empty receipt"
    for line in lines:
        assert len(line) <= width, f"line too wide ({len(line)}>{width}): {line!r}"
        for char in line:
            assert ord(char) <= 127 or char == "█", f"unsupported non-ascii char in {line!r}"
    for needle in must_contain:
        assert needle in text, f"missing {needle!r}"
    assert "||" in text, "barcode-like bars missing"
    assert "ITEM" in text and "TOKENS" in text, "receipt columns missing"
    assert "TOTAL" in text, "total line missing"


def main() -> int:
    codex = run_case(
        "--provider", "openai",
        "--agent-tool", "codex",
        "--model", "gpt-5.4",
        "--input-tokens", "82149",
        "--cached-input-tokens", "52608",
        "--output-tokens", "541",
        "--reasoning-output-tokens", "86",
        "--context-window", "258400",
        "--width", "48",
    )
    assert_receipt(codex, 48, ["CODEX", "THANK YOU FOR CODING WITH", "CONTEXT USED", "USD ESTIMATE", "$"])
    assert "DATA: SNAPSHOT" not in codex
    assert "Reasoning Tokens" not in codex

    claude = run_case(
        "--provider", "anthropic",
        "--agent-tool", "claude-code",
        "--model", "claude-sonnet-4.5",
        "--input-tokens", "12487",
        "--cached-input-tokens", "8742",
        "--cache-write-tokens", "1024",
        "--output-tokens", "3215",
        "--width", "48",
    )
    assert_receipt(claude, 48, ["████", "CLAUDE", "CODE", "Cache Write Tokens", "USD ESTIMATE"])

    unknown = run_case(
        "--provider", "openai",
        "--agent-tool", "codex",
        "--model", "mystery-model",
        "--input-tokens", "1000",
        "--output-tokens", "500",
        "--width", "42",
    )
    assert_receipt(unknown, 42, ["PRICE", "UNMAPPED"])

    split_brand_and_model = run_case(
        "--provider", "openai",
        "--agent-tool", "claude-code",
        "--model", "gpt-5.4",
        "--input-tokens", "1000",
        "--output-tokens", "500",
        "--width", "48",
    )
    assert_receipt(split_brand_and_model, 48, ["████", "THANK YOU FOR CODING WITH CHATGPT"])

    fields = run_case(
        "--provider", "openai",
        "--agent-tool", "codex",
        "--model", "gpt-5.4",
        "--input-tokens", "1000",
        "--output-tokens", "500",
        "--show-fields",
    )
    assert "token_usage_fields_available" in fields
    assert "cache_write_tokens" in fields

    print("token-receipt validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
