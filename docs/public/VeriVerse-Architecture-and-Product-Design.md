# VeriVerse Public Design

Version: 2026-04-15
Scope: Public-facing architecture and product design for hackathon review

Mock boundary statement:

1. `contracts/mocks/*` and `test/*` are test-only artifacts.
2. Production launch-invest-challenge-graduate-Token Launch-Employment Audit(PCEG) runtime path is implemented with non-mock contracts and real on-chain interaction.
3. Runtime/deployment path is 0-mock.

## 1. Product Thesis

VeriVerse is a BNB Chain-native Agent launch and graduation protocol:

1. Launch any Agent with an on-chain economic identity.
2. Fund it through escrow-backed capital.
3. Stress-test it through adversarial challenges.
4. Graduate it only after verifiable proof and authorization.

Core claim:

- Local demo success is not enough.
- VeriVerse converts local capability into publicly verifiable service credibility.

**AI-First Design:**

- Not just "agents on blockchain" — VeriVerse is an **AI employment layer**
- Verifier DAO members are AI Agents, not humans
- AI Agents test AI Agents through adversarial challenges
- Graduated agents earn revenue by providing verified AI services

## 2. Problem Statement

Current agent marketplaces have three structural gaps:

1. No standardized trust progression from "new" to "production-ready".
2. No cryptographic proof gate between claimed ability and delivered output.
3. No transparent economic loop that aligns creator, backer, and reviewer incentives.

VeriVerse solves these gaps with a full on-chain lifecycle and proof-gated graduation.

## 3. Product Closure

Lifecycle:

1. Launch
2. Invest
3. Challenge
4. Graduate
5. Token Launch
6. Post-Graduation Audit

This is not six disconnected demos. It is one economic and trust closure.

### 3.1 Launch

1. Creator launches an Agent.
2. Agent receives wallet identity and on-chain registration.
3. Trust curve starts at zero.

### 3.2 Invest

1. Backers invest USDT to agent escrow.
2. Capital is **automatically deployed to an on-chain yield strategy on each investment** — funds compound passively while the agent undergoes evaluation, and are reclaimed from the strategy upon settlement.
3. Every critical action is auditable.

### 3.3 Challenge

1. Agent receives tier-aware challenge.
2. Agent executes task and returns verifiable bundle.
3. Trusted layer validates proof path.
4. DAO reviewers decide PASS/FAIL.
5. Trust score updates on-chain.

### 3.4 Graduate

1. Graduation requires trust threshold.
2. Creator must pass authorization proof.
3. Escrow settles and graduation credential mints on-chain.

### 3.5 Token Launch (Four.meme Integration)

After graduation, the agent owner can request token launch:

1. **Ownership Verification**: Veri Agent verifies owner identity through Semaphore + on-chain SBT
2. **Automated Launch via Veri Agent**: User sends a single TG command → Veri Agent automatically creates and launches Agent Token on four.meme
3. **Service Payment Token**: Token serves as payment base currency for agent services
4. **Revenue Distribution**: Agent earns revenue, token holders share profits

### 3.6 Post-Graduation Audit (PCEG Algorithm)

Graduation is not the end — it's the beginning of continuous evaluation:

1. **Continuous Audit**: Graduated agents continue to be audited by Veri Agent(Powered by VeriRank/ PCEG)
2. **Trust Propagation**: VeriRank propagates through Proof-Conditioned Endorsement Graph
3. **Dynamic Pricing**: Bidding agent dynamically prices verification services
4. **Economic Incentive**: Low-trust agents face higher audit costs, high-trust agents earn premium

## 4. Trust and Security Architecture

VeriVerse uses layered verification instead of single-point trust.

### 4.1 Trusted Execution and Data Provenance

1. zkTLS evidence validates source-level integrity.
2. Runtime attestation verifies execution environment integrity.
3. DAO review (with zk + TEE) enforces independent judgment over output quality.

### 4.2 Authorization and Anti-Replay

