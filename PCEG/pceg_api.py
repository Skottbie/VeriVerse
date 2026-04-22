#!/usr/bin/env python3
"""
VeriVerse — Public PCEG REST API (BSC Testnet)
Read-only endpoints exposing the Proof-Conditioned Endorsement Graph.

Mounted as a FastAPI sub-router at /pceg/* on the Worker server.
Reuses bidding_agent.py functions for chain scanning + VeriRank calculation,
but skips OnchainOS seed scores (requires API key) — uses uniform personalization.
"""

import asyncio
import json
import os
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

# bidding_agent is loaded lazily inside _refresh_cache() to avoid OOM on
# low-memory CVM (web3 + networkx + numpy + scipy ≈ 400 MB at import time).
_ba = None  # will hold bidding_agent module after first lazy load

# Known test/invalid proof_hash values
_KNOWN_TEST_HASHES = {
    "abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234",
    "0" * 64,
}


def _classify_data_source(proof_hash: str) -> str:
    """Classify an edge as 'preseed_demo' or 'live' based on proof_hash format."""
    if not proof_hash or proof_hash in _KNOWN_TEST_HASHES:
        return "preseed_demo"
    # ABI-encoded uint256 timestamps have 48+ leading zeros — preseed artifact
    if proof_hash[:48] == "0" * 48:
        return "preseed_demo"
    return "live"

router = APIRouter(prefix="/pceg", tags=["PCEG"])

# ── In-memory cache to avoid re-scanning on every request ────────────────
_CACHE_TTL = 120  # seconds
_cache: dict = {"ts": 0, "edges": [], "parsed": [], "rankings": []}


# ── Response models ──────────────────────────────────────────────────────

class EdgeResponse(BaseModel):
    tx_hash: str
    client: str
    worker: str
    proof_hash: str = ""
    tee_fingerprint: str = ""
    amount_usdt: float = 0.0
    age_days: float = 0.0
    proof_quality: float = 0.0
    weight: float = 0.0
    ts: int = 0
    data_source: str = "live"  # "live" or "preseed_demo"
    edge_type: str = "endorsement"  # "endorsement" or "dispute"
    dispute_reason: str = ""  # e.g. "zk_proof_invalid", only for dispute edges


class WorkerRanking(BaseModel):
    worker: str
    final_score: float
    verirank: float
    edge_count: int
    unique_clients: int
    total_weight: float
    last_active: int = 0
    tee_stable: bool = True
    anomalies: list[str] = Field(default_factory=list)


class GraphSummary(BaseModel):
    total_edges: int
    live_edges: int = 0
    demo_edges: int = 0
    endorsement_edges: int = 0
    dispute_edges: int = 0
    total_workers: int
    total_clients: int
    registry: str
    last_scan_ts: int
    rankings: list[WorkerRanking]


class WorkerDetail(BaseModel):
    worker: str
    verirank: float
    edge_count: int
    unique_clients: int
    total_weight: float
    last_active: int = 0
    tee_stable: bool = True
    anomalies: list[str] = Field(default_factory=list)
    edges: list[EdgeResponse] = Field(default_factory=list)


# ── Core: build rankings from chain data ─────────────────────────────────

def _refresh_cache() -> None:
    """Fetch edges from BSC, parse, compute VeriRank, cache results."""
    now = int(time.time())
    if now - _cache["ts"] < _CACHE_TTL and _cache["parsed"]:
        return  # fresh enough

    # Lazy-load bidding_agent on first call (avoids 400MB import at startup)
    global _ba
    if _ba is None:
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(__file__))
        import bidding_agent
        bidding_agent.VERITASK_MODE = "demo"
        _ba = bidding_agent

    raw_logs = _ba.fetch_edges_cached(_ba.BSC_RPC_URL)
    parsed = _ba._parse_logs_to_edges(_ba.BSC_RPC_URL, raw_logs, use_registry=True)

    # Label each edge as "live" or "preseed_demo" (no filtering — show everything)
    for e in parsed:
        e["data_source"] = _classify_data_source(e.get("proof_hash", ""))

    # Group edges by worker
    workers_edges: dict[str, list[dict]] = {}
    all_clients: set[str] = set()
    for edge in parsed:
        w = edge.get("worker", "").lower()
        if w:
            workers_edges.setdefault(w, []).append(edge)
            c = edge.get("client", "").lower()
            if c:
                all_clients.add(c)

    # Uniform seed scores (no OnchainOS dependency), with DEMO_SEED_OVERRIDES
    seed_scores = {c: 1.0 for c in all_clients}
    _demo_raw = os.environ.get("DEMO_SEED_OVERRIDES", "")
    if _demo_raw:
        for k, v in json.loads(_demo_raw).items():
            if k.lower() in seed_scores:
                seed_scores[k.lower()] = float(v)

    # Build graph + VeriRank
    G = _ba.build_graph(workers_edges, seed_scores)
    pr_scores = _ba.run_verirank(G, seed_scores)
    worker_list = list(workers_edges.keys())
    anomalies = _ba.detect_anomalies(G, worker_list)

    # Compose rankings
    rankings: list[dict] = []
    for w in worker_list:
        edges = workers_edges[w]
        pr = pr_scores.get(w, 0.0)
        worker_anomalies = anomalies.get(w, [])

        penalty = 1.0
        if "client_clique" in worker_anomalies:
            penalty *= 0.3
        elif "isolated_endorser" in worker_anomalies:
            penalty *= 0.5

        edge_timestamps = [int(e.get("ts", 0)) for e in edges]
        last_active = max(edge_timestamps) if edge_timestamps else 0
        tee_fps = {e.get("tee_fingerprint", "") for e in edges} - {"", "mock"}

        # Post-hoc dispute deduction (mirrors bidding_agent.py rank_workers logic)
        dispute_deduction = sum(
            abs(e["weight"]) * seed_scores.get(e.get("client", "").lower(), 0.0)
            for e in edges if e.get("edge_type") == "dispute"
        )
        final_score = max(0.0, pr * penalty - dispute_deduction)

        rankings.append({
            "worker": w,
            "final_score": round(final_score, 8),
            "verirank": round(pr * penalty, 8),
            "edge_count": len(edges),
            "unique_clients": len({e.get("client", "") for e in edges}),
            "total_weight": round(sum(e["weight"] for e in edges), 6),
            "last_active": last_active,
            "tee_stable": len(tee_fps) <= 1,
            "anomalies": worker_anomalies,
        })

    rankings.sort(key=lambda x: x["final_score"], reverse=True)

    _cache.update({
        "ts": now,
        "edges": raw_logs,
        "parsed": parsed,
        "rankings": rankings,
        "workers_edges": workers_edges,
        "all_clients": all_clients,
    })


