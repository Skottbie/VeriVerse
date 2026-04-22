/**
 * tokenMode.js — TOKEN_MODE 三层切换
 * 环境变量 TOKEN_MODE = mock | pausable | fourmeme (默认 mock)
 */
import dotenv from "dotenv";
dotenv.config();

const TOKEN_MODE = process.env.TOKEN_MODE || "mock";

const MOCK_DATA = {
  name: "TST_DO_NOT_BUY",
  symbol: "VTEST",
  mcap: "$42,350",
  price: "0.00004235 BNB",
  volume24h: "2.3 BNB",
  holders: 37,
  taxInfo: {
    feeRate: 5,
    divideRate: 60,
    liquidityRate: 30,
    recipientRate: 10,
  },
  economy: {
    agentRevenue: "$42.30",
    serviceCalls: 17,
    holderDividends: "$253.80",
    lpReinvested: "$126.90",
  },
  fourmemeUrl: null,
  isTestMode: true,
};

export function getTokenMode() {
  return TOKEN_MODE;
}

export function isMockMode() {
  return TOKEN_MODE === "mock";
}

export function getMockTokenData(agentId, tokenCA) {
  return {
    hasToken: true,
    agentId,
    tokenCA: tokenCA || "0x00000000000000000000000000000000CAFE4444",
    ...MOCK_DATA,
  };
}
