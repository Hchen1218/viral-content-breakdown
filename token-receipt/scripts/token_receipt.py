#!/usr/bin/env python3
"""Render AI token usage as a fixed-width ASCII receipt."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


ALLOWED_WIDTHS = (42, 48, 56, 64)
SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PRICING = SKILL_DIR / "references" / "pricing.json"
DEFAULT_FOOTER = "auto"
PIXEL_CHARS = {"█", "░", "▒", "▓", "▐", "▛", "▜", "▌", "▘", "▝", "¥"}
COMMON_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "total_tokens",
)
OPTIONAL_TOKEN_FIELDS = (
    "reasoning_output_tokens",
    "cache_write_tokens",
)
RECEIPT_TOKEN_FIELDS = COMMON_TOKEN_FIELDS + OPTIONAL_TOKEN_FIELDS


@dataclass
class UsageSnapshot:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0
    context_window: Optional[int] = None
    provider: str = "unknown"
    model: str = "UNRECORDED"
    source: str = "manual"
    session_id: str = "manual"
    timestamp: Optional[str] = None
    scope: str = "latest-turn"
    available_fields: Tuple[str, ...] = ()


@dataclass
class PriceEstimate:
    status: str
    amount: Optional[float]
    model: str = "UNMAPPED"
    currency: str = "USD"
    source_url: str = ""
    source_checked_at: str = ""
    rate_note: str = ""


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def fmt_int(value: Optional[int]) -> str:
    return f"{int(value or 0):,}"


def truncate(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    if max_len <= 3:
        return value[:max_len]
    return value[: max_len - 3] + "..."


def as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_iso(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        text = value.replace("Z", "+00:00")
        return dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def display_time(value: Optional[str]) -> str:
    parsed = parse_iso(value)
    if not parsed:
        return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    local = parsed.astimezone()
    return local.strftime("%Y-%m-%d %H:%M:%S")


def iter_session_files() -> Iterable[Path]:
    home = Path.home()
    roots = [
        home / ".codex" / "sessions",
        home / ".codex" / "archived_sessions",
    ]
    for root in roots:
        if not root.exists():
            continue
        yield from root.rglob("*.jsonl")


def newest_session_file() -> Optional[Path]:
    files = list(iter_session_files())
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def maybe_model_from_meta(payload: Dict[str, Any]) -> Optional[str]:
    for key in ("model", "model_id", "model_name", "model_slug"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def model_from_env() -> Optional[str]:
    for key in ("CODEX_MODEL", "OPENAI_MODEL", "ANTHROPIC_MODEL", "MODEL"):
        value = os.environ.get(key)
        if value:
            return value.strip()
    return None


def load_snapshot_from_session(path: Path, scope: str, model_override: Optional[str], provider_override: Optional[str]) -> UsageSnapshot:
    session_meta: Dict[str, Any] = {}
    token_event: Optional[Dict[str, Any]] = None
    token_timestamp: Optional[str] = None

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            item_type = item.get("type")
            payload = item.get("payload") or {}
            if item_type == "session_meta" and isinstance(payload, dict):
                session_meta = payload
            if item_type == "event_msg" and isinstance(payload, dict) and payload.get("type") == "token_count":
                token_event = payload
                token_timestamp = item.get("timestamp")

    if not token_event:
        raise SystemExit(f"No token_count event found in {path}")

    info = token_event.get("info") or {}
    usage_key = "total_token_usage" if scope == "session" else "last_token_usage"
    usage = info.get(usage_key) or {}
    available_fields = tuple(sorted(k for k in usage.keys() if isinstance(k, str)))
    provider = provider_override or session_meta.get("model_provider") or "unknown"
    model = model_override or maybe_model_from_meta(session_meta) or model_from_env() or "UNRECORDED"
    session_id = str(session_meta.get("id") or path.stem)

    return UsageSnapshot(
        input_tokens=as_int(usage.get("input_tokens")),
        cached_input_tokens=as_int(usage.get("cached_input_tokens")),
        output_tokens=as_int(usage.get("output_tokens")),
        reasoning_output_tokens=as_int(usage.get("reasoning_output_tokens")),
        total_tokens=as_int(usage.get("total_tokens")),
        context_window=as_int(info.get("model_context_window")) or None,
        provider=str(provider),
        model=str(model),
        source=str(path),
        session_id=session_id,
        timestamp=token_timestamp or session_meta.get("timestamp"),
        scope=scope,
        available_fields=available_fields,
    )


def load_manual_snapshot(args: argparse.Namespace) -> UsageSnapshot:
    total = args.total_tokens
    if total is None:
        total = as_int(args.input_tokens) + as_int(args.output_tokens)
    available_fields = []
    if args.input_tokens is not None:
        available_fields.append("input_tokens")
    if args.output_tokens is not None:
        available_fields.append("output_tokens")
    if args.cached_input_tokens is not None:
        available_fields.append("cached_input_tokens")
    if args.cache_write_tokens is not None:
        available_fields.append("cache_write_tokens")
    if args.reasoning_output_tokens is not None:
        available_fields.append("reasoning_output_tokens")
    if total is not None:
        available_fields.append("total_tokens")

    return UsageSnapshot(
        input_tokens=as_int(args.input_tokens),
        cached_input_tokens=as_int(args.cached_input_tokens),
        cache_write_tokens=as_int(args.cache_write_tokens),
        output_tokens=as_int(args.output_tokens),
        reasoning_output_tokens=as_int(args.reasoning_output_tokens),
        total_tokens=as_int(total),
        context_window=as_int(args.context_window) or None,
        provider=args.provider or "unknown",
        model=args.model or model_from_env() or "UNRECORDED",
        source="manual",
        session_id=args.receipt_seed or "manual",
        timestamp=None,
        scope=args.scope,
        available_fields=tuple(sorted(set(available_fields))),
    )


def load_pricing(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def find_price(pricing: Dict[str, Any], provider: str, model: str) -> Optional[Dict[str, Any]]:
    if not model or model == "UNRECORDED":
        return None
    provider_key = normalize(provider)
    model_key = normalize(model)
    for entry in pricing.get("models", []):
        entry_provider = normalize(str(entry.get("provider", "")))
        aliases = [entry.get("model", "")] + list(entry.get("aliases", []))
        alias_keys = {normalize(str(alias)) for alias in aliases}
        provider_matches = not provider_key or provider_key == "unknown" or provider_key == entry_provider
        if provider_matches and model_key in alias_keys:
            return entry
    for entry in pricing.get("models", []):
        aliases = [entry.get("model", "")] + list(entry.get("aliases", []))
        if model_key in {normalize(str(alias)) for alias in aliases}:
            return entry
    return None


def estimate_cost(snapshot: UsageSnapshot, pricing_path: Path) -> PriceEstimate:
    pricing = load_pricing(pricing_path)
    entry = find_price(pricing, snapshot.provider, snapshot.model)
    if not entry:
        return PriceEstimate(status="UNMAPPED", amount=None)

    cached = min(snapshot.cached_input_tokens, snapshot.input_tokens)
    cache_write = min(snapshot.cache_write_tokens, max(snapshot.input_tokens - cached, 0))
    uncached = max(snapshot.input_tokens - cached - cache_write, 0)

    input_rate = float(entry.get("input_per_million", 0.0))
    cached_rate = float(entry.get("cached_input_per_million", input_rate))
    cache_write_rate = float(entry.get("cache_write_5m_per_million", input_rate))
    output_rate = float(entry.get("output_per_million", 0.0))

    amount = (
        uncached * input_rate
        + cached * cached_rate
        + cache_write * cache_write_rate
        + snapshot.output_tokens * output_rate
    ) / 1_000_000

    return PriceEstimate(
        status="ESTIMATE",
        amount=amount,
        model=str(entry.get("model", snapshot.model)),
        currency=str(entry.get("currency", pricing.get("currency", "USD"))).upper(),
        source_url=str(entry.get("source_url", "")),
        source_checked_at=str(entry.get("source_checked_at", "")),
        rate_note=str(entry.get("rate_note", "")),
    )


class Receipt:
    def __init__(self, width: int) -> None:
        if width not in ALLOWED_WIDTHS:
            raise SystemExit(f"--width must be one of {ALLOWED_WIDTHS}")
        self.width = width
        self.lines: List[str] = []

    def add(self, text: str = "") -> None:
        text = truncate(text, self.width)
        self.lines.append(text)

    def center(self, text: str = "") -> None:
        self.add(truncate(text, self.width).center(self.width).rstrip())

    def rule(self, char: str = "-") -> None:
        self.add(char * self.width)

    def kv(self, left: str, right: str) -> None:
        right = str(right)
        max_left = max(1, self.width - len(right) - 1)
        left = truncate(left, max_left)
        self.add(left + " " * max(1, self.width - len(left) - len(right)) + right)

    def blank(self) -> None:
        self.add("")

    def text(self) -> str:
        for line in self.lines:
            if len(line) > self.width:
                raise AssertionError(f"line exceeds width: {line!r}")
            for char in line:
                if ord(char) > 127 and char not in PIXEL_CHARS:
                    raise AssertionError(f"unsupported non-ascii character: {line!r}")
        return "\n".join(self.lines)


def receipt_id(snapshot: UsageSnapshot, provider: str) -> str:
    stamp = parse_iso(snapshot.timestamp)
    if stamp:
        date_part = stamp.strftime("%Y%m%d_%H%M%S")
    else:
        date_part = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    seed = f"{snapshot.session_id}:{snapshot.provider}:{snapshot.model}:{snapshot.total_tokens}:{snapshot.source}:{date_part}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:6].upper()
    prefix = "CC" if normalize(provider) == "anthropic" else "CX" if normalize(provider) == "openai" else "AI"
    return f"{prefix}_{date_part}_{digest}"


def barcode(seed: str, width: int) -> str:
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    patterns = ["|", "||", "| ", " ||", "|||", " |"]
    raw = "".join(patterns[int(char, 16) % len(patterns)] for char in digest)
    target = min(width - 8, max(24, width - 16))
    raw = raw[:target]
    return raw.center(width).rstrip()


def auto_brand(provider: str, source: str, explicit: str) -> str:
    if explicit != "auto":
        return explicit
    provider_key = normalize(provider)
    source_key = normalize(source)
    if provider_key == "trae" or "trae" in source_key:
        return "trae"
    if provider_key == "openai" or "codex" in source_key:
        return "codex"
    if provider_key == "anthropic" or "claude" in source_key:
        return "claude-code"
    return "generic"


def add_centered_block(receipt: Receipt, lines: List[str]) -> None:
    nonempty = [line for line in lines if line.strip()]
    shared_indent = min((len(line) - len(line.lstrip(" ")) for line in nonempty), default=0)
    normalized = [line[shared_indent:] for line in lines]
    block_width = max(len(line.rstrip()) for line in normalized)
    left_pad = max((receipt.width - block_width) // 2, 0)
    for line in normalized:
        receipt.add(" " * left_pad + line.rstrip())


def add_logo(receipt: Receipt, agent_tool: str) -> None:
    if agent_tool == "codex":
        add_centered_block(
            receipt,
            [
                "      █████",
                "    █    ██   ███",
                "  ███ ██    ██   █",
                "██ ██ ██████   ███",
                "█  ██ ██    ███   █",
                "██   ███    █  ██  █",
                "  ███   █████  ██ ██",
                "  █   ██    █  ███",
                "   ███   ██    █",
                "         █████",
            ],
        )
        receipt.center("CODEX")
        return
    if agent_tool == "trae":
        add_centered_block(
            receipt,
            [
                "   ██████████████",
                "███▒▒▒▒▒▒▒▒▒▒▒▒▒▒███",
                "███▒▒██████████▒▒███",
                "███▒▒██▒▒▒█▒▒▒█▒▒███",
                "███▒▒██████████▒▒███",
                "█████▒▒▒▒▒▒▒▒▒▒▒▒███",
                "   █████████████",
            ],
        )
        receipt.center("TRAE")
        return
    if agent_tool == "claude-code":
        add_centered_block(
            receipt,
            [
                "▐▛███▜▌",
                "▜█████▛▘",
                " ▘▘ ▝▝",
            ],
        )
        receipt.center("CLAUDE CODE")
        return
    receipt.center("[ AI CHECKOUT ]")


def product_name(snapshot: UsageSnapshot) -> str:
    model_key = normalize(snapshot.model)
    provider_key = normalize(snapshot.provider)
    if "claude" in model_key:
        return "Claude"
    if "codex" in model_key:
        return "Codex"
    if "gpt" in model_key:
        return "ChatGPT"
    if "gemini" in model_key or provider_key == "google":
        return "Gemini"
    if "deepseek" in model_key or provider_key == "deepseek":
        return "DeepSeek"
    if "kimi" in model_key or provider_key == "moonshot":
        return "Kimi"
    if "glm" in model_key or provider_key in ("zhipu", "bigmodel"):
        return "GLM"
    if "mimo" in model_key or provider_key == "xiaomi":
        return "MiMo"
    if "qwen" in model_key or provider_key in ("qwen", "dashscope"):
        return "Qwen"
    if "minimax" in model_key or provider_key == "minimax":
        return "MiniMax"
    if "trae" in model_key:
        return "Trae"
    if snapshot.model and snapshot.model != "UNRECORDED":
        return truncate(snapshot.model, 16)
    if provider_key == "anthropic":
        return "Claude"
    if provider_key == "openai":
        return "ChatGPT"
    return "AI"


def context_used(snapshot: UsageSnapshot) -> str:
    used = fmt_int(snapshot.input_tokens)
    if snapshot.context_window:
        return f"{used}/{fmt_int(snapshot.context_window)}"
    return used


def auto_footer(snapshot: UsageSnapshot, estimate: PriceEstimate, tone: str, hint: str = "") -> str:
    key = f"{snapshot.provider}:{snapshot.model}:{snapshot.total_tokens}:{hint}:{tone}"
    digest = int(hashlib.sha1(key.encode("utf-8")).hexdigest()[:8], 16)
    model_key = normalize(snapshot.model)
    provider_key = normalize(snapshot.provider)

    snarky = [
        "NO REFUNDS ON REASONING.",
        "CONTEXT WAS HARMED IN THIS CHAT.",
        "YOUR TOKENS HAVE UNIONIZED.",
        "ANOTHER FINE DAY AT THE PROMPT MINES.",
        "WE DEBUGGED THE RECEIPT, TOO.",
    ]
    encouraging = [
        "KEEP BUILDING AMAZING THINGS.",
        "SHIP IT BEFORE THE CACHE COOLS.",
        "GOOD CONTEXT, BETTER OUTPUT.",
        "YOU TURNED TOKENS INTO MOMENTUM.",
        "TINY TOKENS, REAL PROGRESS.",
    ]
    claude_encouraging = [
        "KEEP BUILDING AMAZING THINGS.\nCLAUDE CODE IS HERE TO HELP.",
        "CLAUDE KEPT THE CONTEXT WARM.",
        "PROMPTS IN, MOMENTUM OUT.",
    ]
    dry = [
        "SNAPSHOT ONLY. TAX NOT INCLUDED.",
        "ESTIMATED COST, REAL CONTEXT.",
        "PAID IN TOKENS, PRINTED IN PIXELS.",
        "RECEIPT DOES NOT INCLUDE THIS RECEIPT.",
    ]

    if tone == "snarky":
        pool = snarky
    elif tone == "encouraging":
        pool = encouraging
    elif tone == "dry":
        pool = dry
    elif "claude" in model_key or provider_key == "anthropic":
        pool = snarky + encouraging + claude_encouraging
    elif "gpt" in model_key or provider_key == "openai":
        pool = dry + encouraging
    else:
        pool = snarky + dry + encouraging
    return pool[digest % len(pool)]


def source_has(snapshot: UsageSnapshot, field: str) -> bool:
    return field in snapshot.available_fields


def footer_lines(text: str, width: int) -> List[str]:
    normalized = text.replace("\\n", "\n")
    lines: List[str] = []
    for raw in normalized.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        lines.append(truncate(raw.upper(), width))
    return lines or [""]


def money(amount: Optional[float], currency: str = "USD") -> str:
    if amount is None:
        return "UNMAPPED"
    if 0 < amount < 0.000001:
        return f"<{currency_symbol(currency)}0.000001"
    return f"{currency_symbol(currency)}{amount:.6f}"


def currency_symbol(currency: str) -> str:
    key = currency.upper()
    if key == "USD":
        return "$"
    if key in ("CNY", "RMB"):
        return "¥"
    return f"{key} "


def available_fields_report(snapshot: UsageSnapshot) -> Dict[str, Any]:
    available = sorted(snapshot.available_fields)
    rendered = [field for field in RECEIPT_TOKEN_FIELDS if field in snapshot.available_fields]
    unavailable_common = [field for field in COMMON_TOKEN_FIELDS if field not in snapshot.available_fields]
    available_optional = [field for field in OPTIONAL_TOKEN_FIELDS if field in snapshot.available_fields]
    return {
        "source": snapshot.source,
        "scope": snapshot.scope,
        "provider": snapshot.provider,
        "model": snapshot.model,
        "token_usage_fields_available": available,
        "receipt_fields_common": list(COMMON_TOKEN_FIELDS),
        "receipt_fields_optional_if_available": list(OPTIONAL_TOKEN_FIELDS),
        "receipt_fields_rendered_by_default": rendered,
        "receipt_common_fields_missing_from_source": unavailable_common,
        "receipt_optional_fields_available": available_optional,
        "context_fields_available": ["model_context_window"] if snapshot.context_window else [],
        "metadata_fields_supported": ["session_id", "timestamp", "model_provider", "model"],
        "known_unavailable_in_codex_token_count": [
            "cache_write_tokens unless provided manually or present in another provider log",
            "tool_use_tokens",
            "system_tokens",
        ],
    }


def print_receipt(text: str, stream: bool, delay: float) -> None:
    if not stream:
        print(text)
        return
    for line in text.splitlines():
        print(line, flush=True)
        if delay > 0:
            time.sleep(delay)


def render_receipt(snapshot: UsageSnapshot, estimate: PriceEstimate, width: int, agent_tool: str, footer: str, footer_tone: str, conversation_hint: str) -> str:
    provider = snapshot.provider.upper() if snapshot.provider else "UNKNOWN"
    rid = receipt_id(snapshot, snapshot.provider)
    footer_text = auto_footer(snapshot, estimate, footer_tone, conversation_hint) if footer == "auto" else footer
    receipt = Receipt(width)

    add_logo(receipt, agent_tool)
    receipt.blank()
    receipt.center(f"THANK YOU FOR CODING WITH {product_name(snapshot)}")
    receipt.center(f"RECEIPT #: {rid}")
    receipt.center(f"DATE: {display_time(snapshot.timestamp)}")
    receipt.rule()
    receipt.kv("PROVIDER", provider)
    receipt.kv("MODEL", snapshot.model)
    receipt.kv("CONTEXT USED", context_used(snapshot))
    receipt.rule()
    receipt.kv("ITEM", "TOKENS")
    receipt.rule()
    if source_has(snapshot, "input_tokens"):
        receipt.kv("Input Tokens", fmt_int(snapshot.input_tokens))
    if source_has(snapshot, "output_tokens"):
        receipt.kv("Output Tokens", fmt_int(snapshot.output_tokens))
    if source_has(snapshot, "cached_input_tokens"):
        receipt.kv("Cache Read Tokens", fmt_int(snapshot.cached_input_tokens))
    if source_has(snapshot, "reasoning_output_tokens"):
        receipt.kv("Reasoning Tokens", fmt_int(snapshot.reasoning_output_tokens))
    if source_has(snapshot, "cache_write_tokens"):
        receipt.kv("Cache Write Tokens", fmt_int(snapshot.cache_write_tokens))
    receipt.rule()
    receipt.kv("TOTAL", f"{fmt_int(snapshot.total_tokens)} TOKENS")
    receipt.rule()
    receipt.kv(f"{estimate.currency} ESTIMATE", money(estimate.amount, estimate.currency))
    if estimate.status == "UNMAPPED":
        receipt.kv("PRICE", "UNMAPPED")
    else:
        receipt.kv("PRICE", estimate.model)
        if estimate.source_checked_at:
            receipt.kv("PRICE DATE", estimate.source_checked_at)
        if estimate.rate_note:
            receipt.kv("RATE NOTE", estimate.rate_note)
    receipt.rule()
    for line in footer_lines(footer_text, width):
        receipt.center(line)
    receipt.blank()
    receipt.add(barcode(rid, width))
    receipt.center(rid)

    return receipt.text()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render token usage as an ASCII thermal receipt.")
    parser.add_argument("--session", type=Path, help="Codex JSONL session path. Defaults to newest local session.")
    parser.add_argument("--scope", choices=("latest-turn", "session"), default="latest-turn")
    parser.add_argument("--width", type=int, choices=ALLOWED_WIDTHS, default=48)
    parser.add_argument("--agent-tool", choices=("auto", "codex", "claude-code", "trae", "generic"), default=None, help="Agent/tool logo source. Use codex, claude-code, or trae for the matching agent logo.")
    parser.add_argument("--brand", choices=("auto", "codex", "claude-code", "trae", "generic"), default=None, help="Backward-compatible alias for --agent-tool.")
    parser.add_argument("--pricing", type=Path, default=DEFAULT_PRICING)
    parser.add_argument("--footer", default=DEFAULT_FOOTER, help="Custom footer line, or 'auto' for model-aware footer.")
    parser.add_argument("--footer-tone", choices=("auto", "snarky", "encouraging", "dry"), default="auto")
    parser.add_argument("--conversation-hint", default="", help="Optional short hint used to vary auto footer selection.")
    parser.add_argument("--conversation-summary", default="", help="Alias for a current-chat summary used to vary auto footer selection.")
    parser.add_argument("--provider", help="Override provider, e.g. openai or anthropic.")
    parser.add_argument("--model", help="Override model for display and pricing.")
    parser.add_argument("--input-tokens", type=int)
    parser.add_argument("--cached-input-tokens", type=int)
    parser.add_argument("--cache-write-tokens", type=int)
    parser.add_argument("--output-tokens", type=int)
    parser.add_argument("--reasoning-output-tokens", type=int)
    parser.add_argument("--total-tokens", type=int)
    parser.add_argument("--context-window", type=int)
    parser.add_argument("--receipt-seed")
    parser.add_argument("--show-fields", action="store_true", help="Print a JSON report of fields available from the selected source instead of a receipt.")
    parser.add_argument("--stream", action="store_true", help="Print receipt one line at a time, like a receipt printer.")
    parser.add_argument("--stream-delay", type=float, default=0.03, help="Delay in seconds between lines when --stream is used.")
    return parser


def has_manual_usage(args: argparse.Namespace) -> bool:
    return args.input_tokens is not None or args.output_tokens is not None or args.total_tokens is not None


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if has_manual_usage(args):
        snapshot = load_manual_snapshot(args)
    else:
        session_path = args.session or newest_session_file()
        if not session_path:
            raise SystemExit("No Codex session file found. Provide --input-tokens and --output-tokens for manual mode.")
        snapshot = load_snapshot_from_session(session_path, args.scope, args.model, args.provider)

    if args.provider:
        snapshot.provider = args.provider
    if args.model:
        snapshot.model = args.model

    if args.show_fields:
        print(json.dumps(available_fields_report(snapshot), indent=2, ensure_ascii=True))
        return 0

    estimate = estimate_cost(snapshot, args.pricing)
    agent_tool = auto_brand(snapshot.provider, snapshot.source, args.agent_tool or args.brand or "auto")
    conversation_hint = args.conversation_summary or args.conversation_hint
    receipt_text = render_receipt(snapshot, estimate, args.width, agent_tool, args.footer, args.footer_tone, conversation_hint)
    print_receipt(receipt_text, args.stream, args.stream_delay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
