// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract MockSemaphore {
    mapping(uint256 => bool) public groups;
    mapping(uint256 => mapping(uint256 => bool)) public members;
    mapping(uint256 => uint256) private _roots;
    mapping(uint256 => uint256) private _sizes;

    function createGroup(uint256 groupId, uint256, address) external {
        require(groupId != 0, "Invalid group");
        require(!groups[groupId], "Group exists");
        groups[groupId] = true;
    }

    function addMember(uint256 groupId, uint256 identityCommitment) external {
        require(groups[groupId], "Group not exist");
        members[groupId][identityCommitment] = true;
        _sizes[groupId]++;
    }

    function getMerkleTreeRoot(uint256 groupId) external view returns (uint256) {
        require(groups[groupId], "Group not exist");
        return _roots[groupId];
    }

    function getMerkleTreeSize(uint256 groupId) external view returns (uint256) {
        require(groups[groupId], "Group not exist");
        return _sizes[groupId];
    }

    /// @dev Set the Merkle root for a group (computed off-chain via @semaphore-protocol/group).
    function setMerkleTreeRoot(uint256 groupId, uint256 root) external {
        require(groups[groupId], "Group not exist");
        _roots[groupId] = root;
    }

    function verifyProof(
        uint256 groupId,
        uint256,
        uint256,
        uint256,
        uint256 externalNullifier,
        uint256[8] calldata
    ) external {
        require(groups[groupId], "Group not exist");
        require(externalNullifier != 0, "Invalid proof");
    }
}
