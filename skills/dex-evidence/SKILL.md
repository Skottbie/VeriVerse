---
name: dex-evidence
description: >
  M4 路由证据层。通过 PancakeSwap V3 QuoterV2 提取 swap quote 路由来源与 DEX 命中证据，不执行真实换币。
  触发词：DEX 证据、route evidence、路由来源、PancakeSwap 报价证据。
license: MIT
metadata:
  author: VeriVerse
  version: "2.0.0"
  openclaw:
    requires:
      bins: ["python3"]
      env: []
---

# SKILL: dex-evidence

角色：评审证据层（M4）。

## Command

```bash
python3 {baseDir}/dex_evidence.py \
  --from-token <FROM_TOKEN_ADDRESS> \
  --to-token <TO_TOKEN_ADDRESS> \
  --amount <MINIMAL_UNITS> \
  --chain bsc \
  --json
```

输出要点：
- routeEvidence.routeSources: 报价里识别到的路由来源列表
- routeEvidence.containsDex: 是否命中已知 DEX (PancakeSwap/Uniswap)
- routeEvidence.dexMatches: 命中的 DEX 来源名称
- routeEvidence.quoteSummary: 报价关键摘要（toTokenAmount/gasEstimate）

约束：
- 本技能只做 quote 证据提取，不做 approve/swap/broadcast。
- 任何真实换币执行请走既有的 Step 0c 流程。
