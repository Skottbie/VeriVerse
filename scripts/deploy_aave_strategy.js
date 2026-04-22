import hre from "hardhat";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ZERO_ADDRESS = "0x0000000000000000000000000000000000000000";

function readAddresses(addressesPath) {
  if (!fs.existsSync(addressesPath)) {
    throw new Error("addresses.json not found - deploy VTRegistry and VeriEscrow first");
  }
  return JSON.parse(fs.readFileSync(addressesPath, "utf8"));
}

async function main() {
  const addressesPath = path.resolve(__dirname, "../addresses.json");
  const addresses = readAddresses(addressesPath);
  const networkName = hre.network.name;

  const escrowAddress =
    process.env.ESCROW_ADDRESS ||
    addresses[networkName]?.VeriEscrow;
  const usdtAddress =
    process.env.USDT_ADDRESS ||
    addresses[networkName]?.USDT;
  const aavePoolAddress = process.env.AAVE_POOL_ADDRESS;
  const aUsdtAddress = process.env.AAVE_ATOKEN_ADDRESS;

  if (!escrowAddress) {
    throw new Error(`VeriEscrow address missing for network ${networkName} (set ESCROW_ADDRESS or addresses.json)`);
  }
  if (!usdtAddress) {
    throw new Error(`USDT address missing for network ${networkName} (set USDT_ADDRESS or addresses.json)`);
  }
  if (!aavePoolAddress) {
    throw new Error("AAVE_POOL_ADDRESS is required");
  }
  if (!aUsdtAddress) {
    throw new Error("AAVE_ATOKEN_ADDRESS is required");
  }

  const [deployer] = await hre.ethers.getSigners();
  console.log("Deploying AaveSupplyStrategy with:", deployer.address);

  const balance = await hre.ethers.provider.getBalance(deployer.address);
  console.log("Balance:", hre.ethers.formatEther(balance), "OKB");
  console.log("Escrow:", escrowAddress);
  console.log("USDT:", usdtAddress);
  console.log("Aave Pool:", aavePoolAddress);
  console.log("Aave aToken:", aUsdtAddress);

  const Strategy = await hre.ethers.getContractFactory("AaveSupplyStrategy");
  const strategy = await Strategy.deploy(
    usdtAddress,
    aUsdtAddress,
    aavePoolAddress,
    escrowAddress
  );
  await strategy.waitForDeployment();

  const strategyAddress = await strategy.getAddress();
  console.log("AaveSupplyStrategy deployed to:", strategyAddress);

  const autoBind = (process.env.AUTO_SET_YIELD_STRATEGY || "true").toLowerCase() !== "false";
  if (autoBind) {
    const escrow = await hre.ethers.getContractAt("VeriEscrow", escrowAddress);
    const currentStrategy = await escrow.yieldStrategy();

    if (currentStrategy.toLowerCase() !== strategyAddress.toLowerCase()) {
      if (currentStrategy !== ZERO_ADDRESS) {
        console.log("Replacing existing strategy:", currentStrategy);
      }
      const tx = await escrow.setYieldStrategy(strategyAddress);
      const receipt = await tx.wait();
      if (!receipt || Number(receipt.status) !== 1) {
        throw new Error("setYieldStrategy transaction failed");
      }
      console.log("Yield strategy bound to escrow:", strategyAddress);
    } else {
      console.log("Yield strategy already bound, skipping setYieldStrategy");
    }
  }

  addresses[networkName] = {
    ...addresses[networkName],
    VeriEscrow: escrowAddress,
    USDT: usdtAddress,
    AaveSupplyStrategy: strategyAddress,
    AavePool: aavePoolAddress,
    AaveAToken: aUsdtAddress,
    strategyDeployedAt: new Date().toISOString(),
  };

  fs.writeFileSync(addressesPath, JSON.stringify(addresses, null, 2));
  console.log("Addresses saved to addresses.json");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
