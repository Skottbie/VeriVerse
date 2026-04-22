/**
 * deploy_testnet.js — Deploy all contracts to BSC Testnet
 * 
 * Deploys: MockUSDT → MockSemaphore → VTRegistry → VeriSBT → VeriEscrowV2
 * Then: setMinter(escrow), setRegistrar(escrow), mint test USDT
 * 
 * Usage: npx hardhat run scripts/deploy_testnet.js --network bsc_testnet
 */
import hre from "hardhat";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  console.log("═══════════════════════════════════════════════════");
  console.log("  VeriVerse BSC Testnet Deployment");
  console.log("═══════════════════════════════════════════════════");
  console.log("Deployer:", deployer.address);

  const balance = await hre.ethers.provider.getBalance(deployer.address);
  const balanceBNB = hre.ethers.formatEther(balance);
  console.log("Balance:", balanceBNB, "tBNB");

  if (parseFloat(balanceBNB) < 0.01) {
    throw new Error(
      `Insufficient tBNB (${balanceBNB}). Get testnet BNB from https://www.bnbchain.org/en/testnet-faucet`
    );
  }

  // 1. MockUSDT
  console.log("\n[1/5] Deploying MockUSDT...");
  const MockUSDT = await hre.ethers.getContractFactory("MockUSDT");
  const usdt = await MockUSDT.deploy();
  await usdt.waitForDeployment();
  const usdtAddress = await usdt.getAddress();
  console.log("  MockUSDT:", usdtAddress);

  // Mint 10,000 USDT to deployer
  const mintTx = await usdt.mint(deployer.address, 10000n * 10n ** 6n); // 6 decimals
  await mintTx.wait();
  console.log("  Minted 10,000 mUSDT to deployer");

  // 2. MockSemaphore
  console.log("\n[2/5] Deploying MockSemaphore...");
  const MockSemaphore = await hre.ethers.getContractFactory("MockSemaphore");
  const semaphore = await MockSemaphore.deploy();
  await semaphore.waitForDeployment();
  const semaphoreAddress = await semaphore.getAddress();
  console.log("  MockSemaphore:", semaphoreAddress);

  // 3. VTRegistry
  console.log("\n[3/5] Deploying VTRegistry...");
  const VTRegistry = await hre.ethers.getContractFactory("VTRegistry");
  const registry = await VTRegistry.deploy();
  await registry.waitForDeployment();
  const registryAddress = await registry.getAddress();
  console.log("  VTRegistry:", registryAddress);

  // 4. VeriSBT
  console.log("\n[4/5] Deploying VeriSBT...");
  const VeriSBT = await hre.ethers.getContractFactory("VeriSBT");
  const sbt = await VeriSBT.deploy(deployer.address);
  await sbt.waitForDeployment();
  const sbtAddress = await sbt.getAddress();
  console.log("  VeriSBT:", sbtAddress);

  // 5. VeriEscrowV2
  console.log("\n[5/5] Deploying VeriEscrowV2...");
  const VeriEscrow = await hre.ethers.getContractFactory("VeriEscrowV2");
  const escrow = await VeriEscrow.deploy(usdtAddress, registryAddress, semaphoreAddress, sbtAddress);
  await escrow.waitForDeployment();
  const escrowAddress = await escrow.getAddress();
  console.log("  VeriEscrowV2:", escrowAddress);

  // Post-deploy: permissions
  console.log("\n[Post] Setting permissions...");

  const setMinterTx = await sbt.setMinter(escrowAddress);
  await setMinterTx.wait();
  console.log("  VeriSBT.setMinter →", escrowAddress);

  const setRegistrarTx = await registry.setRegistrar(escrowAddress);
  await setRegistrarTx.wait();
  console.log("  VTRegistry.setRegistrar →", escrowAddress);

  // Verify permissions
  const registrar = await registry.registrar();
  if (registrar.toLowerCase() !== escrowAddress.toLowerCase()) {
    throw new Error(`setRegistrar verify FAILED: ${registrar}`);
  }
  console.log("  Permissions verified ✓");

  // Save addresses
  const addressesPath = path.resolve(__dirname, "../addresses.json");
  let addresses = {};
  if (fs.existsSync(addressesPath)) {
    addresses = JSON.parse(fs.readFileSync(addressesPath, "utf8"));
  }

  addresses.bsc_testnet = {
    VTRegistry: registryAddress,
    VeriEscrow: escrowAddress,
    VeriSBT: sbtAddress,
    Semaphore: semaphoreAddress,
    USDT: usdtAddress,
    deployer: deployer.address,
    deployedAt: new Date().toISOString(),
    note: "MockUSDT (6 decimals) + MockSemaphore for testnet",
  };

  fs.writeFileSync(addressesPath, JSON.stringify(addresses, null, 2));

  console.log("\n═══════════════════════════════════════════════════");
  console.log("  Deployment Complete!");
  console.log("═══════════════════════════════════════════════════");
  console.log(JSON.stringify(addresses.bsc_testnet, null, 2));
  console.log("\nAddresses saved to addresses.json");
  console.log("Explorer: https://testnet.bscscan.com/address/" + escrowAddress);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
