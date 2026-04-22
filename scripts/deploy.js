import hre from "hardhat";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  console.log("Deploying with:", deployer.address);

  const balance = await hre.ethers.provider.getBalance(deployer.address);
  console.log("Balance:", hre.ethers.formatEther(balance), "OKB");

  const VTRegistry = await hre.ethers.getContractFactory("VTRegistry");
  const registry = await VTRegistry.deploy();
  await registry.waitForDeployment();

  const address = await registry.getAddress();
  console.log("VTRegistry deployed to:", address);

  // Save addresses to file
  const addressesPath = path.resolve(__dirname, "../addresses.json");
  let addresses = {};
  if (fs.existsSync(addressesPath)) {
    addresses = JSON.parse(fs.readFileSync(addressesPath, "utf8"));
  }

  const networkName = hre.network.name;
  addresses[networkName] = {
    ...addresses[networkName],
    VTRegistry: address,
    deployer: deployer.address,
    deployedAt: new Date().toISOString(),
  };

  fs.writeFileSync(addressesPath, JSON.stringify(addresses, null, 2));
  console.log("Addresses saved to addresses.json");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
