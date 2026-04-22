// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/// @title VeriSBT
/// @notice Soulbound graduation credential for agents.
contract VeriSBT is ERC721URIStorage, Ownable {
    error NotMinter();
    error Soulbound();
    error AlreadyMinted(uint256 agentId);
    error InvalidHolder();

    address public minter;

    // agentId => tokenId (tokenId is equal to agentId for simpler traceability)
    mapping(uint256 => uint256) private agentToTokenId;

    event MinterUpdated(address indexed previousMinter, address indexed newMinter);
    event SBTMinted(uint256 indexed agentId, uint256 indexed tokenId, address indexed holder, string tokenUri);

    constructor(address initialOwner) ERC721("VeriVerse Graduation SBT", "VGSBT") Ownable(initialOwner) {}

    modifier onlyMinter() {
        if (msg.sender != minter) {
            revert NotMinter();
        }
        _;
    }

    function setMinter(address newMinter) external onlyOwner {
        address previous = minter;
        minter = newMinter;
        emit MinterUpdated(previous, newMinter);
    }

    function mint(uint256 agentId, address holder, string calldata tokenUri) external onlyMinter returns (uint256 tokenId) {
        if (holder == address(0)) {
            revert InvalidHolder();
        }
        if (agentToTokenId[agentId] != 0) {
            revert AlreadyMinted(agentId);
        }

        tokenId = agentId;
        agentToTokenId[agentId] = tokenId;

        _safeMint(holder, tokenId);
        _setTokenURI(tokenId, tokenUri);

        emit SBTMinted(agentId, tokenId, holder, tokenUri);
    }

    function holderOf(uint256 agentId) external view returns (address) {
        uint256 tokenId = agentToTokenId[agentId];
        if (tokenId == 0) {
            return address(0);
        }
        return ownerOf(tokenId);
    }

    function _update(address to, uint256 tokenId, address auth) internal override returns (address from) {
        from = _ownerOf(tokenId);
        if (from != address(0) && to != address(0)) {
            revert Soulbound();
        }
        return super._update(to, tokenId, auth);
    }
}
