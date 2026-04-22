import hre from "hardhat";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// BSC Testnet MockUSDT default address (can be overridden by USDT_ADDRESS env)
const DEFAULT_USDT_ADDRESS = "0xF8De09e7772366A104c4d42269891AD1ca7Be720";
const USDT_ADDRESS = process.env.USDT_ADDRESS || DEFAULT_USDT_ADDRESS;
const SEMAPHORE_ADDRESS_BY_NETWORK = {
  bsc: "0x8006099be7188e8DceB29Cf0aAB3eeD5E0842276",
  bsc_testnet: "0x8006099be7188e8DceB29Cf0aAB3eeD5E0842276",
};

async function main() {
  // Read VTRegistry address from addresses.json
  const addressesPath = path.resolve(__dirname, "../addresses.json");
  if (!fs.existsSync(addressesPath)) {
    throw new Error("addresses.json not found — deploy VTRegistry first");
  }
  const addresses = JSON.parse(fs.readFileSync(addressesPath, "utf8"));
  const networkName = hre.network.name;
  const registryAddress = addresses[networkName]?.VTRegistry;
  if (!registryAddress) {
    throw new Error(`VTRegistry address not found for network ${networkName}`);
  }

  const semaphoreAddress = process.env.SEMAPHORE_ADDRESS || SEMAPHORE_ADDRESS_BY_NETWORK[networkName];
  if (!semaphoreAddress) {
    throw new Error(`Semaphore address not configured for network ${networkName}`);
  }

  const [deployer] = await hre.ethers.getSigners();
  console.log("Deploying VeriEscrowV2 with:", deployer.address);
  console.log("VTRegistry:", registryAddress);
  console.log("USDT:", USDT_ADDRESS);
  console.log("Semaphore:", semaphoreAddress);

  const balance = await hre.ethers.provider.getBalance(deployer.address);
  console.log("Balance:", hre.ethers.formatEther(balance), "BNB");

  const VeriSBT = await hre.ethers.getContractFactory("VeriSBT");
  const sbt = await VeriSBT.deploy(deployer.address);
  await sbt.waitForDeployment();

  const sbtAddress = await sbt.getAddress();
  console.log("VeriSBT deployed to:", sbtAddress);

  const VeriEscrow = await hre.ethers.getContractFactory("VeriEscrowV2");
  const escrow = await VeriEscrow.deploy(USDT_ADDRESS, registryAddress, semaphoreAddress, sbtAddress);
  await escrow.waitForDeployment();

  const escrowAddress = await escrow.getAddress();
  console.log("VeriEscrowV2 deployed to:", escrowAddress);

  const setMinterTx = await sbt.setMinter(escrowAddress);
  const setMinterReceipt = await setMinterTx.wait();
  if (!setMinterReceipt || Number(setMinterReceipt.status) !== 1) {
    throw new Error("setMinter transaction failed");
  }
  console.log("VeriSBT minter set to:", escrowAddress);

  const registry = await hre.ethers.getContractAt("VTRegistry", registryAddress);
  const setRegistrarTx = await registry.setRegistrar(escrowAddress);
  const setRegistrarReceipt = await setRegistrarTx.wait();
  if (!setRegistrarReceipt || Number(setRegistrarReceipt.status) !== 1) {
    throw new Error("setRegistrar transaction failed");
  }

  const registrarAfter = await registry.registrar();
  if (registrarAfter.toLowerCase() !== escrowAddress.toLowerCase()) {
    throw new Error(`setRegistrar verification failed: got ${registrarAfter}`);
  }
  console.log("VTRegistry registrar set to:", escrowAddress);

  // Save to addresses.json
  addresses[networkName] = {
    ...addresses[networkName],
    VeriEscrow: escrowAddress,
    VeriSBT: sbtAddress,
    Semaphore: semaphoreAddress,
    USDT: USDT_ADDRESS,
    sbtDeployedAt: new Date().toISOString(),
    escrowDeployedAt: new Date().toISOString(),
  };

  fs.writeFileSync(addressesPath, JSON.stringify(addresses, null, 2));
  console.log("Addresses saved to addresses.json");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
