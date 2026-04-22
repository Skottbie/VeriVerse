#!/usr/bin/env python3
"""
VeriTask 3.5 — Bidding Agent
Reads the Proof-Conditioned Endorsement Graph from BNB Chain and selects
the best Worker for a new task.

Flow:
  1. Fetch candidate Worker addresses (from CLI arg or well-known registry)
  2. For each Worker: fetch reputation edges via BNB Chain RPC (eth_getLogs)
  3. Verify each edge's proof_hash + tee_fingerprint
  4. For each Client: query OnchainOS market portfolio-overview (seed score)
  5. Compute smart-money bonus via signal list + leaderboard
  6. Run Proof-Conditioned VeriRank (networkx)
  7. Detect wash-trading anomalies
  8. Output ranked Workers (best first)

Usage:
    python bidding_agent.py --workers 0xA,0xB,0xC
    python bidding_agent.py --workers 0xWorker1 --json
    python bidding_agent.py --workers 0xWorker1 --task-type defi_tvl
"""

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import networkx as nx
import requests as http_requests
from dotenv import load_dotenv
from web3 import Web3

# ── bootstrap ──────────────────────────────────────────────────────────────
load_dotenv(Path(__file__).parent.parent / ".env")

BSC_RPC_URL = os.getenv("BSC_RPC_URL", "https://data-seed-prebsc-1-s1.binance.org:8545")

# VTRegistry contract on BSC Testnet
VT_REGISTRY = os.getenv("VT_REGISTRY_ADDRESS", "0x1545655b6d42A51E5e8c85Ed162bD84aba35480C")
# Event Edge(address indexed client, address indexed worker, bytes data)
EDGE_TOPIC = "0xf22cc026ce4ac199da8ab4400164e45d4edf7dc048ee4a6538462d80f16ff0b4"

# VTRegistry deploy block (search won't go before this)
VT_REGISTRY_DEPLOY_BLOCK = int(os.getenv("VT_REGISTRY_DEPLOY_BLOCK", "0"))

# VeriTask calldata prefix (must match graph_anchor.py)
CALLDATA_PREFIX = "VT2:"

# demo mode: read client from VT2 calldata; production: from event topic1
VERITASK_MODE = os.getenv("VERITASK_MODE", "production")

# VeriRank damping and convergence
VERIRANK_ALPHA = 0.85
VERIRANK_ITERATIONS = 100

# Decay half-life: 30 days in seconds
DECAY_LAMBDA = math.log(2) / (30 * 86400)


# ── Edge cache file ─────────────────────────────────────────────────────────
EDGE_CACHE_FILE = Path(__file__).parent / "edge_cache.json"


# ── RPC: fetch reputation edges ────────────────────────────────────────────

_RPC_ID = 0


