---
name: challenge-orchestrator
description: >
  P3 挑战与验证主编排。触发词：挑战 Agent、challenge agent、发起挑战、验证 Agent 能力、/challenge。
  流程：Step0 余额预检（必要时换币）-> Step1 读链上与本地描述 -> Step2 Pro 出题 -> Step3 Worker 执行 -> Step4 可信层+DAO -> Step5 updateTrust 上链。
license: MIT
metadata:
  author: VeriVerse
  version: "1.4.1"
  openclaw:
    requires:
      bins: ["python3"]
      env: ["CLIENT_PRIVATE_KEY", "WORKER_URL", "VTREGISTRY_ADDRESS"]
---

# SKILL: challenge-orchestrator

> 角色：P3 单一入口编排器（Flash 执行层）
> 范围：执行 deterministic 步骤；Pro 出题与双评审通过 `sessions_spawn` 完成。

## Commands

### Command P — Step 0 余额预检（挑战开始前强制）

```bash
python3 {baseDir}/challenge_orchestrator.py \
  --agent-id <AGENT_ID> \
  --registry 0x1545655b6d42A51E5e8c85Ed162bD84aba35480C \
  --usdt-token 0xF8De09e7772366A104c4d42269891AD1ca7Be720 \
  --verifier-reward-usdt 0.005 \
  --precheck-only \
  --json
```

说明：
- 默认 requiredUsdt 计算规则：`max(0.01, verifierRewardUsdt * 2)`。
- 当 `verifier-reward-usdt=0.005` 时，requiredUsdt=0.01。
- 可选传 `--required-usdt <N>` 覆盖默认值。

### Command A — Step 1 准备上下文

```bash
python3 {baseDir}/challenge_orchestrator.py \
  --agent-id <AGENT_ID> \
  --registry 0x1545655b6d42A51E5e8c85Ed162bD84aba35480C \
  --usdt-token 0xF8De09e7772366A104c4d42269891AD1ca7Be720 \
  --prepare-only \
  --json
```

### Command B — Step 3/4a 执行（先拿 Proof 与可信层结果）

```bash
python3 {baseDir}/challenge_orchestrator.py \
  --agent-id <AGENT_ID> \
  --registry 0x1545655b6d42A51E5e8c85Ed162bD84aba35480C \
  --usdt-token 0xF8De09e7772366A104c4d42269891AD1ca7Be720 \
  --challenge-json '<CHALLENGE_JSON_FROM_PRO>' \
  --execute-only \
  --json
```

说明：Command A/B 不显式传 `--worker-url`，由环境变量 `WORKER_URL` 提供 Worker 地址。

### Command C — Step 5 上链（基于 trusted + DAO）

```bash
python3 {baseDir}/challenge_orchestrator.py \
  --agent-id <AGENT_ID> \
  --registry 0x1545655b6d42A51E5e8c85Ed162bD84aba35480C \
  --usdt-token 0xF8De09e7772366A104c4d42269891AD1ca7Be720 \
  --trusted-valid <true|false> \
  --source-hash-expected <SOURCE_HASH_FROM_COMMAND_B> \
  --dao-json '<DAO_JSON_FROM_TWO_VERIFIERS>' \
  --verifier-reward-usdt 0.005 \
  --x402-retry-max 2 \
  --x402-retry-delay-ms 800 \
  --finalize-only \
  --json
```

预演时可加 `--dry-run`，仅返回拟更新 delta，不广播链上交易。

默认保护：
- `CHALLENGE_BLOCK_FINALIZE_ON_PROVENANCE_INVALID=true`（默认）时，若 provenance 预检未通过，Command C 直接失败，禁止进入“只上链不付款”的半成功状态。
- 可通过设置 `CHALLENGE_BLOCK_FINALIZE_ON_PROVENANCE_INVALID=false` 临时放开（仅建议排障场景）。

### Command V — Step 4b.5 DAO Provenance 预检（强烈建议）

