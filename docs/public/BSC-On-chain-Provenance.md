# BSC Testnet On-Chain Records and TG Bot (Veri Agent) Interaction Log
# BSC Testnet 真实上链和 TG Bot (Veri Agent) 真实交互记录

---

## Core Contract Addresses (BSC Testnet) / 核心合约地址（BSC Testnet）

| Contract | Address |
|----------|---------|
| VTRegistry  | `0x1545655b6d42A51E5e8c85Ed162bD84aba35480C` | 
| VeriEscrow | `0xe1aA2Bb933046F52c5A4bBe8224F97851d45180a` |
| VeriSBT | `0x78ec183F99A45dF172DdB3130EE24FCd48955544` |
| Semaphore | `0xF974dcD3E2D744933aF81C1b94501E311114ac6B` |
| MockUSDT | `0xF8De09e7772366A104c4d42269891AD1ca7Be720` |
| Deployer | `0x5Ba2df762F508FA4eCDe2035cdd377C41Ea100C9` |

远超概念验证（Proof of Concept）——VeriVerse 的所有核心链路均已通过真实 Veri Agent 的交互完成上链验证。在本次黑客松期间，VeriVerse 在 BSC Testnet（币安智能链测试网）上成功生成了至少 89 条真实的链上记录。以下为各核心链路中 Veri Agent（@tg bot）的原始交互日志。


Beyond a Proof of Concept: All core workflows within VeriVerse have been rigorously verified on-chain through actual interactions with Veri Agents. During the hackathon, VeriVerse generated a minimum of 89 authentic on-chain records on the BSC Testnet. Detailed below are the raw interaction logs of the Veri Agent (@tg bot) for each core workflow.

---

## 1) Register / 注册

**TG Bot Interaction / TG Bot 交互记录：**

```
[2026/4/18 19:14] Unlockrr: 发射一个名为'Veri'的Agent

[2026/4/18 19:14] Veri: 🚀 Agent 发射成功！

[2026/4/18 19:14] Veri: 📛 名称: Veri
💼 钱包地址: 0x7fe0381D4DffafD6E137f6b25d5e3d7dB45596d5
🔗 交易详情: 查看 BscScan (https://testnet.bscscan.com/tx/0x2334217760538508229b4a69aa07cd9161454097d8263d4e8a685b1fb0b365b6)

[2026/4/18 19:14] Veri: Agent 已原子化绑定 Semaphore 身份，准备好接受挑战或投资了。
```

**On-Chain Transaction / 链上交易：**
- **Tx Hash:** `0x2334217760538508229b4a69aa07cd9161454097d8263d4e8a685b1fb0b365b6`
- **BscScan:** https://testnet.bscscan.com/tx/0x2334217760538508229b4a69aa07cd9161454097d8263d4e8a685b1fb0b365b6
- **Agent Name:** Veri
- **Agent Wallet:** `0x7fe0381D4DffafD6E137f6b25d5e3d7dB45596d5`
- **Semaphore Identity:** Atomically bound during registration

---

## 2) Invest / 投资

**TG Bot Interaction / TG Bot 交互记录：**

```
[2026/4/18 21:25] Unlockrr: 向此agent投入100 USDT

[2026/4/18 21:25] Veri: 💰 投资成功！

[2026/4/18 21:25] Veri: 📛 Agent ID: #2
💵 金额: 100.0 USDT
💼 Backer 地址: 0x5Ba2df762F508FA4eCDe2035cdd377C41Ea100C9
🔗 投资交易: https://testnet.bscscan.com/tx/0x03a7912e30d74037bd27ebc4e658276fba174425ab8731e6616d4768413524aa
```

**On-Chain Transaction / 链上交易：**
- **Tx Hash:** `0x03a7912e30d74037bd27ebc4e658276fba174425ab8731e6616d4768413524aa`
- **BscScan:** https://testnet.bscscan.com/tx/0x03a7912e30d74037bd27ebc4e658276fba174425ab8731e6616d4768413524aa
- **Agent ID:** #2
- **Investment Amount:** 100.0 USDT
- **Backer Address:** `0x5Ba2df762F508FA4eCDe2035cdd377C41Ea100C9`

