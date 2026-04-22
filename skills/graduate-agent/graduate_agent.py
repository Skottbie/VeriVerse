#!/usr/bin/env python3
"""
graduate_agent.py — P4 毕业授权执行器（原子式）

No-touch mode:
  - If proof is not provided, auto-generate from local semaphore identity store.
  - If token-uri is not provided, auto-generate metadata URI (Pinata if configured,
    otherwise deterministic local ipfs:// fallback).

Flow:
    1) graduateAtomicByProof(agentId, proof, signalHash, tokenUri)
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3

CHAIN_ID = int(os.getenv("CHAIN_ID", "97"))
RPC_URL = os.getenv("BSC_RPC_URL", "https://bsc-testnet-rpc.publicnode.com")
EXPLORER_BASE = os.getenv("EXPLORER_BASE", "https://testnet.bscscan.com/tx/")
SEMAPHORE_TREE_DEPTH = int(os.getenv("SEMAPHORE_TREE_DEPTH", "20"))

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ADDRESSES_FILE = PROJECT_ROOT / "addresses.json"
SEMAPHORE_IDENTITY_DIR = PROJECT_ROOT / "data" / "semaphore-identities"
SEMAPHORE_TOOLS = PROJECT_ROOT / "scripts" / "semaphore_local_tools.mjs"

for env_path in [
    Path("/home/skottbie/.openclaw/.env"),
    Path("/home/skottbie/.openclaw/workspace/.env"),
    PROJECT_ROOT.parent / ".env",
    PROJECT_ROOT / ".env",
]:
    if env_path.exists():
        load_dotenv(env_path, override=False)

ESCROW_ABI = [
    {
        "inputs": [],
        "name": "owner",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "semaphore",
        "outputs": [{"internalType": "contract ISemaphore", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "name": "agentGroupId",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "agentId", "type": "uint256"},
            {
                "components": [
                    {"internalType": "uint256", "name": "merkleTreeDepth", "type": "uint256"},
                    {"internalType": "uint256", "name": "merkleTreeRoot", "type": "uint256"},
                    {"internalType": "uint256", "name": "nullifier", "type": "uint256"},
                    {"internalType": "uint256", "name": "message", "type": "uint256"},
                    {"internalType": "uint256", "name": "scope", "type": "uint256"},
                    {"internalType": "uint256[8]", "name": "points", "type": "uint256[8]"},
                ],
                "internalType": "struct ISemaphore.SemaphoreProof",
                "name": "proof",
                "type": "tuple",
            },
            {"internalType": "uint256", "name": "signalHash", "type": "uint256"},
        ],
        "name": "authorizeGraduateByProof",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "agentId", "type": "uint256"},
            {
                "components": [
                    {"internalType": "uint256", "name": "merkleTreeDepth", "type": "uint256"},
                    {"internalType": "uint256", "name": "merkleTreeRoot", "type": "uint256"},
                    {"internalType": "uint256", "name": "nullifier", "type": "uint256"},
                    {"internalType": "uint256", "name": "message", "type": "uint256"},
                    {"internalType": "uint256", "name": "scope", "type": "uint256"},
                    {"internalType": "uint256[8]", "name": "points", "type": "uint256[8]"},
                ],
                "internalType": "struct ISemaphore.SemaphoreProof",
                "name": "proof",
                "type": "tuple",
            },
            {"internalType": "uint256", "name": "signalHash", "type": "uint256"},
            {"internalType": "string", "name": "tokenUri", "type": "string"},
        ],
        "name": "graduateAtomicByProof",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

SEMAPHORE_ABI = [
    {
        "inputs": [{"internalType": "uint256", "name": "groupId", "type": "uint256"}],
        "name": "getMerkleTreeRoot",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }
]


def _to_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("0x"):
            return int(value, 16)
        return int(value)
    raise ValueError(f"Unsupported numeric value: {value}")


def _expected_scope(agent_id: int, chain_id: int) -> int:
    return int.from_bytes(
        Web3.solidity_keccak(["string", "uint256", "uint256"], ["graduate", agent_id, chain_id]),
        byteorder="big",
    )


def _expected_signal(agent_id: int, chain_id: int) -> int:
    return int.from_bytes(
        Web3.solidity_keccak(["string", "uint256", "uint256"], ["graduate-signal", agent_id, chain_id]),
        byteorder="big",
    )


def _load_default_escrow() -> str:
    if not ADDRESSES_FILE.exists():
        raise ValueError("Escrow required: --escrow or addresses.json")

    try:
        data = json.loads(ADDRESSES_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid addresses.json: {exc}") from exc

    escrow = (data.get("bsc") or {}).get("VeriEscrow")
    if not isinstance(escrow, str) or not Web3.is_address(escrow):
        raise ValueError("Escrow missing or invalid in addresses.json[bsc].VeriEscrow")
    return escrow


def _run_node_tool(args: list[str]) -> dict[str, Any]:
    if not SEMAPHORE_TOOLS.exists():
        raise RuntimeError(f"Semaphore helper not found: {SEMAPHORE_TOOLS}")

    cmd = ["node", str(SEMAPHORE_TOOLS)] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        err = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"semaphore helper failed: {err}")

    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid semaphore helper output: {exc}") from exc


def _load_identity_payload(agent_id: int) -> dict[str, Any]:
    identity_path = SEMAPHORE_IDENTITY_DIR / f"{agent_id}.json"
    if not identity_path.exists():
        raise ValueError("Authorization material unavailable (GRAD-AUTH-01)")

    try:
        payload = json.loads(identity_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Authorization material invalid (GRAD-AUTH-02)") from exc

    if not payload.get("identityExport") or not payload.get("commitment"):
        raise ValueError("Authorization material incomplete (GRAD-AUTH-03)")
    return payload


def _auto_generate_proof(
    agent_id: int,
    expected_signal: int,
    expected_scope: int,
    w3: Web3,
    escrow,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = _load_identity_payload(agent_id)
    identity_export = str(payload["identityExport"])
    commitment = str(payload["commitment"])

    group_id = int(escrow.functions.agentGroupId(agent_id).call())
    if group_id == 0:
        raise ValueError(f"Agent #{agent_id} has no semaphore group binding")

    proof_bundle = _run_node_tool(
        [
            "generate-proof",
            "--identity",
            identity_export,
            "--commitment",
            commitment,
            "--signal",
            str(expected_signal),
            "--scope",
            str(expected_scope),
            "--group-id",
            str(group_id),
            "--merkle-tree-depth",
            str(SEMAPHORE_TREE_DEPTH),
        ]
    )

    proof = proof_bundle.get("proof")
    if not isinstance(proof, dict):
        raise ValueError("Invalid proof payload generated by semaphore helper")

    semaphore_address = escrow.functions.semaphore().call()
    semaphore = w3.eth.contract(address=Web3.to_checksum_address(semaphore_address), abi=SEMAPHORE_ABI)
    chain_root = int(semaphore.functions.getMerkleTreeRoot(group_id).call())
    local_root = _to_int(str(proof.get("merkleTreeRoot", proof_bundle.get("groupRoot", "0"))))

    if local_root != chain_root:
        raise ValueError("Authorization root mismatch (GRAD-AUTH-04)")

    return proof, {
        "identityPath": str(SEMAPHORE_IDENTITY_DIR / f"{agent_id}.json"),
        "groupId": group_id,
        "groupRoot": str(local_root),
        "semaphore": semaphore_address,
    }


def _load_proof_from_args(args: argparse.Namespace) -> dict[str, Any] | None:
    if args.proof_file:
        with open(args.proof_file, "r", encoding="utf-8") as f:
            return json.load(f)
    if args.proof_json:
        return json.loads(args.proof_json)
    return None


def _normalize_proof(raw: dict[str, Any]) -> tuple[int, int, int, int, int, list[int]]:
    depth = _to_int(raw.get("merkleTreeDepth"))
    root = _to_int(raw.get("merkleTreeRoot"))
    nullifier = _to_int(raw.get("nullifier", raw.get("nullifierHash")))
    message = _to_int(raw.get("message", raw.get("signalHash")))
    scope = _to_int(raw.get("scope", raw.get("externalNullifier")))

    points_raw = raw.get("points")
    if not isinstance(points_raw, list) or len(points_raw) != 8:
        raise ValueError("proof.points must be a list with 8 items")
    points = [_to_int(x) for x in points_raw]

    return depth, root, nullifier, message, scope, points


def _upload_metadata_to_pinata(metadata: dict[str, Any]) -> tuple[str | None, str | None]:
    jwt = os.getenv("PINATA_JWT", "").strip()
    if not jwt:
        return None, None

    body = {
        "pinataMetadata": {
            "name": f"veriverse-graduate-{metadata.get('agentId', 'unknown')}"
        },
        "pinataContent": metadata,
    }

    req = Request(
        "https://api.pinata.cloud/pinning/pinJSONToIPFS",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {jwt}",
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=25) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            ipfs_hash = payload.get("IpfsHash")
            if ipfs_hash:
                return f"ipfs://{ipfs_hash}", str(ipfs_hash)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None, None

    return None, None


def _build_auto_token_uri(agent_id: int, signer: str, escrow_address: str) -> tuple[str, dict[str, Any]]:
    metadata = {
        "name": f"VeriVerse Graduation Credential #{agent_id}",
        "description": "Auto-generated by local no-touch graduation flow",
        "agentId": agent_id,
        "issuer": signer,
        "escrow": escrow_address,
        "issuedAt": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }

    pinata_uri, ipfs_hash = _upload_metadata_to_pinata(metadata)
    if pinata_uri:
        return pinata_uri, {"source": "pinata", "ipfsHash": ipfs_hash}

    digest = hashlib.sha256(json.dumps(metadata, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return f"ipfs://local-{digest[:46]}", {"source": "local-fallback"}


def _send_tx(w3: Web3, fn, pk: str, sender: str, nonce: int, chain_id: int) -> tuple[str, int]:
    tx = fn.build_transaction(
        {
            "from": sender,
            "chainId": chain_id,
            "nonce": nonce,
            "gasPrice": w3.eth.gas_price,
        }
    )
    if "gas" not in tx:
        tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)

    signed = Account.sign_transaction(tx, pk)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    if int(receipt.status) != 1:
        raise RuntimeError(f"Transaction failed: {tx_hash.hex()}")

    return tx_hash.hex(), nonce + 1


def graduate_agent(
    agent_id: int,
    escrow_address: str,
    token_uri: str,
    proof_raw: dict[str, Any] | None,
) -> dict[str, Any]:
    if not Web3.is_address(escrow_address):
        return {"success": False, "error": "Invalid escrow address"}

    private_key = (os.getenv("GRADUATE_PRIVATE_KEY", "") or os.getenv("CLIENT_PRIVATE_KEY", "")).strip()
    if not private_key:
        return {"success": False, "error": "Missing signer private key (set GRADUATE_PRIVATE_KEY or CLIENT_PRIVATE_KEY)"}
    pk = private_key if private_key.startswith("0x") else f"0x{private_key}"
    signer = Account.from_key(pk)

    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        return {"success": False, "error": f"RPC connection failed: {RPC_URL}"}

    escrow = w3.eth.contract(address=Web3.to_checksum_address(escrow_address), abi=ESCROW_ABI)

    owner = escrow.functions.owner().call()
    if signer.address.lower() != owner.lower():
        return {
            "success": False,
            "error": f"CLIENT_PRIVATE_KEY address {signer.address} is not escrow owner {owner}",
        }

    expected_scope = _expected_scope(agent_id, CHAIN_ID)
    expected_signal = _expected_signal(agent_id, CHAIN_ID)

    auto_proof_meta: dict[str, Any] | None = None
    if proof_raw is None:
        try:
            proof_raw, auto_proof_meta = _auto_generate_proof(agent_id, expected_signal, expected_scope, w3, escrow)
        except Exception as exc:
            print(f"[Graduate] Auto proof error: {exc}", file=sys.stderr)
            return {
                "success": False,
                "error": "Anonymous authorization unavailable",
                "errorCode": "GRAD-AUTH-01",
                "hint": "Re-initiate graduation authorization.",
            }

    try:
        depth, root, nullifier, message, scope, points = _normalize_proof(proof_raw)
    except Exception as exc:
        print(f"[Graduate] Proof payload error: {exc}", file=sys.stderr)
        return {
            "success": False,
            "error": "Authorization proof format invalid",
            "errorCode": "GRAD-AUTH-02",
            "hint": "Provide a valid authorization proof payload.",
        }

    if scope != expected_scope:
        return {
            "success": False,
            "error": "Authorization proof mismatch",
            "errorCode": "GRAD-AUTH-03",
            "hint": "Re-generate proof under current authorization scope.",
        }

    if message != expected_signal:
        return {
            "success": False,
            "error": "Authorization proof mismatch",
            "errorCode": "GRAD-AUTH-03",
            "hint": "Re-generate proof under current authorization scope.",
        }

    resolved_token_uri = token_uri.strip()
    token_uri_meta: dict[str, Any] | None = None
    if not resolved_token_uri:
        resolved_token_uri, token_uri_meta = _build_auto_token_uri(agent_id, signer.address, escrow_address)

    if not resolved_token_uri.startswith("ipfs://"):
        return {
            "success": False,
            "error": "Graduation metadata unavailable",
            "errorCode": "GRAD-META-01",
            "hint": "Provide a valid metadata URI.",
        }

    proof_tuple = (depth, root, nullifier, message, scope, points)

    try:
        nonce = w3.eth.get_transaction_count(signer.address)
        atomic_tx, _ = _send_tx(
            w3,
            escrow.functions.graduateAtomicByProof(agent_id, proof_tuple, expected_signal, resolved_token_uri),
            pk,
            signer.address,
            nonce,
            CHAIN_ID,
        )
    except Exception as exc:
        print(f"[Graduate] Internal error: {exc}", file=sys.stderr)
        result = {
            "success": False,
            "error": "Graduation execution failed",
            "errorCode": "GRAD-EXEC-01",
            "hint": "Retry later or verify escrow has atomic graduation deployed.",
        }
        return result

    result = {
        "success": True,
        "agentId": agent_id,
        "escrow": escrow_address,
        "tokenUri": resolved_token_uri,
        "atomicTxHash": atomic_tx,
        "settleTxHash": atomic_tx,
        "signalHash": str(expected_signal),
        "scope": str(expected_scope),
        "explorerAtomic": f"{EXPLORER_BASE}{atomic_tx}",
        "explorerSettle": f"{EXPLORER_BASE}{atomic_tx}",
        "autoProofUsed": auto_proof_meta is not None,
        "autoTokenUriUsed": token_uri_meta is not None,
    }

    if auto_proof_meta is not None:
        result["autoProofMeta"] = auto_proof_meta
    if token_uri_meta is not None:
        result["tokenUriMeta"] = token_uri_meta

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="VeriVerse Graduate Agent (P4)")
    parser.add_argument("--agent-id", type=int, required=True, help="Agent ID")
    parser.add_argument("--escrow", default="", help="VeriEscrow address (optional, defaults to addresses.json bsc)")
    parser.add_argument("--token-uri", default="", help="Graduation token URI (optional, auto-generated when empty)")
    parser.add_argument("--proof-file", default="", help="Path to proof JSON file")
    parser.add_argument("--proof-json", default="", help="Proof JSON string")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    try:
        escrow_address = args.escrow.strip() or _load_default_escrow()
        proof_payload = _load_proof_from_args(args)
        result = graduate_agent(args.agent_id, escrow_address, args.token_uri, proof_payload)
    except Exception as exc:
        print(f"[Graduate] Init error: {exc}", file=sys.stderr)
        result = {
            "success": False,
            "error": "Graduation initialization failed",
            "errorCode": "GRAD-INIT-01",
            "hint": "Verify runtime configuration and retry.",
        }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result.get("success"):
            print("[Graduate] ✅ 完成毕业链路")
            print(f"[Graduate] Agent: #{result['agentId']}")
            print(f"[Graduate] tokenUri: {result['tokenUri']}")
            print(f"[Graduate] atomic: {result['atomicTxHash']}")
            print(f"[Graduate] settle: {result['settleTxHash']}")
        else:
            print(f"[Graduate] ❌ {result.get('error', 'unknown error')}")
            sys.exit(1)


if __name__ == "__main__":
    main()
