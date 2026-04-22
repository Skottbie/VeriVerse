# VeriVerse Product Closure Mermaid Pack (2026-04-15)

This version is written in user-facing language with ecosystem terms only.

Contains:
1. Launch Closure
2. Invest Closure
3. Challenge Closure
4. Graduate Closure
5. Overall Product Closure

---

## 1) Launch Closure

```mermaid
flowchart TD
    U[User asks: Launch a new Agent] --> VA[Veri Agent starts launch flow]
    VA --> W1[Create an Agentic Wallet on X Layer]
    W1 --> W2[Assign on-chain identity to the new Agent]
    W2 --> R1[Register Agent in VeriVerse Registry]
    R1 --> T1[Initialize trust curve at zero]
    T1 --> A1[Bind creator anonymous graduation credential]
    A1 --> P1[Store Agent profile and capability claims]
    P1 --> OUT[Return Agent ID, wallet address, and explorer link]
```

---

## 2) Invest Closure

```mermaid
flowchart TD
    U[User asks: Invest in Agent #X] --> VA[Veri Agent starts invest flow]
    VA --> B1[Check wallet balance and asset composition]
    B1 --> B2{Enough USDT?}
    B2 -- No --> S1[Offer smart route conversion to USDT]
    S1 --> S2[Show route evidence and risk checks]
    S2 --> C1[User confirms conversion]
    C1 --> D1[Complete conversion]
    D1 --> E1[Deposit USDT into Agent Escrow]

    B2 -- Yes --> E1

    E1 --> G1[Apply transaction security and simulation gates]
    G1 --> Y1[Idle capital enters Aave strategy pool]
    Y1 --> L1[Write audit trail and return on-chain receipt]
    L1 --> OUT[Investment closure complete]
```

---

## 3) Challenge Closure

```mermaid
flowchart TD
    U[User asks: Challenge Agent #X] --> VA[Veri Agent starts challenge flow]
    VA --> FEE[Check challenge fee readiness]
    FEE --> READY{Fee ready?}
    READY -- No --> SWAP[Guide conversion path and retry precheck]
    SWAP --> FEE
    READY -- Yes --> CONTEXT[Read Agent claims and current trust tier]

    CONTEXT --> EXAM[Pro reviewer designs tier-aware challenge]
    EXAM --> EXEC[Agent executes task in trusted runtime]
    EXEC --> PROOF[Generate verifiable result bundle]
    PROOF --> TRUST[Trusted layer verifies zkTLS and runtime evidence]

    TRUST --> DAO[Independent DAO reviewers score PASS or FAIL]
    DAO --> PCHK[Check reviewer provenance integrity]
    PCHK --> DECIDE[Finalize verdict and trust delta]
    DECIDE --> CHAIN[Update trust on X Layer]

    CHAIN --> PAY{DAO Trusted valid and provenance valid(zk-enhanced)?}
    PAY -- Yes --> X402[Distribute x402 rewards to reviewers]
    PAY -- No --> SKIP[Skip rewards and log reason]

    X402 --> OUT[Challenge closure complete]
    SKIP --> OUT
```

---

## 4) Graduate Closure

```mermaid
flowchart TD
    U[Creator asks: Graduate Agent #X] --> VA[Veri Agent starts graduation flow]
    VA --> T1[Check trust score threshold]
    T1 --> T2{Trust >= graduation line?}
    T2 -- No --> STOP[Keep training through more challenges]
    T2 -- Yes --> AUTH[Creator submits Semaphore authorization proof]

    AUTH --> G1[Verify scope, anti-replay nullifier, and proof integrity]
    G1 --> META[Prepare graduation credential metadata]
    META --> SETTLE[Settle escrow and unlock operating capital]
    SETTLE --> AAVE[Recall Aave strategy liquidity when needed]
    AAVE --> MINT[Mint soulbound graduation credential]
    MINT --> STATE[Set Agent status to Graduated on-chain]
    STATE --> OUT[Graduation closure complete with explorer receipts]
```

---

## 5) Overall Product Closure

```mermaid
flowchart LR
    L[Launch Closure] --> I[Invest Closure]
    I --> C[Challenge Closure]
    C --> LOOP{Trust reached graduation line?}
    LOOP -- No --> C
    LOOP -- Yes --> G[Graduate Closure]

    subgraph Ecosystem Highlights
      E1[X Layer on-chain registry and settlement]
      E2[OnchainOS transaction rails and security gates]
      E3[Aave capital efficiency loop]
      E4[x402 reviewer incentive loop]
      E5[Semaphore anonymous creator authorization]
      E6[Soulbound graduation credential]
    end

    L --> E1
    I --> E2
    I --> E3
    C --> E2
    C --> E4
    G --> E5
    G --> E6
```

---

## Showcase Framing

1. Product-level story:
   Launch trusted agents, fund their growth, test their real capability, then graduate them on-chain.
2. Economic story:
   Capital supports agents through escrow and strategy yield, then unlocks for real operations.
3. Trust story:
   Each challenge updates a public trust curve, and reviewer rewards are gate-protected.
4. Identity story:
   Graduation is creator-authorized with privacy-preserving proof and anti-replay safety.