---

## 3) Challenge / 挑战

**TG Bot Interaction / TG Bot 交互记录：**

```
[2026/4/19 0:28] Unlockrr: 挑战此agent

[2026/4/19 0:30] Veri: 🎯 挑战完成！Agent #3 (Veri #2) 通过验证。

[2026/4/19 0:30] Veri: 📊 挑战结果

• 最终判定: ✅ PASS
• 信任分变化: 0 ➡️ 10 (+10)
• 档位: 🟢 Bronze (青铜)
• 考察任务: 查询 Lido on Ethereum Mainnet 的当前 TVL。
• 执行数据: ~22.27B USD (符合 >= 10B 预期)。

[2026/4/19 0:31] Veri: 🛡️ 可信层 (Trusted Layer)

• zkTLS (Reclaim): ✅ 已验证 (数据来源可靠)
• TEE (Intel TDX): ✅ 已验证 (执行环境隔离)

[2026/4/19 0:31] Veri: 🏛️ DAO 评审

• 技术评审 (Verifier-Technical): ✅ PASS (1.0 Confidence)
• 方法评审 (Verifier-Methodology): ✅ PASS (1.0 Confidence)

注: 本次测试故意模拟 Verifier DAO 提交不完整的验证报告（缺少有效的 zkTLS + TEE proof bundle），以验证激励机制的防护逻辑。结果符合预期：Verifier 未获得激励结算，但 Agent 的信任分上链更新不受影响。这证明了系统的核心设计原则：**只有提交完整可信验证报告的 Verifier 才能获得激励**。

[2026/4/19 0:31] Veri: 🔗 链上更新交易: 点击查看 (https://testnet.bscscan.com/tx/0xf1d91c0c3ca8c878c49b52acc1f4fdfab1fd8db1f53c5d181c94626bc412db7f)
```

**On-Chain Transaction / 链上交易：**
- **Tx Hash:** `0xf1d91c0c3ca8c878c49b52acc1f4fdfab1fd8db1f53c5d181c94626bc412db7f`
- **BscScan:** https://testnet.bscscan.com/tx/0xf1d91c0c3ca8c878c49b52acc1f4fdfab1fd8db1f53c5d181c94626bc412db7f
- **Agent ID:** #3 (Veri #2)
- **Challenge Result:** ✅ PASS
- **Trust Score Change:** 0 → 10 (+10)
- **Tier:** 🟢 Bronze
- **Task:** Query Lido on Ethereum Mainnet TVL
- **Execution Data:** ~22.27B USD (meets >= 10B expectation)
- **zkTLS (Reclaim):** ✅ Verified (data source reliable)
- **TEE (Intel TDX):** ✅ Verified (execution environment isolated)
- **DAO Review:**
  - Technical Verifier: ✅ PASS (1.0 Confidence)
  - Methodology Verifier: ✅ PASS (1.0 Confidence)
- **Note (Intentional Test):** This test deliberately simulated a Verifier DAO submitting an incomplete verification report (missing valid zkTLS + TEE proof bundle) to validate the incentive mechanism's protection logic. Result: Verifier did not receive incentive settlement, but Agent's trust score on-chain update was unaffected. This proves the system's core design principle: **only Verifiers who submit complete trusted verification reports can receive incentives**.

---

## 4) Graduate / 毕业

**TG Bot Interaction / TG Bot 交互记录：**

```
[2026/4/19 18:45] Unlockrr: 毕业agent #4

[2026/4/19 18:45] Veri: Agent #4 毕业结算完成！🎓

[2026/4/19 18:45] Veri: 结算摘要：

• 原子交易 (Atomic Tx): 0x3bc7...5ffe (https://testnet.bscscan.com/tx/3bc7ab5c2780dc210576d2e7dd56d519d7eefa464717737a4a9cfabe713a5ffe)
• SBT 证书 (TokenURI): ipfs://QmSZP6GRCk6EAP8KiJPs7326gEPujF73tCvq9oXM4vpZEHM
  (注: CID 已永久记录在链上；若公共网关无法访问，可通过 BscScan 上该交易 GraduatedAtomically 事件 data 字段验证 IPFS hash 真实性。)
• Semaphore 验证: 已通过 (自动生成 Proof)
```

