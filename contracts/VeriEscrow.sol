// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @dev Minimal interface for VTRegistry — only what VeriEscrow needs.
interface IVTRegistry {
    enum Status { Active, Graduated, Deactivated }
    struct Agent {
        string name;
        address creator;
        address wallet;
        int256 trustScore;
        Status status;
    }
    function nextAgentId() external view returns (uint256);
    function getAgent(uint256 agentId) external view returns (Agent memory);
    function registerFor(address creator, string calldata name, address wallet) external returns (uint256);
    function graduate(uint256 agentId) external;
}

interface ISemaphore {
    struct SemaphoreProof {
        uint256 merkleTreeDepth;
        uint256 merkleTreeRoot;
        uint256 nullifier;
        uint256 message;
        uint256 scope;
        uint256[8] points;
    }

    function createGroup(uint256 groupId, uint256 merkleTreeDepth, address admin) external;
    function addMember(uint256 groupId, uint256 identityCommitment) external;
    function verifyProof(
        uint256 groupId,
        uint256 merkleTreeRoot,
        uint256 signal,
        uint256 nullifierHash,
        uint256 externalNullifier,
        uint256[8] calldata proof
    ) external;
}

interface IVeriSBT {
    function mint(uint256 agentId, address holder, string calldata tokenUri) external returns (uint256 tokenId);
}

interface IYieldStrategy {
    function deposit(uint256 amount) external;
    function withdraw(uint256 amount, address to) external returns (uint256);
    function totalManagedAssets() external view returns (uint256);
}

