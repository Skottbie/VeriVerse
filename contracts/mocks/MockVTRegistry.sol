// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract MockVTRegistry {
    enum Status {
        Active,
        Graduated,
        Deactivated
    }

    struct Agent {
        string name;
        address creator;
        address wallet;
        int256 trustScore;
        Status status;
    }

    uint256 public nextAgentId = 1;
    mapping(uint256 => Agent) private agents;

    function registerMock(string calldata name, address creator, address wallet, int256 trustScore) external returns (uint256) {
        uint256 agentId = nextAgentId++;
        agents[agentId] = Agent({
            name: name,
            creator: creator,
            wallet: wallet,
            trustScore: trustScore,
            status: Status.Active
        });
        return agentId;
    }

    function setTrust(uint256 agentId, int256 trustScore) external {
        agents[agentId].trustScore = trustScore;
    }

    function graduate(uint256 agentId) external {
        require(agentId > 0 && agentId < nextAgentId, "Agent does not exist");
        require(agents[agentId].status == Status.Active, "Agent not active");
        agents[agentId].status = Status.Graduated;
    }

    function getAgent(uint256 agentId) external view returns (Agent memory) {
        return agents[agentId];
    }
}
