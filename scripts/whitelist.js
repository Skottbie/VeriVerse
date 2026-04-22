import hre from "hardhat";
import { readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const addresses = JSON.parse(readFileSync(resolve(__dirname, "../addresses.json"), "utf8"));
const net = hre.network.name === "bsc" ? "bsc" : "bsc_testnet";
const REGISTRY = addresses[net]?.VTRegistry;
const BSC_DEPLOYER = addresses[net]?.deployer;

if (!REGISTRY) throw new Error(`VTRegistry address not found in addresses.json for network "${net}"`);
if (!BSC_DEPLOYER) throw new Error(`deployer address not found in addresses.json for network "${net}"`);

async function main() {
  const reg = await hre.ethers.getContractAt("VTRegistry", REGISTRY);
  const target = process.argv[2] || BSC_DEPLOYER;

  console.log("devMode:", await reg.devMode());
  console.log("target:", target);
  console.log("whitelist before:", await reg.whitelist(target));

  const tx = await reg.addToWhitelist(target);
  const receipt = await tx.wait();

  console.log("whitelist after:", await reg.whitelist(target));
  console.log("tx:", tx.hash);
}

main().catch(console.error);
