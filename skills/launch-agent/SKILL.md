---
name: launch-agent
description: >
  发射 AI Agent。创建 Agent 钱包 + 注册到 VTRegistry 链上合约（BSC）。
  触发: 发射, launch, 注册Agent, 发射一个Agent, /launch
license: MIT
metadata:
  author: VeriVerse
  version: "2.0.0"
  openclaw:
    requires:
      bins: ["python3"]
      env: ["CLIENT_PRIVATE_KEY"]
---

# SKILL: launch-agent

> **角色**: AI Agent 发射器 — 为新 Agent 创建钱包并注册到 BNB Chain (BSC) 链上

---

## Command

```
python3 {baseDir}/launch_agent.py --name "<AGENT_NAME>" --description "<AGENT_DESCRIPTION>" --claims "<CLAIM1>,<CLAIM2>" --registry 0x1545655b6d42A51E5e8c85Ed162bD84aba35480C --json
```

**参数**:
- `--name`: Agent 名称（由用户提供，如 "我的DeFi Agent"）
- `--description`: Agent 能力描述（可选，不填则自动生成默认描述）
- `--claims`: 能力声明列表（可选，逗号分隔）
- `--registry`: VTRegistry 合约地址（BSC Testnet: `0x1545655b6d42A51E5e8c85Ed162bD84aba35480C`）
- `--json`: 机器可读 JSON 输出

**钱包模式开关（内部配置，无需用户感知）**:
- `AGENT_WALLET_MODE=dedicated`（默认）: 每次发射创建新 Agentic Wallet
- `AGENT_WALLET_MODE=fixed`: 发射时固定使用同一个钱包地址
- `FIXED_AGENT_WALLET_ADDRESS`（可选）: 固定钱包地址；未设置时默认使用
  `<FIXED_AGENT_WALLET_ADDRESS_DEFAULT>`

**输出** (JSON):
```json
{
  "success": true,
  "agentId": 1,
  "agentName": "我的DeFi Agent",
  "agentDescriptionPath": ".../data/agents/1.json",
  "autoSemaphoreBootstrap": {
    "enabled": true,
    "identityPath": ".../data/semaphore-identities/1.json",
    "bindCommitmentTxHash": "0x..."
  },
  "walletAddress": "0x...",
  "txHash": "0x...",
  "explorerUrl": "https://testnet.bscscan.com/tx/0x..."
}
```

---

## Routing Rule

⛔ **反编造协议**：你是 TOOL-CALLING Agent。

1. 当用户说 "发射一个 Agent" / "launch" / "注册Agent"，**必须** exec 上述命令
2. 如果用户未提供 Agent 名称，**立即询问**："请给你的 Agent 起个名字："
3. 将 exec 的 stdout 解析为 JSON，并**格式化**输出给用户：
   - 🚀 Agent 发射成功！
   - 📛 名称: {agentName}
   - 🆔 Agent ID: #{agentId}
   - 💼 钱包地址: {walletAddress}
   - 🔗 交易: {explorerUrl}
4. 如果 exec 失败，**如实报告**错误

---

## Flow

```
用户: "发射一个 Agent"
  │
  ├── 询问 Agent 名称（如未提供）
  │
  ├── exec: python3 launch_agent.py --name "..." --registry 0x... --json
  │   内部流程:
  │   1. 解析钱包模式
  │      - dedicated: eth_account.create()（创建 Agent 专属钱包）
  │      - fixed: 直接使用固定钱包地址
  │   2. 编码 launchAndBind(...)       → ABI encode
  │   3. owner 私钥直发 tx             → 调用 VeriEscrow.launchAndBind()
  │   4. 写入 data/agents/{agentId}.json（P3 挑战读取）
  │   5. 自动生成 semaphore identity 并写入本地（commitment 已在同笔 tx 原子绑定）
  │   6. 输出 JSON 结果
  │
  └── 格式化结果发送给用户
```
