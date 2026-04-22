#!/usr/bin/env python3
"""dex_evidence.py - extract swap route evidence via PancakeSwap V3 QuoterV2.

This script is an evidence layer for review flows: it does not execute swaps.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
VERITASK_ROOT = ROOT_DIR.parent

for env_path in [
    Path("/home/skottbie/.openclaw/.env"),
    Path("/home/skottbie/.openclaw/workspace/.env"),
    ROOT_DIR / ".env",
    VERITASK_ROOT / ".env",
]:
    if env_path.exists():
        load_dotenv(env_path)

BSC_RPC_URL = os.getenv("BSC_RPC_URL", "https://bsc-testnet-rpc.publicnode.com")
# PancakeSwap V3 QuoterV2 on BSC
PANCAKESWAP_QUOTER_V2 = os.getenv(
    "PANCAKESWAP_QUOTER_V2",
    "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997",
)

SOURCE_KEYS = {
    "dex",
    "dexname",
    "source",
    "sourcename",
    "protocol",
    "protocolname",
    "router",
    "routername",
    "liquiditysource",
    "provider",
    "providername",
}

DEX_PATTERNS = [
    re.compile(r"\\bpancakeswap\\b", re.IGNORECASE),
    re.compile(r"\\bpancake\\s*v[23]\\b", re.IGNORECASE),
    re.compile(r"\\buniswap\\b", re.IGNORECASE),
    re.compile(r"\\buniswap\\s*v[23]\\b", re.IGNORECASE),
]


def _keccak256(text: str) -> bytes:
    from web3 import Web3
    return Web3.keccak(text=text)


def _quote_exact_input_single(from_token: str, to_token: str, amount: int, fee: int = 2500) -> dict[str, Any]:
    """Call PancakeSwap V3 QuoterV2.quoteExactInputSingle via eth_call."""
    from eth_abi import encode as abi_encode

    # quoteExactInputSingle((address,address,uint256,uint24,uint160))
    selector = _keccak256("quoteExactInputSingle((address,address,uint256,uint24,uint160))")[:4]
    params = abi_encode(
        ["(address,address,uint256,uint24,uint160)"],
        [(from_token, to_token, amount, fee, 0)],
    )
    data_hex = "0x" + selector.hex() + params.hex()

    resp = requests.post(
        BSC_RPC_URL,
        json={
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [{"to": PANCAKESWAP_QUOTER_V2, "data": data_hex}, "latest"],
            "id": 1,
        },
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "error" in payload:
        raise RuntimeError(f"QuoterV2 call failed: {payload['error']}")
    result_hex = payload.get("result", "0x")
    if len(result_hex) < 66:
        raise RuntimeError(f"QuoterV2 returned unexpected: {result_hex[:100]}")

    from eth_abi import decode as abi_decode
    (amount_out, sqrt_price_x96, initial_tick, gas_estimate) = abi_decode(
        ["uint256", "uint160", "int24", "uint256"], bytes.fromhex(result_hex[2:])
    )
    return {
        "amountOut": str(amount_out),
        "sqrtPriceX96After": str(sqrt_price_x96),
        "initializedTicksCrossed": initial_tick,
        "gasEstimate": str(gas_estimate),
        "routeSources": ["PancakeSwap V3"],
    }


def _extract_first_item(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    return item
        return payload

    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                return item

    return {}


def _collect_protocol_mentions(node: Any, path: str, out: list[dict[str, str]]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            key_str = str(key)
            child_path = f"{path}.{key_str}"
            normalized_key = key_str.strip().lower()

            if isinstance(value, str) and normalized_key in SOURCE_KEYS:
                val = value.strip()
                if val:
                    out.append({"path": child_path, "value": val})

            _collect_protocol_mentions(value, child_path, out)

    elif isinstance(node, list):
        for idx, item in enumerate(node):
            _collect_protocol_mentions(item, f"{path}[{idx}]", out)


def _normalize_unique(values: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for value in values:
        key = value.strip().lower()
        if key and key not in seen:
            seen[key] = value.strip()
    return list(seen.values())


def _is_dex_source(name: str) -> bool:
    return any(pattern.search(name) for pattern in DEX_PATTERNS)


def build_route_evidence(quote_payload: Any) -> dict[str, Any]:
    mentions: list[dict[str, str]] = []
    _collect_protocol_mentions(quote_payload, "$", mentions)

    sources = _normalize_unique([item["value"] for item in mentions])
    dex_matches = [source for source in sources if _is_dex_source(source)]

    first = _extract_first_item(quote_payload)
    quote_summary = {
        "fromTokenAmount": first.get("fromTokenAmount"),
        "toTokenAmount": first.get("toTokenAmount") or first.get("amountOut"),
        "priceImpactPercent": first.get("priceImpactPercent"),
        "gasFee": first.get("gasFee") or first.get("gasEstimate"),
        "estimatedOutUsd": first.get("toTokenValue"),
    }

    return {
        "routeSources": sources,
        "routeSourceMentions": mentions,
        "containsDex": len(dex_matches) > 0,
        "dexMatches": dex_matches,
        # Keep backward compat keys
        "containsUniswap": len(dex_matches) > 0,
        "uniswapMatches": dex_matches,
        "quoteSummary": quote_summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract DEX route evidence via PancakeSwap QuoterV2")
    parser.add_argument("--from-token", required=True, help="From token contract address")
    parser.add_argument("--to-token", required=True, help="To token contract address")
    parser.add_argument("--amount", required=True, help="Amount in token minimal units")
    parser.add_argument("--chain", default="bsc", help="Chain name (currently only bsc)")
    parser.add_argument("--fee", type=int, default=2500, help="PancakeSwap V3 fee tier (default 2500 = 0.25%%)")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    try:
        quote_payload = _quote_exact_input_single(
            from_token=args.from_token,
            to_token=args.to_token,
            amount=int(args.amount),
            fee=args.fee,
        )

        evidence = build_route_evidence(quote_payload)
        result = {
            "success": True,
            "mode": "route-evidence",
            "chain": args.chain,
            "fromToken": args.from_token,
            "toToken": args.to_token,
            "amount": args.amount,
            "routeEvidence": evidence,
        }

        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        else:
            verdict = "FOUND" if evidence["containsDex"] else "NOT_FOUND"
            print(f"DEX evidence: {verdict}")
            print(f"Sources: {', '.join(evidence['routeSources']) or 'N/A'}")

    except Exception as exc:
        out = {"success": False, "error": str(exc)}
        if args.json:
            print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            print(f"Route evidence failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
