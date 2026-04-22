import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { createWalletClient, createPublicClient, http, parseAbi } from "viem";
import { bscTestnet } from "viem/chains";
import { privateKeyToAccount } from "viem/accounts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(__dirname, "..");
const statePath = path.resolve(projectRoot, "dashboard", "demo_state.js");
const stateJsonPath = path.resolve(projectRoot, "dashboard", "demo_state.json");

function buildDefaultState() {
  return {
    version: 1,
    revision: 0,
    updatedAt: null,
    enabled: false,
    steps: {
      launch_veri2_agent18: false,
      invest_agent17_usdt_0_05: false,
      challenge_agent17_trust_plus25: false,
      graduate_agent17: false,
      link_token_agent_17: false,
    },
  };
}

function usage() {
  return [
    "Usage:",
    "  node scripts/demo_dashboard_closure.js <command>",
    "",
    "Commands:",
    "  launch      Enable: show Veri #2 as NODE #18",
    "  invest      Enable: add +0.05 USDT stake event for NODE #17",
    "  challenge   Enable: add +25 trust event for NODE #17",
    "  graduate    Enable: set NODE #17 to GRADUATED",
    "  link-token  Link mock token CA to Agent #17 on-chain",
    "  all         Enable all steps",
    "  reset       Disable all steps (revert)",
    "  status      Print current state",
  ].join("\n");
}

function parseExistingState(text) {
  if (!text) return null;
  const match = text.match(
    /window\.__VERIVERSE_DEMO_STATE__\s*=\s*(\{[\s\S]*\})\s*;\s*$/m
  );
  if (!match) return null;
  try {
    return JSON.parse(match[1]);
  } catch (_) {
    return null;
  }
}

function loadState() {
  try {
    if (!fs.existsSync(statePath)) return buildDefaultState();
    const raw = fs.readFileSync(statePath, "utf8");
    const parsed = parseExistingState(raw);
    if (!parsed || typeof parsed !== "object") return buildDefaultState();
    return {
      ...buildDefaultState(),
      ...parsed,
      steps: {
        ...buildDefaultState().steps,
        ...(parsed.steps || {}),
      },
    };
  } catch (_) {
    return buildDefaultState();
  }
}

function renderStateFile(state) {
  const json = JSON.stringify(state, null, 2);
  return [
    "// AUTO-GENERATED DEMO STATE (front-end only)",
    "// Use `npm run demo:*` commands to update. Do not edit manually.",
    "",
    `window.__VERIVERSE_DEMO_STATE__ = ${json};`,
    "",
  ].join("\n");
}

function renderStateJson(state) {
  return `${JSON.stringify(state, null, 2)}\n`;
}

function normalizeState(next) {
  const baseline = buildDefaultState();
  const merged = {
    ...baseline,
    ...(next || {}),
    steps: {
      ...baseline.steps,
      ...((next && next.steps) || {}),
    },
  };
  merged.revision = Number.isFinite(Number(merged.revision))
    ? Number(merged.revision)
    : 0;
  return merged;
}

function bumpState(next) {
  const state = normalizeState(next);
  state.revision += 1;
  state.updatedAt = new Date().toISOString();
  return state;
}

function saveState(state) {
  const normalized = normalizeState(state);
  const content = renderStateFile(normalized);
  const jsonContent = renderStateJson(normalized);
  fs.writeFileSync(statePath, content, "utf8");
  fs.writeFileSync(stateJsonPath, jsonContent, "utf8");
}

function setAllSteps(state, value) {
  for (const key of Object.keys(state.steps || {})) {
    state.steps[key] = Boolean(value);
  }
}

function ensureEnabled(state) {
  state.enabled = true;
}

function enableStep(state, stepKey) {
  ensureEnabled(state);
  if (!state.steps || typeof state.steps !== "object") {
    state.steps = buildDefaultState().steps;
  }
  state.steps[stepKey] = true;
}

const MOCK_TOKEN_CA = "0x000000000000000000000000000000000000dEaD";
const DEMO_AGENT_ID = 17;

async function linkTokenOnChain() {
  const addrPath = path.resolve(projectRoot, "addresses.json");
  const addrs = JSON.parse(fs.readFileSync(addrPath, "utf8"));
  const registryAddr = addrs.bsc_testnet?.VTRegistry;
  if (!registryAddr) { console.error("ERR: VTRegistry address not found"); return; }

  const pk = process.env.PRIVATE_KEY;
  if (!pk) { console.error("ERR: PRIVATE_KEY env not set"); return; }

  const account = privateKeyToAccount(pk.startsWith("0x") ? pk : `0x${pk}`);
  const walletClient = createWalletClient({ account, chain: bscTestnet, transport: http() });
  const publicClient = createPublicClient({ chain: bscTestnet, transport: http() });

  const abi = parseAbi(["function linkAgentToken(uint256 agentId, address tokenCA) external"]);

  console.log(`Linking Agent #${DEMO_AGENT_ID} → ${MOCK_TOKEN_CA} ...`);
  try {
    const hash = await walletClient.writeContract({
      address: registryAddr,
      abi,
      functionName: "linkAgentToken",
      args: [BigInt(DEMO_AGENT_ID), MOCK_TOKEN_CA],
    });
    console.log(`TX sent: ${hash}`);
    const receipt = await publicClient.waitForTransactionReceipt({ hash });
    console.log(`TX confirmed in block ${receipt.blockNumber}. linkAgentToken done.`);
  } catch (err) {
    console.error("linkAgentToken failed:", err.shortMessage || err.message);
  }
}

async function main() {
  const cmd = String(process.argv[2] || "status").trim().toLowerCase();
  let state = loadState();

  if (cmd === "status") {
    console.log(JSON.stringify(state, null, 2));
    return;
  }

  if (cmd === "reset") {
    state = bumpState(buildDefaultState());
    saveState(state);
    console.log("OK: demo state reset.");
    return;
  }

  if (cmd === "launch") {
    enableStep(state, "launch_veri2_agent18");
  } else if (cmd === "invest") {
    enableStep(state, "invest_agent17_usdt_0_05");
  } else if (cmd === "challenge") {
    enableStep(state, "challenge_agent17_trust_plus25");
  } else if (cmd === "graduate") {
    enableStep(state, "graduate_agent17");
  } else if (cmd === "link-token") {
    enableStep(state, "link_token_agent_17");
    state = bumpState(state);
    saveState(state);
    console.log("OK: demo state updated (link-token).");
    // Now call on-chain linkAgentToken
    await linkTokenOnChain();
    return;
  } else if (cmd === "all") {
    ensureEnabled(state);
    setAllSteps(state, true);
  } else {
    console.error(`Unknown command '${cmd}'.\n\n${usage()}`);
    process.exitCode = 1;
    return;
  }

  state = bumpState(state);
  saveState(state);
  console.log(`OK: demo state updated (${cmd}).`);
}

main().catch(console.error);