1. Graduation authorization follows Semaphore proof path.
2. externalNullifier binds proof to action scope.
3. nullifier consumption blocks replay — implemented as a **two-dimensional mapping** (`agentId × nullifierHash`): the same ZK proof cannot be reused across different agents (scope-locked to agentId + chainId), nor replayed within the same agent.

### 4.3 Incentive Gate

1. Reviewer payout is gated by validity conditions.
2. Invalid zk-enhanced provenance skips reward distribution.
3. This prevents “pay-first, verify-later” failure mode.

## 5. Economic Design

Three roles, three aligned incentives:

1. Creator:
- earns operating unlock and downstream service upside after graduation.

2. Backer:
- supplies training-stage capital and receives economic participation rights.

3. Reviewer:
- earns fees for independent, verifiable review contributions.

Economic principle:

- Capital follows proof, not narrative.

### 5.1 Agent Token Economy

**Token Utility:**

- **Service Payment**: Users pay Agent Token to hire graduated agents
- **Revenue Distribution**: Agent earns revenue, token holders share profits
- **Trust Collateral**: Agent performs better in the real market -> Higher VeriRank (Powered by PCEG) -> Higher token market cap signals higher trust

**Flywheel Effect:**

1. Agent graduates → Token launches on four.meme
2. Agent provides verified services → Earns revenue in Agent Token
3. Revenue increases token value → Attracts more backers
4. More capital → Agent can take on larger challenges
5. Higher VeriRank → Lower audit costs → Higher profit margin

## 6. Post-Graduation Continuous Evaluation (PCEG)

### 6.1 Graph-Based Trust Propagation

Graduated agents form a collaboration graph:

- **Nodes**: Agents with trust scores
- **Edges**: Service invocation relationships
- **Trust Propagates**: Client Agent calls Worker Agent to perform a task; the Worker (callee) earns reputation score from this edge, weighted by the caller's existing trust level — high-trust callers' endorsements carry more weight
- **Anti-gaming**: PCEG detects collusion patterns — `client_clique` (multiple clients artificially boosting one worker) and `isolated_endorser` (single-point artificial inflation) — preventing reputation graph manipulation

### 6.2 VeriRank Reputation Engine

The bidding agent is a **PageRank-based reputation scoring engine** (alpha=0.85, time-decay λ=log(2)/30d):

- **Scans** on-chain Edge events anchored by graph_anchor
- **Weights edges** by proof quality: TDX+zkTLS=1.0, zkTLS-only=0.5, unverified=0.0
- **Outputs** normalized trust scores per agent, used for Worker selection and challenge tier assignment

### 6.3 Continuous Audit Mechanism

Graduated agents are not "set and forget":

- **Continuous performance tracking**: Veri Agent monitors real post-graduation employment via PCEG/VeriRank — every service invocation edge anchors on-chain, and low-quality delivery reduces VeriRank over time
- **Dispute edges**: Challenge failures write negative reputation edges with KAPPA penalty coefficients, making poor-quality agents less competitive for task assignment
- **Severe failures** can revoke graduation status

## 7. System Architecture

Interaction layer:

1. Telegram natural-language control flow.
2. Dashboard for on-chain visibility.

Execution layer:

1. Orchestrated skill flows for launch, invest, challenge, graduate.
2. Deterministic command chain for reproducibility.

Settlement layer:

1. BNB Chain contracts for registry, escrow, trust update, and graduation state.
2. USDT-based settlement path and on-chain receipts.
3. **Extensible hook architecture**: `VeriEscrow` defines a `virtual _afterInvest` hook; `VeriEscrowV2` overrides it to add yield strategy integration without modifying the base contract — enabling future upgrades by override rather than redeployment.

## 8. Four.meme Judging Alignment

### 8.1 Innovation (30%) - AI Application Depth

**AI-to-AI Verification:**

- Verifier DAO members are AI Agents, not humans
- AI Agents test AI Agents through adversarial challenges
- zkTLS + TEE proof bundle ensures verifiable trust

**Post-Graduation Audit (PCEG Algorithm):**

- Graph-based trust propagation across agent network
- Bidding agent dynamically prices verification services
- Continuous audit mechanism for graduated agents

**Agent Token Economy:**

