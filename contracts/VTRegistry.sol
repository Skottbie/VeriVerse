// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title VTRegistry v2 — VeriVerse Agent Registry
/// @notice Registers AI Agents, tracks trust scores, and stores agent metadata.
///         Extends v1 (pure event log) with stateful agent registry.
contract VTRegistry {
    // ── Types ────────────────────────────────────────────────────────────

    enum Status { Active, Graduated, Deactivated }

    struct Agent {
        string name;
        address creator;
        address wallet;
        int256 trustScore;
        Status status;
    }

    // ── State ────────────────────────────────────────────────────────────

    uint256 public nextAgentId = 1;
    mapping(uint256 => Agent) private agents;
    mapping(uint256 => address) public agentTokenCA;  // agentId → Four.meme Token CA (one-time immutable)

    address public owner;
    address public registrar;
    bool public devMode = true;  // Only owner/whitelist can register/anchor when true
    mapping(address => bool) public whitelist;

    // ── Events ───────────────────────────────────────────────────────────

    event AgentRegistered(uint256 indexed agentId, address indexed creator, address wallet, string name);
    event TrustUpdated(uint256 indexed agentId, int256 newScore);
    event StatusChanged(uint256 indexed agentId, Status newStatus);

    // v1 compatibility: reputation edge event
    event Edge(address indexed client, address indexed worker, bytes data);

    event RegistrationOpened();  // Emitted when devMode is turned off

    event WhitelistUpdated(address indexed addr, bool status);
    event RegistrarUpdated(address indexed registrar);
    event AgentTokenLinked(uint256 indexed agentId, address indexed tokenCA);
    event EarlyExitFlagged(uint256 indexed agentId, address indexed backer);

    // ── Modifiers ────────────────────────────────────────────────────────

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    modifier onlyOwnerOrRegistrar() {
        require(msg.sender == owner || msg.sender == registrar, "Not owner or registrar");
        _;
    }

    modifier agentExists(uint256 agentId) {
        require(agentId > 0 && agentId < nextAgentId, "Agent does not exist");
        _;
    }

    modifier whenOpen() {
        require(!devMode || msg.sender == owner || whitelist[msg.sender], "Registration not open yet");
        _;
    }

    // ── Constructor ──────────────────────────────────────────────────────

    constructor() {
        owner = msg.sender;
    }

    // ── Core Functions ───────────────────────────────────────────────────

    /// @notice Register a new Agent on-chain.
    /// @param name    Human-readable name for the Agent
    /// @param wallet  The Agent's on-chain wallet address
    /// @return agentId The unique ID assigned to this Agent
    function register(string calldata name, address wallet) external whenOpen returns (uint256 agentId) {
        agentId = _register(name, wallet, msg.sender);
    }

    /// @notice Owner/registrar path for atomic launch orchestration.
    /// @dev Used by escrow launch-and-bind entrypoint to guarantee all-or-nothing flow.
    function registerFor(address creator, string calldata name, address wallet)
        external
        onlyOwnerOrRegistrar
        returns (uint256 agentId)
    {
        require(creator != address(0), "Invalid creator");
        agentId = _register(name, wallet, creator);
    }

    function _register(string calldata name, address wallet, address creator) internal returns (uint256 agentId) {
        require(bytes(name).length > 0, "Name required");
        require(bytes(name).length <= 128, "Name too long");
        require(wallet != address(0), "Invalid wallet");

        agentId = nextAgentId++;
        agents[agentId] = Agent({
            name: name,
            creator: creator,
            wallet: wallet,
            trustScore: 0,
            status: Status.Active
        });

        emit AgentRegistered(agentId, creator, wallet, name);
    }

    /// @notice Update an Agent's trust score by delta. Only callable by owner.
    /// @param agentId The Agent to update
    /// @param delta   Positive or negative trust change
    function updateTrust(uint256 agentId, int256 delta) external onlyOwner agentExists(agentId) {
        require(agents[agentId].status == Status.Active, "Agent not active");
        int256 nextScore = agents[agentId].trustScore + delta;
        if (nextScore < 0) {
            nextScore = 0;
        }
        agents[agentId].trustScore = nextScore;
        emit TrustUpdated(agentId, agents[agentId].trustScore);
    }

    /// @notice Mark an Agent as graduated. Callable by owner or registrar.
    function graduate(uint256 agentId) external onlyOwnerOrRegistrar agentExists(agentId) {
        require(agents[agentId].status == Status.Active, "Agent not active");
        agents[agentId].status = Status.Graduated;
        emit StatusChanged(agentId, Status.Graduated);
    }

    // ── Token Binding ─────────────────────────────────────────────────────

    /// @notice Bind a Four.meme Token CA to a graduated Agent. One-time immutable.
    /// @param agentId  The graduated Agent
    /// @param tokenCA  The Four.meme Token contract address
    function linkAgentToken(uint256 agentId, address tokenCA)
        external
        onlyOwnerOrRegistrar
        agentExists(agentId)
    {
        require(agents[agentId].status == Status.Graduated, "Agent not graduated");
        require(tokenCA != address(0), "Invalid token address");
        require(agentTokenCA[agentId] == address(0), "Token already linked");
        agentTokenCA[agentId] = tokenCA;
        emit AgentTokenLinked(agentId, tokenCA);
    }

    /// @notice Flag a backer for early exit (pre-graduation withdrawal).
    /// @param agentId  The Agent being backed
    /// @param backer   The backer address flagged
    function flagEarlyExit(uint256 agentId, address backer)
        external
        onlyOwner
        agentExists(agentId)
    {
        emit EarlyExitFlagged(agentId, backer);
    }

    // ── View Functions ───────────────────────────────────────────────────

    /// @notice Get full Agent data.
    function getAgent(uint256 agentId) external view agentExists(agentId) returns (Agent memory) {
        return agents[agentId];
    }

    // ── v1 Compatibility ─────────────────────────────────────────────────

    /// @notice Anchor a reputation edge (v1 compat). msg.sender = client.
    function anchor(address worker, bytes calldata data) external whenOpen {
        emit Edge(msg.sender, worker, data);
    }

    // ── Admin Functions ──────────────────────────────────────────────────

    /// @notice Set an optional registrar contract that can call registerFor.
    function setRegistrar(address newRegistrar) external onlyOwner {
        registrar = newRegistrar;
        emit RegistrarUpdated(newRegistrar);
    }

    /// @notice Irreversibly open registration to all users. Only callable by owner.
    function openRegistration() external onlyOwner {
        require(devMode, "Already open");
        devMode = false;
        emit RegistrationOpened();
    }

    /// @notice Add an address to the whitelist (can register in devMode).
    function addToWhitelist(address addr) external onlyOwner {
        whitelist[addr] = true;
        emit WhitelistUpdated(addr, true);
    }

    /// @notice Remove an address from the whitelist.
    function removeFromWhitelist(address addr) external onlyOwner {
        whitelist[addr] = false;
        emit WhitelistUpdated(addr, false);
    }
}