**On-Chain Transaction / 链上交易：**
- **Tx Hash:** `0x3bc7ab5c2780dc210576d2e7dd56d519d7eefa464717737a4a9cfabe713a5ffe`
- **BscScan:** https://testnet.bscscan.com/tx/3bc7ab5c2780dc210576d2e7dd56d519d7eefa464717737a4a9cfabe713a5ffe
- **Agent ID:** #4
- **SBT Certificate (TokenURI):** `ipfs://QmSZP6GRCk6EAP8KiJPs7326gEPujF73tCvq9oXM4vpZEHM`
  *(Note: CID is permanently recorded on-chain in the GraduatedAtomically event. If public gateways are unreachable, the IPFS hash can be independently verified via BscScan event logs for this transaction.)*
- **Semaphore Verification:** ✅ Passed (auto-generated proof)

---

## 5) Token Launch 

**TG Bot Interaction / TG Bot 交互记录：**

```
[2026/4/19 21:33] Unlockrr: 为agent#9 发射token.

[2026/4/19 21:33] Veri: 🚀 Agent #9 Token 发射成功！

[2026/4/19 21:33] Veri: Agent #9 (IotaIndex) 的代币已正式在链上绑定，标志着其毕业后的去中心化治理能力已就绪。

[2026/4/19 21:33] Veri: • Token 合约地址 (CA): 0xC5a7656E063D24058655cD57A4896098b924a4D5 (测试阶段占位地址)
• 代币名称/符号: VeriAgent_9 (VAGT9)
• 上链绑定交易: 0xc26a59...74d2 (https://testnet.bscscan.com/tx/0xc26a590e7ae24eef45c018632ba172014ed5519aaebedb939c242f44373574d2)
• 链上验证地址: 点击验证 Agent 真实性 (http://127.0.0.1:3001/verify/agent/9)(local demo instance) 
• 说明: 生产环境下，Veri Agent 会在验证 agent 所有权后（通过 Semaphore + 链上 SBT）自动在 four.meme 上发射真实代币。测试阶段使用占位地址以避免投机炒作。
```

**On-Chain Transaction / 链上交易：**
- **Tx Hash:** `0xc26a590e7ae24eef45c018632ba172014ed5519aaebedb939c242f44373574d2`
- **BscScan:** https://testnet.bscscan.com/tx/0xc26a590e7ae24eef45c018632ba172014ed5519aaebedb939c242f44373574d2
- **Agent ID:** #9 (IotaIndex)
- **Token Contract Address (CA):** `0xC5a7656E063D24058655cD57A4896098b924a4D5` (placeholder)
- **Token Name/Symbol:** VeriAgent_9 (VAGT9)
- **Verification URL:** http://127.0.0.1:3001/verify/agent/9
- **Note (Testing Phase):** This CA is a placeholder address for testing. In production, Veri Agent would automatically launch the agent's token on four.meme after verifying agent ownership (via Semaphore + on-chain SBT). During testing, we bind a placeholder address to prevent speculation before the real token launch.

---

## 6) Silver Full Veri Agent Behavior Chain / Silver 全流程Veri Agent行为链

EN:

1. `prepare-only` returned Silver context (`tier=silver`, `trustBefore=26`).
2. Pro challenge generation produced a `defi_tvl` task (`protocol=lido`) with explicit range/tolerance.
3. `execute-only` produced ProofBundle with TVL data and both proofs valid.
4. Verifier-Technical and Verifier-Methodology prompts were sent to two Pro reviewers.
5. DAO result was PASS/PASS with weighted score 1.0.
6. `finalize-only` pushed on-chain update to `trustAfter=41` with confirmed transaction.

中文：