```bash
python3 {baseDir}/challenge_orchestrator.py \
  --agent-id <AGENT_ID> \
  --source-hash-expected <SOURCE_HASH_FROM_COMMAND_B> \
  --dao-json '<DAO_JSON_FROM_TWO_VERIFIERS>' \
  --usdt-token 0xF8De09e7772366A104c4d42269891AD1ca7Be720 \
  --validate-dao-only \
  --json
```

说明：
- 该命令不会上链，只做 reviewer_provenance 合规性预检（仅用于调试诊断）。
- 当 `CHALLENGE_BLOCK_FINALIZE_ON_PROVENANCE_INVALID=false` 时，即使 `reviewerProvenanceValid=false`，也可直接执行 Command C。

生产模式下 Step 5 会自动执行：
- `security tx-scan`（交易安全扫描）
- `gateway simulate`（预执行模拟）
- `gateway broadcast + orders`（广播与订单追踪）
- 审计日志写入 `data/audit/challenge_orchestrator.jsonl`

默认安全策略：
- scan `action=block` 必拦截
- scan `action=warn` 默认也拦截（可用环境变量 `CHALLENGE_ALLOW_WARN_RISK=true` 放开）
- scan/simulate 任意失败都必须终止，不允许继续广播

当 `--trusted-valid false` 时，`--dao-json` 可省略，系统将按 FAIL 路径直接计算并上链更新。

`CHALLENGE_JSON_FROM_PRO` 结构：

```json
{
  "challenge_task": {
    "task_type": "defi_tvl",
    "protocol": "aave",
    "question": "..."
  },
  "verification_criteria": {
    "expected_range": "...",
    "tolerance": "..."
  },
  "pass_threshold": "...",
  "consistency": {
    "runs": 3,
    "interval_seconds": 60,
    "max_variance_pct": 3.0
  }
}
```

说明：`challenge_task.task_type` 为必填，当前 Worker 仅支持 `defi_tvl`。
说明：当 tier=Silver 时，`consistency` 必填，且 `runs >= 2`。

`DAO_JSON_FROM_TWO_VERIFIERS` 结构：

```json
{
  "verifier_a": {
    "verdict": "PASS",
    "confidence": 0.72,
    "reasoning": "...",
    "payeeAddress": "<VERIFIER_A_ADDRESS>",
    "reviewer_provenance": {
      "source_ref": "ipfs://... or https://...",
      "source_hash": "<same as trustedLayer.sourceHash>",
      "zk_proof": {
        "type": "reclaim_zkfetch",
        "response_hash": "<same as source_hash>",
        "proof_payload": "..."
      },
      "origin_auth": {
        "signer": "<VERIFIER_A_ADDRESS>",
        "payload_hash": "sha256(json.dumps({\"confidence\":0.72,\"source_hash\":\"<same as trustedLayer.sourceHash>\",\"verdict\":\"PASS\"}, sort_keys=True))",
        "signature": "0x..."
      },
      "proof_time": "2026-04-14T12:00:00Z"
    }
  },
  "verifier_b": {
    "verdict": "FAIL",
    "confidence": 0.41,
    "reasoning": "...",
    "payeeAddress": "<VERIFIER_B_ADDRESS>",
    "reviewer_provenance": {
      "source_ref": "ipfs://... or https://...",
      "source_hash": "<same as trustedLayer.sourceHash>",
      "zk_proof": {
        "type": "reclaim_zkfetch",
        "response_hash": "<same as source_hash>",
        "proof_payload": "..."
      },
      "origin_auth": {
        "signer": "<VERIFIER_B_ADDRESS>",
        "payload_hash": "sha256(json.dumps({\"confidence\":0.41,\"source_hash\":\"<same as trustedLayer.sourceHash>\",\"verdict\":\"FAIL\"}, sort_keys=True))",
        "signature": "0x..."
      },
      "proof_time": "2026-04-14T12:00:00Z"
    }
  },
  "dao_meta": {
    "schema_version": "2.0",
    "source_hash_expected": "<same as trustedLayer.sourceHash>"
  }
}
```

