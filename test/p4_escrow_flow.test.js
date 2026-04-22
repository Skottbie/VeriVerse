import { expect } from "chai";
import hardhat from "hardhat";

const { ethers } = hardhat;

function buildHashes(agentId, chainId) {
  const scope = BigInt(
    ethers.solidityPackedKeccak256(
      ["string", "uint256", "uint256"],
      ["graduate", agentId, chainId]
    )
  );
  const signal = BigInt(
    ethers.solidityPackedKeccak256(
      ["string", "uint256", "uint256"],
      ["graduate-signal", agentId, chainId]
    )
  );
  return { scope, signal };
}

function buildProof(scope, signal, nullifier = 123n) {
  return {
    merkleTreeDepth: 20,
    merkleTreeRoot: 1,
    nullifier,
    message: signal,
    scope,
    points: [1n, 2n, 3n, 4n, 5n, 6n, 7n, 8n],
  };
}

describe("P4 escrow graduation flow", function () {
  it("graduates atomically, settles funds, and syncs registry status", async function () {
    const [owner, creator, agentWallet, backer] = await ethers.getSigners();

    const USDT = await ethers.getContractFactory("MockUSDT");
    const Registry = await ethers.getContractFactory("MockVTRegistry");
    const Semaphore = await ethers.getContractFactory("MockSemaphore");
    const SBT = await ethers.getContractFactory("VeriSBT");
    const Escrow = await ethers.getContractFactory("VeriEscrow");

    const usdt = await USDT.deploy();
    const registry = await Registry.deploy();
    const semaphore = await Semaphore.deploy();
    const sbt = await SBT.deploy(owner.address);

    const escrow = await Escrow.deploy(
      await usdt.getAddress(),
      await registry.getAddress(),
      await semaphore.getAddress(),
      await sbt.getAddress()
    );

    await sbt.setMinter(await escrow.getAddress());

    const registerTx = await registry.registerMock(
      "Agent-A",
      creator.address,
      agentWallet.address,
      120
    );
    await registerTx.wait();
    const agentId = 1;

    await usdt.mint(backer.address, 1_000_000n);
    await usdt.connect(backer).approve(await escrow.getAddress(), 1_000_000n);
    await escrow.connect(backer).invest(agentId, 1_000_000n);

    await escrow.connect(creator).bindCreatorCommitment(agentId, 999n);

    const network = await ethers.provider.getNetwork();
    const { scope, signal } = buildHashes(agentId, Number(network.chainId));
    const proof = buildProof(scope, signal, 888n);

    await escrow.graduateAtomicByProof(agentId, proof, signal, "ipfs://demo-cid");

    const recipientBalance = await usdt.balanceOf(agentWallet.address);
    expect(recipientBalance).to.equal(1_000_000n);

    const holder = await sbt.holderOf(agentId);
    expect(holder).to.equal(creator.address);

    const agent = await registry.getAgent(agentId);
    expect(agent.status).to.equal(1n);
  });

  it("rejects nullifier replay under same agent", async function () {
    const [owner, creator, agentWallet] = await ethers.getSigners();

    const USDT = await ethers.getContractFactory("MockUSDT");
    const Registry = await ethers.getContractFactory("MockVTRegistry");
    const Semaphore = await ethers.getContractFactory("MockSemaphore");
    const SBT = await ethers.getContractFactory("VeriSBT");
    const Escrow = await ethers.getContractFactory("VeriEscrow");

    const usdt = await USDT.deploy();
    const registry = await Registry.deploy();
    const semaphore = await Semaphore.deploy();
    const sbt = await SBT.deploy(owner.address);

    const escrow = await Escrow.deploy(
      await usdt.getAddress(),
      await registry.getAddress(),
      await semaphore.getAddress(),
      await sbt.getAddress()
    );

    await registry.registerMock("Agent-B", creator.address, agentWallet.address, 120);
    await escrow.connect(creator).bindCreatorCommitment(1, 111n);

    const network = await ethers.provider.getNetwork();
    const { scope, signal } = buildHashes(1, Number(network.chainId));
    const proof = buildProof(scope, signal, 777n);

    await escrow.authorizeGraduateByProof(1, proof, signal);
    await expect(escrow.authorizeGraduateByProof(1, proof, signal)).to.be.revertedWith(
      "Nullifier already used"
    );
  });

  it("refunds with fixed 3% fee", async function () {
    const [owner, creator, agentWallet, backer] = await ethers.getSigners();

    const USDT = await ethers.getContractFactory("MockUSDT");
    const Registry = await ethers.getContractFactory("MockVTRegistry");
    const Semaphore = await ethers.getContractFactory("MockSemaphore");
    const SBT = await ethers.getContractFactory("VeriSBT");
    const Escrow = await ethers.getContractFactory("VeriEscrow");

    const usdt = await USDT.deploy();
    const registry = await Registry.deploy();
    const semaphore = await Semaphore.deploy();
    const sbt = await SBT.deploy(owner.address);

    const escrow = await Escrow.deploy(
      await usdt.getAddress(),
      await registry.getAddress(),
      await semaphore.getAddress(),
      await sbt.getAddress()
    );

    await registry.registerMock("Agent-C", creator.address, agentWallet.address, 10);

    await usdt.mint(backer.address, 1_000_000n);
    await usdt.connect(backer).approve(await escrow.getAddress(), 1_000_000n);
    await escrow.connect(backer).invest(1, 1_000_000n);

    await escrow.refund(1);

    const backerBalance = await usdt.balanceOf(backer.address);
    const ownerBalance = await usdt.balanceOf(owner.address);

    expect(backerBalance).to.equal(970_000n);
    expect(ownerBalance).to.equal(30_000n);
  });

  it("disables owner fallback commitment binding when hardened", async function () {
    const [owner, creator, agentWallet] = await ethers.getSigners();

    const USDT = await ethers.getContractFactory("MockUSDT");
    const Registry = await ethers.getContractFactory("MockVTRegistry");
    const Semaphore = await ethers.getContractFactory("MockSemaphore");
    const SBT = await ethers.getContractFactory("VeriSBT");
    const Escrow = await ethers.getContractFactory("VeriEscrow");

    const usdt = await USDT.deploy();
    const registry = await Registry.deploy();
    const semaphore = await Semaphore.deploy();
    const sbt = await SBT.deploy(owner.address);

    const escrow = await Escrow.deploy(
      await usdt.getAddress(),
      await registry.getAddress(),
      await semaphore.getAddress(),
      await sbt.getAddress()
    );

    await registry.registerMock("Agent-D", creator.address, agentWallet.address, 120);

    await escrow.disableOwnerCommitmentBinding();

    await expect(escrow.bindCreatorCommitment(1, 321n)).to.be.revertedWith(
      "Owner binding disabled"
    );

    await escrow.connect(creator).bindCreatorCommitment(1, 321n);
  });

  it("transfers ownership and enforces new owner privileges", async function () {
    const [owner, newOwner] = await ethers.getSigners();

    const USDT = await ethers.getContractFactory("MockUSDT");
    const Registry = await ethers.getContractFactory("MockVTRegistry");
    const Semaphore = await ethers.getContractFactory("MockSemaphore");
    const SBT = await ethers.getContractFactory("VeriSBT");
    const Escrow = await ethers.getContractFactory("VeriEscrow");

    const usdt = await USDT.deploy();
    const registry = await Registry.deploy();
    const semaphore = await Semaphore.deploy();
    const sbt = await SBT.deploy(owner.address);

    const escrow = await Escrow.deploy(
      await usdt.getAddress(),
      await registry.getAddress(),
      await semaphore.getAddress(),
      await sbt.getAddress()
    );

    await expect(escrow.connect(owner).transferOwnership(newOwner.address))
      .to.emit(escrow, "OwnershipTransferred")
      .withArgs(owner.address, newOwner.address);

    await expect(escrow.connect(owner).disableOwnerCommitmentBinding()).to.be.revertedWith(
      "Not owner"
    );

    await escrow.connect(newOwner).disableOwnerCommitmentBinding();
  });

  it("deploys idle funds to strategy and withdraws back", async function () {
    const [owner, creator, agentWallet, backer] = await ethers.getSigners();

    const USDT = await ethers.getContractFactory("MockUSDT");
    const Registry = await ethers.getContractFactory("MockVTRegistry");
    const Semaphore = await ethers.getContractFactory("MockSemaphore");
    const SBT = await ethers.getContractFactory("VeriSBT");
    const Escrow = await ethers.getContractFactory("VeriEscrow");
    const Strategy = await ethers.getContractFactory("MockYieldStrategy");

    const usdt = await USDT.deploy();
    const registry = await Registry.deploy();
    const semaphore = await Semaphore.deploy();
    const sbt = await SBT.deploy(owner.address);

    const escrow = await Escrow.deploy(
      await usdt.getAddress(),
      await registry.getAddress(),
      await semaphore.getAddress(),
      await sbt.getAddress()
    );

    const strategy = await Strategy.deploy(await usdt.getAddress(), await escrow.getAddress());

    await registry.registerMock("Agent-Strategy", creator.address, agentWallet.address, 120);

    await usdt.mint(backer.address, 1_000_000n);
    await usdt.connect(backer).approve(await escrow.getAddress(), 1_000_000n);
    await escrow.connect(backer).invest(1, 1_000_000n);

    await escrow.setYieldStrategy(await strategy.getAddress());

    await escrow.deployIdleToStrategy(400_000n);
    expect(await usdt.balanceOf(await escrow.getAddress())).to.equal(600_000n);
    expect(await strategy.totalManagedAssets()).to.equal(400_000n);

    await escrow.withdrawFromStrategy(250_000n);
    expect(await usdt.balanceOf(await escrow.getAddress())).to.equal(850_000n);
    expect(await strategy.totalManagedAssets()).to.equal(150_000n);
  });

  it("auto-withdraws strategy funds when graduating with low liquid balance", async function () {
    const [owner, creator, agentWallet, backer] = await ethers.getSigners();

    const USDT = await ethers.getContractFactory("MockUSDT");
    const Registry = await ethers.getContractFactory("MockVTRegistry");
    const Semaphore = await ethers.getContractFactory("MockSemaphore");
    const SBT = await ethers.getContractFactory("VeriSBT");
    const Escrow = await ethers.getContractFactory("VeriEscrow");
    const Strategy = await ethers.getContractFactory("MockYieldStrategy");

    const usdt = await USDT.deploy();
    const registry = await Registry.deploy();
    const semaphore = await Semaphore.deploy();
    const sbt = await SBT.deploy(owner.address);

    const escrow = await Escrow.deploy(
      await usdt.getAddress(),
      await registry.getAddress(),
      await semaphore.getAddress(),
      await sbt.getAddress()
    );

    await sbt.setMinter(await escrow.getAddress());

    const strategy = await Strategy.deploy(await usdt.getAddress(), await escrow.getAddress());

    await registry.registerMock("Agent-Strategy-Settle", creator.address, agentWallet.address, 120);

    await usdt.mint(backer.address, 1_000_000n);
    await usdt.connect(backer).approve(await escrow.getAddress(), 1_000_000n);
    await escrow.connect(backer).invest(1, 1_000_000n);

    await escrow.connect(creator).bindCreatorCommitment(1, 1234n);
    await escrow.setYieldStrategy(await strategy.getAddress());
    await escrow.deployIdleToStrategy(700_000n);

    const network = await ethers.provider.getNetwork();
    const { scope, signal } = buildHashes(1, Number(network.chainId));
    const proof = buildProof(scope, signal, 4321n);

    await escrow.graduateAtomicByProof(1, proof, signal, "ipfs://auto-recall");

    expect(await usdt.balanceOf(agentWallet.address)).to.equal(1_000_000n);
    expect(await strategy.totalManagedAssets()).to.equal(0n);
    expect(await usdt.balanceOf(await escrow.getAddress())).to.equal(0n);
  });

  it("accepts only ipfs token URI format", async function () {
    const [owner, creator, agentWallet] = await ethers.getSigners();

    const USDT = await ethers.getContractFactory("MockUSDT");
    const Registry = await ethers.getContractFactory("MockVTRegistry");
    const Semaphore = await ethers.getContractFactory("MockSemaphore");
    const SBT = await ethers.getContractFactory("VeriSBT");
    const Escrow = await ethers.getContractFactory("VeriEscrow");

    const usdt = await USDT.deploy();
    const registry = await Registry.deploy();
    const semaphore = await Semaphore.deploy();
    const sbt = await SBT.deploy(owner.address);

    const escrow = await Escrow.deploy(
      await usdt.getAddress(),
      await registry.getAddress(),
      await semaphore.getAddress(),
      await sbt.getAddress()
    );

    await registry.registerMock("Agent-E", creator.address, agentWallet.address, 120);

    await expect(escrow.setGraduationTokenURI(1, "https://example.com/meta.json")).to.be.revertedWith(
      "Token URI must start with ipfs://"
    );

    await escrow.setGraduationTokenURI(1, "ipfs://bafy-demo-cid");
  });
});
