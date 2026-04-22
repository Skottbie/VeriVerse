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

describe("VeriEscrowV2 auto strategy behavior", function () {
  async function deployFixture() {
    const [owner, creator, agentWallet, backer] = await ethers.getSigners();

    const USDT = await ethers.getContractFactory("MockUSDT");
    const Registry = await ethers.getContractFactory("MockVTRegistry");
    const Semaphore = await ethers.getContractFactory("MockSemaphore");
    const SBT = await ethers.getContractFactory("VeriSBT");
    const EscrowV2 = await ethers.getContractFactory("VeriEscrowV2");
    const Strategy = await ethers.getContractFactory("MockYieldStrategy");

    const usdt = await USDT.deploy();
    const registry = await Registry.deploy();
    const semaphore = await Semaphore.deploy();
    const sbt = await SBT.deploy(owner.address);

    const escrow = await EscrowV2.deploy(
      await usdt.getAddress(),
      await registry.getAddress(),
      await semaphore.getAddress(),
      await sbt.getAddress()
    );

    const strategy = await Strategy.deploy(await usdt.getAddress(), await escrow.getAddress());

    return {
      owner,
      creator,
      agentWallet,
      backer,
      usdt,
      registry,
      semaphore,
      sbt,
      escrow,
      strategy,
    };
  }

  it("auto deploys full invest to strategy by default", async function () {
    const { creator, agentWallet, backer, usdt, registry, escrow, strategy } = await deployFixture();

    await registry.registerMock("Agent-V2-A", creator.address, agentWallet.address, 120);
    await escrow.setYieldStrategy(await strategy.getAddress());

    await usdt.mint(backer.address, 1_000_000n);
    await usdt.connect(backer).approve(await escrow.getAddress(), 1_000_000n);
    await escrow.connect(backer).invest(1, 1_000_000n);

    expect(await usdt.balanceOf(await escrow.getAddress())).to.equal(0n);
    expect(await strategy.totalManagedAssets()).to.equal(1_000_000n);
  });

  it("respects configured deploy bps and liquid reserve", async function () {
    const { creator, agentWallet, backer, usdt, registry, escrow, strategy } = await deployFixture();

    await registry.registerMock("Agent-V2-B", creator.address, agentWallet.address, 120);
    await escrow.setYieldStrategy(await strategy.getAddress());
    await escrow.setAutoDeployOnInvestConfig(true, 5_000, 100_000n);

    await usdt.mint(backer.address, 1_000_000n);
    await usdt.connect(backer).approve(await escrow.getAddress(), 1_000_000n);
    await escrow.connect(backer).invest(1, 1_000_000n);

    expect(await strategy.totalManagedAssets()).to.equal(500_000n);
    expect(await usdt.balanceOf(await escrow.getAddress())).to.equal(500_000n);
  });

  it("supports disabling auto deploy", async function () {
    const { creator, agentWallet, backer, usdt, registry, escrow, strategy } = await deployFixture();

    await registry.registerMock("Agent-V2-C", creator.address, agentWallet.address, 120);
    await escrow.setYieldStrategy(await strategy.getAddress());
    await escrow.setAutoDeployOnInvestConfig(false, 10_000, 0);

    await usdt.mint(backer.address, 1_000_000n);
    await usdt.connect(backer).approve(await escrow.getAddress(), 1_000_000n);
    await escrow.connect(backer).invest(1, 1_000_000n);

    expect(await strategy.totalManagedAssets()).to.equal(0n);
    expect(await usdt.balanceOf(await escrow.getAddress())).to.equal(1_000_000n);
  });

  it("auto recalls strategy funds during atomic graduation settlement", async function () {
    const { creator, agentWallet, backer, usdt, registry, sbt, escrow, strategy } = await deployFixture();

    await sbt.setMinter(await escrow.getAddress());
    await registry.registerMock("Agent-V2-D", creator.address, agentWallet.address, 120);
    await escrow.setYieldStrategy(await strategy.getAddress());

    await usdt.mint(backer.address, 1_000_000n);
    await usdt.connect(backer).approve(await escrow.getAddress(), 1_000_000n);
    await escrow.connect(backer).invest(1, 1_000_000n);

    await escrow.connect(creator).bindCreatorCommitment(1, 999n);

    const network = await ethers.provider.getNetwork();
    const { scope, signal } = buildHashes(1, Number(network.chainId));
    const proof = buildProof(scope, signal, 777n);

    await escrow.graduateAtomicByProof(1, proof, signal, "ipfs://v2-auto-recall");

    expect(await usdt.balanceOf(agentWallet.address)).to.equal(1_000_000n);
    expect(await strategy.totalManagedAssets()).to.equal(0n);
    expect(await usdt.balanceOf(await escrow.getAddress())).to.equal(0n);
  });
});
