import hre from "hardhat";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

async function main() {
  const agentIdArg = process.env.AGENT_ID || process.argv[2];
  const groupIdArg = process.env.GROUP_ID || process.argv[3] || agentIdArg;

  if (!agentIdArg) {
    throw new Error("Missing AGENT_ID. Usage: AGENT_ID=4 npx hardhat run --network bsc scripts/import_binding.js");
  }

  const agentId = BigInt(agentIdArg);
  const groupId = BigInt(groupIdArg);

  const addressesPath = path.resolve(__dirname, "../addresses.json");
  if (!fs.existsSync(addressesPath)) {
    throw new Error("addresses.json not found");
  }

  const addresses = JSON.parse(fs.readFileSync(addressesPath, "utf8"));
  const networkName = hre.network.name;
  const escrowAddress = addresses[networkName]?.VeriEscrow;
  if (!escrowAddress) {
    throw new Error(`VeriEscrow address not found for network ${networkName}`);
  }

  const [caller] = await hre.ethers.getSigners();
  console.log("Caller:", caller.address);
  console.log("Escrow:", escrowAddress);
  console.log("agentId:", agentId.toString());
  console.log("groupId:", groupId.toString());

  const escrow = await hre.ethers.getContractAt("VeriEscrow", escrowAddress);
  const tx = await escrow.importExistingGroupBinding(agentId, groupId);
  const receipt = await tx.wait();
  if (!receipt || Number(receipt.status) !== 1) {
    throw new Error("importExistingGroupBinding transaction failed");
  }

  const importedGroup = await escrow.agentGroupId(agentId);
  const importedBound = await escrow.creatorCommitmentBound(agentId);

  console.log("import tx:", tx.hash);
  console.log("agentGroupId:", importedGroup.toString());
  console.log("creatorCommitmentBound:", importedBound);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