def _rpc_call(rpc_url: str, method: str, params: list, _retries: int = 3):
    """Raw JSON-RPC call via requests with retry (avoids web3 provider 400 errors on BNB Chain)."""
    global _RPC_ID
    _RPC_ID += 1
    for attempt in range(_retries):
        try:
            resp = http_requests.post(
                rpc_url,
                json={"jsonrpc": "2.0", "method": method, "params": params, "id": _RPC_ID},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(f"RPC error ({method}): {data['error']}")
            return data["result"]
        except (http_requests.exceptions.ConnectionError,
                http_requests.exceptions.Timeout) as e:
            if attempt < _retries - 1:
                wait = 2 ** (attempt + 1)
                print(f"[Bidding] RPC retry {attempt+1}/{_retries} in {wait}s: {e}", file=sys.stderr)
                time.sleep(wait)
            else:
                raise


def _paginated_get_logs(rpc_url: str, filter_obj: dict,
                        from_block: int, to_block: int) -> list[dict]:
    """
    Generic paginated eth_getLogs. Paginated to handle BNB Chain block range limits.
    Shared by all fetch_*_logs helpers.
    """
    PAGE_SIZE = 4999  # BSC allows up to 5000 blocks per page
    all_logs: list[dict] = []
    cursor = from_block

    while cursor <= to_block:
        page_end = min(cursor + PAGE_SIZE, to_block)
        filt = {**filter_obj, "fromBlock": hex(cursor), "toBlock": hex(page_end)}
        page_logs = _rpc_call(rpc_url, "eth_getLogs", [filt])
        all_logs.extend(page_logs)
        cursor = page_end + 1
        time.sleep(0.15)  # respect BSC rate limit

    return all_logs


def fetch_edge_logs(rpc_url: str, worker_address: str,
                    from_block: int = 0, to_block: str = "latest") -> list[dict]:
    """
    Fetch VTRegistry Edge events where indexed worker == worker_address.
    Returns log entries whose data field contains ABI-encoded VT2 payload.
    """
    registry = Web3.to_checksum_address(VT_REGISTRY)
    worker_padded = "0x" + worker_address[2:].lower().zfill(64)

    if to_block == "latest":
        latest = int(_rpc_call(rpc_url, "eth_blockNumber", []), 16)
    else:
        latest = int(to_block, 16) if isinstance(to_block, str) else to_block

    return _paginated_get_logs(rpc_url, {
        "address": registry,
        "topics": [EDGE_TOPIC, None, worker_padded],
    }, from_block, latest)


def fetch_all_edge_logs(rpc_url: str,
                        from_block: int, to_block: int) -> list[dict]:
    """
    Fetch ALL VTRegistry Edge events in one batch scan (no worker filter).
    This reduces N-worker × 159 pages → 1 × 159 pages of RPC calls.
    """
    registry = Web3.to_checksum_address(VT_REGISTRY)
    return _paginated_get_logs(rpc_url, {
        "address": registry,
        "topics": [EDGE_TOPIC],
    }, from_block, to_block)


# ── Edge cache: persist scanned edges to avoid re-scanning ──────────────────

def _load_edge_cache() -> dict:
    """
    Load cached edge data from disk.
    Returns {"last_scanned_block": int, "edges": [raw_log_dict, ...]}.
    """
    if not EDGE_CACHE_FILE.exists():
        return {"last_scanned_block": 0, "edges": []}
    try:
        with open(EDGE_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "last_scanned_block": int(data.get("last_scanned_block", 0)),
            "edges": data.get("edges", []),
        }
    except (json.JSONDecodeError, ValueError, OSError):
        return {"last_scanned_block": 0, "edges": []}


def _save_edge_cache(last_scanned_block: int, edges: list[dict]) -> None:
    """Persist scanned edge logs to disk for incremental re-use."""
    data = {"last_scanned_block": last_scanned_block, "edges": edges}
    tmp = EDGE_CACHE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    tmp.replace(EDGE_CACHE_FILE)


def fetch_edges_cached(rpc_url: str) -> list[dict]:
    """
    Fetch all VTRegistry Edge events using local cache + incremental scan.

    First call: full scan from VT_REGISTRY_DEPLOY_BLOCK to latest → ~159 pages.
    Subsequent calls: scan only new blocks since last_scanned_block → 1-5 pages.
    """
    cache = _load_edge_cache()
    cached_block = cache["last_scanned_block"]
    cached_edges = cache["edges"]

    latest_block = int(_rpc_call(rpc_url, "eth_blockNumber", []), 16)
    start_block = max(VT_REGISTRY_DEPLOY_BLOCK, cached_block + 1)

    if start_block > latest_block:
        print(f"[Bidding] Edge cache up-to-date (block {cached_block})", file=sys.stderr)
        return cached_edges

    blocks_to_scan = latest_block - start_block + 1
    pages_est = max(1, blocks_to_scan // 100 + 1)
    print(f"[Bidding] Scanning edges: blocks {start_block}..{latest_block} "
          f"(~{pages_est} pages, {'incremental' if cached_block > 0 else 'full'})",
          file=sys.stderr)

    new_logs = fetch_all_edge_logs(rpc_url, start_block, latest_block)
    print(f"[Bidding]   → {len(new_logs)} new raw Edge events", file=sys.stderr)

    all_edges = cached_edges + new_logs
    _save_edge_cache(latest_block, all_edges)
    return all_edges


def parse_edge_event_data(data_hex: str) -> str:
    """
    Decode ABI-encoded bytes from Edge event data field.
    ABI layout: offset(32) + length(32) + payload(padded).
    Returns the raw payload as a hex string (0x-prefixed).
    """
    raw = bytes.fromhex(data_hex.removeprefix("0x"))
    if len(raw) < 64:
        return ""
    # offset at bytes [0:32] — should be 0x20 = 32
    data_len = int.from_bytes(raw[32:64], "big")
    payload = raw[64:64 + data_len]
    return "0x" + payload.hex()


def fetch_calldata(rpc_url: str, tx_hash: str) -> str:
    """
    Retrieve the input (calldata) field of a transaction.
    Returns hex string (0x-prefixed) or empty string on error.
    """
    try:
        tx = _rpc_call(rpc_url, "eth_getTransactionByHash", [tx_hash])
        if tx is None:
            return ""
        return tx.get("input", "")
    except Exception:
        return ""


def parse_vt_calldata(calldata_hex: str) -> dict | None:
    """
    Try to decode a VeriTask calldata hex string.
    Returns the parsed JSON dict if valid, else None.
    """
    try:
        raw = bytes.fromhex(calldata_hex.removeprefix("0x")).decode("utf-8", errors="replace")
        if not raw.startswith(CALLDATA_PREFIX):
            return None
        payload = raw[len(CALLDATA_PREFIX):]
        edge = json.loads(payload)
        # Minimal schema check
        required = {"v", "worker", "client", "proof_hash", "tee_fingerprint", "ts"}
        if not required.issubset(edge.keys()):
            return None
        return edge
    except Exception:
        return None


def compute_proof_quality(edge: dict) -> float:
    """
    Determine proof_quality weight for a single edge [0.0, 1.0]:
      - tee_fingerprint != "mock" AND proof_hash length == 64  → 1.0  (real TDX + zkTLS)
      - tee_fingerprint == "mock" AND proof_hash length == 64  → 0.5  (zkTLS only)
      - otherwise                                               → 0.0  (no verified proof)
    """
    pq = edge.get("proof_hash", "")
    tee = edge.get("tee_fingerprint", "")
    has_valid_hash = len(pq) == 64
    has_real_tee = tee not in ("", "mock")
    if has_valid_hash and has_real_tee:
        return 1.0
    if has_valid_hash:
        return 0.5
    return 0.0


# Dispute κ coefficients by reason
DISPUTE_KAPPA = {
    "zk_proof_invalid": 0.3,
    "tee_attestation_invalid": 0.5,
    "full_proof_failure": 0.8,
}


def build_reputation_edges(rpc_url: str, worker_address: str,
                            max_blocks_back: int = 50_000) -> list[dict]:
    """
    Query BSC for all VeriTask reputation edges pointing to worker.
    Uses VTRegistry Edge events.

    Returns a list of edge dicts with additional fields:
      amount_usdt (float), age_days (float), proof_quality (float), weight (float)
    """
    latest_block = int(_rpc_call(rpc_url, "eth_blockNumber", []), 16)
    from_block = max(0, latest_block - max_blocks_back)
    if VT_REGISTRY_DEPLOY_BLOCK > 0:
        from_block = max(from_block, VT_REGISTRY_DEPLOY_BLOCK)

    logs = fetch_edge_logs(rpc_url, worker_address, from_block, hex(latest_block))
    return _parse_logs_to_edges(rpc_url, logs, use_registry=True)


def _parse_logs_to_edges(rpc_url: str, logs: list[dict],
                         use_registry: bool) -> list[dict]:
    """
    Convert raw eth_getLogs results into scored edge dicts.
    Shared by both per-worker build_reputation_edges and batch pipeline.
    """
    edges = []
    now = time.time()

    for log in logs:
        tx_hash = log.get("transactionHash", "")

        if use_registry:
            # VTRegistry Edge: data field contains ABI-encoded VT2 calldata
            calldata_hex = parse_edge_event_data(log.get("data", ""))
        else:
            # Legacy: fetch tx input
            calldata_hex = fetch_calldata(rpc_url, tx_hash)

        edge = parse_vt_calldata(calldata_hex)
        if edge is None:
            continue  # not a VeriTask edge

        # In production mode with VTRegistry, override client from event topic1
        # (msg.sender, ECDSA-guaranteed). In demo mode, trust calldata client.
        if use_registry and VERITASK_MODE != "demo":
            topics = log.get("topics", [])
            if len(topics) >= 2:
                edge["client"] = "0x" + topics[1][-40:]
            if len(topics) >= 3:
                edge["worker"] = "0x" + topics[2][-40:]

        # Edge age in days
        edge_ts = int(edge.get("ts", now))
        age_seconds = max(0.0, now - edge_ts)
        age_days = age_seconds / 86400

        # Amount
        try:
            amount_usdt = float(edge.get("amount_usdt", "0"))
        except ValueError:
            amount_usdt = 0.0

        pq = compute_proof_quality(edge)

        # Determine edge_type: v3 edges have explicit field; v2 defaults to endorsement
        edge_type = edge.get("edge_type", "endorsement")

        if edge_type == "dispute":
            # Negative edge: w_dispute = -κ × e^(-λ × age_days)
            # seed(client) is applied later in build_graph when seed_scores are available
            kappa = DISPUTE_KAPPA.get(edge.get("dispute_reason", ""), 0.3)
            weight = -kappa * math.exp(-DECAY_LAMBDA * age_days)
        else:
            # Positive edge weight formula from design.md:
            # proof_quality × log(1 + amount_USD) × e^(-λ × age_days)
            weight = pq * math.log1p(amount_usdt) * math.exp(-DECAY_LAMBDA * age_days)

        edges.append({
            **edge,
            "tx_hash": tx_hash,
            "amount_usdt": amount_usdt,
            "age_days": age_days,
            "proof_quality": pq,
            "weight": weight,
        })

    return edges


# ── VeriVerse seed scores (uniform for MVP) ─────────────────────────────────

def compute_veriverse_seed_score(client_address: str) -> float:
    """
    VeriVerse Employment Audit seed score.
    MVP: all Clients equally weighted = 1.0.
    Future: can integrate BSC on-chain behavior analysis.
    """
    _demo_raw = os.environ.get("DEMO_SEED_OVERRIDES", "")
    if _demo_raw:
        _demo_map = {k.lower(): float(v) for k, v in json.loads(_demo_raw).items()}
        if client_address.lower() in _demo_map:
            return _demo_map[client_address.lower()]
    return 1.0


# ── Graph construction + VeriRank ──────────────────────────────────────────

def build_graph(all_edges: dict[str, list[dict]],
                seed_scores: dict[str, float]) -> nx.DiGraph:
    """
    Build a directed graph where:
      - Nodes: Worker and Client addresses
      - Edges: client → worker (direction = "client endorses worker")
      - Edge weight: from build_reputation_edges() weight field
        For dispute edges, weight is multiplied by seed(client) here.
      - Node personalization: seed_scores for Client nodes

    Returns a networkx DiGraph.
    """
    G = nx.DiGraph()

    for worker_addr, edges in all_edges.items():
        for edge in edges:
            client_addr = edge.get("client", "").lower()
            w_addr = worker_addr.lower()
            if not client_addr:
                continue

            w = edge["weight"]
            # For dispute edges, apply seed(client) to the negative weight
            if edge.get("edge_type") == "dispute":
                client_seed = seed_scores.get(client_addr, 0.0)
                w = w * client_seed  # w is already negative; seed scales severity

            existing = G.get_edge_data(client_addr, w_addr)
            if existing:
                G[client_addr][w_addr]["weight"] += w
            else:
                G.add_edge(client_addr, w_addr, weight=w)

    # Add any isolated nodes
    for addr, score in seed_scores.items():
        if addr not in G:
            G.add_node(addr)
        G.nodes[addr]["seed"] = score

    return G


def run_verirank(G: nx.DiGraph, seed_scores: dict[str, float]) -> dict[str, float]:
    """
    Run weighted VeriRank (personalized proof-conditioned reputation ranking) with personalization = seed_scores.
    Returns dict {address: verirank_score}.
    """
    if len(G) == 0:
        return {}

    # Personalization vector: seed_scores for clients, 0 for workers
    all_nodes = list(G.nodes())
    total_seed = sum(seed_scores.values()) or 1.0
    personalization = {
        n: seed_scores.get(n, 0.0) / total_seed
        for n in all_nodes
    }
    # If all personalization is zero, fall back to uniform
    if sum(personalization.values()) == 0:
        personalization = None

    try:
        scores = nx.pagerank(
            G,
            alpha=VERIRANK_ALPHA,
            max_iter=VERIRANK_ITERATIONS,
            weight="weight",
            personalization=personalization,
        )
    except nx.PowerIterationFailedConvergence:
        # Fallback: unweighted uniform VeriRank
        scores = nx.pagerank(G, alpha=VERIRANK_ALPHA)

    return scores


# ── Wash-trading detection ─────────────────────────────────────────────────

def detect_anomalies(G: nx.DiGraph, worker_addresses: list[str]) -> dict[str, list[str]]:
    """
    Simple anomaly checks per worker:
      1. Cycle: worker appears in its own short-cycle client chain (< 7 days)
      2. Isolated endorser: worker only has 1-2 unique clients
      3. Clique: endorsing clients are densely interconnected

    Returns {worker_addr: [list of anomaly flags]}
    """
    flags: dict[str, list[str]] = {}

    for worker in worker_addresses:
        w = worker.lower()
        worker_flags = []
        in_edges = list(G.in_edges(w))
        unique_clients = {u for u, _ in in_edges}

        if len(unique_clients) <= 2 and len(in_edges) > 0:
            worker_flags.append("isolated_endorser")

        # Check if any client also has an outgoing edge to this worker's clients
        # (rough clique detection)
        client_set = unique_clients
        clique_count = sum(
            1 for c in client_set
            if any(G.has_edge(c, other_c) for other_c in client_set if other_c != c)
        )
        if len(client_set) > 1 and clique_count / len(client_set) > 0.5:
            worker_flags.append("client_clique")

        if worker_flags:
            flags[w] = worker_flags

    return flags


# ── Main scoring pipeline ──────────────────────────────────────────────────

def rank_workers(worker_addresses: list[str], verbose: bool = False) -> list[dict]:
    """
    Full Bidding Agent pipeline. Returns workers sorted by final_score descending.
    """
    # Verify RPC connectivity
    try:
        _rpc_call(BSC_RPC_URL, "eth_blockNumber", [])
    except Exception as e:
        raise ConnectionError(f"Cannot connect to BSC RPC ({BSC_RPC_URL}): {e}")

    # Step 1: Fetch reputation edges — batch scan + cache via VTRegistry
    all_edges: dict[str, list[dict]] = {}
    all_clients: set[str] = set()
    worker_set = {w.lower() for w in worker_addresses}

    raw_logs = fetch_edges_cached(BSC_RPC_URL)
    parsed = _parse_logs_to_edges(BSC_RPC_URL, raw_logs, use_registry=True)

    # Group parsed edges by worker address
    for w in worker_addresses:
        all_edges[w.lower()] = []

    for edge in parsed:
        w = edge.get("worker", "").lower()
        if w in worker_set:
            all_edges[w].append(edge)
        for e_client in [edge.get("client", "").lower()]:
            if e_client:
                all_clients.add(e_client)

    for w in worker_addresses:
        cnt = len(all_edges.get(w.lower(), []))
        print(f"[Bidding]   {w[:14]}... → {cnt} edges", file=sys.stderr)

    # Step 2: Seed scores for all Client nodes found (uniform for VeriVerse MVP)
    seed_scores: dict[str, float] = {}
    for client_addr in all_clients:
        if client_addr:
            seed_scores[client_addr] = compute_veriverse_seed_score(client_addr)

    # Step 3: Build graph + VeriRank
    G = build_graph(all_edges, seed_scores)
    pr_scores = run_verirank(G, seed_scores)

    # Step 4: Anomaly detection
    anomalies = detect_anomalies(G, worker_addresses)

    # Step 5: Compose results
    results = []
    for worker in worker_addresses:
        w = worker.lower()
        edges = all_edges.get(w, [])
        pr = pr_scores.get(w, 0.0)
        worker_anomalies = anomalies.get(w, [])

        # Apply anomaly penalty: isolated_endorser → ×0.5, client_clique → ×0.3
        penalty = 1.0
        if "client_clique" in worker_anomalies:
            penalty *= 0.3
        elif "isolated_endorser" in worker_anomalies:
            penalty *= 0.5

        final_score = pr * penalty

        # Post-hoc dispute penalty: nx.pagerank cannot process negative edge weights
        # as expected deductions, so apply penalty explicitly after PageRank.
        dispute_deduction = sum(
            abs(e["weight"]) * seed_scores.get(e.get("client", "").lower(), 0.0)
            for e in edges if e.get("edge_type") == "dispute"
        )
        final_score = max(0.0, final_score - dispute_deduction)

        # ③ last_active: most recent edge timestamp
        edge_timestamps = [int(e.get("ts", 0)) for e in edges]
        last_active = max(edge_timestamps) if edge_timestamps else 0

        # ④ tee_stable: all tee_fingerprints consistent?
        tee_fps = {e.get("tee_fingerprint", "") for e in edges} - {"", "mock"}
        tee_stable = len(tee_fps) <= 1  # True if 0 or 1 unique real fingerprint

        # ⑤ endorser_stats: mean + stddev of endorsing Clients' seed scores
        client_seeds = [seed_scores.get(e.get("client", "").lower(), 0.0) for e in edges]
        endorser_mean = sum(client_seeds) / len(client_seeds) if client_seeds else 0.0
        endorser_std = (
            (sum((s - endorser_mean) ** 2 for s in client_seeds) / len(client_seeds)) ** 0.5
            if client_seeds else 0.0
        )

        results.append({
            "worker": worker,
            "final_score": round(final_score, 8),
            "verirank": round(pr, 8),
            "edge_count": len(edges),
            "unique_clients": len({e.get("client", "") for e in edges}),
            "total_weight": round(sum(e["weight"] for e in edges), 6),
            "last_active": last_active,
            "tee_stable": tee_stable,
            "endorser_mean": round(endorser_mean, 6),
            "endorser_std": round(endorser_std, 6),
            "anomalies": worker_anomalies,
        })

    results.sort(key=lambda x: x["final_score"], reverse=True)
    return results


def load_registry(registry_path: str) -> list[dict]:
    """Load worker_registry.json and return list of worker entries."""
    with open(registry_path, "r", encoding="utf-8") as f:
        registry = json.load(f)
    return registry.get("workers", [])


def main():
    parser = argparse.ArgumentParser(description="VeriTask Bidding Agent — rank Workers by reputation")
    parser.add_argument("--workers", default="",
                        help="Comma-separated Worker addresses to evaluate")
    parser.add_argument("--registry", default="",
                        help="Path to worker_registry.json (alternative to --workers)")
    parser.add_argument("--json", action="store_true", help="Output result as JSON")
    parser.add_argument("--verbose", action="store_true", help="Show edge details per worker")
    args = parser.parse_args()

    worker_list = []
    registry_data = []

    if args.registry:
        registry_data = load_registry(args.registry)
        worker_list = [w["address"] for w in registry_data if w.get("address")]
    elif args.workers:
        worker_list = [w.strip() for w in args.workers.split(",") if w.strip()]

    if not worker_list:
        print("Error: no valid worker addresses. Use --workers or --registry.", file=sys.stderr)
        sys.exit(1)

    ranked = rank_workers(worker_list, verbose=args.verbose)

    # Enrich results with registry metadata (alias, url) if available
    registry_map = {w["address"].lower(): w for w in registry_data}
    for r in ranked:
        meta = registry_map.get(r["worker"].lower(), {})
        r["alias"] = meta.get("alias", "")
        r["url"] = meta.get("url", "")

    if args.json:
        print(json.dumps(ranked, indent=2))
    else:
        print("\n[Bidding] Worker ranking:")
        for i, r in enumerate(ranked, 1):
            anomaly_str = f"  ⚠️  {r['anomalies']}" if r["anomalies"] else ""
            print(
                f"  #{i}  {r['worker'][:14]}...  "
                f"score={r['final_score']:.6f}  "
                f"edges={r['edge_count']}  "
                f"clients={r['unique_clients']}"
                f"{anomaly_str}"
            )
        if ranked:
            print(f"\n[Bidding] ✅ Best Worker: {ranked[0]['worker']}")


if __name__ == "__main__":
    main()