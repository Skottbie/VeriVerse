#!/usr/bin/env python3
"""
token_launcher.py — VeriVerse Agent Token 发射器（Mock 模式）

校验：Graduated + SBT holder → 生成 Mock Token CA → linkAgentToken 上链

Usage:
    python3 token_launcher.py --agent-id 4 --registry 0x... --sbt 0x... --json
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from eth_abi import encode as abi_encode
from eth_account import Account
from web3 import Web3


# ── Env loading (same pattern as other skills) ────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parents[2]

for env_path in [
    Path("/home/skottbie/.openclaw/.env"),
    Path("/home/skottbie/.openclaw/workspace/.env"),
    PROJECT_ROOT.parent / ".env",
    PROJECT_ROOT / ".env",
]:
    if env_path.exists():
        load_dotenv(env_path, override=False)


# ── Constants ─────────────────────────────────────────────────────────

CHAIN_ID = int(os.getenv("CHAIN_ID", "97"))
RPC_URL = os.getenv("BSC_RPC_URL", "https://bsc-testnet-rpc.publicnode.com")
EXPLORER_BASE = os.getenv("EXPLORER_BASE", "https://testnet.bscscan.com/tx/")
VERIFY_BASE_URL = os.getenv("VERIFY_BASE_URL", "http://127.0.0.1:3001")

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# ABI fragments
REGISTRY_ABI = [
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
        "inputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "name": "agentTokenCA",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "agentId", "type": "uint256"},
            {"internalType": "address", "name": "tokenCA", "type": "address"},
        ],
        "name": "linkAgentToken",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

SBT_ABI = [
    {
        "inputs": [{"internalType": "uint256", "name": "agentId", "type": "uint256"}],
        "name": "holderOf",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]


# ── Helpers ───────────────────────────────────────────────────────────


def _generate_mock_token_ca(agent_id: int) -> str:
    """Generate a deterministic mock Token CA from agentId.

    Format: 0x + 28 zeros + agentId (8 hex) + 4444
    Obviously recognizable as test address with 4444 suffix.
    """
    addr = f"0x{'0' * 28}{agent_id:08x}4444"
    return Web3.to_checksum_address(addr)


def _fail(msg: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"success": False, "error": msg}, ensure_ascii=False))
    else:
        print(f"❌ {msg}", file=sys.stderr)
    sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="VeriVerse Agent Token Launcher")
    parser.add_argument("--agent-id", type=int, required=True, help="Agent ID")
    parser.add_argument("--registry", required=True, help="VTRegistry address")
    parser.add_argument("--sbt", required=True, help="VeriSBT address")
    parser.add_argument("--private-key", default=None, help="Override CLIENT_PRIVATE_KEY (for local testing)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    agent_id = args.agent_id
    as_json = args.json

    # ── 0. Private key ────────────────────────────────────────────────
    client_pk = (args.private_key or os.getenv("CLIENT_PRIVATE_KEY", "")).strip()
    if not client_pk:
        _fail("CLIENT_PRIVATE_KEY missing in environment", as_json)

    pk_hex = client_pk if client_pk.startswith("0x") else f"0x{client_pk}"
    account = Account.from_key(pk_hex)
    caller = account.address

    w3 = Web3(Web3.HTTPProvider(RPC_URL))

    registry_addr = Web3.to_checksum_address(args.registry)
    sbt_addr = Web3.to_checksum_address(args.sbt)

    registry = w3.eth.contract(address=registry_addr, abi=REGISTRY_ABI)
    sbt = w3.eth.contract(address=sbt_addr, abi=SBT_ABI)

    # ── 1. Check agent graduated ──────────────────────────────────────
    try:
        agent_data = registry.functions.getAgent(agent_id).call()
    except Exception as e:
        _fail(f"getAgent({agent_id}) failed: {e}", as_json)

    agent_name = agent_data[0]
    agent_status = agent_data[4]

    if agent_status != 1:
        status_labels = {0: "ACTIVE", 1: "GRADUATED", 2: "DEACTIVATED"}
        label = status_labels.get(agent_status, f"UNKNOWN({agent_status})")
        _fail(f"Agent #{agent_id} is {label}, not GRADUATED. Cannot launch token.", as_json)

    # ── 2. Check SBT holder == caller ─────────────────────────────────
    try:
        sbt_holder = sbt.functions.holderOf(agent_id).call()
    except Exception as e:
        _fail(f"SBT.holderOf({agent_id}) failed: {e}", as_json)

    if sbt_holder == ZERO_ADDRESS:
        _fail(f"Agent #{agent_id} has no SBT minted. Graduate first.", as_json)

    if sbt_holder.lower() != caller.lower():
        _fail(
            f"SBT holder ({sbt_holder[:10]}...) != caller ({caller[:10]}...). "
            f"Only the SBT holder can launch the Agent Token.",
            as_json,
        )

    # ── 3. Check no existing token ────────────────────────────────────
    try:
        existing_ca = registry.functions.agentTokenCA(agent_id).call()
    except Exception:
        existing_ca = ZERO_ADDRESS

    if existing_ca != ZERO_ADDRESS:
        _fail(
            f"Agent #{agent_id} already has a Token linked: {existing_ca}. "
            f"linkAgentToken is one-time immutable.",
            as_json,
        )

    # ── 4. Generate mock token ────────────────────────────────────────
    mock_ca = _generate_mock_token_ca(agent_id)
    token_name = f"VeriAgent_{agent_id}"
    token_symbol = f"VAGT{agent_id}"
    verify_url = f"{VERIFY_BASE_URL}/verify/agent/{agent_id}"
    description = f"VeriVerse Certified Agent #{agent_id} | Verify: {verify_url}"

    if not as_json:
        print(f"🚀 Launching Agent Token for #{agent_id} ({agent_name})...")
        print(f"   Mock Token CA: {mock_ca}")
        print(f"   Calling linkAgentToken({agent_id}, {mock_ca})...")

    # ── 5. Call linkAgentToken on-chain ────────────────────────────────
    try:
        tx_data = registry.functions.linkAgentToken(agent_id, mock_ca).build_transaction(
            {
                "from": caller,
                "nonce": w3.eth.get_transaction_count(caller),
                "gas": 150_000,
                "gasPrice": w3.eth.gas_price,
                "chainId": CHAIN_ID,
            }
        )
        signed = account.sign_transaction(tx_data)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    except Exception as e:
        _fail(f"linkAgentToken TX failed: {e}", as_json)

    tx_hash_hex = receipt.transactionHash.hex()
    if not tx_hash_hex.startswith("0x"):
        tx_hash_hex = f"0x{tx_hash_hex}"

    success = receipt.status == 1

    result = {
        "success": success,
        "agentId": agent_id,
        "agentName": agent_name,
        "tokenCA": mock_ca,
        "tokenName": token_name,
        "tokenSymbol": token_symbol,
        "tokenMode": "mock",
        "description": description,
        "linkTxHash": tx_hash_hex,
        "explorerUrl": f"{EXPLORER_BASE}{tx_hash_hex}",
        "verifyUrl": verify_url,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if not success:
        result["error"] = "linkAgentToken transaction reverted"

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        if success:
            print(f"✅ Agent Token launched!")
            print(f"   Token: {token_name} ({token_symbol})")
            print(f"   CA: {mock_ca}")
            print(f"   TX: {EXPLORER_BASE}{tx_hash_hex}")
            print(f"   Verify: {verify_url}")
        else:
            print(f"❌ linkAgentToken reverted. TX: {EXPLORER_BASE}{tx_hash_hex}")


if __name__ == "__main__":
    main()
