import hre from "hardhat";
import fs from "fs";

async function main() {
  const proofPath = process.env.PROOF_PATH || "/tmp/agent4_proof.json";
  const raw = JSON.parse(fs.readFileSync(proofPath, "utf8"));

  const escrowAddr = raw.escrow;
  const agentId = BigInt(raw.agentId);
  const signalHash = BigInt(raw.signalHash);

  const proof = {
    merkleTreeDepth: BigInt(raw.proof.merkleTreeDepth),
    merkleTreeRoot: BigInt(raw.proof.merkleTreeRoot),
    nullifier: BigInt(raw.proof.nullifier ?? raw.proof.nullifierHash),
    message: BigInt(raw.proof.message ?? raw.proof.signalHash),
    scope: BigInt(raw.proof.scope ?? raw.proof.externalNullifier),
    points: raw.proof.points.map((x) => BigInt(x)),
  };

  const escrow = await hre.ethers.getContractAt("VeriEscrow", escrowAddr);

  try {
    const gas = await escrow.authorizeGraduateByProof.estimateGas(agentId, proof, signalHash);
    console.log("authorize estimateGas OK", gas.toString());
  } catch (e) {
    console.log("authorize estimateGas FAIL", e?.shortMessage || e?.message || e);
    if (e?.data) {
      console.log("error data", e.data);
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
