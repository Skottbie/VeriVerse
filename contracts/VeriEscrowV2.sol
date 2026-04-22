// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./VeriEscrow.sol";

/// @title VeriEscrowV2
/// @notice Extends VeriEscrow with optional auto-deploy behavior after invest.
contract VeriEscrowV2 is VeriEscrow {
    uint16 public constant AUTO_DEPLOY_BPS_BASE = 10_000;

    bool public autoDeployOnInvestEnabled;
    uint16 public autoDeployOnInvestBps;
    uint256 public minLiquidReserve;

    event AutoDeployConfigUpdated(
        bool enabled,
        uint16 deployBps,
        uint256 minReserveAmount,
        uint256 timestamp
    );
    event AutoDeployOnInvestTriggered(
        uint256 indexed agentId,
        uint256 investedAmount,
        uint256 deployedAmount,
        address indexed strategy
    );

    constructor(address _usdt, address _registry, address _semaphore, address _sbt)
        VeriEscrow(_usdt, _registry, _semaphore, _sbt)
    {
        autoDeployOnInvestEnabled = true;
        autoDeployOnInvestBps = AUTO_DEPLOY_BPS_BASE;
        minLiquidReserve = 0;
    }

    /// @notice Configure invest-time auto deploy policy.
    /// @param enabled Enable/disable auto deployment after invest.
    /// @param deployBps Portion of each new invest amount to deploy (0-10000).
    /// @param minReserveAmount Minimal USDT to keep liquid in escrow.
    function setAutoDeployOnInvestConfig(
        bool enabled,
        uint16 deployBps,
        uint256 minReserveAmount
    ) external onlyOwner {
        require(deployBps <= AUTO_DEPLOY_BPS_BASE, "Invalid deploy bps");

        autoDeployOnInvestEnabled = enabled;
        autoDeployOnInvestBps = deployBps;
        minLiquidReserve = minReserveAmount;

        emit AutoDeployConfigUpdated(enabled, deployBps, minReserveAmount, block.timestamp);
    }

    /// @notice Preview the deploy amount that would be attempted for one invest.
    function previewAutoDeployAmount(uint256 investedAmount) external view returns (uint256) {
        return _computeAutoDeployAmount(investedAmount);
    }

    function _afterInvest(uint256 agentId, uint256 amount) internal override {
        uint256 deployAmount = _computeAutoDeployAmount(amount);
        if (deployAmount == 0) {
            return;
        }

        _deployIdleToStrategy(deployAmount);
        emit AutoDeployOnInvestTriggered(agentId, amount, deployAmount, yieldStrategy);
    }

    function _computeAutoDeployAmount(uint256 investedAmount) internal view returns (uint256) {
        if (!autoDeployOnInvestEnabled) {
            return 0;
        }
        if (yieldStrategy == address(0)) {
            return 0;
        }
        if (autoDeployOnInvestBps == 0) {
            return 0;
        }

        uint256 target = (investedAmount * autoDeployOnInvestBps) / AUTO_DEPLOY_BPS_BASE;
        if (target == 0) {
            return 0;
        }

        uint256 liquid = usdt.balanceOf(address(this));
        if (liquid <= minLiquidReserve) {
            return 0;
        }

        uint256 available = liquid - minLiquidReserve;
        return target > available ? available : target;
    }
}
