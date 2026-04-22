/**
 * fix_semaphore.js — Redeploy MockSemaphore (v2) + VeriEscrowV2 to fix GRAD-AUTH-01
 *
 * Root cause: Original MockSemaphore lacked getMerkleTreeRoot(), causing
 * graduate_agent.py's on-chain root check to revert.
 *
 * This script:
 *   1. Deploys new MockSemaphore (with getMerkleTreeRoot + setMerkleTreeRoot)
 *   2. Deploys new VeriEscrowV2 (same USDT/VTRegistry/VeriSBT, new Semaphore)
 *   3. Migrates permissions: VeriSBT.setMinter + VTRegistry.setRegistrar → new escrow
 *   4. Calls escrow.bindCreatorCommitment(2, commitment) → creates group + adds member
 *   5. Computes correct Merkle root via @semaphore-protocol/group and sets it on-chain
 *   6. Updates addresses.json
 *
 * Usage: npx hardhat run scripts/fix_semaphore.js --network bsc_testnet
 */
import hre from "hardhat";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { Group } from "@semaphore-protocol/group";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const AGENT_ID = 2;
const SEMAPHORE_TREE_DEPTH = 20;

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  console.log("═══════════════════════════════════════════════════");
  console.log("  MockSemaphore v2 + VeriEscrowV2 Fix Deployment");
  console.log("═══════════════════════════════════════════════════");
  console.log("Deployer:", deployer.address);

  const balance = await hre.ethers.provider.getBalance(deployer.address);
  console.log("Balance:", hre.ethers.formatEther(balance), "tBNB");

  // Load existing addresses
  const addressesPath = path.resolve(__dirname, "../addresses.json");
  const addresses = JSON.parse(fs.readFileSync(addressesPath, "utf8"));
  const existing = addresses.bsc_testnet || addresses.bsc;
  if (!existing) throw new Error("No bsc_testnet entry in addresses.json");

  const usdtAddress = existing.USDT;
  const registryAddress = existing.VTRegistry;
  const sbtAddress = existing.VeriSBT;
  const oldSemaphoreAddress = existing.Semaphore;
  const oldEscrowAddress = existing.VeriEscrow;

  console.log("\nExisting contracts (unchanged):");
  console.log("  MockUSDT:", usdtAddress);
  console.log("  VTRegistry:", registryAddress);
  console.log("  VeriSBT:", sbtAddress);
  console.log("  Old Semaphore:", oldSemaphoreAddress);
  console.log("  Old Escrow:", oldEscrowAddress);

  // Load Agent #2 identity commitment
  const identityPath = path.resolve(__dirname, "../data/semaphore-identities", `${AGENT_ID}.json`);
  const identity = JSON.parse(fs.readFileSync(identityPath, "utf8"));
  const commitment = BigInt(identity.commitment);
  console.log(`\nAgent #${AGENT_ID} commitment:`, commitment.toString().slice(0, 20) + "...");

  // 1. Deploy new MockSemaphore
  console.log("\n[1/6] Deploying MockSemaphore v2...");
  const MockSemaphore = await hre.ethers.getContractFactory("MockSemaphore");
  const semaphore = await MockSemaphore.deploy();
  await semaphore.waitForDeployment();
  const semaphoreAddress = await semaphore.getAddress();
  console.log("  MockSemaphore v2:", semaphoreAddress);

  // 2. Deploy new VeriEscrowV2
  console.log("\n[2/6] Deploying VeriEscrowV2...");
  const VeriEscrow = await hre.ethers.getContractFactory("VeriEscrowV2");
  const escrow = await VeriEscrow.deploy(usdtAddress, registryAddress, semaphoreAddress, sbtAddress);
  await escrow.waitForDeployment();
  const escrowAddress = await escrow.getAddress();
  console.log("  VeriEscrowV2:", escrowAddress);

  // 3. Migrate permissions
  console.log("\n[3/6] Migrating permissions...");
  const sbt = await hre.ethers.getContractAt("VeriSBT", sbtAddress);
  const registry = await hre.ethers.getContractAt("VTRegistry", registryAddress);

  const setMinterTx = await sbt.setMinter(escrowAddress);
  await setMinterTx.wait();
  console.log("  VeriSBT.setMinter →", escrowAddress);

  const setRegistrarTx = await registry.setRegistrar(escrowAddress);
  await setRegistrarTx.wait();
  console.log("  VTRegistry.setRegistrar →", escrowAddress);

  // Verify
  const registrar = await registry.registrar();
  if (registrar.toLowerCase() !== escrowAddress.toLowerCase()) {
    throw new Error(`setRegistrar verify FAILED: ${registrar}`);
  }
  console.log("  Permissions verified ✓");

  // 4. Bind agent commitment (creates group + adds member on new semaphore)
  console.log(`\n[4/6] Binding Agent #${AGENT_ID} commitment...`);
  const bindTx = await escrow.bindCreatorCommitment(AGENT_ID, commitment);
  await bindTx.wait();
  const groupId = await escrow.agentGroupId(AGENT_ID);
  console.log("  agentGroupId:", groupId.toString());

  // 5. Compute Merkle root off-chain and set on-chain
  console.log("\n[5/6] Computing Merkle root...");
  const group = new Group(Number(groupId), SEMAPHORE_TREE_DEPTH, [commitment]);
  const merkleRoot = group.root;
  console.log("  Computed root:", merkleRoot.toString().slice(0, 20) + "...");

  const setRootTx = await semaphore.setMerkleTreeRoot(groupId, merkleRoot);
  await setRootTx.wait();

  // Verify root matches
  const chainRoot = await semaphore.getMerkleTreeRoot(groupId);
  if (chainRoot.toString() !== merkleRoot.toString()) {
    throw new Error(`Root mismatch! chain=${chainRoot} local=${merkleRoot}`);
  }
  console.log("  On-chain root set and verified ✓");

  // 6. Update addresses.json
  console.log("\n[6/6] Updating addresses.json...");
  addresses.bsc_testnet = {
    ...existing,
    VeriEscrow: escrowAddress,
    Semaphore: semaphoreAddress,
    oldVeriEscrow: oldEscrowAddress,
    oldSemaphore: oldSemaphoreAddress,
    deployedAt: new Date().toISOString(),
    note: "MockSemaphore v2 (with getMerkleTreeRoot) + redeployed VeriEscrowV2",
  };

  fs.writeFileSync(addressesPath, JSON.stringify(addresses, null, 2));

  console.log("\n═══════════════════════════════════════════════════");
  console.log("  Fix Deployment Complete!");
  console.log("═══════════════════════════════════════════════════");
  console.log("  New MockSemaphore:", semaphoreAddress);
  console.log("  New VeriEscrowV2:", escrowAddress);
  console.log("  Agent #2 group:", groupId.toString());
  console.log("  Merkle root set ✓");
  console.log("\nAddresses saved to addresses.json");
  console.log("Explorer: https://testnet.bscscan.com/address/" + escrowAddress);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