async def _ensure_cache() -> None:
    """Run _refresh_cache in a thread pool so it never blocks the event loop."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _refresh_cache)


# ── Endpoints ────────────────────────────────────────────────────────────

@router.get("/graph", response_model=GraphSummary)
async def get_graph():
    """Full PCEG reputation graph summary with VeriRank scores for all workers."""
    try:
        await _ensure_cache()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Chain scan failed: {e}")

    all_workers = {r["worker"] for r in _cache["rankings"]}
    parsed = _cache["parsed"]
    live_count = sum(1 for e in parsed if e.get("data_source") == "live")
    dispute_count = sum(1 for e in parsed if e.get("edge_type") == "dispute")
    endorsement_count = len(parsed) - dispute_count
    return GraphSummary(
        total_edges=len(parsed),
        live_edges=live_count,
        demo_edges=len(parsed) - live_count,
        endorsement_edges=endorsement_count,
        dispute_edges=dispute_count,
        total_workers=len(all_workers),
        total_clients=len(_cache.get("all_clients", set())),
        registry=(_ba.VT_REGISTRY if _ba else "") or "(legacy USDT Transfer)",
        last_scan_ts=_cache["ts"],
        rankings=[WorkerRanking(**r) for r in _cache["rankings"]],
    )


@router.get("/rankings", response_model=list[WorkerRanking])
async def get_rankings():
    """All workers ranked by VeriRank score (descending)."""
    try:
        await _ensure_cache()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Chain scan failed: {e}")

    return [WorkerRanking(**r) for r in _cache["rankings"]]


@router.get("/worker/{address}", response_model=WorkerDetail)
async def get_worker(address: str):
    """Single worker reputation details including all edge history."""
    try:
        await _ensure_cache()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Chain scan failed: {e}")

    addr = address.lower()
    workers_edges = _cache.get("workers_edges", {})
    if addr not in workers_edges:
        raise HTTPException(status_code=404, detail=f"Worker {address} not found in PCEG")

    # Find ranking entry
    ranking = next((r for r in _cache["rankings"] if r["worker"] == addr), None)
    if ranking is None:
        raise HTTPException(status_code=404, detail=f"Worker {address} not found in rankings")

    edges = workers_edges[addr]
    edge_responses = [
        EdgeResponse(
            tx_hash=e.get("tx_hash", ""),
            client=e.get("client", ""),
            worker=e.get("worker", ""),
            proof_hash=e.get("proof_hash", ""),
            tee_fingerprint=e.get("tee_fingerprint", ""),
            amount_usdt=e.get("amount_usdt", 0.0),
            age_days=round(e.get("age_days", 0.0), 2),
            proof_quality=e.get("proof_quality", 0.0),
            weight=round(e.get("weight", 0.0), 6),
            ts=int(e.get("ts", 0)),
            data_source=e.get("data_source", "live"),
            edge_type=e.get("edge_type", "endorsement"),
            dispute_reason=e.get("dispute_reason", ""),
        )
        for e in edges
    ]

    return WorkerDetail(edges=edge_responses, **ranking)


@router.get("/edge/{tx_hash}", response_model=Optional[EdgeResponse])
async def get_edge(tx_hash: str):
    """Look up a single edge by transaction hash."""
    try:
        _refresh_cache()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Chain scan failed: {e}")

    tx_lower = tx_hash.lower()
    for edge in _cache.get("parsed", []):
        if edge.get("tx_hash", "").lower() == tx_lower:
            return EdgeResponse(
                tx_hash=edge.get("tx_hash", ""),
                client=edge.get("client", ""),
                worker=edge.get("worker", ""),
                proof_hash=edge.get("proof_hash", ""),
                tee_fingerprint=edge.get("tee_fingerprint", ""),
                amount_usdt=edge.get("amount_usdt", 0.0),
                age_days=round(edge.get("age_days", 0.0), 2),
                proof_quality=edge.get("proof_quality", 0.0),
                weight=round(edge.get("weight", 0.0), 6),
                ts=int(edge.get("ts", 0)),
                data_source=edge.get("data_source", "live"),
                edge_type=edge.get("edge_type", "endorsement"),
                dispute_reason=edge.get("dispute_reason", ""),
            )

    raise HTTPException(status_code=404, detail=f"Edge with txHash {tx_hash} not found")
