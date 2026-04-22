// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

interface IAavePool {
    function supply(address asset, uint256 amount, address onBehalfOf, uint16 referralCode) external;
    function withdraw(address asset, uint256 amount, address to) external returns (uint256);
}

/// @title AaveSupplyStrategy
/// @notice Minimal strategy adapter: escrow-controlled supply/withdraw on Aave.
contract AaveSupplyStrategy {
    using SafeERC20 for IERC20;

    IERC20 public immutable usdt;
    IERC20 public immutable aToken;
    IAavePool public immutable pool;
    address public immutable escrow;

    modifier onlyEscrow() {
        require(msg.sender == escrow, "Only escrow");
        _;
    }

    constructor(address _usdt, address _aToken, address _pool, address _escrow) {
        require(_usdt != address(0), "Invalid USDT");
        require(_aToken != address(0), "Invalid aToken");
        require(_pool != address(0), "Invalid pool");
        require(_escrow != address(0), "Invalid escrow");

        usdt = IERC20(_usdt);
        aToken = IERC20(_aToken);
        pool = IAavePool(_pool);
        escrow = _escrow;
    }

    function deposit(uint256 amount) external onlyEscrow {
        if (amount == 0) {
            return;
        }
        usdt.safeIncreaseAllowance(address(pool), amount);
        pool.supply(address(usdt), amount, address(this), 0);
    }

    function withdraw(uint256 amount, address to) external onlyEscrow returns (uint256) {
        require(to != address(0), "Invalid recipient");
        return pool.withdraw(address(usdt), amount, to);
    }

    function totalManagedAssets() external view returns (uint256) {
        return aToken.balanceOf(address(this));
    }
}
