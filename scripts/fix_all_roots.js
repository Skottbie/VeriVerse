/**
 * fix_all_roots.js — Universal Semaphore Merkle root fixer
 *
 * Iterates ALL identity files in data/semaphore-identities/*.json,
 * checks each agent's on-chain group root, and sets it if root == 0.
 *
 * This is idempotent: agents with correct roots are skipped.
 * Works for Agent #2, #3, and any future agents (4, 5, 6, ...).
 *
 * Usage: npx hardhat run scripts/fix_all_roots.js --network bsc_testnet
 */
import hre from "hardhat";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { Group } from "@semaphore-protocol/group";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SEMAPHORE_TREE_DEPTH = 20;

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  console.log("═══════════════════════════════════════════════════");
  console.log("  Universal Semaphore Merkle Root Fixer");
  console.log("═══════════════════════════════════════════════════");
  console.log("Deployer:", deployer.address);

  // Load contract addresses
  const addressesPath = path.resolve(__dirname, "../addresses.json");
  const addresses = JSON.parse(fs.readFileSync(addressesPath, "utf8"));
  const network = addresses.bsc_testnet || addresses.bsc;
  if (!network) throw new Error("No bsc_testnet/bsc entry in addresses.json");

  const semaphoreAddress = network.Semaphore;
  const escrowAddress = network.VeriEscrow;
  if (!semaphoreAddress || !escrowAddress) {
    throw new Error("Missing Semaphore or VeriEscrow address");
  }

  console.log("Semaphore:", semaphoreAddress);
  console.log("VeriEscrow:", escrowAddress);

  const semaphore = await hre.ethers.getContractAt("MockSemaphore", semaphoreAddress);
  const escrow = await hre.ethers.getContractAt("VeriEscrowV2", escrowAddress);

  // Scan all identity files
  const identitiesDir = path.resolve(__dirname, "../data/semaphore-identities");
  if (!fs.existsSync(identitiesDir)) {
    console.log("\nNo identity directory found. Nothing to fix.");
    return;
  }

  const files = fs.readdirSync(identitiesDir).filter((f) => f.endsWith(".json"));
  if (files.length === 0) {
    console.log("\nNo identity files found. Nothing to fix.");
    return;
  }

  console.log(`\nFound ${files.length} identity file(s):`);

  let fixed = 0;
  let skipped = 0;
  let errors = 0;

  for (const file of files) {
    const agentId = parseInt(path.basename(file, ".json"), 10);
    if (isNaN(agentId)) {
      console.log(`  [SKIP] ${file} — not a valid agent ID`);
      skipped++;
      continue;
    }

    try {
      const identity = JSON.parse(fs.readFileSync(path.join(identitiesDir, file), "utf8"));
      const commitment = BigInt(identity.commitment);

      // Check on-chain state
      const groupId = await escrow.agentGroupId(agentId);
      if (groupId === 0n) {
        console.log(`  [SKIP] Agent #${agentId} — no group binding (groupId=0)`);
        skipped++;
        continue;
      }

      const chainRoot = await semaphore.getMerkleTreeRoot(groupId);
      if (chainRoot !== 0n) {
        console.log(`  [OK]   Agent #${agentId} — root already set (groupId=${groupId})`);
        skipped++;
        continue;
      }

      // Root is 0 — compute and set
      console.log(`  [FIX]  Agent #${agentId} — groupId=${groupId}, root=0, fixing...`);
      const group = new Group(Number(groupId), SEMAPHORE_TREE_DEPTH, [commitment]);
      const merkleRoot = group.root;
      console.log(`         Computed root: ${merkleRoot.toString().slice(0, 30)}...`);

      const tx = await semaphore.setMerkleTreeRoot(groupId, merkleRoot);
      await tx.wait();

      // Verify
      const verifyRoot = await semaphore.getMerkleTreeRoot(groupId);
      if (verifyRoot.toString() !== merkleRoot.toString()) {
        throw new Error(`Root verification failed: chain=${verifyRoot} local=${merkleRoot}`);
      }

      console.log(`         Root set and verified ✓ (tx: ${tx.hash})`);
      fixed++;
    } catch (e) {
      console.log(`  [ERR]  Agent #${agentId} — ${e.message}`);
      errors++;
    }
  }

  console.log("\n═══════════════════════════════════════════════════");
  console.log(`  Results: ${fixed} fixed, ${skipped} skipped, ${errors} errors`);
  console.log("═══════════════════════════════════════════════════");
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
