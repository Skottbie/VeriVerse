#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path

from web3 import Web3

spec = importlib.util.spec_from_file_location("ga", "skills/graduate-agent/graduate_agent.py")
ga = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ga)

addresses = json.loads(Path("addresses.json").read_text(encoding="utf-8"))["bsc"]

w3 = Web3(Web3.HTTPProvider(ga.RPC_URL))
escrow = w3.eth.contract(
    address=Web3.to_checksum_address(addresses["VeriEscrow"]),
    abi=ga.ESCROW_ABI,
)

agent_id = 4
expected_scope = ga._expected_scope(agent_id, ga.CHAIN_ID)
expected_signal = ga._expected_signal(agent_id, ga.CHAIN_ID)
proof_raw, _ = ga._auto_generate_proof(agent_id, expected_signal, expected_scope, w3, escrow)

out_dir = Path("tmp")
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / "agent4_proof.json"
out_path.write_text(
    json.dumps(
        {
            "agentId": agent_id,
            "signalHash": str(expected_signal),
            "proof": proof_raw,
            "escrow": addresses["VeriEscrow"],
        },
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
print(str(out_path))
