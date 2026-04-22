#!/usr/bin/env python3
"""
launch_agent.py — VeriVerse Agent 发射脚本

创建 Agent 钱包 → 获取 BSC 地址 → 原子调用 VeriEscrow.launchAndBind() 上链

Usage:
    python3 launch_agent.py --name "MyAgent" --registry 0x... --json
"""

import argparse
from datetime import datetime, timezone
import json
import os
import re
import subprocess
import sys
import hashlib
import time
from pathlib import Path

from eth_abi import encode
from eth_account import Account
from dotenv import load_dotenv
from web3 import Web3
from web3.exceptions import TransactionNotFound


# ── Config ────────────────────────────────────────────────────────────────

CHAIN_INDEX = os.getenv("CHAIN_INDEX", "97")  # BSC testnet
CHAIN_ID = int(os.getenv("CHAIN_ID", "97"))
RPC_URL = os.getenv("BSC_RPC_URL", "https://bsc-testnet-rpc.publicnode.com")
EXPLORER_BASE = os.getenv("EXPLORER_BASE", "https://testnet.bscscan.com/tx/")
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_DATA_DIR = PROJECT_ROOT / "data" / "agents"
SEMAPHORE_IDENTITY_DIR = PROJECT_ROOT / "data" / "semaphore-identities"
SEMAPHORE_TOOLS = PROJECT_ROOT / "scripts" / "semaphore_local_tools.mjs"
ADDRESSES_FILE = PROJECT_ROOT / "addresses.json"
AUTO_SEMAPHORE_BIND = os.environ.get("AUTO_SEMAPHORE_BIND", "1").lower() not in {"0", "false", "no"}
ATOMIC_LAUNCH = os.environ.get("ATOMIC_LAUNCH", "1").lower() not in {"0", "false", "no"}
# onchainos removed — all tx signing via CLIENT_PRIVATE_KEY + web3.py
DEFAULT_FIXED_AGENT_WALLET_ADDRESS = ""
AGENT_WALLET_MODE = os.environ.get("AGENT_WALLET_MODE", "dedicated").strip().lower()
FIXED_AGENT_WALLET_ADDRESS = os.environ.get("FIXED_AGENT_WALLET_ADDRESS", DEFAULT_FIXED_AGENT_WALLET_ADDRESS).strip()

for env_path in [
    Path("/home/skottbie/.openclaw/.env"),
    Path("/home/skottbie/.openclaw/workspace/.env"),
    PROJECT_ROOT.parent / ".env",
    PROJECT_ROOT / ".env",
]:
    if env_path.exists():
        load_dotenv(env_path, override=False)

# Re-read runtime config after dotenv loading.
RPC_URL = os.getenv("BSC_RPC_URL", RPC_URL)
AUTO_SEMAPHORE_BIND = os.environ.get("AUTO_SEMAPHORE_BIND", "1").lower() not in {"0", "false", "no"}
ATOMIC_LAUNCH = os.environ.get("ATOMIC_LAUNCH", "1").lower() not in {"0", "false", "no"}
# (onchainos re-reads removed)
AGENT_WALLET_MODE = os.environ.get("AGENT_WALLET_MODE", AGENT_WALLET_MODE).strip().lower()
FIXED_AGENT_WALLET_ADDRESS = os.environ.get("FIXED_AGENT_WALLET_ADDRESS", FIXED_AGENT_WALLET_ADDRESS).strip()


# ── Helpers ───────────────────────────────────────────────────────────────

def keccak256(text: str) -> bytes:
    """Compute keccak256 hash via web3."""
    return Web3.keccak(text=text)


def function_selector(signature: str) -> bytes:
    """Get the 4-byte function selector for a Solidity function signature."""
    return keccak256(signature)[:4]


def encode_register_calldata(name: str, wallet: str) -> str:
    """ABI-encode register(string,address) calldata."""
    selector = function_selector("register(string,address)")
    params = encode(["string", "address"], [name, wallet])
    return "0x" + selector.hex() + params.hex()


def encode_bind_commitment_calldata(agent_id: int, commitment: int) -> str:
    """ABI-encode bindCreatorCommitment(uint256,uint256) calldata."""
    selector = function_selector("bindCreatorCommitment(uint256,uint256)")
    params = encode(["uint256", "uint256"], [agent_id, commitment])
    return "0x" + selector.hex() + params.hex()


