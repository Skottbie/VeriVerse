import "@nomicfoundation/hardhat-toolbox";
import dotenv from "dotenv";
import { fileURLToPath } from "url";
import path from "path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.resolve(__dirname, ".env") });

/** @type {import('hardhat/config').HardhatUserConfig} */
export default {
  solidity: {
    version: "0.8.28",
    settings: {
      evmVersion: "cancun",
      optimizer: {
        enabled: true,
        runs: 50,
      },
    },
  },
  networks: {
    bsc_testnet: {
      url: "https://bsc-testnet-rpc.publicnode.com",
      chainId: 97,
      accounts: process.env.CLIENT_PRIVATE_KEY ? [process.env.CLIENT_PRIVATE_KEY] : [],
    },
    bsc: {
      url: "https://bsc-dataseed.binance.org",
      chainId: 56,
      accounts: process.env.CLIENT_PRIVATE_KEY ? [process.env.CLIENT_PRIVATE_KEY] : [],
    },
  },
};