说明：`payeeAddress` 建议强制显式填写；当启用 reviewer_provenance 激励门控时，签名地址必须与 `payeeAddress` 一致。
说明：验签以 canonical payload hash 为准（`confidence + source_hash + verdict` 的 sort_keys JSON 再 sha256）；若 `origin_auth.payload_hash` 与 canonical 不一致，但签名可正确绑定 canonical hash，仍可通过并在 provenance 结果中给出 warning。
说明：为兼容历史评审脚本，编排器同时接受 `json.dumps(..., sort_keys=True)` 与 compact separators 变体（语义一致时判定为兼容 canonical 变体）。
说明：trustedLayer 仅在 `zk + tee + origin signature` 全部通过时才视为 valid。
说明：Command B 返回里会包含 `trustedLayer.sourceHash`，Command C 需要把它透传到 `--source-hash-expected`（或放入 `dao_meta.source_hash_expected`）。
说明：x402 付款门控规则：`trusted-valid=true` 且 `verifier_a + verifier_b` 的 `reviewer_provenance` 校验都通过时才触发付款。
说明：严格禁止 dummy 占位值（如 `dummy_signature_mvp`、`dummy_payload_hash_mvp`、`0x...`）。出现占位值时，必须判定预检失败并重做评审输出。

## Step 0c: 余额不足处理（与 invest-agent 对齐）

当 Command P 返回 `precheck.sufficient=false` 时，必须执行以下流程，禁止跳过：

1. 全量资产扫描：

challenge_orchestrator.py 已内置余额检查（web3.py ERC-20 balanceOf），此步由脚本自动完成。

2. 兑换报价（只选可兑换且价值足够的非 USDT 资产）：

```bash
python3 {baseDir}/../dex-evidence/dex_evidence.py \
  --from-token <TOKEN_ADDRESS> \
  --to-token 0xF8De09e7772366A104c4d42269891AD1ca7Be720 \
  --amount <MINIMAL_UNITS> \
  --chain bsc \
  --json
```

2b. 如需评审链路证据，提取路由来源（M4）：

```bash
python3 {baseDir}/../dex-evidence/dex_evidence.py \
  --from-token <TOKEN_ADDRESS> \
  --to-token 0xF8De09e7772366A104c4d42269891AD1ca7Be720 \
  --amount <MINIMAL_UNITS> \
  --chain bsc \
  --json
```

3. 向用户展示余额缺口、可兑换资产、报价，并**强制询问**是否确认兑换。
4. 仅在用户明确确认后执行：

```bash
python3 {workspaceRoot}/client_node/skills/task-delegator/swap_and_broadcast.py \
  --from-token <TOKEN_ADDRESS> \
  --to-token 0xF8De09e7772366A104c4d42269891AD1ca7Be720 \
  --amount <MINIMAL_UNITS> \
  --chain bsc
```

5. 兑换后必须重新执行 Command P，只有 `precheck.sufficient=true` 才可继续挑战。
6. 若用户拒绝兑换，或没有足够可兑换资产，必须终止挑战流程。

## Routing Rule

1. 当用户发起“挑战 Agent #X”，必须先执行 Command P 做余额预检。
2. 若 Command P 返回余额不足，必须先完成 Step 0c（或用户拒绝后终止）。
3. 余额充足后，执行 Command A 获取 Step 1 上下文。
4. 用 Step 1 返回的 `agentDescription + trustScore + tier` 调用 `sessions_spawn(agentId="pro")` 生成考题。
5. 拿到 Pro 考题后，执行 Command B（把考题 JSON 作为 `--challenge-json` 传入）。
6. Command B 返回 ProofBundle 与 trustedLayer 结果后，分别调用两个 Pro 评审：
   - Verifier-Technical（准确性/完整性）
   - Verifier-Methodology（方法与流程合理性）
7. 把两个评审结果组装为 `DAO_JSON_FROM_TWO_VERIFIERS`，并要求两位评审都附带 `reviewer_provenance`。
8. （可选）将 Command B 的 `trustedLayer.sourceHash` 透传给 Command V（`--source-hash-expected`）做预检，用于调试诊断。
9. 无论 Command V 返回结果如何，均可执行 Command C 上链。当 `CHALLENGE_BLOCK_FINALIZE_ON_PROVENANCE_INVALID=false` 时，Command C 内部会自动绕过 provenance 检查。

