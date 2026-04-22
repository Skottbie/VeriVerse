#!/usr/bin/env python3
"""
VeriVerse invest-agent: Backer invests USDT into Agent's Escrow.

Flow:
  1. Load CLIENT_PRIVATE_KEY → derive EOA address
  2. Check USDT balance via web3.py ERC-20 balanceOf (read-only)
  3. Sign approve(escrow, amount) locally → broadcast via web3.py
  4. Sign invest(agentId, amount) locally → broadcast via web3.py

Pattern: CLIENT_PRIVATE_KEY sign → web3.py send_raw_transaction
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from eth_abi import encode
from eth_account import Account
from eth_utils import to_checksum_address

# Load .env from openclaw workspace
for env_path in [
    Path("/home/skottbie/.openclaw/.env"),
    Path("/home/skottbie/.openclaw/workspace/.env"),
    Path(__file__).resolve().parent.parent.parent / ".env",
]:
    if env_path.exists():
        load_dotenv(env_path)


def keccak256(text: str) -> bytes:
    from web3 import Web3
    return Web3.keccak(text=text)


def function_selector(sig: str) -> bytes:
    """Return the 4-byte function selector for a Solidity signature."""
    return keccak256(sig)[:4]


# ── Config ────────────────────────────────────────────────────────────────

CHAIN_ID = int(os.getenv("CHAIN_ID", "97"))  # BSC testnet
CHAIN_INDEX = os.getenv("CHAIN_INDEX", "97")
CHAIN_NAME = "bsc"
RPC_URL = os.getenv("BSC_RPC_URL", "https://bsc-testnet-rpc.publicnode.com")
EXPLORER_BASE = os.getenv("EXPLORER_BASE", "https://testnet.bscscan.com/tx/")
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
USDT_DECIMALS = 6

# onchainos removed — all operations via web3.py / GoPlus API
INVEST_ENABLE_SECURITY_SCAN = os.environ.get("INVEST_ENABLE_SECURITY_SCAN", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
INVEST_ENABLE_SIMULATE = os.environ.get("INVEST_ENABLE_SIMULATE", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
INVEST_ALLOW_WARN_RISK = os.environ.get("INVEST_ALLOW_WARN_RISK", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
INVEST_AUTO_DEPLOY_TO_STRATEGY = os.environ.get("INVEST_AUTO_DEPLOY_TO_STRATEGY", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
AUDIT_LOG_PATH = Path(__file__).resolve().parents[2] / "data" / "audit" / "invest_agent.jsonl"


# ── Helpers ───────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    print(f"\033[36m[Invest] {msg}\033[0m", file=sys.stderr)


def _err(msg: str) -> None:
    print(f"\033[31m[Invest] ❌ {msg}\033[0m", file=sys.stderr)


# _run_onchainos removed — replaced by direct web3.py / GoPlus calls


def _get_nonce(address: str) -> int:
    """Get current nonce via BSC JSON-RPC."""
    resp = requests.post(
        RPC_URL,
        json={"jsonrpc": "2.0", "method": "eth_getTransactionCount",
              "params": [address, "latest"], "id": 1},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"RPC error: {data['error']}")
    return int(data["result"], 16)


def _get_gas_price() -> int:
    """Get current gas price via BSC JSON-RPC."""
    resp = requests.post(
        RPC_URL,
        json={"jsonrpc": "2.0", "method": "eth_gasPrice", "params": [], "id": 1},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"RPC error: {data['error']}")
    return int(data["result"], 16)


def _get_tx_receipt(tx_hash: str) -> dict[str, Any] | None:
    """Fetch transaction receipt from BSC JSON-RPC."""
    resp = requests.post(
        RPC_URL,
        json={"jsonrpc": "2.0", "method": "eth_getTransactionReceipt", "params": [tx_hash], "id": 1},
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "error" in payload:
        raise RuntimeError(f"RPC error: {payload['error']}")
    result = payload.get("result")
    if result is None:
        return None
    if not isinstance(result, dict):
        raise RuntimeError(f"Unexpected receipt result: {payload}")
    return result


def _wait_receipt_status(tx_hash: str, timeout_seconds: int = 20) -> str:
    """Wait for tx receipt status; return success/reverted/pending."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        receipt = _get_tx_receipt(tx_hash)
        if receipt is None:
            time.sleep(1)
            continue
        status_hex = str(receipt.get("status", "")).lower()
        if status_hex == "0x1":
            return "success"
        if status_hex == "0x0":
            return "reverted"
        return "unknown"
    return "pending"


