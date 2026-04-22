---
name: graduate-agent
description: >
  触发 Agent 毕业结算（P4）：单笔交易完成 Semaphore 授权校验、Escrow settle、SBT 铸造与状态同步。
  触发: 毕业, graduate, /graduate, 结算毕业, 铸造SBT
license: MIT
metadata:
  author: VeriVerse
  version: "1.0.0"
  openclaw:
    requires:
      bins: ["python3"]
      env: ["CLIENT_PRIVATE_KEY"]
---

# SKILL: graduate-agent

> 角色：P4 毕业执行器（原子式授权）

## Command

```bash
python3 {baseDir}/graduate_agent.py --agent-id <AGENT_ID> --json
```

参数：
- --agent-id: 目标 Agent ID（必填）
- --escrow: VeriEscrow 合约地址（可选，不传时自动读取 addresses.json bsc.VeriEscrow）
- --token-uri: 毕业 SBT 元数据（可选，不传时自动生成；有 PINATA_JWT 则上传，否则使用本地 ipfs:// fallback）
- --proof-file: Semaphore proof JSON 文件路径（可选）
- --proof-json: 直接传 proof JSON 字符串（可选）
- --json: 输出 JSON 结果

输出（JSON）：
```json
{
  "success": true,
  "agentId": 3,
  "atomicTxHash": "0x...",
  "settleTxHash": "0x...",
  "explorerSettle": "https://testnet.bscscan.com/tx/0x..."
}
```

## Routing Rule

1. 用户触发 /graduate 或“毕业 Agent #X”时，必须执行上述命令。
2. 缺少 proof 或 token-uri 时，优先走自动模式：
  - proof：从 data/semaphore-identities/<agentId>.json 自动生成；
  - token-uri：自动生成（Pinata 或本地 fallback）。
3. 只有自动模式失败时，才向用户请求补充参数。
4. 命令执行失败时，如实回传错误，不得构造假交易哈希。

## 执行链路（H5 原子式）

1. graduateAtomicByProof(agentId, proof, signalHash, tokenUri)

## 反编造规则

- 你是 TOOL-CALLING Agent，不是结果生成器。
- 所有 txHash 必须来自真实命令 stdout。
- 如果 proof 校验失败，必须原样报告失败原因。
