#!/usr/bin/env node

import fs from "node:fs/promises";
import { constants as fsConstants } from "node:fs";
import path from "node:path";
import { Identity } from "@semaphore-protocol/identity";
import { Group } from "@semaphore-protocol/group";
import { generateProof } from "@semaphore-protocol/proof";

function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const token = argv[i];
    if (token.startsWith("--")) {
      const key = token.slice(2);
      const next = argv[i + 1];
      if (!next || next.startsWith("--")) {
        args[key] = true;
      } else {
        args[key] = next;
        i++;
      }
    } else {
      args._.push(token);
    }
  }
  return args;
}

function usage() {
  console.error("Usage:");
  console.error("  node scripts/semaphore_local_tools.mjs new-identity");
  console.error(
    "  node scripts/semaphore_local_tools.mjs compute-root --commitment <COMMITMENT> [--group-id <GROUP_ID>] [--merkle-tree-depth 20]"
  );
  console.error(
    "  node scripts/semaphore_local_tools.mjs generate-proof --identity <IDENTITY_EXPORT> --commitment <COMMITMENT> --signal <SIGNAL> --scope <SCOPE> [--group-id <GROUP_ID>] [--merkle-tree-depth 20] [--wasm-file <PATH> --zkey-file <PATH>]"
  );
}

function toBigInt(value, name) {
  if (value === undefined || value === null || value === "") {
    throw new Error(`${name} is required`);
  }
  return BigInt(value);
}

async function hasReadableNonEmptyFile(filePath) {
  try {
    await fs.access(filePath, fsConstants.R_OK);
    const stats = await fs.stat(filePath);
    return stats.isFile() && stats.size > 0;
  } catch {
    return false;
  }
}

async function downloadBinaryFile(url, filePath) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`download failed (${response.status}) for ${url}`);
  }

  const arrayBuffer = await response.arrayBuffer();
  if (!arrayBuffer.byteLength) {
    throw new Error(`download returned empty payload for ${url}`);
  }

  const tempPath = `${filePath}.tmp`;
  await fs.writeFile(tempPath, Buffer.from(arrayBuffer));
  await fs.rename(tempPath, filePath);
}

async function resolveSnarkArtifacts(merkleTreeDepth, args) {
  const wasmOverride = args["wasm-file"] ?? process.env.SEMAPHORE_WASM_FILE;
  const zkeyOverride = args["zkey-file"] ?? process.env.SEMAPHORE_ZKEY_FILE;

  if (Boolean(wasmOverride) !== Boolean(zkeyOverride)) {
    throw new Error("wasm-file and zkey-file must be provided together");
  }

  if (wasmOverride && zkeyOverride) {
    const wasmFilePath = path.resolve(wasmOverride);
    const zkeyFilePath = path.resolve(zkeyOverride);

    if (!(await hasReadableNonEmptyFile(wasmFilePath))) {
      throw new Error(`wasm-file is missing or empty: ${wasmFilePath}`);
    }
    if (!(await hasReadableNonEmptyFile(zkeyFilePath))) {
      throw new Error(`zkey-file is missing or empty: ${zkeyFilePath}`);
    }

    return { wasmFilePath, zkeyFilePath };
  }

  const cacheRoot = process.env.SEMAPHORE_ARTIFACTS_DIR
    ? path.resolve(process.env.SEMAPHORE_ARTIFACTS_DIR)
    : path.resolve(process.cwd(), ".cache", "semaphore", "artifacts");
  const depthDir = path.join(cacheRoot, String(merkleTreeDepth));

  await fs.mkdir(depthDir, { recursive: true });

  const wasmFilePath = path.join(depthDir, "semaphore.wasm");
  const zkeyFilePath = path.join(depthDir, "semaphore.zkey");
  const baseUrl = `https://www.trusted-setup-pse.org/semaphore/${merkleTreeDepth}`;

  if (!(await hasReadableNonEmptyFile(wasmFilePath))) {
    await downloadBinaryFile(`${baseUrl}/semaphore.wasm`, wasmFilePath);
  }
  if (!(await hasReadableNonEmptyFile(zkeyFilePath))) {
    await downloadBinaryFile(`${baseUrl}/semaphore.zkey`, zkeyFilePath);
  }

  return { wasmFilePath, zkeyFilePath };
}

async function main() {
  const argv = process.argv.slice(2);
  if (argv.length === 0) {
    usage();
    process.exit(1);
  }

  const command = argv[0];
  const args = parseArgs(argv.slice(1));

  if (command === "new-identity") {
    const identity = new Identity();
    const out = {
      identityExport: identity.toString(),
      commitment: identity.commitment.toString(),
      identityFormat: "semaphore-v3-json",
    };
    process.stdout.write(`${JSON.stringify(out)}\n`);
    process.exit(0);
  }

  if (command === "compute-root") {
    const commitment = toBigInt(args.commitment, "commitment");
    const groupId = toBigInt(args["group-id"] ?? "1", "group-id");
    const merkleTreeDepth = Number(args["merkle-tree-depth"] ?? args.depth ?? "20");

    if (!Number.isInteger(merkleTreeDepth) || merkleTreeDepth <= 0) {
      throw new Error("merkle-tree-depth must be a positive integer");
    }

    const group = new Group(groupId, merkleTreeDepth, [commitment]);
    const out = { groupRoot: group.root.toString() };
    process.stdout.write(`${JSON.stringify(out)}\n`);
    process.exit(0);
  }

  if (command === "generate-proof") {
    const identityExport = args.identity;
    const commitment = toBigInt(args.commitment, "commitment");
    const signal = toBigInt(args.signal, "signal");
    const scope = toBigInt(args.scope, "scope");
    const groupId = toBigInt(args["group-id"] ?? "1", "group-id");
    const merkleTreeDepth = Number(args["merkle-tree-depth"] ?? args.depth ?? "20");

    if (!identityExport || typeof identityExport !== "string") {
      throw new Error("identity is required");
    }
    if (!Number.isInteger(merkleTreeDepth) || merkleTreeDepth <= 0) {
      throw new Error("merkle-tree-depth must be a positive integer");
    }

    const identity = new Identity(identityExport);
    if (identity.commitment.toString() !== commitment.toString()) {
      throw new Error("identity commitment mismatch (legacy identity material unsupported)");
    }

    const group = new Group(groupId, merkleTreeDepth, [commitment]);
    const snarkArtifacts = await resolveSnarkArtifacts(merkleTreeDepth, args);
    const fullProof = await generateProof(identity, group, scope, signal, snarkArtifacts);

    const out = {
      groupRoot: group.root.toString(),
      proof: {
        merkleTreeDepth,
        merkleTreeRoot: fullProof.merkleTreeRoot.toString(),
        nullifier: fullProof.nullifierHash.toString(),
        message: fullProof.signal.toString(),
        scope: fullProof.externalNullifier.toString(),
        points: fullProof.proof.map((v) => v.toString()),
      },
    };

    process.stdout.write(`${JSON.stringify(out)}\n`);
    process.exit(0);
  }

  usage();
  process.exit(1);
}

main().catch((err) => {
  console.error(String(err));
  process.exit(1);
});
