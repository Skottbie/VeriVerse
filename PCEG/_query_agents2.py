#!/usr/bin/env python3
"""Query all agents in VTRegistry v2 on BSC Testnet."""
from web3 import Web3
import json, os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

w3 = Web3(Web3.HTTPProvider(os.getenv('BSC_RPC_URL')))
reg = w3.to_checksum_address(os.getenv('VT_REGISTRY_ADDRESS'))
abi = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'goldsky', 'vtregistry.abi.json')))
c = w3.eth.contract(address=reg, abi=abi)

next_id = c.functions.nextAgentId().call()
print(f"nextAgentId = {next_id}  (agents: 1..{next_id - 1})")
status_map = {0: 'Pending', 1: 'Registered', 2: 'Graduated'}

for i in range(1, next_id):
    a = c.functions.getAgent(i).call()
    name, creator, wallet, trust, status = a
    print(f"  [{i}] {wallet}  status={status_map.get(status, status)}  trust={trust}  name={name}  creator={creator}")
