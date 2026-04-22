#!/usr/bin/env python3
"""Quick query: list all agents in VTRegistry on BSC Testnet."""
from web3 import Web3
import json, os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

w3 = Web3(Web3.HTTPProvider(os.getenv('BSC_RPC_URL')))
reg = w3.to_checksum_address(os.getenv('VT_REGISTRY_ADDRESS'))

abi = json.loads('''[
  {"inputs":[],"name":"agentCount","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
  {"inputs":[{"type":"uint256"}],"name":"agentList","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
  {"inputs":[{"type":"address"}],"name":"agents","outputs":[{"type":"uint8"},{"type":"string"},{"type":"address"},{"type":"uint256"}],"stateMutability":"view","type":"function"}
]''')

c = w3.eth.contract(address=reg, abi=abi)
count = c.functions.agentCount().call()
print(f"Agent count: {count}")
status_map = {0: 'None', 1: 'Registered', 2: 'Graduated'}
for i in range(count):
    addr = c.functions.agentList(i).call()
    info = c.functions.agents(addr).call()
    print(f"  [{i}] {addr}  status={status_map.get(info[0], info[0])}  name={info[1]}  owner={info[2]}")