/// @title VeriEscrow — Backer investment escrow for VeriVerse Agents
/// @notice Holds USDT deposits per Agent. Backers invest via approve+transferFrom.
///         Settlement (graduate/refund) triggered by owner after trust verification.
contract VeriEscrow {
    using SafeERC20 for IERC20;

    // ── Types ────────────────────────────────────────────────────────────

    enum EscrowStatus { Active, Settled, Refunded }

    struct Escrow {
        uint256 totalAmount;
        address[] backers;
        mapping(address => uint256) contributions;
        EscrowStatus status;
    }

    // ── State ────────────────────────────────────────────────────────────

    IERC20 public immutable usdt;
    IVTRegistry public immutable registry;
    ISemaphore public immutable semaphore;
    IVeriSBT public immutable sbt;
    address public owner;
    address public yieldStrategy;

    uint256 public constant TRUST_THRESHOLD = 100;
    uint256 public constant REFUND_FEE_BPS = 300; // 3.00%
    uint256 public constant SEMAPHORE_TREE_DEPTH = 20;
    uint256 private constant BPS_BASE = 10_000;

    // agentId => groupId created in Semaphore
    mapping(uint256 => uint256) public agentGroupId;
    // agentId => whether creator commitment has been bound
    mapping(uint256 => bool) public creatorCommitmentBound;
    // agentId => nullifierHash => consumed
    mapping(uint256 => mapping(uint256 => bool)) private usedNullifiers;
    // agentId => proof authorization gate for settle
    mapping(uint256 => bool) public settleAuthorized;
    // agentId => graduation metadata URI (ipfs://...)
    mapping(uint256 => string) private graduationTokenUris;
    // if false, owner fallback binding is disabled and only creator can bind commitment
    bool public ownerCommitmentBindingEnabled = true;

    mapping(uint256 => Escrow) private escrows; // agentId => Escrow

    // ── Events ───────────────────────────────────────────────────────────

    event Invested(uint256 indexed agentId, address indexed backer, uint256 amount);
    event Settled(uint256 indexed agentId, EscrowStatus status);
    event CreatorCommitmentBound(uint256 indexed agentId, uint256 indexed groupId, uint256 commitment);
    event AgentLaunchedAndBound(
        uint256 indexed agentId,
        address indexed creator,
        address wallet,
        uint256 indexed groupId,
        uint256 commitment
    );
    event ExistingGroupBindingImported(uint256 indexed agentId, uint256 indexed groupId);
    event GraduateAuthorized(uint256 indexed agentId, uint256 indexed nullifierHash, uint256 signalHash);
    event GraduationTokenURISet(uint256 indexed agentId, string tokenUri);
    event GraduatedAtomically(uint256 indexed agentId, uint256 indexed nullifierHash, string tokenUri, uint256 settledAmount);
    event RefundFeeCollected(uint256 indexed agentId, uint256 totalFee);
    event OwnerCommitmentBindingDisabled();
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event YieldStrategyUpdated(address indexed previousStrategy, address indexed newStrategy);
    event IdleFundsDeployed(uint256 amount, address indexed strategy);
    event StrategyFundsWithdrawn(uint256 amount, address indexed strategy);

    // ── Modifiers ────────────────────────────────────────────────────────

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    // ── Constructor ──────────────────────────────────────────────────────

    /// @param _usdt     Address of the USDT token on BNB Chain
    /// @param _registry Address of the VTRegistry contract
    /// @param _semaphore Address of Semaphore contract on BNB Chain
    /// @param _sbt      Address of VeriSBT contract
    constructor(address _usdt, address _registry, address _semaphore, address _sbt) {
        require(_usdt != address(0), "Invalid USDT address");
        require(_registry != address(0), "Invalid registry address");
        require(_semaphore != address(0), "Invalid semaphore address");
        require(_sbt != address(0), "Invalid SBT address");
        usdt = IERC20(_usdt);
        registry = IVTRegistry(_registry);
        semaphore = ISemaphore(_semaphore);
        sbt = IVeriSBT(_sbt);
        owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);
    }

    // ── Core Functions ───────────────────────────────────────────────────

    /// @notice Invest USDT into an Agent's escrow.
    /// @param agentId The Agent to invest in (must exist in VTRegistry)
    /// @param amount  USDT amount (6 decimals)
    function invest(uint256 agentId, uint256 amount) external virtual {
        require(agentId > 0 && agentId < registry.nextAgentId(), "Agent does not exist");
        require(amount > 0, "Amount must be > 0");

        IVTRegistry.Agent memory agent = registry.getAgent(agentId);
        require(agent.status == IVTRegistry.Status.Active, "Agent not active");

        Escrow storage e = escrows[agentId];
        require(e.status == EscrowStatus.Active, "Escrow not active");

        // Transfer USDT from backer to this contract
        usdt.safeTransferFrom(msg.sender, address(this), amount);

        // Record contribution
        if (e.contributions[msg.sender] == 0) {
            e.backers.push(msg.sender);
        }
        e.contributions[msg.sender] += amount;
        e.totalAmount += amount;

        emit Invested(agentId, msg.sender, amount);
        _afterInvest(agentId, amount);
    }

    /// @dev Hook for child contracts to extend post-invest behavior.
    function _afterInvest(uint256 agentId, uint256 amount) internal virtual {
        agentId;
        amount;
    }

    /// @notice Atomic launch path: register in VTRegistry and bind Semaphore commitment in one tx.
    /// @dev Requires VTRegistry registrar to be set to this escrow contract.
    function launchAndBind(
        address creator,
        string calldata name,
        address wallet,
        uint256 commitment
    ) external onlyOwner returns (uint256 agentId, uint256 groupId) {
        require(creator != address(0), "Invalid creator");
        require(commitment != 0, "Invalid commitment");

        agentId = registry.registerFor(creator, name, wallet);
        require(agentId != 0, "Invalid agentId");

        groupId = agentId;
        semaphore.createGroup(groupId, SEMAPHORE_TREE_DEPTH, address(this));
        require(groupId != 0, "Invalid groupId");
        semaphore.addMember(groupId, commitment);

        agentGroupId[agentId] = groupId;
        creatorCommitmentBound[agentId] = true;

        emit CreatorCommitmentBound(agentId, groupId, commitment);
        emit AgentLaunchedAndBound(agentId, creator, wallet, groupId, commitment);
    }

    /// @notice Bind Creator's Semaphore commitment to an Agent.
    ///         For new Agent launch this should happen immediately.
    ///         For migration owner can execute one-time manual binding.
    function bindCreatorCommitment(uint256 agentId, uint256 commitment) external {
        require(agentId > 0 && agentId < registry.nextAgentId(), "Agent does not exist");
        require(commitment != 0, "Invalid commitment");

        IVTRegistry.Agent memory agent = registry.getAgent(agentId);
        require(agent.status == IVTRegistry.Status.Active, "Agent not active");
        if (msg.sender != agent.creator) {
            require(ownerCommitmentBindingEnabled, "Owner binding disabled");
            require(msg.sender == owner, "Not creator or owner");
        }
        require(!creatorCommitmentBound[agentId], "Commitment already bound");

        uint256 groupId = agentId;
        semaphore.createGroup(groupId, SEMAPHORE_TREE_DEPTH, address(this));
        require(groupId != 0, "Invalid groupId");
        semaphore.addMember(groupId, commitment);

        agentGroupId[agentId] = groupId;
        creatorCommitmentBound[agentId] = true;

        emit CreatorCommitmentBound(agentId, groupId, commitment);
    }

    /// @notice Import an existing Semaphore group binding for migration to a new Escrow.
    /// @dev This does not create/add members in Semaphore; it only imports local mapping state.
    ///      Use only when the group already exists in Semaphore and contains the creator commitment.
    function importExistingGroupBinding(uint256 agentId, uint256 groupId) external onlyOwner {
        require(agentId > 0 && agentId < registry.nextAgentId(), "Agent does not exist");
        require(groupId != 0, "Invalid groupId");
        require(groupId == agentId, "Group must equal agentId");
        require(!creatorCommitmentBound[agentId], "Commitment already bound");

        IVTRegistry.Agent memory agent = registry.getAgent(agentId);
        require(agent.status == IVTRegistry.Status.Active, "Agent not active");

        agentGroupId[agentId] = groupId;
        creatorCommitmentBound[agentId] = true;

        emit ExistingGroupBindingImported(agentId, groupId);
    }

    /// @notice Set metadata URI used when graduating this Agent.
    /// @dev URI should follow ipfs://... format.
    function setGraduationTokenURI(uint256 agentId, string calldata tokenUri) external onlyOwner {
        require(agentId > 0 && agentId < registry.nextAgentId(), "Agent does not exist");
        _requireTokenURIFormat(tokenUri);

        graduationTokenUris[agentId] = tokenUri;
        emit GraduationTokenURISet(agentId, tokenUri);
    }

    /// @notice First step of two-step graduation flow.
    ///         Verifies Semaphore proof and opens settle gate.
    function authorizeGraduateByProof(
        uint256 agentId,
        ISemaphore.SemaphoreProof calldata proof,
        uint256 signalHash
    ) external {
        _consumeGraduationProof(agentId, proof, signalHash, true);
    }

    /// @notice Atomic graduation flow.
    ///         Verifies Semaphore proof, records token URI, settles funds, mints SBT,
    ///         and syncs VTRegistry graduation status in one transaction.
    function graduateAtomicByProof(
        uint256 agentId,
        ISemaphore.SemaphoreProof calldata proof,
        uint256 signalHash,
        string calldata tokenUri
    ) external onlyOwner {
        _requireTokenURIFormat(tokenUri);
        _consumeGraduationProof(agentId, proof, signalHash, false);

        Escrow storage e = escrows[agentId];
        require(e.status == EscrowStatus.Active, "Escrow not active");
        require(e.totalAmount > 0, "Nothing to settle");

        IVTRegistry.Agent memory agent = registry.getAgent(agentId);
        require(agent.wallet != address(0), "Agent wallet not set");

        graduationTokenUris[agentId] = tokenUri;
        settleAuthorized[agentId] = false;
        e.status = EscrowStatus.Settled;

        _ensureLiquidFunds(e.totalAmount);
        usdt.safeTransfer(agent.wallet, e.totalAmount);
        sbt.mint(agentId, agent.creator, tokenUri);
        registry.graduate(agentId);

        emit GraduationTokenURISet(agentId, tokenUri);
        emit Settled(agentId, EscrowStatus.Settled);
        emit GraduatedAtomically(agentId, proof.nullifier, tokenUri, e.totalAmount);
    }

    function _requireTokenURIFormat(string calldata tokenUri) internal pure {
        bytes memory uri = bytes(tokenUri);
        require(uri.length > 7, "Token URI required");
        require(
            uri[0] == "i" &&
            uri[1] == "p" &&
            uri[2] == "f" &&
            uri[3] == "s" &&
            uri[4] == ":" &&
            uri[5] == "/" &&
            uri[6] == "/",
            "Token URI must start with ipfs://"
        );
    }

    function _consumeGraduationProof(
        uint256 agentId,
        ISemaphore.SemaphoreProof calldata proof,
        uint256 signalHash,
        bool openSettleGate
    ) internal {
        require(agentId > 0 && agentId < registry.nextAgentId(), "Agent does not exist");
        require(creatorCommitmentBound[agentId], "Commitment not bound");

        uint256 groupId = agentGroupId[agentId];
        require(groupId != 0, "Group not initialized");

        // H3: externalNullifier=keccak256("graduate",agentId,chainId)
        uint256 expectedScope = uint256(keccak256(abi.encodePacked("graduate", agentId, block.chainid)));
        require(proof.scope == expectedScope, "Invalid scope");

        // H2: minimal package includes signalHash; enforce deterministic signal to avoid context mismatch.
        uint256 expectedSignal = uint256(keccak256(abi.encodePacked("graduate-signal", agentId, block.chainid)));
        require(signalHash == expectedSignal, "Invalid signal hash");
        require(proof.message == signalHash, "Proof message mismatch");

        require(!usedNullifiers[agentId][proof.nullifier], "Nullifier already used");

        IVTRegistry.Agent memory agent = registry.getAgent(agentId);
        require(agent.status == IVTRegistry.Status.Active, "Agent not active");
        require(agent.trustScore >= int256(TRUST_THRESHOLD), "Trust score below threshold");

        semaphore.verifyProof(
            groupId,
            proof.merkleTreeRoot,
            proof.message,
            proof.nullifier,
            proof.scope,
            proof.points
        );

        usedNullifiers[agentId][proof.nullifier] = true;
        if (openSettleGate) {
            settleAuthorized[agentId] = true;
        }

        emit GraduateAuthorized(agentId, proof.nullifier, signalHash);
    }

    /// @notice Query nullifier usage in agent scope.
    function isNullifierUsed(uint256 agentId, uint256 nullifierHash) external view returns (bool) {
        return usedNullifiers[agentId][nullifierHash];
    }

    /// @notice Settle an Agent's escrow (graduate). Only owner.
    ///         Two-step flow: authorize proof first, then settle.
    ///         Transfers all funds to Agent wallet and mints graduation SBT.
    /// @param agentId The Agent to settle
    function settle(uint256 agentId) external onlyOwner {
        Escrow storage e = escrows[agentId];
        require(e.status == EscrowStatus.Active, "Escrow not active");
        require(e.totalAmount > 0, "Nothing to settle");
        require(settleAuthorized[agentId], "Graduate authorization required");

        IVTRegistry.Agent memory agent = registry.getAgent(agentId);
        require(agent.status == IVTRegistry.Status.Active, "Agent not active");
        require(agent.trustScore >= int256(TRUST_THRESHOLD), "Trust score below threshold");

        address recipient = agent.wallet;
        require(recipient != address(0), "Agent wallet not set");

        string memory tokenUri = graduationTokenUris[agentId];
        require(bytes(tokenUri).length > 0, "Graduation token URI not set");

        e.status = EscrowStatus.Settled;
        settleAuthorized[agentId] = false;
        _ensureLiquidFunds(e.totalAmount);
        usdt.safeTransfer(recipient, e.totalAmount);

        // Mint SBT to creator as graduation credential holder.
        sbt.mint(agentId, agent.creator, tokenUri);
        registry.graduate(agentId);

        emit Settled(agentId, EscrowStatus.Settled);
    }

    /// @notice Refund all backers for an Agent. Only owner.
    /// @param agentId The Agent to refund
    function refund(uint256 agentId) external onlyOwner {
        Escrow storage e = escrows[agentId];
        require(e.status == EscrowStatus.Active, "Escrow not active");
        require(e.totalAmount > 0, "Nothing to refund");

        _ensureLiquidFunds(e.totalAmount);
        e.status = EscrowStatus.Refunded;

        uint256 totalFee;

        for (uint256 i = 0; i < e.backers.length; i++) {
            address backer = e.backers[i];
            uint256 amount = e.contributions[backer];
            if (amount > 0) {
                e.contributions[backer] = 0;
                uint256 fee = (amount * REFUND_FEE_BPS) / BPS_BASE;
                uint256 net = amount - fee;
                totalFee += fee;
                usdt.safeTransfer(backer, net);
            }
        }

        if (totalFee > 0) {
            usdt.safeTransfer(owner, totalFee);
            emit RefundFeeCollected(agentId, totalFee);
        }

        emit Settled(agentId, EscrowStatus.Refunded);
    }

    /// @notice Disable owner fallback for commitment binding.
    ///         Irreversible hardening: once disabled, only creator can bind.
    function disableOwnerCommitmentBinding() external onlyOwner {
        require(ownerCommitmentBindingEnabled, "Owner binding already disabled");
        ownerCommitmentBindingEnabled = false;
        emit OwnerCommitmentBindingDisabled();
    }

    /// @notice Transfer contract ownership to a new owner address.
    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "Invalid owner");
        address previousOwner = owner;
        owner = newOwner;
        emit OwnershipTransferred(previousOwner, newOwner);
    }

    /// @notice Set or replace the optional yield strategy contract.
    /// @dev Set address(0) to disable strategy deployment.
    function setYieldStrategy(address newStrategy) external onlyOwner {
        address previousStrategy = yieldStrategy;
        yieldStrategy = newStrategy;
        emit YieldStrategyUpdated(previousStrategy, newStrategy);
    }

    /// @notice Deploy idle USDT from escrow into the configured strategy.
    /// @dev Does not change external user flow. Owner controls deployment cadence.
    function deployIdleToStrategy(uint256 amount) external onlyOwner {
        _deployIdleToStrategy(amount);
    }

    /// @notice Withdraw USDT from strategy back to escrow.
    /// @return withdrawn Amount actually withdrawn from strategy.
    function withdrawFromStrategy(uint256 amount) external onlyOwner returns (uint256 withdrawn) {
        require(yieldStrategy != address(0), "Yield strategy not set");
        require(amount > 0, "Amount must be > 0");

        withdrawn = IYieldStrategy(yieldStrategy).withdraw(amount, address(this));
        emit StrategyFundsWithdrawn(withdrawn, yieldStrategy);
    }

    function _ensureLiquidFunds(uint256 requiredAmount) internal {
        uint256 liquid = usdt.balanceOf(address(this));
        if (liquid >= requiredAmount) {
            return;
        }

        require(yieldStrategy != address(0), "Insufficient liquid USDT");

        uint256 needed = requiredAmount - liquid;
        uint256 withdrawn = IYieldStrategy(yieldStrategy).withdraw(needed, address(this));
        emit StrategyFundsWithdrawn(withdrawn, yieldStrategy);

        require(usdt.balanceOf(address(this)) >= requiredAmount, "Insufficient liquid after strategy withdraw");
    }

    function _deployIdleToStrategy(uint256 amount) internal {
        require(yieldStrategy != address(0), "Yield strategy not set");
        require(amount > 0, "Amount must be > 0");
        require(usdt.balanceOf(address(this)) >= amount, "Insufficient liquid USDT");

        usdt.safeTransfer(yieldStrategy, amount);
        IYieldStrategy(yieldStrategy).deposit(amount);

        emit IdleFundsDeployed(amount, yieldStrategy);
    }

    // ── View Functions ───────────────────────────────────────────────────

    /// @notice Get escrow info for an Agent.
    function getEscrow(uint256 agentId) external view returns (
        uint256 totalAmount,
        uint256 backerCount,
        EscrowStatus status
    ) {
        Escrow storage e = escrows[agentId];
        return (e.totalAmount, e.backers.length, e.status);
    }

    /// @notice Get a backer's contribution to an Agent.
    function getContribution(uint256 agentId, address backer) external view returns (uint256) {
        return escrows[agentId].contributions[backer];
    }

    /// @notice Read total assets currently managed by strategy.
    function getStrategyManagedAssets() external view returns (uint256) {
        if (yieldStrategy == address(0)) {
            return 0;
        }
        try IYieldStrategy(yieldStrategy).totalManagedAssets() returns (uint256 assets) {
            return assets;
        } catch {
            return 0;
        }
    }
}
