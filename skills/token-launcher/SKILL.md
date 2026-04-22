---
name: token-launcher
description: >
  发射 Agent Token（毕业即发币）。已毕业并持有 SBT 的 Creator 可发射 Agent Token，绑定到链上。
  触发: 发币, 发射token, launch token, /token, 发射agent token, agent token, 毕业发币
license: MIT
metadata:
  author: VeriVerse
  version: "1.0.0"
  openclaw:
    requires:
      bins: ["python3"]
      env: ["CLIENT_PRIVATE_KEY"]
---

# SKILL: token-launcher

> **角色**: Agent Token 发射器 — 校验毕业状态 + SBT 身份 → Mock Token → linkAgentToken 上链

---

## Command

```
python3 {baseDir}/token_launcher.py --agent-id <AGENT_ID> --registry 0x1545655b6d42A51E5e8c85Ed162bD84aba35480C --sbt 0x78ec183F99A45dF172DdB3130EE24FCd48955544 --json
```

**参数**:
- `--agent-id`: 目标 Agent ID（必填）
- `--registry`: VTRegistry 合约地址 — `0x1545655b6d42A51E5e8c85Ed162bD84aba35480C`
- `--sbt`: VeriSBT 合约地址 — `0x78ec183F99A45dF172DdB3130EE24FCd48955544`
- `--json`: 机器可读 JSON 输出（**始终加上**）

**⚠️ 重要**: 收到用户发币请求后，**立即** exec 上述命令。不要拆分步骤。

**输出** (JSON):
```json
{
  "success": true,
  "agentId": 4,
  "tokenCA": "0x...",
  "tokenName": "VeriAgent_4",
  "tokenSymbol": "VAGT4",
  "tokenMode": "mock",
  "linkTxHash": "0x...",
  "explorerUrl": "https://testnet.bscscan.com/tx/0x...",
  "verifyUrl": "http://127.0.0.1:3001/verify/agent/4",
  "description": "VeriVerse Certified Agent #4 | Verify: http://127.0.0.1:3001/verify/agent/4"
}
```

---

## 前置校验（脚本内部自动执行）

1. `VTRegistry.getAgent(agentId).status == 1 (Graduated)` — 必须已毕业
2. `VeriSBT.holderOf(agentId) == callerAddress` — 调用者必须是 SBT 持有者（毕业凭证）
3. `VTRegistry.agentTokenCA(agentId) == address(0)` — 未绑定过 Token（一次性不可变）

任一校验失败 → 返回具体错误信息，不执行上链交易。

---

## Routing Rule

1. 用户触发 "发射 Agent Token" / "给 Agent #X 发币" / "/token X" 时，必须执行上述命令。
2. 命令执行成功后，告知用户 Token 已绑定，附 BSCScan 链接和验证页 URL。
3. 命令执行失败时，如实回传错误，不得构造假交易哈希。

## 反编造规则

- 你是 TOOL-CALLING Agent，不是结果生成器。
- 不得编造 Token 地址或交易哈希。
- 不得跳过 exec 直接回复"已完成"。