def _eth_call(to_address: str, data_hex: str) -> str:
    """Run eth_call against BSC JSON-RPC and return raw hex result."""
    resp = requests.post(
        RPC_URL,
        json={
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [{"to": to_address, "data": data_hex}, "latest"],
            "id": 1,
        },
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "error" in payload:
        raise RuntimeError(f"RPC error: {payload['error']}")
    result = payload.get("result")
    if not isinstance(result, str) or not result.startswith("0x"):
        raise RuntimeError(f"Unexpected eth_call result: {payload}")
    return result


def _decode_abi_address(raw_hex: str) -> str:
    """Decode an ABI-encoded address return value (single 32-byte word)."""
    if not isinstance(raw_hex, str) or not raw_hex.startswith("0x"):
        raise RuntimeError(f"Invalid ABI hex: {raw_hex}")
    body = raw_hex[2:]
    if len(body) < 64:
        body = body.rjust(64, "0")
    addr_hex = "0x" + body[-40:]
    return to_checksum_address(addr_hex)


def _read_escrow_owner(escrow_address: str) -> str:
    """Read VeriEscrow.owner() via eth_call."""
    selector = "0x" + function_selector("owner()").hex()
    return _decode_abi_address(_eth_call(escrow_address, selector))


def _read_yield_strategy(escrow_address: str) -> str:
    """Read VeriEscrow.yieldStrategy() via eth_call."""
    selector = "0x" + function_selector("yieldStrategy()").hex()
    return _decode_abi_address(_eth_call(escrow_address, selector))


def _sign_tx(tx_dict: dict, private_key: str) -> str:
    """Sign a transaction and return raw signed tx hex."""
    for addr_key in ("to", "from"):
        if addr_key in tx_dict and isinstance(tx_dict[addr_key], str):
            tx_dict[addr_key] = to_checksum_address(tx_dict[addr_key])
    signed = Account.sign_transaction(tx_dict, private_key)
    return "0x" + signed.raw_transaction.hex()


def _broadcast(signed_tx_hex: str, wallet_address: str) -> dict:
    """Broadcast signed tx via BSC JSON-RPC send_raw_transaction."""
    resp = requests.post(
        RPC_URL,
        json={"jsonrpc": "2.0", "method": "eth_sendRawTransaction",
              "params": [signed_tx_hex], "id": 1},
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "error" in payload:
        return {"ok": False, "error": payload["error"].get("message", str(payload["error"]))}
    tx_hash = payload.get("result")
    return {"ok": True, "data": {"txHash": tx_hash}}


def _extract_tx_hash(result: dict) -> str | None:
    """Extract tx hash from broadcast response."""
    if not isinstance(result, dict):
        return None
    data = result.get("data")
    if isinstance(data, dict):
        return data.get("txHash")
    return result.get("result")


def _append_audit(event: str, payload: dict) -> None:
    """Append best-effort JSONL audit records for investment flow."""
    try:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,
            **payload,
        }
        with AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError):
        # Audit write must never block the main flow.
        return


def _extract_risk_action(scan_result: Any) -> str:
    """Extract security action from varied scan result shapes."""
    if isinstance(scan_result, dict):
        action = scan_result.get("action")
        if isinstance(action, str):
            return action.strip().lower()

        data = scan_result.get("data")
        if isinstance(data, dict):
            data_action = data.get("action")
            if isinstance(data_action, str):
                return data_action.strip().lower()
        if isinstance(data, list) and data and isinstance(data[0], dict):
            data_action = data[0].get("action")
            if isinstance(data_action, str):
                return data_action.strip().lower()

    if isinstance(scan_result, list) and scan_result and isinstance(scan_result[0], dict):
        action = scan_result[0].get("action")
        if isinstance(action, str):
            return action.strip().lower()

    return ""


def _extract_fail_reason(sim_result: Any) -> str:
    """Extract simulation failReason from varied result shapes."""
    if isinstance(sim_result, dict):
        direct = sim_result.get("failReason")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()

        data = sim_result.get("data")
        if isinstance(data, dict):
            fr = data.get("failReason")
            if isinstance(fr, str) and fr.strip():
                return fr.strip()
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    fr = item.get("failReason")
                    if isinstance(fr, str) and fr.strip():
                        return fr.strip()

    if isinstance(sim_result, list):
        for item in sim_result:
            if isinstance(item, dict):
                fr = item.get("failReason")
                if isinstance(fr, str) and fr.strip():
                    return fr.strip()

    return ""