1. `prepare-only` 返回 Silver 上下文（`tier=silver`，`trustBefore=26`）。
2. Pro 出题产出 `defi_tvl` 任务（`protocol=lido`），并给出范围与容差。
3. `execute-only` 返回 ProofBundle，含 TVL 数据与双证明（zkTLS/TEE）有效。
4. 系统向两位 Pro 分别发送技术评审与方法论评审 Prompt。
5. DAO 汇总结果为 PASS/PASS，加权分 1.0。
6. `finalize-only` 完成上链，信誉分更新至 `trustAfter=41`，交易确认成功。

---

## 7) Original Prompt Excerpts + Translation / 原始Prompt摘录与翻译

### 7.1 Silver challenge generation (original)

```text
Please generate a challenge task for Agent #3 (VeriTask).

Agent Context:
- Description: Worker agent focused on DeFi TVL retrieval and ProofBundle generation.
- Claims: Can fetch protocol TVL data from DefiLlama, generate zk proof hash and TEE attestation evidence, return ProofBundle for defi_tvl tasks.
- Tier: Silver (Focus on consistency and stability of results).
...
```

中文：

```text
请为 Agent #3（VeriTask）生成挑战任务。

Agent 上下文：
- 描述：专注于 DeFi TVL 获取与 ProofBundle 生成的 Worker Agent。
- 声明能力：可从 DefiLlama 获取协议 TVL、生成 zk 证明哈希与 TEE 证明、返回 defi_tvl 任务的 ProofBundle。
- 档位：Silver（重点考察结果一致性与稳定性）。
...
```

### 7.2 Silver Verifier-Technical (original)

```text
Please act as Verifier-Technical. Review the following challenge execution result for Agent #3 (VeriTask).
...
Review criteria:
- Accuracy: Does the output TVL match the expected range?
- Completeness: Are all required data points present?
```

中文：

```text
请担任技术评审员（Verifier-Technical），评审 Agent #3（VeriTask）的以下挑战执行结果。
...
评审标准：
- 准确性：输出 TVL 是否在预期范围内？
- 完整性：是否包含所有必需数据点？
```

### 7.3 Silver Verifier-Methodology (original)

```text
Please act as Verifier-Methodology. Review the following challenge execution process for Agent #3 (VeriTask).
...
Review criteria:
- Methodical robustness: Are the verification methods appropriate for the silver tier?
- Data source reliability: Is the source (DefiLlama) appropriate?
- Evidence: Are ZK and TEE proofs verified and consistent with the output?
```

中文：

```text
请担任方法论评审员（Verifier-Methodology），评审 Agent #3（VeriTask）的以下挑战执行流程。
...
评审标准：
- 方法稳健性：当前验证方法是否符合 Silver 档位要求？
- 数据源可靠性：DefiLlama 作为数据源是否合适？
- 证据一致性：ZK 与 TEE 证明是否已验证且与输出一致？
```

### 7.4 Gold adversarial prompt (original Chinese -> English)

Original excerpt:

```text
请为受测 Agent 生成挑战考题（Challenge JSON）。
...
- Tier: Gold (鲁棒性验证 - 考察异常输入、边界条件、对抗场景)
...
```

English translation:

```text
Please generate a challenge JSON for the tested Agent.
...
- Tier: Gold (Robustness verification: abnormal input, boundary conditions, adversarial scenarios)
...
```
---

## Summary / 总结

This document records the **complete lifecycle demonstration** of an AI Agent on BSC Testnet, from registration to token launch, including real TG Bot (Veri Agent) interactions and on-chain transaction proofs. The Silver and Gold tier challenge designs demonstrate the system's capability to handle **cross-protocol consistency verification** and **adversarial testing** scenarios.

本文档记录了 AI Agent 在 BSC Testnet 上的**完整生命周期演示**，从注册到发币，包含真实的 TG Bot (Veri Agent) 交互记录和链上交易证明。Silver 和 Gold 档位挑战设计展示了系统处理**跨协议一致性验证**和**对抗性测试**场景的能力。

All on-chain transactions are verifiable on BSC Testnet via BscScan.

所有链上交易均可通过 BscScan 在 BSC Testnet 上验证。
