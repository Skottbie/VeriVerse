// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

contract MockYieldStrategy {
    using SafeERC20 for IERC20;

    IERC20 public immutable usdt;
    address public immutable escrow;
    uint256 public managedAssets;

    modifier onlyEscrow() {
        require(msg.sender == escrow, "Only escrow");
        _;
    }

    constructor(address _usdt, address _escrow) {
        require(_usdt != address(0), "Invalid USDT");
        require(_escrow != address(0), "Invalid escrow");
        usdt = IERC20(_usdt);
        escrow = _escrow;
    }

    function deposit(uint256 amount) external onlyEscrow {
        managedAssets += amount;
    }

    function withdraw(uint256 amount, address to) external onlyEscrow returns (uint256) {
        require(to != address(0), "Invalid recipient");

        uint256 available = managedAssets;
        uint256 actual = amount > available ? available : amount;

        managedAssets -= actual;
        usdt.safeTransfer(to, actual);
        return actual;
    }

    function totalManagedAssets() external view returns (uint256) {
        return managedAssets;
    }
}