def _simulate_tx(from_addr: str, to_addr: str, data_hex: str, amount_raw: int = 0) -> dict:
    """Simulate tx via eth_call as a pre-broadcast guardrail."""
    try:
        value_hex = hex(amount_raw) if amount_raw else "0x0"
        resp = requests.post(
            RPC_URL,
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


def _security_scan_tx(from_addr: str, to_addr: str, data_hex: str, value_raw: int = 0) -> dict:
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
            return {"ok": False, "error": "security: honeypot detected", "raw": data}
        if token_info.get("is_blacklisted") == "1":
            return {"ok": False, "error": "security: blacklisted token", "raw": data}
        return {"ok": True, "action": "pass", "raw": data}
    except Exception as e:
        _log(f"GoPlus security scan failed (non-blocking): {e}")
        return {"ok": True, "action": "skipped", "raw": None}


def encode_approve_calldata(spender: str, amount: int) -> str:
    """ABI-encode approve(address,uint256) calldata."""
    selector = function_selector("approve(address,uint256)")
    params = encode(["address", "uint256"], [spender, amount])
    return "0x" + selector.hex() + params.hex()


def encode_invest_calldata(agent_id: int, amount: int) -> str:
    """ABI-encode invest(uint256,uint256) calldata."""
    selector = function_selector("invest(uint256,uint256)")
    params = encode(["uint256", "uint256"], [agent_id, amount])
    return "0x" + selector.hex() + params.hex()


def encode_deploy_idle_calldata(amount: int) -> str:
    """ABI-encode deployIdleToStrategy(uint256) calldata."""
    selector = function_selector("deployIdleToStrategy(uint256)")
    params = encode(["uint256"], [amount])
    return "0x" + selector.hex() + params.hex()


# ── Balance Check ─────────────────────────────────────────────────────────

USDT_ADDRESS = os.getenv("USDT_ADDRESS", "0xF8De09e7772366A104c4d42269891AD1ca7Be720")


def check_usdt_balance(wallet_address: str) -> float | None:
    """Check USDT balance on BSC via ERC-20 balanceOf (read-only).
    Returns balance in UI units, or None if query failed."""
    try:
        selector = function_selector("balanceOf(address)")
        params = encode(["address"], [to_checksum_address(wallet_address)])
        data_hex = "0x" + selector.hex() + params.hex()
        raw = _eth_call(USDT_ADDRESS, data_hex)
        balance_raw = int(raw, 16)
        return balance_raw / (10 ** USDT_DECIMALS)
    except Exception:
        return None


def _auto_deploy_idle_to_strategy(escrow_address: str, amount_raw: int, fallback_private_key: str) -> dict[str, Any]:
    """Best-effort auto deploy using existing deployed Escrow (no contract redeploy required)."""
    result: dict[str, Any] = {
        "enabled": INVEST_AUTO_DEPLOY_TO_STRATEGY,
        "attempted": False,
        "success": False,
        "txHash": None,
        "error": None,
        "reasonCode": None,
        "simulateWarning": None,
        "receiptStatus": None,
        "escrowOwner": None,
        "strategy": None,
        "signer": None,
        "skippedReason": None,
        "ownerReadError": None,
        "strategyReadError": None,
    }

    if not INVEST_AUTO_DEPLOY_TO_STRATEGY:
        result["skippedReason"] = "disabled_by_env"
        result["reasonCode"] = "disabled_by_env"
        return result

    owner_addr: str | None = None
    strategy_addr: str | None = None

    try:
        owner_addr = _read_escrow_owner(escrow_address)
        result["escrowOwner"] = owner_addr
    except Exception as exc:
        result["ownerReadError"] = str(exc)

    try:
        strategy_addr = _read_yield_strategy(escrow_address)
        result["strategy"] = strategy_addr
    except Exception as exc:
        result["strategyReadError"] = str(exc)

    zero_addr = "0x0000000000000000000000000000000000000000"
    if strategy_addr is not None and strategy_addr.lower() == zero_addr.lower():
        result["skippedReason"] = "strategy_not_set"
        result["reasonCode"] = "strategy_not_set"
        return result

    owner_pk = os.getenv("ESCROW_OWNER_PRIVATE_KEY", "").strip()
    signer_pk = owner_pk if owner_pk else fallback_private_key
    signer_pk = signer_pk if signer_pk.startswith("0x") else f"0x{signer_pk}"

    try:
        signer_addr = Account.from_key(signer_pk).address
        result["signer"] = signer_addr
    except Exception as exc:
        result["error"] = f"invalid_signer_private_key: {exc}"
        return result

    if owner_addr is not None and signer_addr.lower() != owner_addr.lower():
        result["skippedReason"] = "signer_not_owner"
        result["reasonCode"] = "signer_not_owner"
        return result

    deploy_calldata = encode_deploy_idle_calldata(amount_raw)
    result["attempted"] = True

    if INVEST_ENABLE_SECURITY_SCAN:
        scan_result = _security_scan_tx(signer_addr, escrow_address, deploy_calldata, 0)
        if not scan_result.get("ok"):
            result["error"] = f"security_scan_blocked: {scan_result.get('error', 'unknown')}"
            return result

    if INVEST_ENABLE_SIMULATE:
        sim_result = _simulate_tx(signer_addr, escrow_address, deploy_calldata, 0)
        if not sim_result.get("ok"):
            # Auto deploy is a best-effort post-step: keep attempting broadcast
            # even when simulation cannot pass deterministically on this RPC.
            result["simulateWarning"] = sim_result.get("error", "unknown")
            result["error"] = f"simulate_failed_but_continue: {sim_result.get('error', 'unknown')}"

    try:
        gas_price = _get_gas_price()
        nonce = _get_nonce(signer_addr)
        tx = {
            "to": escrow_address,
            "data": bytes.fromhex(deploy_calldata[2:]),
            "value": 0,
            "gas": 300000,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": CHAIN_ID,
        }
        signed = _sign_tx(tx, signer_pk)
        broadcast = _broadcast(signed, signer_addr)
        if not broadcast.get("ok"):
            broadcast_error = str(broadcast.get("error", "unknown"))
            if result.get("ownerReadError") and result.get("strategyReadError") and "execution reverted" in broadcast_error.lower():
                result["reasonCode"] = "likely_contract_incompatible"
                result["error"] = "broadcast_failed: likely contract lacks strategy methods on deployed address"
            else:
                result["reasonCode"] = "broadcast_failed"
                result["error"] = f"broadcast_failed: {broadcast_error}"
            return result

        tx_hash = _extract_tx_hash(broadcast)
        result["txHash"] = tx_hash
        if tx_hash:
            receipt_status = _wait_receipt_status(tx_hash)
            result["receiptStatus"] = receipt_status
            if receipt_status == "success":
                result["success"] = True
                result["reasonCode"] = "ok"
                return result
            if receipt_status == "reverted":
                if result.get("ownerReadError") and result.get("strategyReadError"):
                    result["reasonCode"] = "likely_contract_incompatible"
                    result["error"] = "auto deploy tx reverted on-chain; deployed escrow likely lacks strategy methods"
                else:
                    result["reasonCode"] = "tx_reverted"
                    result["error"] = "auto deploy tx reverted on-chain"
                return result

            result["reasonCode"] = "receipt_pending"
            result["error"] = "auto deploy tx broadcasted but receipt pending"
            return result

        result["success"] = True
        result["reasonCode"] = "broadcast_only"
        return result
    except Exception as exc:
        result["reasonCode"] = "deploy_exception"
        result["error"] = f"deploy_exception: {exc}"
        return result

def invest_agent(agent_id: int, amount_usdt: float, escrow_address: str, usdt_address: str) -> dict:
    """
    Full invest flow using CLIENT_PRIVATE_KEY (regular EOA, not AA wallet):
    1. Load private key → derive address (0x012e...)
    2. Check USDT balance via web3.py ERC-20 balanceOf
    3. Sign approve(escrow, amount) → broadcast via BSC RPC
    4. Sign invest(agentId, amount) → broadcast via BSC RPC
    """

    # Input validation
    if not ADDRESS_RE.match(escrow_address):
        return {"success": False, "error": f"Invalid escrow address: {escrow_address}"}
    if not ADDRESS_RE.match(usdt_address):
        return {"success": False, "error": f"Invalid USDT address: {usdt_address}"}
    if agent_id <= 0:
        return {"success": False, "error": "Agent ID must be positive"}
    if amount_usdt <= 0:
        return {"success": False, "error": "Amount must be positive"}

    amount_raw = int(amount_usdt * (10 ** USDT_DECIMALS))
    _append_audit(
        "invest_start",
        {
            "agentId": agent_id,
            "amountUsdt": amount_usdt,
            "escrow": escrow_address,
            "usdt": usdt_address,
        },
    )

    # Step 1: Load private key and derive EOA address
    private_key = os.getenv("CLIENT_PRIVATE_KEY", "")
    if not private_key:
        _append_audit("invest_failed", {"reason": "missing_client_private_key"})
        return {"success": False, "error": "CLIENT_PRIVATE_KEY not set in .env"}
    pk_hex = private_key if private_key.startswith("0x") else f"0x{private_key}"
    backer_wallet = Account.from_key(pk_hex).address
    _log(f"Backer wallet (EOA): {backer_wallet}")

    # Step 2: Check USDT balance
    _log(f"Checking USDT balance for {backer_wallet[:10]}...")
    usdt_balance = check_usdt_balance(backer_wallet)

    if usdt_balance is None:
        _append_audit("invest_failed", {"reason": "balance_query_failed", "wallet": backer_wallet})
        return {"success": False, "error": "USDT balance query failed (API error)."}

    _log(f"USDT balance: {usdt_balance}")

    if usdt_balance < amount_usdt:
        _append_audit(
            "invest_failed",
            {
                "reason": "insufficient_usdt",
                "wallet": backer_wallet,
                "balance": usdt_balance,
                "needed": amount_usdt,
            },
        )
        return {
            "success": False,
            "error": f"Insufficient USDT: have {usdt_balance}, need {amount_usdt}. Please swap tokens to USDT first.",
            "balance": usdt_balance,
            "needed": amount_usdt,
        }

    # Step 3: Approve USDT spending by Escrow contract
    _log(f"Approving {amount_usdt} USDT for Escrow...")
    approve_calldata = encode_approve_calldata(escrow_address, amount_raw)

    if INVEST_ENABLE_SECURITY_SCAN:
        scan_result = _security_scan_tx(backer_wallet, usdt_address, approve_calldata, 0)
        _append_audit("approve_security_scan", {"ok": scan_result.get("ok"), "error": scan_result.get("error")})
        if not scan_result.get("ok"):
            return {
                "success": False,
                "error": f"Approve blocked by security scan: {scan_result.get('error', 'unknown error')}",
            }

    if INVEST_ENABLE_SIMULATE:
        sim_result = _simulate_tx(backer_wallet, usdt_address, approve_calldata, 0)
        _append_audit("approve_simulate", {"ok": sim_result.get("ok"), "error": sim_result.get("error")})
        if not sim_result.get("ok"):
            return {
                "success": False,
                "error": f"Approve blocked by simulation: {sim_result.get('error', 'unknown error')}",
            }

    try:
        gas_price = _get_gas_price()
        nonce = _get_nonce(backer_wallet)
        _log(f"  nonce={nonce}, gasPrice={gas_price}")

        approve_tx = {
            "to": usdt_address,
            "data": bytes.fromhex(approve_calldata[2:]),
            "value": 0,
            "gas": 200000,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": CHAIN_ID,
        }
        signed_approve = _sign_tx(approve_tx, pk_hex)
        approve_result = _broadcast(signed_approve, backer_wallet)
        _append_audit("approve_broadcast", {"ok": approve_result.get("ok"), "tx": _extract_tx_hash(approve_result)})

        if not approve_result.get("ok"):
            err = approve_result.get("error", "Unknown broadcast error")
            _append_audit("invest_failed", {"reason": "approve_broadcast_failed", "error": err})
            return {"success": False, "error": f"USDT approve broadcast failed: {err}"}

        approve_tx_hash = _extract_tx_hash(approve_result)
        _log(f"  Approve txHash: {approve_tx_hash}")

        # Wait for approve to confirm
        time.sleep(3)
    except Exception as e:
        _append_audit("invest_failed", {"reason": "approve_exception", "error": str(e)})
        return {"success": False, "error": f"USDT approve failed: {e}"}

    # Step 4: Call VeriEscrow.invest(agentId, amount)
    _log(f"Investing {amount_usdt} USDT into Agent #{agent_id}...")
    invest_calldata = encode_invest_calldata(agent_id, amount_raw)

    if INVEST_ENABLE_SECURITY_SCAN:
        scan_result = _security_scan_tx(backer_wallet, escrow_address, invest_calldata, 0)
        _append_audit("invest_security_scan", {"ok": scan_result.get("ok"), "error": scan_result.get("error")})
        if not scan_result.get("ok"):
            return {
                "success": False,
                "error": f"Invest blocked by security scan: {scan_result.get('error', 'unknown error')}",
            }

    if INVEST_ENABLE_SIMULATE:
        sim_result = _simulate_tx(backer_wallet, escrow_address, invest_calldata, 0)
        _append_audit("invest_simulate", {"ok": sim_result.get("ok"), "error": sim_result.get("error")})
        if not sim_result.get("ok"):
            return {
                "success": False,
                "error": f"Invest blocked by simulation: {sim_result.get('error', 'unknown error')}",
            }

    try:
        nonce = _get_nonce(backer_wallet)
        invest_tx = {
            "to": escrow_address,
            "data": bytes.fromhex(invest_calldata[2:]),
            "value": 0,
            "gas": 300000,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": CHAIN_ID,
        }
        signed_invest = _sign_tx(invest_tx, pk_hex)
        invest_result = _broadcast(signed_invest, backer_wallet)
        _append_audit("invest_broadcast", {"ok": invest_result.get("ok"), "tx": _extract_tx_hash(invest_result)})

        if not invest_result.get("ok"):
            err = invest_result.get("error", "Unknown broadcast error")
            _append_audit("invest_failed", {"reason": "invest_broadcast_failed", "error": err})
            return {"success": False, "error": f"Escrow invest broadcast failed: {err}"}

        invest_tx_hash = _extract_tx_hash(invest_result)
        _log(f"  Invest txHash: {invest_tx_hash}")
    except Exception as e:
        _append_audit("invest_failed", {"reason": "invest_exception", "error": str(e)})
        return {"success": False, "error": f"Escrow invest failed: {e}"}

    _append_audit(
        "invest_success",
        {
            "agentId": agent_id,
            "backer": backer_wallet,
            "amount": amount_usdt,
            "approveTx": approve_tx_hash,
            "investTx": invest_tx_hash,
        },
    )

    auto_deploy_result = _auto_deploy_idle_to_strategy(escrow_address, amount_raw, pk_hex)
    _append_audit(
        "auto_deploy_strategy",
        {
            "agentId": agent_id,
            "attempted": auto_deploy_result.get("attempted"),
            "success": auto_deploy_result.get("success"),
            "txHash": auto_deploy_result.get("txHash"),
            "error": auto_deploy_result.get("error"),
            "skippedReason": auto_deploy_result.get("skippedReason"),
        },
    )

    return {
        "success": True,
        "agentId": agent_id,
        "backer": backer_wallet,
        "amount": str(amount_usdt),
        "approveTxHash": approve_tx_hash or "pending",
        "investTxHash": invest_tx_hash or "pending",
        "autoDeployToStrategy": auto_deploy_result,
        "explorerUrl": f"{EXPLORER_BASE}{invest_tx_hash}" if invest_tx_hash else None,
        "escrowAddress": escrow_address,
        "auditLogPath": str(AUDIT_LOG_PATH),
    }


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="VeriVerse Backer Invest")
    parser.add_argument("--agent-id", type=int, required=True, help="Agent ID to invest in")
    parser.add_argument("--amount", type=float, required=True, help="USDT amount")
    parser.add_argument("--escrow", required=True, help="VeriEscrow contract address")
    parser.add_argument("--usdt", default=os.getenv("USDT_ADDRESS", "0xF8De09e7772366A104c4d42269891AD1ca7Be720"),
                        help="USDT contract address on BSC")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    result = invest_agent(args.agent_id, args.amount, args.escrow, args.usdt)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if result["success"]:
            print(f"💰 投资成功！")
            print(f"📛 Agent: #{result['agentId']}")
            print(f"💼 Backer 钱包: {result['backer']}")
            print(f"💵 金额: {result['amount']} USDT")
            print(f"🔗 交易: {result.get('explorerUrl', 'pending')}")
        else:
            print(f"❌ 投资失败: {result['error']}")
            sys.exit(1)


if __name__ == "__main__":
    main()