def encode_launch_and_bind_calldata(creator: str, name: str, wallet: str, commitment: int) -> str:
    """ABI-encode launchAndBind(address,string,address,uint256) calldata."""
    selector = function_selector("launchAndBind(address,string,address,uint256)")
    params = encode(["address", "string", "address", "uint256"], [creator, name, wallet, commitment])
    return "0x" + selector.hex() + params.hex()



def run_node_tool(args: list[str]) -> dict:
    """Run local semaphore helper and parse JSON output."""
    cmd = ["node", str(SEMAPHORE_TOOLS)] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        err = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"semaphore tool failed: {err}")

    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid semaphore tool output: {exc}") from exc




def check_register_permission(registry_address: str, creator_address: str) -> tuple[bool, dict]:
    """Read-only permission check for VTRegistry.register gate."""
    snapshot = {
        "creatorAddress": creator_address,
        "creatorIsOwner": False,
        "creatorWhitelisted": False,
        "devMode": None,
        "owner": None,
    }

    try:
        w3 = Web3(Web3.HTTPProvider(RPC_URL))
        if not w3.is_connected():
            snapshot["warning"] = "RPC unavailable, permission precheck skipped"
            return True, snapshot

        registry = w3.eth.contract(
            address=Web3.to_checksum_address(registry_address),
            abi=[
                {
                    "inputs": [],
                    "name": "owner",
                    "outputs": [{"internalType": "address", "name": "", "type": "address"}],
                    "stateMutability": "view",
                    "type": "function",
                },
                {
                    "inputs": [],
                    "name": "devMode",
                    "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
                    "stateMutability": "view",
                    "type": "function",
                },
                {
                    "inputs": [{"internalType": "address", "name": "", "type": "address"}],
                    "name": "whitelist",
                    "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
                    "stateMutability": "view",
                    "type": "function",
                },
            ],
        )

        owner = Web3.to_checksum_address(registry.functions.owner().call())
        dev_mode = bool(registry.functions.devMode().call())
        creator = Web3.to_checksum_address(creator_address)
        whitelisted = bool(registry.functions.whitelist(creator).call())

        snapshot.update(
            {
                "owner": owner,
                "devMode": dev_mode,
                "creatorIsOwner": owner.lower() == creator.lower(),
                "creatorWhitelisted": whitelisted,
            }
        )

        can_register = (not dev_mode) or snapshot["creatorIsOwner"] or whitelisted
        return can_register, snapshot
    except Exception as e:
        snapshot["warning"] = f"permission precheck skipped: {e}"
        return True, snapshot


def private_key_address() -> str | None:
    """Resolve EOA address from CLIENT_PRIVATE_KEY."""
    pk = os.getenv("CLIENT_PRIVATE_KEY", "").strip()
    if not pk:
        return None
    try:
        pk_hex = pk if pk.startswith("0x") else f"0x{pk}"
        return Web3.to_checksum_address(Account.from_key(pk_hex).address)
    except Exception:
        return None


def send_contract_call_via_private_key(to_address: str, calldata: str) -> tuple[str, str]:
    """Send contract tx using CLIENT_PRIVATE_KEY and return (txHash, senderAddress)."""
    pk = os.getenv("CLIENT_PRIVATE_KEY", "").strip()
    if not pk:
        raise RuntimeError("CLIENT_PRIVATE_KEY missing")

    pk_hex = pk if pk.startswith("0x") else f"0x{pk}"
    account = Account.from_key(pk_hex)

    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        raise RuntimeError("RPC unavailable")

    sender = Web3.to_checksum_address(account.address)
    tx = {
        "chainId": CHAIN_ID,
        "nonce": w3.eth.get_transaction_count(sender, "pending"),
        "to": Web3.to_checksum_address(to_address),
        "value": 0,
        "data": calldata,
        "from": sender,
        "gasPrice": w3.eth.gas_price,
    }

    try:
        gas_estimate = w3.eth.estimate_gas(tx)
    except Exception as e:
        raise RuntimeError(f"gas estimation failed: {e}") from e

    tx["gas"] = int(gas_estimate * 12 / 10)
    signed = account.sign_transaction(tx)

    try:
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    except Exception as e:
        raise RuntimeError(f"broadcast failed: {e}") from e

    tx_hex = tx_hash.hex()
    if not tx_hex.startswith("0x"):
        tx_hex = f"0x{tx_hex}"
    return tx_hex, sender


