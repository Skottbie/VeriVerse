#!/usr/bin/env python3
"""
challenge_orchestrator.py — VeriVerse P3 deterministic executor.

Implements Step 1/3/4a/4b/5 in one command:
1) Read on-chain agent state + local agent description
2) Execute Worker challenge task and receive ProofBundle
3) Verify trustworthiness layer via verifier.py
4) Apply 2-verifier DAO weighted decision
5) Update trust score on-chain via VTRegistry.updateTrust

Also supports Step 0 precheck mode to verify challenger USDT balance before challenge starts.

Notes:
- Pro exam design (Step 2) and two verifier opinions (Step 4b source) are handled by SKILL orchestration.
- This script only executes deterministic parts and enforces the finalized decision rule.
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3


# --- Env loading -----------------------------------------------------------

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


# --- Shared verifier reuse -------------------------------------------------

VERIFIER_DIR = VERITASK_ROOT / "client_node" / "skills" / "verifier"
if VERIFIER_DIR.exists():
    sys.path.insert(0, str(VERIFIER_DIR))

try:
    from verifier import verify_proof_bundle  # type: ignore
except Exception as exc:
    raise RuntimeError(f"Failed to import verifier module from {VERIFIER_DIR}: {exc}")

X402_PAYER_DIR = VERITASK_ROOT / "client_node" / "skills" / "okx-x402-payer"
# x402 module kept for reference but no longer called for payment.
# Payment now uses direct web3.py ERC-20 transfer on BSC testnet.


# --- Constants -------------------------------------------------------------


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default

DEFAULT_RPC_URL = os.getenv("BSC_RPC_URL", "https://bsc-testnet-rpc.publicnode.com")
DEFAULT_WORKER_URL = os.getenv("WORKER_URL", "http://127.0.0.1:8001")
CHAIN_ID = int(os.getenv("CHAIN_ID", "97"))
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

DEFAULT_VERIFIER_REWARD_USDT = float(os.getenv("VERIFIER_REWARD_AMOUNT_USDT", "0.005"))
DEFAULT_X402_RETRY_MAX = int(os.getenv("X402_RETRY_MAX", "2"))
DEFAULT_X402_RETRY_DELAY_MS = int(os.getenv("X402_RETRY_DELAY_MS", "800"))
MIN_CHALLENGE_FEE_USDT = float(os.getenv("CHALLENGE_MIN_FEE_USDT", "0.01"))
USDT_TOKEN_CONTRACT = os.getenv(
    "TOKEN_CONTRACT_ADDRESS",
    "0xF8De09e7772366A104c4d42269891AD1ca7Be720",
)
BSC_CHAIN_INDEX = os.getenv("CHAIN_INDEX", "97")
# onchainos removed — all operations via web3.py / GoPlus API
CHAIN_NAME = os.getenv("CHAIN_NAME", "bsc")
CHALLENGE_ENABLE_SECURITY_SCAN = _env_bool("CHALLENGE_ENABLE_SECURITY_SCAN", True)
CHALLENGE_ENABLE_SIMULATE = _env_bool("CHALLENGE_ENABLE_SIMULATE", True)
CHALLENGE_ALLOW_WARN_RISK = _env_bool("CHALLENGE_ALLOW_WARN_RISK", False)
CHALLENGE_BLOCK_FINALIZE_ON_PROVENANCE_INVALID = _env_bool(
    "CHALLENGE_BLOCK_FINALIZE_ON_PROVENANCE_INVALID",
    True,
)
CHALLENGE_AUDIT_LOG_PATH = Path(
    os.getenv(
        "CHALLENGE_AUDIT_LOG_PATH",
        str(ROOT_DIR / "data" / "audit" / "challenge_orchestrator.jsonl"),
    )
)


# Temporary compatibility switch: default keeps legacy 2-layer (zk+tee) behavior.
REQUIRE_ORIGIN_SIGNATURE = _env_bool("CHALLENGE_REQUIRE_ORIGIN_SIGNATURE", False)

PASS_DELTA = {
    "bronze": 10,
    "silver": 15,
    "gold": 20,
    "diamond": 25,
}
FAIL_DELTA = {
    "bronze": -5,
    "silver": -8,
    "gold": -10,
    "diamond": -15,
}

VTREGISTRY_ABI = [
    {
        "inputs": [{"internalType": "uint256", "name": "agentId", "type": "uint256"}],
        "name": "getAgent",
        "outputs": [
            {
                "components": [
                    {"internalType": "string", "name": "name", "type": "string"},
                    {"internalType": "address", "name": "creator", "type": "address"},
                    {"internalType": "address", "name": "wallet", "type": "address"},
                    {"internalType": "int256", "name": "trustScore", "type": "int256"},
                    {"internalType": "uint8", "name": "status", "type": "uint8"},
                ],
                "internalType": "struct VTRegistry.Agent",
                "name": "",
                "type": "tuple",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "agentId", "type": "uint256"},
            {"internalType": "int256", "name": "delta", "type": "int256"},
        ],
        "name": "updateTrust",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "owner",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]

AGENT_SCHEMA_PATH = ROOT_DIR / "data" / "agents" / "schema.json"
WORKER_TASK_TYPE = "defi_tvl"
SILVER_MIN_RUNS = 2
MAX_CHALLENGE_RUNS = 5


# --- Utilities -------------------------------------------------------------


def _log(msg: str) -> None:
    print(f"[Challenge] {msg}", file=sys.stderr)


def _append_audit(event: str, payload: dict[str, Any]) -> None:
    """Best-effort JSONL audit log that must not block main challenge flow."""
    try:
        CHALLENGE_AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,
            **payload,
        }
        with CHALLENGE_AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError):
        return


# _run_onchainos_json removed — replaced by direct web3.py / GoPlus calls


def _extract_first_result_item(payload: Any) -> dict[str, Any]:
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


def _extract_risk_action(scan_result: Any) -> str:
    item = _extract_first_result_item(scan_result)
    action = item.get("action") if isinstance(item, dict) else ""
    if isinstance(action, str):
        return action.strip().lower()
    return ""


def _extract_fail_reason(sim_result: Any) -> str:
    item = _extract_first_result_item(sim_result)
    if isinstance(item, dict):
        fail_reason = item.get("failReason") or item.get("revertReason")
        if isinstance(fail_reason, str) and fail_reason.strip():
            return fail_reason.strip()
    return ""


def _extract_gateway_tx_hash(payload: Any) -> str:
    item = _extract_first_result_item(payload)
    if not isinstance(item, dict):
        return ""
    candidates = [item.get("txHash"), item.get("hash")]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip().startswith("0x"):
            return candidate.strip()
    return ""


def _extract_gateway_order_id(payload: Any) -> str:
    item = _extract_first_result_item(payload)
    if not isinstance(item, dict):
        return ""
    candidates = [item.get("orderId"), item.get("id")]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        if isinstance(candidate, int):
            return str(candidate)
    return ""


def _extract_gateway_order_status(payload: Any) -> str:
    item = _extract_first_result_item(payload)
    if not isinstance(item, dict):
        return ""
    candidates = [item.get("status"), item.get("orderStatus")]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def _security_scan_tx(from_addr: str, to_addr: str, data_hex: str, value_raw: int = 0) -> dict[str, Any]:
    """Run GoPlus token security scan as a pre-broadcast guardrail."""
    try:
        addr = to_addr.lower()
        resp = requests.get(
            f"https://api.gopluslabs.io/api/v1/token_security/56?contract_addresses={addr}",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        result_map = data.get("result", {})
        token_info = result_map.get(addr, {})
        if token_info.get("is_honeypot") == "1":
            return {"ok": False, "error": "security: honeypot detected", "action": "block", "raw": data}
        if token_info.get("is_blacklisted") == "1":
            return {"ok": False, "error": "security: blacklisted token", "action": "block", "raw": data}
        return {"ok": True, "action": "pass", "raw": data}
    except Exception as e:
        _log(f"GoPlus security scan failed (non-blocking): {e}")
        return {"ok": True, "action": "skipped", "raw": None}


def _simulate_tx(from_addr: str, to_addr: str, data_hex: str, amount_raw: int = 0) -> dict[str, Any]:
    """Simulate tx via eth_call as a pre-broadcast guardrail."""
    try:
        rpc_url = os.getenv("BSC_RPC_URL", "https://bsc-testnet-rpc.publicnode.com")
        value_hex = hex(amount_raw) if amount_raw else "0x0"
        resp = requests.post(
            rpc_url,
            json={
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [{"from": from_addr, "to": to_addr, "data": data_hex, "value": value_hex}, "latest"],
                "id": 1,
            },
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        if "error" in payload:
            return {"ok": False, "error": payload["error"].get("message", str(payload["error"])), "raw": payload}
        return {"ok": True, "raw": payload}
    except Exception as e:
        return {"ok": False, "error": f"simulate failed: {e}", "raw": None}


def _broadcast_signed_tx(signed_tx_hex: str, wallet_address: str) -> dict[str, Any]:
    """Broadcast signed tx via BSC JSON-RPC send_raw_transaction."""
    rpc_url = os.getenv("BSC_RPC_URL", "https://bsc-testnet-rpc.publicnode.com")
    resp = requests.post(
        rpc_url,
        json={"jsonrpc": "2.0", "method": "eth_sendRawTransaction",
              "params": [signed_tx_hex], "id": 1},
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "error" in payload:
        return {"ok": False, "error": payload["error"].get("message", str(payload["error"])), "raw": payload}
    tx_hash = payload.get("result", "")
    return {
        "ok": True,
        "txHash": tx_hash,
        "orderId": "",
        "raw": payload,
    }


def _query_gateway_order(wallet_address: str, order_id: str) -> dict[str, Any]:
    """Query tx receipt via BSC JSON-RPC (replaces onchainos gateway orders)."""
    rpc_url = os.getenv("BSC_RPC_URL", "https://bsc-testnet-rpc.publicnode.com")
    resp = requests.post(
        rpc_url,
        json={"jsonrpc": "2.0", "method": "eth_getTransactionReceipt",
              "params": [order_id], "id": 1},
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    receipt = payload.get("result")
    if not receipt:
        return {"txHash": order_id, "status": "pending", "raw": payload}
    status_hex = str(receipt.get("status", "")).lower()
    status = "success" if status_hex == "0x1" else ("reverted" if status_hex == "0x0" else "unknown")
    return {
        "txHash": receipt.get("transactionHash", order_id),
        "status": status,
        "raw": payload,
    }


def _extract_usdt_balance_from_portfolio(payload: Any, usdt_contract: str) -> float:
    target = usdt_contract.lower()

    def _from_token_list(tokens: Any) -> float | None:
        if not isinstance(tokens, list):
            return None
        for token in tokens:
            if not isinstance(token, dict):
                continue
            addr = str(token.get("tokenContractAddress", "")).lower()
            if addr == target:
                try:
                    return float(token.get("balance", "0") or 0)
                except (TypeError, ValueError):
                    return 0.0
        return None

    if isinstance(payload, list):
        bal = _from_token_list(payload)
        if bal is not None:
            return bal

    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                bal = _from_token_list(entry.get("tokenAssets", []))
                if bal is not None:
                    return bal
        elif isinstance(data, dict):
            bal = _from_token_list(data.get("tokenAssets", []))
            if bal is not None:
                return bal

        bal = _from_token_list(payload.get("tokenAssets", []))
        if bal is not None:
            return bal

    return 0.0


def _challenge_fee_required_usdt(verifier_reward_usdt: float) -> float:
    per_verifier = max(0.0, float(verifier_reward_usdt))
    total_reward = per_verifier * 2.0
    return round(max(MIN_CHALLENGE_FEE_USDT, total_reward), 6)


def _precheck_challenger_balance(required_usdt: float) -> dict[str, Any]:
    """Check challenger USDT balance via ERC-20 balanceOf."""
    client_pk = os.getenv("CLIENT_PRIVATE_KEY", "").strip()
    if not client_pk:
        raise RuntimeError("CLIENT_PRIVATE_KEY missing in environment")

    pk_hex = client_pk if client_pk.startswith("0x") else f"0x{client_pk}"
    wallet = Account.from_key(pk_hex).address

    rpc_url = os.getenv("BSC_RPC_URL", "https://bsc-testnet-rpc.publicnode.com")
    usdt_addr = Web3.to_checksum_address(USDT_TOKEN_CONTRACT)
    selector = Web3.keccak(text="balanceOf(address)")[:4]
    from eth_abi import encode as abi_encode
    params = abi_encode(["address"], [wallet])
    data_hex = "0x" + selector.hex() + params.hex()

    resp = requests.post(
        rpc_url,
        json={
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [{"to": usdt_addr, "data": data_hex}, "latest"],
            "id": 1,
        },
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "error" in payload:
        raise RuntimeError(f"RPC error: {payload['error']}")
    balance_raw = int(payload["result"], 16)
    # MockUSDT uses 6 decimals (matching real USDT)
    balance_usdt = balance_raw / (10 ** 6)
    sufficient = balance_usdt >= required_usdt

    return {
        "wallet": wallet,
        "chainIndex": BSC_CHAIN_INDEX,
        "usdtContract": usdt_addr,
        "balanceUsdt": balance_usdt,
        "requiredUsdt": required_usdt,
        "shortfallUsdt": 0.0 if sufficient else round(required_usdt - balance_usdt, 6),
        "sufficient": sufficient,
    }


def _load_registry_address(explicit: str | None) -> str:
    if explicit:
        return Web3.to_checksum_address(explicit)

    env_addr = os.getenv("VTREGISTRY_ADDRESS", "").strip()
    if env_addr:
        return Web3.to_checksum_address(env_addr)

    addresses_path = ROOT_DIR / "addresses.json"
    if addresses_path.exists():
        data = json.loads(addresses_path.read_text(encoding="utf-8"))
        bsc = data.get("bsc", {})
        addr = bsc.get("VTRegistry")
        if addr:
            return Web3.to_checksum_address(addr)

    raise ValueError("VTRegistry address not found (use --registry or VTREGISTRY_ADDRESS)")


def _tier_from_score(score: int) -> str:
    if score <= 25:
        return "bronze"
    if score <= 50:
        return "silver"
    if score <= 75:
        return "gold"
    return "diamond"


def _safe_load_json(text: str | None, file_path: str | None, label: str) -> dict[str, Any]:
    if file_path:
        p = Path(file_path)
        if not p.exists():
            raise ValueError(f"{label} file not found: {file_path}")
        return json.loads(p.read_text(encoding="utf-8-sig"))
    if text:
        return json.loads(text)
    raise ValueError(f"{label} payload missing (use --{label}-json or --{label}-file)")


def _load_agent_description(agent_id: int) -> dict[str, Any]:
    p = ROOT_DIR / "data" / "agents" / f"{agent_id}.json"
    if not p.exists():
        raise FileNotFoundError(f"Agent description file not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _load_agent_schema() -> dict[str, Any]:
    if not AGENT_SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Agent schema file not found: {AGENT_SCHEMA_PATH}")
    return json.loads(AGENT_SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate_agent_description(agent_desc: dict[str, Any], expected_agent_id: int) -> None:
    schema = _load_agent_schema()
    required = schema.get("required", [])
    properties = schema.get("properties", {})

    missing = [k for k in required if k not in agent_desc]
    if missing:
        raise ValueError(f"Agent description missing required fields: {missing}")

    if schema.get("additionalProperties") is False:
        extras = [k for k in agent_desc.keys() if k not in properties.keys()]
        if extras:
            raise ValueError(f"Agent description has unsupported fields: {extras}")

    agent_id = agent_desc.get("agentId")
    if not isinstance(agent_id, int) or agent_id <= 0:
        raise ValueError("agentId must be a positive integer")
    if agent_id != expected_agent_id:
        raise ValueError(
            f"agentId mismatch: description={agent_id}, expected={expected_agent_id}"
        )

    for field in ["name", "description"]:
        val = agent_desc.get(field)
        if not isinstance(val, str) or not val.strip():
            raise ValueError(f"{field} must be a non-empty string")

    claims = agent_desc.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValueError("claims must be a non-empty array")
    if any((not isinstance(c, str) or not c.strip()) for c in claims):
        raise ValueError("claims must contain non-empty strings only")

    supported_tasks = agent_desc.get("supportedTasks")
    if not isinstance(supported_tasks, list) or not supported_tasks:
        raise ValueError("supportedTasks must be a non-empty array")
    normalized_tasks = [str(t).strip().lower() for t in supported_tasks]
    if any(not t for t in normalized_tasks):
        raise ValueError("supportedTasks must contain non-empty task ids")

    allowed_tasks = {
        str(t).strip().lower()
        for t in properties.get("supportedTasks", {}).get("items", {}).get("enum", [])
    }
    if not allowed_tasks:
        allowed_tasks = {WORKER_TASK_TYPE}
    invalid = [t for t in normalized_tasks if t not in allowed_tasks]
    if invalid:
        raise ValueError(f"supportedTasks contains unsupported entries: {invalid}")
    if WORKER_TASK_TYPE not in normalized_tasks:
        raise ValueError(
            f"Agent supportedTasks must include '{WORKER_TASK_TYPE}' for current Worker runtime"
        )

    owner = agent_desc.get("owner", "")
    owner_pattern = properties.get("owner", {}).get("pattern", r"^0x[0-9a-fA-F]{40}$")
    if not isinstance(owner, str) or not re.match(owner_pattern, owner):
        raise ValueError("owner must be a valid EVM address")

    updated_at = agent_desc.get("updatedAt", "")
    if not isinstance(updated_at, str):
        raise ValueError("updatedAt must be an ISO datetime string")
    try:
        datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("updatedAt must be an ISO datetime string") from exc


def _read_agent_onchain(contract: Any, agent_id: int) -> dict[str, Any]:
    if agent_id <= 0:
        raise ValueError("agent_id must be > 0")

    try:
        agent = contract.functions.getAgent(agent_id).call()
    except Exception as exc:
        raise ValueError(f"Agent #{agent_id} does not exist on VTRegistry ({exc})") from exc

    if not isinstance(agent, (tuple, list)) or len(agent) < 5:
        raise ValueError(f"Unexpected getAgent() return shape: {agent}")

    return {
        "name": agent[0],
        "creator": agent[1],
        "wallet": agent[2],
        "trustScore": int(agent[3]),
        "status": int(agent[4]),
    }


def _execute_worker(
    worker_url: str,
    task_type: str,
    protocol: str,
    client_wallet: str,
    timeout_s: int,
) -> dict[str, Any]:
    task_intent = {
        "task_id": str(uuid.uuid4()),
        "type": task_type,
        "params": {"protocol": protocol},
        "client_wallet": client_wallet,
    }
    resp = requests.post(f"{worker_url.rstrip('/')}/execute", json=task_intent, timeout=timeout_s)
    resp.raise_for_status()
    return resp.json()


def _extract_tvl_usd(proof_bundle: dict[str, Any]) -> float:
    data = proof_bundle.get("data")
    if not isinstance(data, dict):
        raise ValueError("proofBundle.data missing")

    tvl_raw = data.get("tvl_usd")
    try:
        tvl = float(tvl_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"proofBundle.data.tvl_usd invalid: {tvl_raw}") from exc

    if tvl <= 0:
        raise ValueError(f"proofBundle.data.tvl_usd must be > 0, got {tvl}")
    return tvl


def _parse_silver_consistency(challenge_payload: dict[str, Any]) -> dict[str, float | int]:
    consistency = challenge_payload.get("consistency")
    if not isinstance(consistency, dict):
        raise ValueError("Silver tier requires consistency object")

    required = ["runs", "interval_seconds", "max_variance_pct"]
    missing = [k for k in required if k not in consistency]
    if missing:
        raise ValueError(f"Silver tier consistency missing fields: {missing}")

    try:
        runs = int(consistency.get("runs"))
    except (TypeError, ValueError) as exc:
        raise ValueError("consistency.runs must be an integer") from exc
    if runs < SILVER_MIN_RUNS:
        raise ValueError(f"Silver tier requires consistency.runs >= {SILVER_MIN_RUNS}")
    if runs > MAX_CHALLENGE_RUNS:
        raise ValueError(f"consistency.runs too large: {runs} (max {MAX_CHALLENGE_RUNS})")

    try:
        interval_seconds = int(consistency.get("interval_seconds"))
    except (TypeError, ValueError) as exc:
        raise ValueError("consistency.interval_seconds must be an integer") from exc
    if interval_seconds < 0:
        raise ValueError("consistency.interval_seconds must be >= 0")
    if interval_seconds > 300:
        raise ValueError("consistency.interval_seconds too large (max 300)")

    try:
        max_variance_pct = float(consistency.get("max_variance_pct"))
    except (TypeError, ValueError) as exc:
        raise ValueError("consistency.max_variance_pct must be a number") from exc
    if max_variance_pct <= 0:
        raise ValueError("consistency.max_variance_pct must be > 0")
    if max_variance_pct > 100:
        raise ValueError("consistency.max_variance_pct too large (max 100)")

    return {
        "runs": runs,
        "intervalSeconds": interval_seconds,
        "maxVariancePct": max_variance_pct,
    }


def _compute_relative_variance_pct(values: list[float]) -> float:
    if not values:
        return 0.0
    mean_val = sum(values) / len(values)
    if mean_val <= 0:
        return 0.0
    spread = max(values) - min(values)
    return (spread / mean_val) * 100.0


def _normalize_verdict(v: str) -> str:
    val = (v or "").strip().upper()
    if val not in {"PASS", "FAIL"}:
        raise ValueError(f"Invalid verdict: {v}")
    return val


def _normalize_confidence(c: Any) -> float:
    val = float(c)
    if not (0 < val <= 1):
        raise ValueError(f"Confidence must be in (0,1], got {c}")
    return val


def _canonical_data_hash(data: Any) -> str:
    data_json = json.dumps(data, sort_keys=True)
    return hashlib.sha256(data_json.encode()).hexdigest()


def _normalize_sha256(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw.startswith("0x"):
        raw = raw[2:]
    if re.fullmatch(r"[0-9a-f]{64}", raw):
        return raw
    return ""


def _review_payload_hash(source_hash: str, verdict: str, confidence: Any, compact: bool = False) -> str:
    payload = {
        "confidence": confidence,
        "source_hash": source_hash,
        "verdict": verdict,
    }
    if compact:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    else:
        canonical = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _review_payload_hash_candidates(
    source_hash: str,
    reviewer_payload: dict[str, Any],
    verdict: str,
    confidence: float,
) -> list[str]:
    raw_verdict = str(reviewer_payload.get("verdict", "")).strip()
    raw_confidence = reviewer_payload.get("confidence")

    verdict_variants: list[str] = [verdict]
    for candidate in [raw_verdict, raw_verdict.upper(), raw_verdict.lower()]:
        if candidate and candidate not in verdict_variants:
            verdict_variants.append(candidate)

    confidence_variants: list[Any] = [confidence]
    if float(confidence).is_integer():
        confidence_variants.append(int(confidence))

    if raw_confidence is not None:
        confidence_variants.append(raw_confidence)
        if isinstance(raw_confidence, str):
            stripped = raw_confidence.strip()
            if stripped:
                confidence_variants.append(stripped)
                try:
                    confidence_variants.append(float(stripped))
                except ValueError:
                    pass

    candidates: list[str] = []
    seen: set[str] = set()
    for verdict_value in verdict_variants:
        for confidence_value in confidence_variants:
            for compact in [False, True]:
                payload_hash = _review_payload_hash(
                    source_hash=source_hash,
                    verdict=verdict_value,
                    confidence=confidence_value,
                    compact=compact,
                )
                if payload_hash not in seen:
                    seen.add(payload_hash)
                    candidates.append(payload_hash)

    return candidates


def _recover_origin_signer(payload_hash: str, signature: str) -> tuple[str, str]:
    attempts: list[tuple[str, Any]] = [
        ("text", encode_defunct(text=payload_hash)),
        ("hexstr", encode_defunct(hexstr=f"0x{payload_hash}")),
    ]

    payload_bytes = bytes.fromhex(payload_hash)
    attempts.append(("bytes", encode_defunct(primitive=payload_bytes)))

    errors: list[str] = []
    for mode, message in attempts:
        try:
            recovered = Account.recover_message(message, signature=signature)
            return recovered, mode
        except Exception as exc:
            errors.append(f"{mode}:{exc}")

    raise ValueError("; ".join(errors))


def _validate_reviewer_provenance(
    reviewer_key: str,
    reviewer_payload: dict[str, Any],
    expected_source_hash: str,
    verdict: str,
    confidence: float,
) -> dict[str, Any]:
    if not expected_source_hash:
        return {
            "is_valid": False,
            "reason": "source hash expected missing",
            "reviewer": reviewer_key,
        }

    provenance = reviewer_payload.get("reviewer_provenance")
    if not isinstance(provenance, dict):
        return {
            "is_valid": False,
            "reason": "reviewer_provenance missing",
            "reviewer": reviewer_key,
        }

    source_ref = str(provenance.get("source_ref", "")).strip()
    source_hash = _normalize_sha256(provenance.get("source_hash") or provenance.get("sourceHash"))
    if source_hash != expected_source_hash:
        return {
            "is_valid": False,
            "reason": "source hash mismatch",
            "reviewer": reviewer_key,
            "sourceRef": source_ref,
            "sourceHash": source_hash,
        }

    zk_proof = provenance.get("zk_proof")
    if not isinstance(zk_proof, dict):
        return {
            "is_valid": False,
            "reason": "zk_proof missing",
            "reviewer": reviewer_key,
            "sourceRef": source_ref,
            "sourceHash": source_hash,
        }

    zk_type = str(zk_proof.get("type", "")).strip().lower()
    if zk_type != "reclaim_zkfetch":
        return {
            "is_valid": False,
            "reason": "zk_proof.type must be reclaim_zkfetch",
            "reviewer": reviewer_key,
            "sourceRef": source_ref,
            "sourceHash": source_hash,
            "zkType": zk_type,
        }

    response_hash = _normalize_sha256(zk_proof.get("response_hash") or zk_proof.get("responseHash"))
    if response_hash != expected_source_hash:
        return {
            "is_valid": False,
            "reason": "zk response hash mismatch",
            "reviewer": reviewer_key,
            "sourceRef": source_ref,
            "sourceHash": source_hash,
            "zkType": zk_type,
        }

    payee_addr = str(reviewer_payload.get("payeeAddress", "")).strip()
    if not payee_addr:
        return {
            "is_valid": False,
            "reason": "payeeAddress required for provenance-bound payment",
            "reviewer": reviewer_key,
            "sourceRef": source_ref,
            "sourceHash": source_hash,
            "zkType": zk_type,
        }
    if not Web3.is_address(payee_addr):
        return {
            "is_valid": False,
            "reason": "invalid payeeAddress",
            "reviewer": reviewer_key,
            "sourceRef": source_ref,
            "sourceHash": source_hash,
            "zkType": zk_type,
        }

    origin_auth = provenance.get("origin_auth")
    if not isinstance(origin_auth, dict):
        return {
            "is_valid": False,
            "reason": "origin_auth missing",
            "reviewer": reviewer_key,
            "sourceRef": source_ref,
            "sourceHash": source_hash,
            "zkType": zk_type,
        }

    payload_hash = _normalize_sha256(origin_auth.get("payload_hash"))
    if not payload_hash:
        return {
            "is_valid": False,
            "reason": "origin payload hash missing",
            "reviewer": reviewer_key,
            "sourceRef": source_ref,
            "sourceHash": source_hash,
            "zkType": zk_type,
        }

    expected_payload_hash = _review_payload_hash(expected_source_hash, verdict, confidence)
    payload_hash_candidates = _review_payload_hash_candidates(
        source_hash=expected_source_hash,
        reviewer_payload=reviewer_payload,
        verdict=verdict,
        confidence=confidence,
    )
    payload_hash_matched = payload_hash in payload_hash_candidates

    signature = str(origin_auth.get("signature", "")).strip()
    if not signature:
        return {
            "is_valid": False,
            "reason": "origin signature missing",
            "reviewer": reviewer_key,
            "sourceRef": source_ref,
            "sourceHash": source_hash,
            "zkType": zk_type,
        }

    recoveries: list[dict[str, str]] = []
    recover_errors: list[str] = []
    for candidate_hash in payload_hash_candidates:
        try:
            recovered_signer, recover_mode = _recover_origin_signer(candidate_hash, signature)
            recoveries.append(
                {
                    "payloadHash": candidate_hash,
                    "signer": recovered_signer,
                    "mode": recover_mode,
                }
            )
        except Exception as exc:
            recover_errors.append(f"{candidate_hash[:8]}...:{exc}")

    if not recoveries:
        return {
            "is_valid": False,
            "reason": "origin signature recovery failed",
            "reviewer": reviewer_key,
            "sourceRef": source_ref,
            "sourceHash": source_hash,
            "zkType": zk_type,
            "payloadHashExpected": expected_payload_hash,
            "payloadHashProvided": payload_hash,
            "payloadHashCandidates": payload_hash_candidates,
            "recoverErrors": recover_errors,
        }

    payee_checksum = Web3.to_checksum_address(payee_addr)
    accepted_recovery = next(
        (entry for entry in recoveries if entry.get("signer", "").lower() == payee_checksum.lower()),
        None,
    )

    if not accepted_recovery:
        return {
            "is_valid": False,
            "reason": "signature signer must match payeeAddress",
            "reviewer": reviewer_key,
            "sourceRef": source_ref,
            "sourceHash": source_hash,
            "zkType": zk_type,
            "payeeAddress": payee_checksum,
            "recoveredSignerCandidates": [entry.get("signer", "") for entry in recoveries],
            "payloadHashExpected": expected_payload_hash,
            "payloadHashProvided": payload_hash,
            "payloadHashCandidates": payload_hash_candidates,
        }

    recovered = str(accepted_recovery.get("signer", ""))
    recover_mode = str(accepted_recovery.get("mode", ""))
    accepted_payload_hash = str(accepted_recovery.get("payloadHash", ""))

    declared_signer = str(origin_auth.get("signer", "")).strip()
    if declared_signer and recovered.lower() != declared_signer.lower():
        return {
            "is_valid": False,
            "reason": "origin signer mismatch",
            "reviewer": reviewer_key,
            "sourceRef": source_ref,
            "sourceHash": source_hash,
            "zkType": zk_type,
            "recoveredSigner": recovered,
        }

    warning_parts: list[str] = []
    if not payload_hash_matched:
        warning_parts.append("origin payload hash differs from accepted canonical variants")
    if accepted_payload_hash and accepted_payload_hash != expected_payload_hash:
        warning_parts.append("signature matched a compatible canonical variant")

    return {
        "is_valid": True,
        "reason": "reviewer provenance verified",
        "reviewer": reviewer_key,
        "sourceRef": source_ref,
        "sourceHash": source_hash,
        "zkType": zk_type,
        "signer": Web3.to_checksum_address(recovered),
        "payeeAddress": payee_checksum,
        "payloadHashExpected": expected_payload_hash,
        "payloadHashAccepted": accepted_payload_hash,
        "payloadHashProvided": payload_hash,
        "payloadHashMatched": payload_hash_matched,
        "payloadHashCandidates": payload_hash_candidates,
        "signatureRecoverMode": recover_mode,
        "warning": "; ".join(warning_parts),
    }


def _proof_bundle_source_hash(proof_bundle: dict[str, Any]) -> str:
    data = proof_bundle.get("data")
    if not isinstance(data, dict):
        return ""
    return _canonical_data_hash(data)


def _resolve_verifier_payees(dao_payload: dict[str, Any]) -> list[str]:
    env_a = os.getenv("DAO_WALLET_A", "").strip()
    env_b = os.getenv("DAO_WALLET_B", "").strip()

    # .env 优先：LLM 生成的 payeeAddress 不可信（可能填成 Client 自己的地址）。
    if env_a and Web3.is_address(env_a):
        candidate_a = env_a
    else:
        va = dao_payload.get("verifier_a", {})
        candidate_a = str((va.get("payeeAddress") if isinstance(va, dict) else "") or "").strip()

    if env_b and Web3.is_address(env_b):
        candidate_b = env_b
    else:
        vb = dao_payload.get("verifier_b", {})
        candidate_b = str((vb.get("payeeAddress") if isinstance(vb, dict) else "") or "").strip()

    if not candidate_a:
        raise ValueError("Verifier A payee address missing (set DAO_WALLET_A in .env)")
    if not candidate_b:
        raise ValueError("Verifier B payee address missing (set DAO_WALLET_B in .env)")

    if not Web3.is_address(candidate_a):
        raise ValueError(f"Invalid verifier A payee address: {candidate_a}")
    if not Web3.is_address(candidate_b):
        raise ValueError(f"Invalid verifier B payee address: {candidate_b}")

    return [Web3.to_checksum_address(candidate_a), Web3.to_checksum_address(candidate_b)]


def _erc20_transfer(payee: str, amount_usdt: float) -> dict[str, Any]:
    """Direct ERC-20 transfer on BSC testnet via web3.py (replaces x402)."""
    client_pk = os.getenv("CLIENT_PRIVATE_KEY", "").strip()
    if not client_pk:
        raise RuntimeError("CLIENT_PRIVATE_KEY missing in environment")

    pk_hex = client_pk if client_pk.startswith("0x") else f"0x{client_pk}"
    rpc_url = os.getenv("BSC_RPC_URL", DEFAULT_RPC_URL)
    explorer_base = os.getenv("EXPLORER_BASE", "https://testnet.bscscan.com/tx/")

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    account = Account.from_key(pk_hex)
    usdt_addr = Web3.to_checksum_address(USDT_TOKEN_CONTRACT)
    payee_addr = Web3.to_checksum_address(payee)

    # ERC-20 transfer(address,uint256) calldata
    from eth_abi import encode as abi_encode
    amount_raw = int(amount_usdt * (10 ** 6))  # MockUSDT 6 decimals
    selector = Web3.keccak(text="transfer(address,uint256)")[:4]
    params = abi_encode(["address", "uint256"], [payee_addr, amount_raw])
    data_hex = "0x" + selector.hex() + params.hex()

    nonce = w3.eth.get_transaction_count(account.address)
    tx = {
        "to": usdt_addr,
        "data": data_hex,
        "gas": 100_000,
        "gasPrice": w3.eth.gas_price,
        "nonce": nonce,
        "chainId": CHAIN_ID,
    }

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

    if receipt.status != 1:
        return {
            "success": False,
            "error": f"ERC-20 transfer reverted (tx: {tx_hash.hex()})",
            "tx_hash": tx_hash.hex(),
        }

    return {
        "success": True,
        "tx_hash": tx_hash.hex(),
        "explorer_url": f"{explorer_base}{tx_hash.hex()}",
    }


def _x402_pay_with_retry(payee: str, amount_usdt: float, max_retries: int, delay_ms: int) -> dict[str, Any]:
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            result = _erc20_transfer(payee, amount_usdt)
            if result.get("success"):
                return {
                    "success": True,
                    "payee": payee,
                    "attempts": attempt,
                    "txHash": result.get("tx_hash"),
                    "explorerUrl": result.get("explorer_url"),
                }

            last_error = result.get("error", "ERC-20 transfer returned success=false")
        except Exception as exc:
            last_error = str(exc)

        if attempt < max_retries:
            time.sleep(max(0, delay_ms) / 1000.0)

    return {
        "success": False,
        "payee": payee,
        "attempts": max_retries,
        "error": str(last_error or "ERC-20 transfer failed"),
    }


def _pay_verifiers_for_challenge(
    dao_payload: dict[str, Any],
    amount_usdt: float,
    max_retries: int,
    delay_ms: int,
) -> dict[str, Any]:
    payees = _resolve_verifier_payees(dao_payload)
    entries: list[dict[str, Any]] = []

    for payee in payees:
        entries.append(_x402_pay_with_retry(payee, amount_usdt, max_retries, delay_ms))

    tx_hashes = [e.get("txHash") for e in entries if e.get("success") and e.get("txHash")]
    failed_wallets = [e.get("payee") for e in entries if not e.get("success") and e.get("payee")]

    return {
        "attempted": True,
        "success": len(failed_wallets) == 0,
        "amountPerVerifierUsdt": amount_usdt,
        "totalAmountUsdt": amount_usdt * len(payees),
        "payees": payees,
        "txHashes": tx_hashes,
        "failedWallets": failed_wallets,
        "results": entries,
    }


def _weighted_dao_decision(dao_payload: dict[str, Any], expected_source_hash: str = "") -> dict[str, Any]:
    # Expected structure:
    # {
    #   "verifier_a": {"verdict": "PASS|FAIL", "confidence": 0.0-1.0, "reasoning": "..."},
    #   "verifier_b": {"verdict": "PASS|FAIL", "confidence": 0.0-1.0, "reasoning": "..."}
    # }
    va = dao_payload.get("verifier_a")
    vb = dao_payload.get("verifier_b")
    if not isinstance(va, dict) or not isinstance(vb, dict):
        raise ValueError("dao payload must include verifier_a and verifier_b objects")

    verdict_a = _normalize_verdict(str(va.get("verdict", "")))
    verdict_b = _normalize_verdict(str(vb.get("verdict", "")))
    conf_a = _normalize_confidence(va.get("confidence", 0))
    conf_b = _normalize_confidence(vb.get("confidence", 0))

    # PASS=1, FAIL=0
    v_a = 1.0 if verdict_a == "PASS" else 0.0
    v_b = 1.0 if verdict_b == "PASS" else 0.0
    score = (conf_a * v_a + conf_b * v_b) / (conf_a + conf_b)

    final_verdict = "PASS" if score > 0.5 else "FAIL"

    dao_meta = dao_payload.get("dao_meta", {})
    meta_source_hash = ""
    if isinstance(dao_meta, dict):
        meta_source_hash = _normalize_sha256(
            dao_meta.get("source_hash_expected") or dao_meta.get("sourceHashExpected")
        )
    source_hash_expected = _normalize_sha256(expected_source_hash) or meta_source_hash

    provenance_a = _validate_reviewer_provenance(
        reviewer_key="verifier_a",
        reviewer_payload=va,
        expected_source_hash=source_hash_expected,
        verdict=verdict_a,
        confidence=conf_a,
    )
    provenance_b = _validate_reviewer_provenance(
        reviewer_key="verifier_b",
        reviewer_payload=vb,
        expected_source_hash=source_hash_expected,
        verdict=verdict_b,
        confidence=conf_b,
    )

    provenance_all_valid = bool(provenance_a.get("is_valid") and provenance_b.get("is_valid"))
    return {
        "verifier_a": {
            "verdict": verdict_a,
            "confidence": conf_a,
            "reasoning": va.get("reasoning", ""),
            "payeeAddress": va.get("payeeAddress", ""),
            "reviewer_provenance": va.get("reviewer_provenance", {}),
        },
        "verifier_b": {
            "verdict": verdict_b,
            "confidence": conf_b,
            "reasoning": vb.get("reasoning", ""),
            "payeeAddress": vb.get("payeeAddress", ""),
            "reviewer_provenance": vb.get("reviewer_provenance", {}),
        },
        "provenance": {
            "required": True,
            "sourceHashExpected": source_hash_expected,
            "verifier_a": provenance_a,
            "verifier_b": provenance_b,
            "allValid": provenance_all_valid,
            "rule": "valid when both verifier provenance entries pass",
        },
        "weighted_score": score,
        "final_verdict": final_verdict,
        "rule": "PASS if score>0.5 else FAIL",
    }


def _effective_delta(current_score: int, raw_delta: int) -> int:
    # Enforce PRD rule: new=max(0, old+delta)
    if current_score + raw_delta >= 0:
        return raw_delta
    return -current_score


def _update_trust_onchain(
    w3: Web3,
    contract: Any,
    agent_id: int,
    delta: int,
    private_key: str,
) -> dict[str, Any]:
    pk = private_key if private_key.startswith("0x") else f"0x{private_key}"
    signer = Account.from_key(pk)

    owner = Web3.to_checksum_address(contract.functions.owner().call())
    if signer.address.lower() != owner.lower():
        raise PermissionError(
            f"CLIENT_PRIVATE_KEY address {signer.address} is not VTRegistry owner {owner}"
        )

    nonce = w3.eth.get_transaction_count(signer.address)
    gas_price = w3.eth.gas_price

    tx = contract.functions.updateTrust(agent_id, delta).build_transaction(
        {
            "from": signer.address,
            "chainId": CHAIN_ID,
            "nonce": nonce,
            "gasPrice": gas_price,
        }
    )

    if "gas" not in tx:
        tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)

    to_addr = str(tx.get("to") or contract.address)
    data_hex = str(tx.get("data") or "0x")
    value_raw = int(tx.get("value") or 0)

    _append_audit(
        "update_trust_tx_prepare",
        {
            "agentId": agent_id,
            "delta": delta,
            "from": signer.address,
            "to": to_addr,
            "nonce": nonce,
            "chainId": CHAIN_ID,
            "securityScanEnabled": CHALLENGE_ENABLE_SECURITY_SCAN,
            "simulateEnabled": CHALLENGE_ENABLE_SIMULATE,
            "allowWarnRisk": CHALLENGE_ALLOW_WARN_RISK,
        },
    )

    if CHALLENGE_ENABLE_SECURITY_SCAN:
        try:
            scan_result = _security_scan_tx(
                from_addr=signer.address,
                to_addr=to_addr,
                data_hex=data_hex,
                value_raw=value_raw,
            )
        except Exception as exc:
            _append_audit(
                "update_trust_security_scan_failed",
                {
                    "error": str(exc),
                },
            )
            raise

        _append_audit(
            "update_trust_security_scan",
            {
                "ok": bool(scan_result.get("ok")),
                "action": scan_result.get("action", ""),
                "error": scan_result.get("error", ""),
            },
        )
        if not scan_result.get("ok"):
            raise RuntimeError(str(scan_result.get("error", "security tx-scan failed")))

    if CHALLENGE_ENABLE_SIMULATE:
        try:
            sim_result = _simulate_tx(
                from_addr=signer.address,
                to_addr=to_addr,
                data_hex=data_hex,
                amount_raw=value_raw,
            )
        except Exception as exc:
            _append_audit(
                "update_trust_simulate_failed",
                {
                    "error": str(exc),
                },
            )
            raise

        _append_audit(
            "update_trust_simulate",
            {
                "ok": bool(sim_result.get("ok")),
                "error": sim_result.get("error", ""),
            },
        )
        if not sim_result.get("ok"):
            raise RuntimeError(str(sim_result.get("error", "gateway simulate failed")))

    signed = Account.sign_transaction(tx, pk)
    signed_tx_hex = signed.raw_transaction.hex()
    if not signed_tx_hex.startswith("0x"):
        signed_tx_hex = f"0x{signed_tx_hex}"

    try:
        broadcast = _broadcast_signed_tx(signed_tx_hex, signer.address)
    except Exception as exc:
        _append_audit(
            "update_trust_broadcast_failed",
            {
                "error": str(exc),
            },
        )
        raise

    _append_audit(
        "update_trust_broadcast",
        {
            "ok": bool(broadcast.get("ok")),
            "txHash": broadcast.get("txHash", ""),
            "orderId": broadcast.get("orderId", ""),
            "error": broadcast.get("error", ""),
        },
    )
    if not broadcast.get("ok"):
        raise RuntimeError(str(broadcast.get("error", "gateway broadcast failed")))

    order_id = str(broadcast.get("orderId") or "")
    order_status = ""
    tx_hash = str(broadcast.get("txHash") or "")

    if order_id:
        try:
            order_snapshot = _query_gateway_order(signer.address, order_id)
            order_status = str(order_snapshot.get("status") or "")
            tx_hash = tx_hash or str(order_snapshot.get("txHash") or "")
            _append_audit(
                "update_trust_order_snapshot",
                {
                    "orderId": order_id,
                    "orderStatus": order_status,
                    "txHash": tx_hash,
                },
            )
        except Exception as exc:
            _append_audit(
                "update_trust_order_snapshot_failed",
                {
                    "orderId": order_id,
                    "error": str(exc),
                },
            )

    if not tx_hash:
        raise RuntimeError("gateway broadcast succeeded but tx hash is unavailable")

    try:
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    except Exception as exc:
        _append_audit(
            "update_trust_receipt_failed",
            {
                "txHash": tx_hash,
                "error": str(exc),
            },
        )
        raise

    receipt_status = int(receipt.status)
    _append_audit(
        "update_trust_receipt",
        {
            "txHash": tx_hash,
            "status": receipt_status,
            "blockNumber": int(receipt.blockNumber),
            "orderId": order_id,
            "orderStatus": order_status,
        },
    )

    return {
        "txHash": tx_hash,
        "txStatus": receipt_status,
        "orderId": order_id,
        "orderStatus": order_status,
        "auditLogPath": str(CHALLENGE_AUDIT_LOG_PATH),
    }


def prepare_context(agent_id: int, registry_address: str, rpc_url: str, worker_url: str) -> dict[str, Any]:
    """Read deterministic context for Pro exam design (Step 1)."""
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise ConnectionError(f"Failed to connect RPC: {rpc_url}")

    contract = w3.eth.contract(address=Web3.to_checksum_address(registry_address), abi=VTREGISTRY_ABI)
    agent_chain = _read_agent_onchain(contract, agent_id)
    agent_desc = _load_agent_description(agent_id)
    _validate_agent_description(agent_desc, agent_id)
    trust_score = int(agent_chain["trustScore"])

    return {
        "success": True,
        "agent": {
            "agentId": agent_id,
            "name": agent_chain["name"],
            "creator": agent_chain["creator"],
            "wallet": agent_chain["wallet"],
            "status": agent_chain["status"],
            "trustScore": trust_score,
            "tier": _tier_from_score(trust_score),
        },
        "agentDescription": agent_desc,
        "executionEnvironment": {
            "workerTaskType": WORKER_TASK_TYPE,
            "workerUrl": worker_url,
        },
    }


def execute_challenge_only(
    agent_id: int,
    registry_address: str,
    worker_url: str,
    challenge_payload: dict[str, Any],
    rpc_url: str,
    worker_timeout: int,
) -> dict[str, Any]:
    """Execute Step 1/3/4a only (used before DAO review)."""
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise ConnectionError(f"Failed to connect RPC: {rpc_url}")

    contract = w3.eth.contract(address=Web3.to_checksum_address(registry_address), abi=VTREGISTRY_ABI)
    agent_chain = _read_agent_onchain(contract, agent_id)
    agent_desc = _load_agent_description(agent_id)
    _validate_agent_description(agent_desc, agent_id)
    trust_before = int(agent_chain["trustScore"])
    tier = _tier_from_score(trust_before)

    challenge_task = challenge_payload.get("challenge_task", {})
    task_type = str(challenge_task.get("task_type", "")).strip().lower()
    if not task_type:
        raise ValueError("challenge_task.task_type missing")
    if task_type != WORKER_TASK_TYPE:
        raise ValueError(
            f"Unsupported challenge_task.task_type='{task_type}', expected '{WORKER_TASK_TYPE}'"
        )

    supported_tasks = [str(t).strip().lower() for t in agent_desc.get("supportedTasks", [])]
    if task_type not in supported_tasks:
        raise ValueError(
            f"Agent description does not support task_type='{task_type}' (supported={supported_tasks})"
        )

    protocol = str(challenge_task.get("protocol", "")).strip().lower()
    if not protocol:
        raise ValueError("challenge_task.protocol missing")
    question = str(challenge_task.get("question", "")).strip()
    if not question:
        raise ValueError("challenge_task.question missing")

    consistency_cfg = None
    run_count = 1
    if tier == "silver":
        consistency_cfg = _parse_silver_consistency(challenge_payload)
        run_count = int(consistency_cfg["runs"])

    client_pk = os.getenv("CLIENT_PRIVATE_KEY", "").strip()
    if not client_pk:
        raise RuntimeError("CLIENT_PRIVATE_KEY missing in environment")
    client_wallet = Account.from_key(client_pk if client_pk.startswith("0x") else f"0x{client_pk}").address

    _log(f"Step 3: executing Worker task for protocol={protocol}, runs={run_count}")

    proof_bundles: list[dict[str, Any]] = []
    execution_runs: list[dict[str, Any]] = []
    trusted_runs: list[dict[str, Any]] = []

    for idx in range(run_count):
        _log(f"Step 3.{idx + 1}: run {idx + 1}/{run_count}")
        proof_bundle = _execute_worker(worker_url, task_type, protocol, client_wallet, worker_timeout)
        with redirect_stdout(sys.stderr):
            trusted_run = verify_proof_bundle(
                proof_bundle,
                require_signature=REQUIRE_ORIGIN_SIGNATURE,
            )

        proof_bundles.append(proof_bundle)
        trusted_runs.append(trusted_run if isinstance(trusted_run, dict) else {"is_valid": bool(trusted_run)})

        run_item = {
            "run": idx + 1,
            "trustedValid": bool(trusted_runs[-1].get("is_valid", False)),
        }
        if tier == "silver":
            run_item["tvlUsd"] = _extract_tvl_usd(proof_bundle)
        execution_runs.append(run_item)

        if consistency_cfg and idx < run_count - 1:
            interval_seconds = int(consistency_cfg["intervalSeconds"])
            if interval_seconds > 0:
                time.sleep(interval_seconds)

    valid_run_count = sum(1 for item in trusted_runs if bool(item.get("is_valid", False)))
    trusted_valid = valid_run_count == run_count

    trusted: dict[str, Any] = {
        "is_valid": trusted_valid,
        "runCount": run_count,
        "validRunCount": valid_run_count,
        "rule": "all runs trusted-valid",
        "originSignatureRequired": REQUIRE_ORIGIN_SIGNATURE,
    }

    if tier == "silver" and consistency_cfg:
        tvl_values = [float(item["tvlUsd"]) for item in execution_runs if "tvlUsd" in item]
        relative_variance_pct = _compute_relative_variance_pct(tvl_values)
        max_variance_pct = float(consistency_cfg["maxVariancePct"])
        consistency_pass = relative_variance_pct <= max_variance_pct
        trusted["consistency"] = {
            "runs": int(consistency_cfg["runs"]),
            "intervalSeconds": int(consistency_cfg["intervalSeconds"]),
            "maxVariancePct": max_variance_pct,
            "actualVariancePct": relative_variance_pct,
            "rule": "PASS if actualVariancePct <= maxVariancePct",
            "is_valid": consistency_pass,
        }
        trusted["is_valid"] = bool(trusted_valid and consistency_pass)
        trusted["rule"] = "silver: all runs trusted-valid AND consistency pass"

    last_proof_bundle = proof_bundles[-1]
    source_hash = _proof_bundle_source_hash(last_proof_bundle)
    trusted["sourceHash"] = source_hash
    trusted["sourceHashRule"] = "sha256(json.dumps(proofBundle.data, sort_keys=True))"

    return {
        "success": True,
        "mode": "execute-only",
        "agent": {
            "agentId": agent_id,
            "name": agent_chain["name"],
            "creator": agent_chain["creator"],
            "wallet": agent_chain["wallet"],
            "status": agent_chain["status"],
        },
        "context": {
            "tier": tier,
            "trustBefore": trust_before,
            "agentDescription": agent_desc,
            "challenge": challenge_payload,
        },
        "proofBundle": last_proof_bundle,
        "proofBundles": proof_bundles,
        "executionRuns": execution_runs,
        "trustedLayer": trusted,
    }


def finalize_trust_update(
    agent_id: int,
    registry_address: str,
    trusted_valid: bool,
    dao_payload: dict[str, Any] | None,
    expected_source_hash: str,
    rpc_url: str,
    dry_run: bool,
    verifier_reward_usdt: float,
    payment_retry_max: int,
    payment_retry_delay_ms: int,
) -> dict[str, Any]:
    """Execute Step 5 with trusted result + DAO payload."""
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise ConnectionError(f"Failed to connect RPC: {rpc_url}")

    contract = w3.eth.contract(address=Web3.to_checksum_address(registry_address), abi=VTREGISTRY_ABI)
    agent_chain = _read_agent_onchain(contract, agent_id)
    trust_before = int(agent_chain["trustScore"])
    tier = _tier_from_score(trust_before)

    if trusted_valid:
        if dao_payload is None:
            raise ValueError("dao payload required when trusted-valid=true")
        dao = _weighted_dao_decision(dao_payload, expected_source_hash=expected_source_hash)
        final_verdict = dao["final_verdict"]
        provenance_valid = bool(dao.get("provenance", {}).get("allValid", False))
        if not provenance_valid and CHALLENGE_BLOCK_FINALIZE_ON_PROVENANCE_INVALID:
            raise ValueError(
                "reviewer provenance invalid; finalize blocked (set "
                "CHALLENGE_BLOCK_FINALIZE_ON_PROVENANCE_INVALID=false to bypass)"
            )
    else:
        dao = {
            "final_verdict": "FAIL",
            "weighted_score": 0.0,
            "rule": "Trusted layer failed -> force FAIL",
            "provenance": {
                "required": True,
                "sourceHashExpected": _normalize_sha256(expected_source_hash),
                "allValid": False,
                "rule": "trusted-invalid short-circuit",
            },
        }
        final_verdict = "FAIL"
        provenance_valid = False

    raw_delta = PASS_DELTA[tier] if final_verdict == "PASS" else FAIL_DELTA[tier]
    effective_delta = _effective_delta(trust_before, raw_delta)
    trust_after = trust_before + effective_delta

    provenance_block = dao.get("provenance", {}) if isinstance(dao, dict) else {}
    verifier_a_provenance = provenance_block.get("verifier_a", {}) if isinstance(provenance_block, dict) else {}
    verifier_b_provenance = provenance_block.get("verifier_b", {}) if isinstance(provenance_block, dict) else {}

    _append_audit(
        "finalize_decision",
        {
            "agentId": agent_id,
            "tier": tier,
            "trustBefore": trust_before,
            "trustAfter": trust_after,
            "trustedValid": bool(trusted_valid),
            "daoVerdict": final_verdict,
            "weightedScore": dao.get("weighted_score") if isinstance(dao, dict) else None,
            "provenanceAllValid": bool(provenance_valid),
            "provenanceReasonA": verifier_a_provenance.get("reason") if isinstance(verifier_a_provenance, dict) else "",
            "provenanceReasonB": verifier_b_provenance.get("reason") if isinstance(verifier_b_provenance, dict) else "",
        },
    )

    tx_hash = None
    tx_status = None
    order_id = None
    order_status = None
    audit_log_path = str(CHALLENGE_AUDIT_LOG_PATH)
    if not dry_run:
        client_pk = os.getenv("CLIENT_PRIVATE_KEY", "").strip()
        if not client_pk:
            raise RuntimeError("CLIENT_PRIVATE_KEY missing in environment")
        tx_result = _update_trust_onchain(
            w3=w3,
            contract=contract,
            agent_id=agent_id,
            delta=effective_delta,
            private_key=client_pk,
        )
        tx_hash = tx_result.get("txHash")
        tx_status = tx_result.get("txStatus")
        order_id = tx_result.get("orderId")
        order_status = tx_result.get("orderStatus")
        audit_log_path = str(tx_result.get("auditLogPath") or CHALLENGE_AUDIT_LOG_PATH)
        if tx_status != 1:
            raise RuntimeError(f"updateTrust transaction failed: {tx_hash}")

    payment: dict[str, Any] = {
        "eligible": bool(trusted_valid and (provenance_valid or not CHALLENGE_BLOCK_FINALIZE_ON_PROVENANCE_INVALID)),
        "attempted": False,
        "success": False,
        "rule": "pay only when trusted-valid=true and both reviewer provenance checks pass",
        "trustedValid": bool(trusted_valid),
        "reviewerProvenanceValid": bool(provenance_valid),
        "daoConsensusPass": bool(final_verdict == "PASS"),
        "amountPerVerifierUsdt": verifier_reward_usdt,
        "totalAmountUsdt": verifier_reward_usdt * 2,
        "payees": [],
        "txHashes": [],
        "failedWallets": [],
        "results": [],
    }

    if not trusted_valid:
        payment["skippedReason"] = "trusted layer invalid"
    elif not provenance_valid and CHALLENGE_BLOCK_FINALIZE_ON_PROVENANCE_INVALID:
        payment["skippedReason"] = "reviewer provenance invalid"
    elif dry_run:
        payment["skippedReason"] = "dry-run mode"
    elif dao_payload is None:
        payment["skippedReason"] = "dao payload missing"
    else:
        try:
            payment_result = _pay_verifiers_for_challenge(
                dao_payload=dao_payload,
                amount_usdt=verifier_reward_usdt,
                max_retries=max(1, payment_retry_max),
                delay_ms=max(0, payment_retry_delay_ms),
            )
            payment = {**payment, **payment_result}
        except Exception as exc:
            payment["attempted"] = True
            payment["success"] = False
            payment["error"] = f"payment orchestration failed: {exc}"

    _append_audit(
        "finalize_payment",
        {
            "agentId": agent_id,
            "eligible": bool(payment.get("eligible", False)),
            "attempted": bool(payment.get("attempted", False)),
            "success": bool(payment.get("success", False)),
            "skippedReason": str(payment.get("skippedReason", "")),
            "failedWallets": payment.get("failedWallets", []),
            "txHashes": payment.get("txHashes", []),
        },
    )

    return {
        "success": True,
        "mode": "finalize-only",
        "agent": {
            "agentId": agent_id,
            "name": agent_chain["name"],
            "creator": agent_chain["creator"],
            "wallet": agent_chain["wallet"],
            "status": agent_chain["status"],
        },
        "decision": {
            "finalVerdict": final_verdict,
            "tier": tier,
            "trustBefore": trust_before,
            "trustAfter": trust_after,
            "rawDelta": raw_delta,
            "effectiveDelta": effective_delta,
            "formula": "new=max(0, old+delta)",
        },
        "dao": dao,
        "onchain": {
            "registry": registry_address,
            "updateTrustTxHash": tx_hash,
            "txStatus": tx_status,
            "gatewayOrderId": order_id,
            "gatewayOrderStatus": order_status,
            "auditLogPath": audit_log_path,
            "dryRun": dry_run,
        },
        "payment": payment,
    }


def validate_dao_only(dao_payload: dict[str, Any], expected_source_hash: str) -> dict[str, Any]:
    """Validate DAO reviewer provenance without writing on-chain state."""
    dao = _weighted_dao_decision(dao_payload, expected_source_hash=expected_source_hash)
    provenance = dao.get("provenance", {}) if isinstance(dao, dict) else {}
    provenance_valid = bool(provenance.get("allValid", False)) if isinstance(provenance, dict) else False

    issues: list[dict[str, Any]] = []
    for reviewer_key in ["verifier_a", "verifier_b"]:
        reviewer_result = provenance.get(reviewer_key, {}) if isinstance(provenance, dict) else {}
        if isinstance(reviewer_result, dict) and not bool(reviewer_result.get("is_valid", False)):
            issues.append(
                {
                    "reviewer": reviewer_key,
                    "reason": str(reviewer_result.get("reason", "unknown")),
                    "details": reviewer_result,
                }
            )

    return {
        "success": True,
        "mode": "validate-dao-only",
        "reviewerProvenanceValid": provenance_valid,
        "gateHint": "safe to run finalize" if provenance_valid else "regenerate verifier outputs before finalize",
        "issues": issues,
        "dao": dao,
    }


# --- Main flow -------------------------------------------------------------


def run_challenge(
    agent_id: int,
    registry_address: str,
    worker_url: str,
    challenge_payload: dict[str, Any],
    dao_payload: dict[str, Any] | None,
    rpc_url: str,
    worker_timeout: int,
    dry_run: bool,
    verifier_reward_usdt: float,
    payment_retry_max: int,
    payment_retry_delay_ms: int,
) -> dict[str, Any]:
    execution = execute_challenge_only(
        agent_id=agent_id,
        registry_address=registry_address,
        worker_url=worker_url,
        challenge_payload=challenge_payload,
        rpc_url=rpc_url,
        worker_timeout=worker_timeout,
    )

    trusted = execution["trustedLayer"]
    trusted_valid = bool(trusted.get("is_valid", False))
    source_hash_expected = str(trusted.get("sourceHash", "")).strip()
    finalization = finalize_trust_update(
        agent_id=agent_id,
        registry_address=registry_address,
        trusted_valid=trusted_valid,
        dao_payload=dao_payload,
        expected_source_hash=source_hash_expected,
        rpc_url=rpc_url,
        dry_run=dry_run,
        verifier_reward_usdt=verifier_reward_usdt,
        payment_retry_max=payment_retry_max,
        payment_retry_delay_ms=payment_retry_delay_ms,
    )

    result = {
        "success": True,
        "mode": "full",
        "agent": execution["agent"],
        "context": {
            **execution["context"],
            "trustAfter": finalization["decision"]["trustAfter"],
        },
        "proofBundle": execution["proofBundle"],
        "trustedLayer": execution["trustedLayer"],
        "dao": finalization["dao"],
        "decision": finalization["decision"],
        "onchain": finalization["onchain"],
        "payment": finalization["payment"],
    }

    if "proofBundles" in execution:
        result["proofBundles"] = execution["proofBundles"]
    if "executionRuns" in execution:
        result["executionRuns"] = execution["executionRuns"]

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="VeriVerse Challenge Orchestrator")
    parser.add_argument("--agent-id", type=int, required=True, help="Agent ID")
    parser.add_argument("--registry", default="", help="VTRegistry address")
    parser.add_argument("--worker-url", default=DEFAULT_WORKER_URL, help="Worker base URL")
    parser.add_argument("--rpc-url", default=DEFAULT_RPC_URL, help="BSC RPC URL")
    parser.add_argument("--worker-timeout", type=int, default=120, help="Worker timeout in seconds")

    parser.add_argument("--challenge-json", default="", help="Challenge JSON string")
    parser.add_argument("--challenge-file", default="", help="Path to challenge JSON file")
    parser.add_argument("--dao-json", default="", help="DAO JSON string")
    parser.add_argument("--dao-file", default="", help="Path to DAO JSON file")
    parser.add_argument(
        "--source-hash-expected",
        default="",
        help="Expected source hash for reviewer_provenance validation in finalize-only mode",
    )
    parser.add_argument("--precheck-only", action="store_true", help="Only run Step 0 balance precheck")
    parser.add_argument("--prepare-only", action="store_true", help="Only read Step 1 context")
    parser.add_argument("--execute-only", action="store_true", help="Run Step 1/3/4a only")
    parser.add_argument(
        "--validate-dao-only",
        action="store_true",
        help="Validate DAO reviewer_provenance only (no on-chain update)",
    )
    parser.add_argument("--finalize-only", action="store_true", help="Run Step 5 only")
    parser.add_argument("--dry-run", action="store_true", help="Do not send updateTrust transaction")
    parser.add_argument(
        "--trusted-valid",
        default="",
        help="Trusted layer result for --finalize-only (true|false)",
    )
    parser.add_argument(
        "--verifier-reward-usdt",
        type=float,
        default=DEFAULT_VERIFIER_REWARD_USDT,
        help="USDT reward per verifier when payment is eligible",
    )
    parser.add_argument(
        "--required-usdt",
        type=float,
        default=-1.0,
        help="Override required USDT threshold for precheck-only (default=max(0.01, reward*2))",
    )
    parser.add_argument(
        "--x402-retry-max",
        type=int,
        default=DEFAULT_X402_RETRY_MAX,
        help="Max retry count for each x402 payment",
    )
    parser.add_argument(
        "--x402-retry-delay-ms",
        type=int,
        default=DEFAULT_X402_RETRY_DELAY_MS,
        help="Delay in ms between x402 payment retries",
    )

    parser.add_argument(
        "--usdt-token",
        default="",
        help="USDT token contract address (overrides TOKEN_CONTRACT_ADDRESS env var)",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    # Override module-level USDT address if explicitly provided via CLI
    global USDT_TOKEN_CONTRACT
    if args.usdt_token:
        USDT_TOKEN_CONTRACT = args.usdt_token

    try:
        registry = _load_registry_address(args.registry or None)

        if args.precheck_only:
            required_usdt = (
                float(args.required_usdt)
                if args.required_usdt >= 0
                else _challenge_fee_required_usdt(args.verifier_reward_usdt)
            )
            balance = _precheck_challenger_balance(required_usdt)
            result = {
                "success": True,
                "mode": "precheck-only",
                "rule": "required=max(minChallengeFeeUsdt, verifierRewardUsdt*2)",
                "minChallengeFeeUsdt": MIN_CHALLENGE_FEE_USDT,
                "verifierRewardUsdt": float(args.verifier_reward_usdt),
                "derivedRequiredUsdt": _challenge_fee_required_usdt(args.verifier_reward_usdt),
                "precheck": balance,
            }
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
            else:
                state = "PASS" if balance.get("sufficient") else "FAIL"
                print(f"✅ Balance precheck {state} for Agent #{args.agent_id}")
            return

        if args.prepare_only:
            result = prepare_context(
                agent_id=args.agent_id,
                registry_address=registry,
                rpc_url=args.rpc_url,
                worker_url=args.worker_url,
            )
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
            else:
                print(f"✅ Prepared context for Agent #{args.agent_id}")
            return

        if args.execute_only:
            challenge_payload = _safe_load_json(args.challenge_json or None, args.challenge_file or None, "challenge")
            result = execute_challenge_only(
                agent_id=args.agent_id,
                registry_address=registry,
                worker_url=args.worker_url,
                challenge_payload=challenge_payload,
                rpc_url=args.rpc_url,
                worker_timeout=args.worker_timeout,
            )
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
            else:
                print(f"✅ Execute-only complete for Agent #{args.agent_id}")
            return

        if args.validate_dao_only:
            dao_payload = _safe_load_json(args.dao_json or None, args.dao_file or None, "dao")
            result = validate_dao_only(
                dao_payload=dao_payload,
                expected_source_hash=args.source_hash_expected,
            )
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
            else:
                status = "PASS" if result.get("reviewerProvenanceValid") else "FAIL"
                print(f"✅ DAO provenance preflight {status}")
            return

        if args.finalize_only:
            if args.trusted_valid == "":
                raise ValueError("--trusted-valid is required for --finalize-only")
            tv = args.trusted_valid.strip().lower()
            if tv not in {"true", "false"}:
                raise ValueError("--trusted-valid must be true or false")
            trusted_valid = tv == "true"
            dao_payload = None
            if args.dao_json or args.dao_file:
                dao_payload = _safe_load_json(args.dao_json or None, args.dao_file or None, "dao")

            result = finalize_trust_update(
                agent_id=args.agent_id,
                registry_address=registry,
                trusted_valid=trusted_valid,
                dao_payload=dao_payload,
                expected_source_hash=args.source_hash_expected,
                rpc_url=args.rpc_url,
                dry_run=args.dry_run,
                verifier_reward_usdt=args.verifier_reward_usdt,
                payment_retry_max=args.x402_retry_max,
                payment_retry_delay_ms=args.x402_retry_delay_ms,
            )
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
            else:
                print(f"✅ Finalize-only complete for Agent #{args.agent_id}")
            return

        challenge_payload = _safe_load_json(args.challenge_json or None, args.challenge_file or None, "challenge")
        dao_payload = None
        if args.dao_json or args.dao_file:
            dao_payload = _safe_load_json(args.dao_json or None, args.dao_file or None, "dao")

        started = time.time()
        result = run_challenge(
            agent_id=args.agent_id,
            registry_address=registry,
            worker_url=args.worker_url,
            challenge_payload=challenge_payload,
            dao_payload=dao_payload,
            rpc_url=args.rpc_url,
            worker_timeout=args.worker_timeout,
            dry_run=args.dry_run,
            verifier_reward_usdt=args.verifier_reward_usdt,
            payment_retry_max=args.x402_retry_max,
            payment_retry_delay_ms=args.x402_retry_delay_ms,
        )
        result["metrics"] = {"durationSec": round(time.time() - started, 3)}

        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        else:
            print(f"✅ Challenge complete for Agent #{args.agent_id}")
            print(f"Verdict: {result['decision']['finalVerdict']}")
            print(f"Delta: {result['decision']['effectiveDelta']}")
            print(f"Tx: {result['onchain']['updateTrustTxHash']}")

    except Exception as exc:
        out = {"success": False, "error": str(exc)}
        if args.json:
            print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            print(f"❌ Challenge failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
