/**
 * routes/agentToken.js — Agent Token API
 * GET /api/agent-token/:agentId → 返回 Agent 基本信息 + Token 数据
 */
import { Router } from "express";
import { createPublicClient, http } from "viem";
import { bscTestnet, bsc } from "viem/chains";
import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import path from "path";
import { getTokenMode, isMockMode, getMockTokenData } from "../lib/tokenMode.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const router = Router();

// ── ABI (minimal — only what we need) ────────────────────────────────
const REGISTRY_ABI = [
  {
    name: "getAgent",
    type: "function",
    stateMutability: "view",
    inputs: [{ name: "agentId", type: "uint256" }],
    outputs: [
      {
        type: "tuple",
        components: [
          { name: "name", type: "string" },
          { name: "creator", type: "address" },
          { name: "wallet", type: "address" },
          { name: "trustScore", type: "int256" },
          { name: "status", type: "uint8" },
        ],
      },
    ],
  },
  {
    name: "agentTokenCA",
    type: "function",
    stateMutability: "view",
    inputs: [{ type: "uint256" }],
    outputs: [{ type: "address" }],
  },
  {
    name: "nextAgentId",
    type: "function",
    stateMutability: "view",
    inputs: [],
    outputs: [{ type: "uint256" }],
  },
];

const STATUS_MAP = { 0: "Active", 1: "Graduated", 2: "Deactivated" };
const ZERO_ADDR = "0x0000000000000000000000000000000000000000";

// ── Addresses (from addresses.json) ──────────────────────────────────
function loadAddresses() {
  const raw = readFileSync(path.resolve(__dirname, "../addresses.json"), "utf-8");
  const all = JSON.parse(raw);
  const network = process.env.TARGET_NETWORK || "bsc_testnet";
  return all[network] || all.bsc_testnet;
}

// ── Viem client ──────────────────────────────────────────────────────
function getClient() {
  const rpcUrl = process.env.BSC_RPC_URL || "https://bsc-testnet-rpc.publicnode.com";
  const chainId = Number(process.env.CHAIN_ID || 97);
  const chain = chainId === 56 ? bsc : bscTestnet;
  return createPublicClient({ chain, transport: http(rpcUrl) });
}

// ── Four.meme HTTP query (used in pausable/fourmeme modes) ───────────
async function fetchFourmemeTokenDetail(tokenCA) {
  try {
    const res = await fetch(
      `https://four.meme/meme-api/v1/private/token/detail?address=${tokenCA}`,
      { headers: { "Accept": "application/json" }, signal: AbortSignal.timeout(5000) }
    );
    if (!res.ok) return null;
    const data = await res.json();
    return data?.data || null;
  } catch {
    return null;
  }
}

// ── GET /api/agent-token/:agentId ────────────────────────────────────
router.get("/:agentId", async (req, res) => {
  try {
    const agentId = Number(req.params.agentId);
    if (!Number.isInteger(agentId) || agentId < 1) {
      return res.status(400).json({ error: "Invalid agentId" });
    }

    const addrs = loadAddresses();
    const registry = addrs.VTRegistry;
    const client = getClient();

    // Read agent info + tokenCA from chain
    const [agent, tokenCA] = await Promise.all([
      client.readContract({
        address: registry,
        abi: REGISTRY_ABI,
        functionName: "getAgent",
        args: [BigInt(agentId)],
      }),
      client.readContract({
        address: registry,
        abi: REGISTRY_ABI,
        functionName: "agentTokenCA",
        args: [BigInt(agentId)],
      }),
    ]);

    const hasToken = tokenCA !== ZERO_ADDR;
    const statusStr = STATUS_MAP[agent.status] || "Unknown";

    const result = {
      agentId,
      name: agent.name,
      creator: agent.creator,
      wallet: agent.wallet,
      trustScore: Number(agent.trustScore),
      status: statusStr,
      tokenMode: getTokenMode(),
      hasToken,
      tokenCA: hasToken ? tokenCA : null,
    };

    // ── Mock mode: return hardcoded data ──────────────────────────────
    if (isMockMode() && hasToken) {
      Object.assign(result, getMockTokenData(agentId, tokenCA));
      return res.json(result);
    }

    // ── Pausable / Fourmeme mode: query Four.meme API ─────────────────
    if (hasToken) {
      const detail = await fetchFourmemeTokenDetail(tokenCA);
      if (detail) {
        result.name_token = detail.tokenName || detail.name;
        result.symbol = detail.tokenSymbol || detail.symbol;
        result.mcap = detail.marketCap || null;
        result.holders = detail.holderCount || null;
        result.fourmemeUrl = `https://four.meme/token/${tokenCA}`;
      }
    }

    res.json(result);
  } catch (err) {
    // Agent not found → contract reverts
    if (err.message?.includes("Agent does not exist")) {
      return res.status(404).json({ error: "Agent not found" });
    }
    console.error("[agentToken] Error:", err.message);
    res.status(500).json({ error: "Internal server error" });
  }
});

// ── GET /api/agent-token (list all graduated agents with tokens) ─────
router.get("/", async (req, res) => {
  try {
    const addrs = loadAddresses();
    const client = getClient();

    const nextId = await client.readContract({
      address: addrs.VTRegistry,
      abi: REGISTRY_ABI,
      functionName: "nextAgentId",
    });

    const total = Number(nextId) - 1;
    const graduates = [];

    for (let i = 1; i <= total; i++) {
      const [agent, tokenCA] = await Promise.all([
        client.readContract({
          address: addrs.VTRegistry,
          abi: REGISTRY_ABI,
          functionName: "getAgent",
          args: [BigInt(i)],
        }),
        client.readContract({
          address: addrs.VTRegistry,
          abi: REGISTRY_ABI,
          functionName: "agentTokenCA",
          args: [BigInt(i)],
        }),
      ]);

      if (agent.status === 1) {
        // Graduated
        graduates.push({
          agentId: i,
          name: agent.name,
          trustScore: Number(agent.trustScore),
          hasToken: tokenCA !== ZERO_ADDR,
          tokenCA: tokenCA !== ZERO_ADDR ? tokenCA : null,
        });
      }
    }

    res.json({ tokenMode: getTokenMode(), total, graduates });
  } catch (err) {
    console.error("[agentToken] List error:", err.message);
    res.status(500).json({ error: "Internal server error" });
  }
});

export default router;
