import hre from "hardhat";

async function main() {
  const escrowAddress = process.env.ESCROW_ADDRESS || process.argv[2];
  const agentIdArg = process.env.AGENT_ID || process.argv[3];

  if (!escrowAddress || !agentIdArg) {
    throw new Error("Usage: ESCROW_ADDRESS=<addr> AGENT_ID=<id> npx hardhat run --network bsc scripts/refund_agent.js");
  }

  const agentId = BigInt(agentIdArg);
  const [caller] = await hre.ethers.getSigners();

  console.log("Caller:", caller.address);
  console.log("Escrow:", escrowAddress);
  console.log("agentId:", agentId.toString());

  const escrow = await hre.ethers.getContractAt("VeriEscrow", escrowAddress);
  const tx = await escrow.refund(agentId);
  const receipt = await tx.wait();
  if (!receipt || Number(receipt.status) !== 1) {
    throw new Error("refund transaction failed");
  }

  console.log("refund tx:", tx.hash);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
