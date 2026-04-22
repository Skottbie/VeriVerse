import { ethers } from "ethers";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import dotenv from "dotenv";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.resolve(__dirname, "../.env") });

function usage() {
  return [
    "Usage:",
    "  node scripts/update_trust.js <agentId> <delta>",
    "",
    "Examples:",
    "  node scripts/update_trust.js 3 +18",
    "  node scripts/update_trust.js 10 -29",
  ].join("\n");
}

function parseAgentId(raw) {
  if (!raw || !/^\d+$/.test(raw)) {
    throw new Error(`Invalid agentId '${raw}'. agentId must be a positive integer.\n\n${usage()}`);
  }
  const id = BigInt(raw);
  if (id <= 0n) {
    throw new Error(`Invalid agentId '${raw}'. agentId must be >= 1.`);
  }
  return id;
}

function parseDelta(raw) {
  if (!raw || !/^[+-]?\d+$/.test(raw)) {
    throw new Error(`Invalid delta '${raw}'. delta must be a signed integer, e.g. +18 or -29.\n\n${usage()}`);
  }
  return BigInt(raw);
}

function getTargetNetworkName() {
  return process.env.TARGET_NETWORK || "bsc";
}

function getRpcUrl(networkName) {
  const envUrl = process.env.RPC_URL?.trim();
  if (envUrl) {
    return envUrl;
  }

  const defaults = {
    bsc: "https://bsc-dataseed.binance.org",
    bsc_testnet: "https://bsc-testnet-rpc.publicnode.com",
  };

  const rpcUrl = defaults[networkName];
  if (!rpcUrl) {
    throw new Error(`No RPC_URL provided and no default RPC for network '${networkName}'`);
  }
  return rpcUrl;
}

function loadRegistryAddress(networkName) {
  const addressesPath = path.resolve(__dirname, "../addresses.json");
  if (!fs.existsSync(addressesPath)) {
    throw new Error("addresses.json not found");
  }

  const addresses = JSON.parse(fs.readFileSync(addressesPath, "utf8"));
  const fromFile = addresses[networkName]?.VTRegistry;
  const fromEnv = process.env.VT_REGISTRY_ADDRESS?.trim();
  const registryAddress = fromFile || fromEnv;
  if (!registryAddress) {
    throw new Error(
      `VTRegistry address not found for network '${networkName}'. ` +
      "Set VT_REGISTRY_ADDRESS or add it to addresses.json."
    );
  }

  if (fromFile && fromEnv && fromFile.toLowerCase() !== fromEnv.toLowerCase()) {
    console.warn(
      `Warning: VT_REGISTRY_ADDRESS(${fromEnv}) ignored, using addresses.json value(${fromFile})`
    );
  }
  return registryAddress;
}

function clampAtZero(value) {
  return value < 0n ? 0n : value;
}

async function main() {
  const [agentIdRaw, deltaRaw] = process.argv.slice(2);
  const agentId = parseAgentId(agentIdRaw);
  const delta = parseDelta(deltaRaw);

  const networkName = getTargetNetworkName();
  const rpcUrl = getRpcUrl(networkName);
  const registryAddress = loadRegistryAddress(networkName);
  const privateKeyRaw = process.env.CLIENT_PRIVATE_KEY?.trim();
  if (!privateKeyRaw) {
    throw new Error("CLIENT_PRIVATE_KEY is missing in env");
  }
  const privateKey = privateKeyRaw.startsWith("0x") ? privateKeyRaw : `0x${privateKeyRaw}`;

  const provider = new ethers.JsonRpcProvider(rpcUrl);
  const signer = new ethers.Wallet(privateKey, provider);
  const registryAbi = [
    "function owner() view returns (address)",
    "function getAgent(uint256) view returns (tuple(string name,address creator,address wallet,int256 trustScore,uint8 status))",
    "function updateTrust(uint256 agentId, int256 delta)",
  ];
  const registry = new ethers.Contract(registryAddress, registryAbi, signer);

  const chain = await provider.getNetwork();
  const nonce = await provider.getTransactionCount(signer.address, "pending");

  const owner = await registry.owner();
  if (signer.address.toLowerCase() !== owner.toLowerCase()) {
    throw new Error(`Signer ${signer.address} is not VTRegistry owner ${owner}`);
  }

  const before = await registry.getAgent(agentId);
  const beforeTrust = BigInt(before.trustScore);
  const expectedAfter = clampAtZero(beforeTrust + delta);

  if (Number(before.status) !== 0) {
    throw new Error(`Agent #${agentId} is not Active (status=${before.status})`);
  }

  console.log("Network:", networkName);
  console.log("ChainId:", chain.chainId.toString());
  console.log("RPC:", rpcUrl);
  console.log("Signer:", signer.address);
  console.log("Nonce(pending):", nonce.toString());
  console.log("Registry:", registryAddress);
  console.log("Agent:", `#${agentId} ${before.name}`);
  console.log("Trust before:", beforeTrust.toString());
  console.log("Delta:", delta.toString());
  console.log("Expected trust after:", expectedAfter.toString());

  const tx = await registry.updateTrust(agentId, delta);
  console.log("Submitted tx:", tx.hash);

  const receipt = await tx.wait();
  if (!receipt || Number(receipt.status) !== 1) {
    throw new Error(`updateTrust transaction failed: ${tx.hash}`);
  }

  const after = await registry.getAgent(agentId);
  const afterTrust = BigInt(after.trustScore);
  console.log("Mined block:", receipt.blockNumber);
  console.log("Trust after:", afterTrust.toString());

  if (afterTrust !== expectedAfter) {
    throw new Error(
      `Post-check mismatch: expected ${expectedAfter.toString()}, got ${afterTrust.toString()}`
    );
  }

  console.log("Done: trust score updated successfully.");
}

main().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