def get_current_escrow_address() -> str | None:
    """Load current bsc escrow address from addresses.json."""
    if not ADDRESSES_FILE.exists():
        return None

    try:
        data = json.loads(ADDRESSES_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    value = (data.get("bsc") or {}).get("VeriEscrow")
    if isinstance(value, str) and ADDRESS_RE.match(value):
        return value
    return None


def get_current_semaphore_address() -> str | None:
    """Load Semaphore contract address from addresses.json."""
    if not ADDRESSES_FILE.exists():
        return None

    try:
        data = json.loads(ADDRESSES_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    value = (data.get("bsc") or {}).get("Semaphore")
    if isinstance(value, str) and ADDRESS_RE.match(value):
        return value
    return None


def compute_merkle_root(commitment: int, group_id: int) -> int:
    """Compute Semaphore group Merkle root off-chain via node helper."""
    result = run_node_tool([
        "compute-root",
        "--commitment", str(commitment),
        "--group-id", str(group_id),
    ])
    return int(result["groupRoot"])


def set_merkle_tree_root_on_chain(semaphore_address: str, group_id: int, merkle_root: int) -> str:
    """Call MockSemaphore.setMerkleTreeRoot(uint256,uint256) via web3.py."""
    selector = function_selector("setMerkleTreeRoot(uint256,uint256)")
    params = encode(["uint256", "uint256"], [group_id, merkle_root])
    calldata = "0x" + selector.hex() + params.hex()
    tx_hash, _ = send_contract_call_via_private_key(semaphore_address, calldata)
    if not tx_hash:
        raise RuntimeError("setMerkleTreeRoot tx hash missing")
    return tx_hash


def generate_identity_material() -> tuple[str, int]:
    """Generate a new semaphore identity payload and commitment."""
    if not SEMAPHORE_TOOLS.exists():
        raise RuntimeError(f"missing semaphore tool: {SEMAPHORE_TOOLS}")

    identity_data = run_node_tool(["new-identity"])
    identity_export = identity_data.get("identityExport")
    commitment_raw = identity_data.get("commitment")
    if not identity_export or not commitment_raw:
        raise RuntimeError("invalid identity payload from semaphore tool")

    return identity_export, int(commitment_raw)


def persist_identity(agent_id: int, identity_export: str, commitment: int) -> str:
    """Persist semaphore identity payload to the canonical local path."""
    SEMAPHORE_IDENTITY_DIR.mkdir(parents=True, exist_ok=True)
    identity_path = SEMAPHORE_IDENTITY_DIR / f"{agent_id}.json"
    payload = {
        "agentId": agent_id,
        "identityExport": identity_export,
        "commitment": str(commitment),
        "createdAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    identity_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return str(identity_path)


def create_identity_for_agent(agent_id: int) -> tuple[int, str]:
    """Create semaphore identity, persist locally, and return commitment + file path."""
    identity_export, commitment = generate_identity_material()
    identity_path = persist_identity(agent_id, identity_export, commitment)

    return commitment, identity_path


def bind_creator_commitment(escrow_address: str, agent_id: int, commitment: int) -> str:
    """Call VeriEscrow.bindCreatorCommitment via web3.py private key signing."""
    calldata = encode_bind_commitment_calldata(agent_id, commitment)
    tx_hash, _ = send_contract_call_via_private_key(escrow_address, calldata)
    if not tx_hash:
        raise RuntimeError("bind commitment tx hash missing")
    return tx_hash


def infer_agent_id_from_receipt(tx_hash: str, registry_address: str) -> int | None:
    """Infer newly registered agentId by decoding AgentRegistered event from tx receipt."""
    try:
        if not tx_hash or not tx_hash.startswith("0x"):
            return None
        w3 = Web3(Web3.HTTPProvider(RPC_URL))
        if not w3.is_connected():
            return None

        receipt = None
        for _ in range(12):
            try:
                receipt = w3.eth.get_transaction_receipt(tx_hash)
                break
            except TransactionNotFound:
                time.sleep(2)
        if receipt is None:
            return None

        topic0 = Web3.keccak(text="AgentRegistered(uint256,address,address,string)").hex()
        registry_checksum = Web3.to_checksum_address(registry_address)

        for log in receipt.logs:
            if log["address"].lower() != registry_checksum.lower():
                continue
            if not log["topics"]:
                continue
            if log["topics"][0].hex().lower() != topic0.lower():
                continue
            if len(log["topics"]) < 2:
                continue
            return int.from_bytes(log["topics"][1], byteorder="big")

        return None
    except Exception:
        return None


def get_agent_group_id(escrow_address: str, agent_id: int) -> int | None:
    """Read agentGroupId from VeriEscrow for post-launch observability."""
    try:
        if not escrow_address:
            return None
        w3 = Web3(Web3.HTTPProvider(RPC_URL))
        if not w3.is_connected():
            return None

        abi = [{
            "inputs": [{"name": "", "type": "uint256"}],
            "name": "agentGroupId",
            "outputs": [{"name": "", "type": "uint256"}],
            "stateMutability": "view",
            "type": "function",
        }]
        contract = w3.eth.contract(address=Web3.to_checksum_address(escrow_address), abi=abi)
        return int(contract.functions.agentGroupId(agent_id).call())
    except Exception:
        return None


def derive_creator_address() -> str:
    """Best-effort derive creator address from CLIENT_PRIVATE_KEY."""
    pk = os.getenv("CLIENT_PRIVATE_KEY", "").strip()
    if not pk:
        return "0x0000000000000000000000000000000000000000"
    try:
        pk_hex = pk if pk.startswith("0x") else f"0x{pk}"
        return Account.from_key(pk_hex).address
    except Exception:
        return "0x0000000000000000000000000000000000000000"


def write_agent_description(agent_id: int, name: str, description: str, claims: list[str]) -> str:
    """Persist MVP agent description for P3 challenge flow."""
    AGENT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "agentId": agent_id,
        "name": name,
        "description": description,
        "claims": claims,
        "supportedTasks": ["defi_tvl"],
        "owner": derive_creator_address(),
        "updatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    out_path = AGENT_DATA_DIR / f"{agent_id}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(out_path)


# ── Main Flow ─────────────────────────────────────────────────────────────

def launch_agent(agent_name: str, registry_address: str, description: str, claims: list[str]) -> dict:
    """
    Full launch flow:
    1. Resolve Agent wallet                    → dedicated(new keypair) / fixed(shared wallet)
    2. Resolve creator address from CLIENT_PRIVATE_KEY
    3. Preferred: atomic launchAndBind         → escrow launches + binds commitment in one tx
    4. Fallback: legacy register + bind        → controlled by ATOMIC_LAUNCH flag
    """

    # Input validation
    if not ADDRESS_RE.match(registry_address):
        return {"success": False, "error": f"Invalid registry address format: {registry_address}"}
    if len(agent_name) > 128:
        return {"success": False, "error": "Agent name too long (max 128 chars)"}

    # Step 1: Resolve wallet for this Agent launch.
    # dedicated: generate a new keypair locally (eth_account)
    # fixed:     reuse a preconfigured wallet address for every launch
    agent_wallet = None
    agent_private_key_hex = None
    wallet_mode = AGENT_WALLET_MODE

    if wallet_mode in {"fixed", "static", "shared"}:
        if not ADDRESS_RE.match(FIXED_AGENT_WALLET_ADDRESS):
            return {
                "success": False,
                "error": "Invalid FIXED_AGENT_WALLET_ADDRESS format",
                "walletMode": wallet_mode,
                "fixedWallet": FIXED_AGENT_WALLET_ADDRESS,
            }
        agent_wallet = Web3.to_checksum_address(FIXED_AGENT_WALLET_ADDRESS)
        print(f"[Launch] Using fixed wallet for Agent '{agent_name}': {agent_wallet}", file=sys.stderr)
        wallet_mode = "fixed"
    elif wallet_mode in {"dedicated", "new", "per-agent"}:
        print(f"[Launch] Creating local keypair for Agent '{agent_name}'...", file=sys.stderr)
        new_account = Account.create()
        agent_wallet = Web3.to_checksum_address(new_account.address)
        agent_private_key_hex = new_account.key.hex()
        print(f"[Launch] Agent wallet: {agent_wallet}", file=sys.stderr)

        if not agent_wallet:
            return {
                "success": False,
                "error": "Local keypair generation returned invalid address",
            }
        wallet_mode = "dedicated"
    else:
        return {
            "success": False,
            "error": "Invalid AGENT_WALLET_MODE (use dedicated or fixed)",
            "walletMode": wallet_mode,
        }

    # Step 2: Resolve creator address from CLIENT_PRIVATE_KEY.
    creator_address = private_key_address()
    permission_snapshot = None
    creator_source = "private-key"

    if not creator_address:
        return {
            "success": False,
            "error": "Could not resolve creator address (set CLIENT_PRIVATE_KEY in .env)",
        }

    try:
        can_register, permission_snapshot = check_register_permission(registry_address, creator_address)
        if not ATOMIC_LAUNCH and not can_register:
            return {
                "success": False,
                "error": "Creator account lacks VTRegistry register permission (devMode gate)",
                "creatorAddress": creator_address,
                "creatorSource": creator_source,
                "permission": permission_snapshot,
            }
    except Exception as e:
        permission_snapshot = {"warning": f"permission precheck skipped: {e}"}

    tx_hash = None
    use_atomic_launch = False
    escrow_address = get_current_escrow_address()
    identity_export = None
    commitment = None
    owner_address = private_key_address()

    if ATOMIC_LAUNCH:
        if not AUTO_SEMAPHORE_BIND:
            return {
                "success": False,
                "error": "ATOMIC_LAUNCH requires AUTO_SEMAPHORE_BIND enabled",
            }
        if not escrow_address:
            return {
                "success": False,
                "error": "ATOMIC_LAUNCH requires VeriEscrow address in addresses.json",
            }

        try:
            identity_export, commitment = generate_identity_material()
        except Exception as e:
            return {"success": False, "error": f"Identity generation failed: {e}"}

        print(f"[Launch] Calling VeriEscrow.launchAndBind() at {escrow_address}...", file=sys.stderr)
        calldata = encode_launch_and_bind_calldata(creator_address, agent_name, agent_wallet, commitment)

        try:
            tx_hash, owner_address = send_contract_call_via_private_key(escrow_address, calldata)
        except RuntimeError as e:
            return {
                "success": False,
                "error": f"Atomic launchAndBind call failed: {e}",
                "creatorAddress": creator_address,
                "permission": permission_snapshot,
                "ownerAddress": private_key_address(),
                "escrowAddress": escrow_address,
            }

        use_atomic_launch = True
    else:
        # Legacy path: creator directly calls VTRegistry.register via private key.
        print("[Launch] Encoding register() calldata...", file=sys.stderr)
        calldata = encode_register_calldata(agent_name, agent_wallet)

        print(f"[Launch] Calling VTRegistry.register() at {registry_address}...", file=sys.stderr)
        try:
            tx_hash, owner_address = send_contract_call_via_private_key(registry_address, calldata)
        except RuntimeError as e:
            failure = {"success": False, "error": f"Contract call failed: {e}"}
            if creator_address:
                failure["creatorAddress"] = creator_address
            if permission_snapshot:
                failure["permission"] = permission_snapshot
            return failure

    result = {
        "success": True,
        "launchMode": "atomic-launch-and-bind" if use_atomic_launch else "legacy-register",
        "walletMode": wallet_mode,
        "agentName": agent_name,
        "walletAddress": agent_wallet,
        "creatorAddress": creator_address,
        "creatorSource": creator_source,
        "txHash": tx_hash or "pending",
        "explorerUrl": f"{EXPLORER_BASE}{tx_hash}" if tx_hash else None,
        "registryAddress": registry_address,
    }
    if use_atomic_launch:
        result["ownerAddress"] = owner_address or private_key_address()
        result["escrowAddress"] = escrow_address
    if permission_snapshot:
        result["permission"] = permission_snapshot

    # Best-effort: persist agent description for P3 challenge flow.
    inferred_id = infer_agent_id_from_receipt(tx_hash or "", registry_address)
    if inferred_id is not None and inferred_id > 0:
        try:
            path = write_agent_description(
                agent_id=inferred_id,
                name=agent_name,
                description=description,
                claims=claims,
            )
            result["agentId"] = inferred_id
            result["agentDescriptionPath"] = path
        except Exception as e:
            result["agentDescriptionWriteWarning"] = str(e)

        # Semaphore bootstrap reporting.
        if use_atomic_launch:
            try:
                if not identity_export or not commitment:
                    raise RuntimeError("missing identity material for atomic launch")
                identity_path = persist_identity(inferred_id, identity_export or "", int(commitment or 0))
                group_id = get_agent_group_id(escrow_address or "", inferred_id)
                bootstrap_info = {
                    "enabled": True,
                    "mode": "atomic-launch-and-bind",
                    "escrowAddress": escrow_address,
                    "commitment": str(commitment),
                    "identityPath": identity_path,
                    "groupId": group_id,
                    "bindCommitmentTxHash": tx_hash,
                    "bindCommitmentExplorer": f"{EXPLORER_BASE}{tx_hash}" if tx_hash else None,
                }
                # Auto-set Merkle root on MockSemaphore (critical for graduation).
                semaphore_addr = get_current_semaphore_address()
                if semaphore_addr and group_id and group_id > 0:
                    merkle_root = compute_merkle_root(int(commitment), group_id)
                    root_tx = set_merkle_tree_root_on_chain(semaphore_addr, group_id, merkle_root)
                    bootstrap_info["merkleRootTxHash"] = root_tx
                    bootstrap_info["merkleRootExplorer"] = f"{EXPLORER_BASE}{root_tx}"
                    print(f"[Launch] Merkle root set for groupId={group_id}", file=sys.stderr)
                result["autoSemaphoreBootstrap"] = bootstrap_info
            except Exception as e:
                result["semaphoreBootstrapWarning"] = str(e)
        elif AUTO_SEMAPHORE_BIND:
            try:
                if not escrow_address:
                    result["semaphoreBootstrapWarning"] = "VeriEscrow address not found in addresses.json"
                else:
                    legacy_commitment, identity_path = create_identity_for_agent(inferred_id)
                    bind_tx_hash = bind_creator_commitment(escrow_address, inferred_id, legacy_commitment)
                    legacy_group_id = get_agent_group_id(escrow_address, inferred_id)
                    bootstrap_info = {
                        "enabled": True,
                        "mode": "legacy-post-bind",
                        "escrowAddress": escrow_address,
                        "commitment": str(legacy_commitment),
                        "identityPath": identity_path,
                        "groupId": legacy_group_id,
                        "bindCommitmentTxHash": bind_tx_hash,
                        "bindCommitmentExplorer": f"{EXPLORER_BASE}{bind_tx_hash}",
                    }
                    # Auto-set Merkle root on MockSemaphore (critical for graduation).
                    semaphore_addr = get_current_semaphore_address()
                    if semaphore_addr and legacy_group_id and legacy_group_id > 0:
                        merkle_root = compute_merkle_root(legacy_commitment, legacy_group_id)
                        root_tx = set_merkle_tree_root_on_chain(semaphore_addr, legacy_group_id, merkle_root)
                        bootstrap_info["merkleRootTxHash"] = root_tx
                        bootstrap_info["merkleRootExplorer"] = f"{EXPLORER_BASE}{root_tx}"
                        print(f"[Launch] Merkle root set for groupId={legacy_group_id}", file=sys.stderr)
                    result["autoSemaphoreBootstrap"] = bootstrap_info
            except Exception as e:
                result["semaphoreBootstrapWarning"] = str(e)
        else:
            result["autoSemaphoreBootstrap"] = {"enabled": False}
    elif inferred_id == 0:
        result["agentIdInferenceWarning"] = "inferred agent id is 0, skip semaphore bootstrap"
    else:
        result["agentIdInferenceWarning"] = "could not infer agent id from receipt yet"

    return result


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="VeriVerse Agent Launcher")
    parser.add_argument("--name", required=True, help="Agent name")
    parser.add_argument("--description", default="", help="Agent capability description")
    parser.add_argument(
        "--claims",
        default="",
        help="Comma-separated capability claims, e.g. 'can fetch tvl,can verify consistency'",
    )
    parser.add_argument("--registry", default=None, help="VTRegistry contract address")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    # Registry address: CLI arg > env var
    registry = args.registry or os.environ.get("VTREGISTRY_ADDRESS")
    if not registry:
        print(json.dumps({"success": False, "error": "Registry address required (--registry or VTREGISTRY_ADDRESS env)"}))
        sys.exit(1)

    description = args.description.strip() or f"{args.name} capability profile"
    claims = [x.strip() for x in args.claims.split(",") if x.strip()]
    if not claims:
        claims = ["Can execute delegated tasks declared by creator"]

    result = launch_agent(args.name, registry, description, claims)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if result["success"]:
            print(f"🚀 Agent 发射成功！")
            print(f"📛 名称: {result['agentName']}")
            print(f"💼 钱包: {result['walletAddress']}")
            print(f"🔗 交易: {result.get('explorerUrl', 'pending')}")
        else:
            print(f"❌ 发射失败: {result.get('error', 'Unknown error')}")
            sys.exit(1)


if __name__ == "__main__":
    main()