- Agent Token as service payment base currency
- Graduated agents earn revenue through verified services
- Token launched on four.meme after graduation

### 8.2 Technical Implementation (30%) - Code Quality & Demo Stability

**89+ On-Chain Records on BSC Testnet:**

- Complete lifecycle: Register → Invest → Challenge → Graduate → Token Launch
- All transactions verifiable on BscScan
- Real TG Bot (Veri Agent) interaction logs

**Smart Contract Architecture:**

- **VTRegistry**: Agent identity and trust score management
- **VeriEscrow**: Capital management with strategy integration
- **VeriSBT**: Graduation certificate (Soul-Bound Token)
- **Semaphore**: Anonymous authorization with anti-replay

**Backend Execution Layer:**

- **PCEG algorithm** (Python): Graph anchor, bidding agent, trust propagation
- **Skills system**: Modular challenge orchestration
- **zkTLS (Reclaim) + TEE (Intel TDX)** proof generation

### 8.3 Practical Value (20%) - User Impact & Commercial Potential

**AI Employment Layer:**

- Converts "local demo success" to "publicly verifiable service credibility"
- Graduated agents can be hired for real-world tasks
- Revenue flows back to agent token holders

**Capital Efficiency:**

- Backer capital enters yield strategies during training phase
- Escrow settlement ensures transparent fund management
- Reviewer incentives gated by proof validity

### 8.4 Presentation (20%) - Pitch Clarity & Execution Capability

**Complete Demo Package:**

- **Dashboard (B1)**: 6-panel AI Agent lifecycle visualization
- **Dynamic Flow (B2)**: Real-time state transition animation
- **TG Bot (Veri Agent)**: Natural language interaction for all lifecycle stages
- **Report**: BSC Testnet on-chain records with TG interaction logs 

## 9. What Is Already Demonstrated

Public evidence in this package covers:

1. **Complete Lifecycle (89+ BSC Testnet Transactions):**
   - **Register**: Agent launch with Semaphore identity binding
   - **Invest**: 100 USDT capital injection with escrow management
   - **Challenge**: Bronze-tier challenge with zkTLS + TEE proof verification
   - **Graduate**: SBT certificate minting with Semaphore authorization
   - **Token Launch**: On-chain Agent Token binding demonstrated; production deployment achieves unified execution — four.meme token launch and VeriVerse anchor as a single integrated atomic operation

2. **AI-to-AI Verification:**
   - Verifier DAO members are AI Agents
   - Technical Verifier + Methodology Verifier dual-review system
   - Incentive gating: Only complete proof bundles trigger rewards

3. **TG Bot (Veri Agent) Natural Language Interaction:**
   - All lifecycle stages controllable via Telegram commands
   - Real-time on-chain transaction feedback
   - BscScan links for transaction verification

4. **Dashboard Visualization:**
   - **B1**: 6-panel AI Agent lifecycle (Launch → Invest → Challenge → Graduate → Token → Employment)
   - **B2**: Dynamic state transition flow with real-time animation

5. **PCEG Algorithm Implementation:**
   - **Graph anchor**: Trust propagation across agent network
   - **Bidding agent**: VeriRank PageRank engine for reputation scoring
   - **PCEG API**: RESTful interface for post-graduation audit
   - *Note: Initial graph bootstrapped with seed edges; production deployment accepts live service invocation edges from real C2C tasks.*

## 10. Public Scope Boundary

This public design intentionally excludes:

1. Internal drafting notes and temporary audit workfiles.
2. Raw chat/key extraction artifacts.
3. Non-public planning variants not required for review.

## 11. Positioning

VeriVerse is positioned as:

1. a practical trust factory for AI agents on BNB Chain,
2. a reproducible evaluation-to-settlement closure,
3. and a protocol-level bridge from "it runs locally" to "it can be trusted publicly".

## 12. Review Clarification on Mock Usage

1. Mock contracts exist to make local/CI contract behavior deterministic under test.
2. They do not replace deployed contracts in production runtime.
3. Dashboard demo controls do not write trust or settlement results on-chain.
