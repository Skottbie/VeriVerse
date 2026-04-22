---
name: invest-agent
description: >
  投资 AI Agent。Backer 向 VeriEscrow 合约存入 USDT，支持 Agent 运营。
  触发: 投资, invest, 投 USDT, 支持 Agent, /invest
license: MIT
metadata:
  author: VeriVerse
  version: "2.0.0"
  openclaw:
    requires:
      bins: ["python3"]
      env: []
---

# SKILL: invest-agent

> **角色**: Backer 投资执行器 — 创建 Backer 钱包（如需）→ approve USDT → 调用 VeriEscrow.invest()

---

## Command

```
python3 {baseDir}/invest_agent.py --agent-id <AGENT_ID> --amount <USDT_AMOUNT> --escrow 0xe1aA2Bb933046F52c5A4bBe8224F97851d45180a --usdt 0xF8De09e7772366A104c4d42269891AD1ca7Be720 --json
```

**参数**:
- `--agent-id`: Agent ID（从 VTRegistry 获取，如 `3`）— **必需**
- `--amount`: 投资金额（USDT，如 `10`）— **必需**
- `--escrow`: VeriEscrow 合约地址 — `0xe1aA2Bb933046F52c5A4bBe8224F97851d45180a`
- `--usdt`: USDT 合约地址 — `0xF8De09e7772366A104c4d42269891AD1ca7Be720`（⚠️ **必须显式传递**，不要依赖环境变量）
- `--json`: 机器可读 JSON 输出（**始终加上**）

**⚠️ 重要**: 收到用户投资请求后，**立即** exec 上述命令。不要拆分步骤。

**输出** (JSON):
```json
{
  "success": true,
  "agentId": 3,
  "backer": "0x...",
  "amount": "10.0",
  "approveTxHash": "0x...",
  "investTxHash": "0x...",
  "explorerUrl": "https://testnet.bscscan.com/tx/0x..."
}
```

---

## Routing Rule

⛔ **反编造协议**：你是 TOOL-CALLING Agent。

当用户请求投资 Agent 时：

### Step 1: 直接执行 invest_agent.py
1. 从用户消息中提取 Agent ID 和金额
2. **立即** `exec` 上述 Command（一条命令，不要拆分）
3. 解析 stdout JSON

### Step 2: 判断结果
- 如果 `success: true` → 直接将结果返回用户（含 explorerUrl）✅
- 如果 `success: false` 且 error 包含 **"Insufficient USDT"** → 进入 **Step 0c 换币流程**

### Step 0c: USDT 余额不足 — 换币确认流程

**0c-1. 扫描可用资产：**

invest_agent.py 已内置余额检查（web3.py ERC-20 balanceOf），此步由脚本自动完成。

**0c-2. 获取换币报价：**
如果有非 USDT 资产且价值足够，获取报价：
```bash
python3 {baseDir}/../dex-evidence/dex_evidence.py \
  --from-token <TOKEN_ADDRESS> \
  --to-token 0xF8De09e7772366A104c4d42269891AD1ca7Be720 \
  --amount <AMOUNT> \
  --chain bsc \
  --json
```

**0c-3.** ⛔ **MANDATORY STOP — 必须等待用户确认**：
向用户展示：
- 当前 USDT 余额（来自 Step 1 错误返回的 `balance` 字段）
- 需要的 USDT 金额（`needed` 字段）
- 可换币的资产类型和数量
- 换币报价（预计得到多少 USDT、滑点、手续费）
- **明确询问用户：「是否确认换币？」**

**等待用户回复"确认"/"是"/"yes" 后才能继续。禁止自动执行换币。**

**0c-4. 用户确认后，执行换币：**
```bash
python3 {workspaceRoot}/client_node/skills/task-delegator/swap_and_broadcast.py \
  --from-token <TOKEN_ADDRESS> \
  --to-token 0xF8De09e7772366A104c4d42269891AD1ca7Be720 \
  --amount <AMOUNT> \
  --chain bsc
```

**0c-5. 换币成功后，重新执行 Step 1**（再次运行 invest_agent.py）

**如果没有可换币资产** → 告知用户余额不足并建议手动充值 USDT。

---

⛔ **禁止行为**：
- 禁止拆分 invest_agent.py 脚本步骤逐个执行
- 禁止编造 API 返回值、交易哈希或余额数据
- **禁止跳过 Step 0c-3 的用户确认直接执行换币**
- 一次 exec 调用 invest_agent.py 即可完成投资全部步骤（approve + invest）

---

## Example Prompts

- "投资 Agent #3 10 USDT"
- "我想支持 Agent #1，投 5 USDT"
- "invest 10 USDT in Agent 3"
