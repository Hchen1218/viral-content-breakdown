#!/usr/bin/env python3
"""Smoke tests for token_receipt.py visual and pricing behavior."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "token_receipt.py"
PIXEL_CHARS = {"█", "░", "▒", "▓", "▐", "▛", "▜", "▌", "▘", "▝", "¥"}


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
            assert ord(char) <= 127 or char in PIXEL_CHARS, f"unsupported non-ascii char in {line!r}"
    for needle in must_contain:
        assert needle in text, f"missing {needle!r}"
    assert "||" in text, "barcode-like bars missing"
    assert "ITEM" in text and "TOKENS" in text, "receipt columns missing"
    assert "TOTAL" in text, "total line missing"


def assert_logo_label_aligned(text: str, label: str, max_delta: float = 0.5) -> None:
    top: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            break
        top.append(line)
    label_index = next((index for index, line in enumerate(top) if label in line), -1)
    assert label_index > 0, f"logo label {label!r} missing from top block"
    logo_lines = top[:label_index]
    starts: list[int] = []
    ends: list[int] = []
    for line in logo_lines:
        filled = [index for index, char in enumerate(line) if char != " "]
        if filled:
            starts.append(min(filled))
            ends.append(max(filled) + 1)
    assert starts and ends, "logo has no visible pixels"
    label_start = top[label_index].index(label)
    label_end = label_start + len(label)
    logo_center = (min(starts) + max(ends)) / 2
    label_center = (label_start + label_end) / 2
    delta = abs(label_center - logo_center)
    assert delta <= max_delta, f"{label} not centered under logo: delta={delta:.1f}"


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
    assert_logo_label_aligned(codex, "CODEX")
    assert "DATA: SNAPSHOT" not in codex
    assert "Reasoning Tokens" in codex

    claude = run_case(
        "--provider", "anthropic",
        "--agent-tool", "claude-code",
        "--model", "claude-sonnet-4.5",
        "--input-tokens", "12487",
        "--cached-input-tokens", "8742",
        "--cache-write-tokens", "1024",
        "--output-tokens", "3215",
        "--reasoning-output-tokens", "128",
        "--width", "48",
    )
    assert_receipt(claude, 48, ["████", "CLAUDE", "CODE", "Reasoning Tokens", "Cache Write Tokens", "USD ESTIMATE"])
    assert_logo_label_aligned(claude, "CLAUDE CODE")

    trae = run_case(
        "--provider", "openai",
        "--agent-tool", "trae",
        "--model", "gpt-5.4",
        "--input-tokens", "12487",
        "--cached-input-tokens", "8742",
        "--output-tokens", "3215",
        "--width", "48",
    )
    assert_receipt(trae, 48, ["TRAE", "THANK YOU FOR CODING WITH ChatGPT", "USD ESTIMATE"])
    assert_logo_label_aligned(trae, "TRAE")

    qwen = run_case(
        "--provider", "alibaba",
        "--agent-tool", "trae",
        "--model", "qwen3.6-plus",
        "--input-tokens", "1000000",
        "--output-tokens", "1000000",
        "--width", "48",
    )
    assert_receipt(qwen, 48, ["THANK YOU FOR CODING WITH Qwen", "CNY ESTIMATE", "¥14.000000", "RATE NOTE"])

    deepseek = run_case(
        "--provider", "deepseek",
        "--agent-tool", "codex",
        "--model", "deepseek-chat",
        "--input-tokens", "1000000",
        "--cached-input-tokens", "500000",
        "--output-tokens", "1000000",
        "--width", "48",
    )
    assert_receipt(deepseek, 48, ["THANK YOU FOR CODING WITH DeepSeek", "USD ESTIMATE", "$0.364000"])

    glm = run_case(
        "--provider", "bigmodel",
        "--agent-tool", "generic",
        "--model", "glm-5-1",
        "--input-tokens", "1000000",
        "--output-tokens", "1000000",
        "--width", "48",
    )
    assert_receipt(glm, 48, ["THANK YOU FOR CODING WITH GLM", "CNY ESTIMATE", "¥30.000000", "ALIYUN CN"])

    mimo = run_case(
        "--provider", "xiaomi",
        "--agent-tool", "generic",
        "--model", "mimo-v2.5-pro",
        "--input-tokens", "1000000",
        "--output-tokens", "1000000",
        "--width", "48",
    )
    assert_receipt(mimo, 48, ["THANK YOU FOR CODING WITH MiMo", "USD ESTIMATE", "$4.000000", "OPENROUTER"])

    minimax = run_case(
        "--provider", "minimax",
        "--agent-tool", "generic",
        "--model", "minimax-m2.7",
        "--input-tokens", "1000000",
        "--output-tokens", "1000000",
        "--width", "48",
    )
    assert_receipt(minimax, 48, ["THANK YOU FOR CODING WITH MiniMax", "USD ESTIMATE", "$1.500000"])

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
    assert_receipt(split_brand_and_model, 48, ["████", "THANK YOU FOR CODING WITH ChatGPT"])

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