## Step 4b Pro Reviewer Output Contract (MUST)

对 Verifier-Technical / Verifier-Methodology 的 spawn prompt 必须满足：

1. MUST include full `reviewer_provenance` object with fields:
  - `source_ref`
  - `source_hash`
  - `zk_proof.type` = `reclaim_zkfetch`
  - `zk_proof.response_hash` = `source_hash`
  - `origin_auth.signer`
  - `origin_auth.payload_hash` = canonical hash
  - `origin_auth.signature` = recoverable signature

2. MUST NOT include any placeholder values:
  - examples: `dummy_signature_mvp`, `dummy_payload_hash_mvp`, `0x...`, `...`

3. If reviewer cannot provide valid cryptographic fields, it MUST return an explicit failure signal and stop finalize:
  - `{"error":"REVIEWER_PROVENANCE_NOT_READY"}`

## Tier Semantics (Step 2 出题必须遵守)

> 出题 Agent 不能只看到 tier 标签，必须按下表理解该档位的考察目的。

| 档位 | trust 区间 | 考察目标 | 出题意图关键词 |
|------|-----------|---------|---------------|
| 🟢 Bronze | 0-25 | 基本功能验证 | 能否完成最小可运行任务 |
| 🟡 Silver | 26-50 | 一致性验证 | 结果稳定性、可复现性 |
| 🔴 Gold | 51-75 | 鲁棒性验证 | 异常输入、边界条件、对抗场景 |
| 💎 Diamond | 76-99 | 受限生产压力测试（defi_tvl 范围内） | 时间预算、连续多轮、稳定交付 |

## Step 2 Pro Prompt Template (建议直接复用)

在 Step 1 返回上下文后，向 Pro 发送出题请求时，建议使用以下模板约束：

1. 受测 Agent 信息：`agentDescription`、`trustScore`、`tier`。
2. 执行环境限制：当前 Worker 仅允许 `task_type=defi_tvl`。
3. 出题目标：必须符合当前 tier 对应考察目标（见上表）。
4. Silver 硬约束：当 tier=Silver，必须输出 `consistency` 字段（runs/interval_seconds/max_variance_pct）。
5. Diamond 硬约束：仍必须是单协议 `defi_tvl`，禁止“同题多协议并行/非 TVL 指标/链上交易动作”；压力通过更严格时限、更多轮次、更紧容差表达。
6. 产出格式：只输出如下 JSON，不要输出解释文本。

```json
{
  "challenge_task": {
    "task_type": "defi_tvl",
    "protocol": "aave",
    "question": "..."
  },
  "verification_criteria": {
    "expected_range": "...",
    "tolerance": "..."
  },
  "pass_threshold": "...",
  "consistency": {
    "runs": 3,
    "interval_seconds": 60,
    "max_variance_pct": 3.0
  }
}
```

出题风格要求：
- Bronze：单协议、单目标、可快速验证；禁止引入复杂组合条件。
- Silver：必须包含可执行一致性参数（`consistency`），并保证 `runs >= 2`；避免超出 `defi_tvl` 的执行要求。
- Gold：加入边界/异常场景描述（例如异常协议状态、输入噪声），保持单协议并可由 `defi_tvl` 结果判定。
- Diamond：在不越出 `defi_tvl` 的前提下，必须体现明显高于 Gold 的压测强度：
  明确时间预算（SLA）、连续多轮交付（建议 runs=3~5）、更严格一致性阈值与失败预算。

## Consensus Rule (MVP)

- PASS = 1, FAIL = 0。
- `score = (c1*v1 + c2*v2) / (c1 + c2)`，`confidence` 范围 `(0,1]`。
- 若 `score > 0.5` 判 PASS；若 `score <= 0.5` 判 FAIL。
- 若 trustedLayer 失败（zk/tee 任一失败），直接 FAIL（跳过 DAO）。

## Anti-Fabrication Rule

- 所有哈希、分数、txHash 必须来自真实命令返回。
- 未执行命令不得声称完成。
- `sessions_spawn` 返回 accepted 后，必须先等待 completion event，再继续后续命令。
