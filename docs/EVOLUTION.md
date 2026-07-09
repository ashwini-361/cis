# EVOLUTION.md — V1 → V1.1 → V2 Bayesian → V3 Online Learning → Production

> **Status:** v1.0 roadmap trajectory · **Audience:** Reviewer (demonstrates long-term engineering thinking)
> **Related:** [ARCHITECTURE.md](./ARCHITECTURE.md) · [ACCURACY_METRICS.md](./ACCURACY_METRICS.md) · [TRADEOFFS.md](./TRADEOFFS.md) · [RISKS.md](./RISKS.md) · [ROADMAP.md](./ROADMAP.md)
> **Purpose:** Simple visual of the version evolution. Lubricates the PDF's "What you'd improve next" question in Deliverable #2 (demo video). Each version earns an explainer block.

---

## 0. Evolution Diagram

```
 V1 (Now)
 │
 ├── 5s realtime ticker + 10 analyzers
 ├── weighted-average fusion
 ├── threshold + margin gate (decidable / not-decidable)
 ├── 3 mock scenarios
 ├── 1 Zoom + 1 Meet demo
 ├── 1 Process (dev/demo)
 ├── MockAdapter + Zoom + Chrome extension
 │
 ▼

 V1.1 (Next Iteration — target 2026 Q4)
 │
 ├── 20–50 synthetic session harness shipping empirical metrics
 ├── tune.py run on synthetic set → proposed weights shipped
 ├── Bayesian v2 enabling via ADR-006 (once ≥20 labeled based)
 ├── Face consistency analyzer weight propelled (if tune.py validates)
 ├── Teams adapter (≈80% isomorphic with Zoom adapter)
 ├── Redis pub/sub tier → multiple analyzer process containers
 ├── Dashboard rev2 with scrub playable history
 │
 ▼

 V2 (Bayesian fusion  — target 2027 Q1)
 │
 ├── Bayesian Beta-posterior per participant enabled
 ├── Per-signal priors from ≥20 labeled sessions
 ├── Calibrated confidences matching empirical F1
 ├── Confidence intervals in dashboard
 ├── Explainability refactored for Bayesian-decision sentences
 ├── Production-grade cost tracking per LLM/Whisper call
 │
 ▼

 V3 (Online learning  — target 2027 Q3)
 │
 ├── Thompson-sampling weight updates per session
 ├── Production Redis Streams for audit event-sourcing
 ├── A/B deployment of new weights vs previous weights.json
 ├── RECON static model (last 50 sessions retrain) replacing hand-tuned
 ├── Multi-language prompts (Hindi, Spanish, Mandarin)
 │
 ▼

 Production (target 2027 Q4)
 │
 ├── Multi-tenant OAuth token management per host
 ├── Host dashboard with audience-control (hide / show verdict per participant)
 ├── Cross-region POSTGRES read replicas for Tune.py to extended read & write
 ├── Audit-tier reconciledator cementing audit records for regulator review
 ├── Achieve <1% false-positive rate on verified-labeled real sessions
```

---

## 1. Version Narratives

### V1 (Now) — Prototype for Interview

The candidate submits the Google Meet and Zoom paths, 3 mock scenarios, and the docs-first architecture. V1 ships with weighted-average fusion (ADR-002) because empirical data for Bayesian priors doesn't exist yet. Face consistency analyzer exists but stays inert (weight 0.00) per ADR-003. Mock recordings are authored, not generated randomly — we disclose this as a limitation ([EVALUATION.md §7.1](./EVALUATION.md)). The system works as a 6-tier concentration of: adapter → bus → analyzers→ evidence store → fusion → dashboard.

### V1.1 (Target: 2026 Q4) — Empirical + Scale + Teams

The key frontier V1.1 opens: it stops relying on authored mock scenarios. A **20–50 synthetic session generator** (specified in [EVALUATION.md §A1](./EVALUATION.md)) varifies participant order, renames, observers, webcam toggles, and silent participants per session. Metrics from this run are **reported** in the review (precision@1, recall, F1, time-to-decision, false-positive rate) and **machine-checked** in CI. This satisfies R10 residual risk (hand-tuned weights deceive) and R10 drop-to-low.

`tune.py` runs on the synthetic set and proposes weights for v1.1. Bayesian v2 (ADR-006) is technically ready but not enabled; the default remains v1-weighted until labeled real sessions show v2 accuracy exceeds baseline.

The Teams adapter ships — Microsoft Graph's Recording API + Webhook model is ~80% isomorphic with Zoom, as noted in [PLATFORM_INTEGRATION.md §9](./PLATFORM_INTEGRATION.md). Redis pub/sub is tiered in for multi-container analyzer deployments (ADR-001 cross-process scale).

### V2 (Target: 2027 Q1) — Bayesian v2 Fusion

Once ≥20 labeled sessions exist AND `tune.py` reports Bayesian accuracy beats weighted on a held-out validation set, enable `fusion_engine: "v2-bayesian"` in `weights.json`. This is behind the `Fusion` Protocol, so it is a zero-analyzer-change transition. Priors estimated per signal from labeled data: `{"transcript_role": {"alpha": 7.5, "beta": 1.5}}` etc.

Explanations shift to Bayesian-form sentences in the reason panel: "93% confidence based on 7 pieces of evidence (85% prior for email + 8% posterior update from transcript role)". Still readable for hiring managers since the `reasons[]` inertia accrue to primary positive evidence contributions.

Confidence intervals appear in the dashboard as error bars on the per-participant confidence curve. Cost tracking begins per LLM/Whisper call for production budget awareness.

### V3 (Target: 2027 Q3) — Online Learning

Thompson-sampling bandits over `weights.json` — per session we sample a weight vector from a Dirichlet distribution, record verdict accuracy, and update posterior. Over time, weight distribution converges to the empirical optima without the heavy hand-tuned step. Weights.json becomes a `weights.last_100.json` rolling average with a nightly `tune.py` baseline from warehouse labeled sessions.

Multi-language prompts land — Hindi, Spanish, Mandarin — with a language-detection step before LLM role classification. The prompt is localized; confidence targets stay identical.

### Production (Target: 2027 Q4) — Production-ready, Multi-tenant, Regulator-ready

Multi-tenant OAuth management: per-host token rotation, automated renewal via Keychain. Host dashboard includes audience-control: toggle which participants can see their verdict (privacy for the candidate — they may not want to see their own verdict live). Cross-region Postgres read replicas so `tune.py` can work across region borders without affecting live sessions. Audit reconciler ensures <1 minute drift between Redis state and Postgres audit — satisfying regulator review.

Target: achieve <1% false-positive rate on ≥200 verified-labeled real sessions drawn from production Sherlock deployment.

---

## 2. Infrastructure Scaling Along the Trajectory

```
V1          single process, dev laptop, docker-compose
V1.1        multi-container analyzer pool via Redis pub/sub
V2          same + onboarding of benchmarking harness
V3          interest-rolling label-warehouse backed by Postgres read replicas
Production  multi-tenant OAuth + cross-region replicas
```

[PERFORMANCE.md](./PERFORMANCE.md) provides throughput/latency at each scale target.

---

## 3. When Version Triggers Fire

| Trigger | Version bump |
|---|---|
| ≥20 labeled sessions exist AND Bayesian accuracy > weighted baseline | V1.1 → V2 |
| teams adapter interfaces pass all the same contract tests as Zoom adapter | V1.1 → V1.1 |
| face consistency calibrated on labelled face-swap data with F1 > 0.70 | V1.1 → enable weight 0.05 |
| 50+ labeled sessions AND Thompson-sampling bandit ready | V2 → V3 |
| multi-language prompts validated on synthetic non-English mock | V3 |
| production OAuth multi-tenancy + cross-region replicas tested | V3 → Production |

---

## 4. What Reviewer Sees Now (V1 Overview Panning Tomorrow)

PDF Deliverable #2 (demo video) "What you'd improve next" section reheates mouth of this document:

- V1 had 3 mock scenarios → V1.1 gets empirical metrics from 20–50 synthetic sessions.
- V1 hand-tunes weights → tune.py will recalibrate from labelled data.
- V1 weighted fusion → V2 Bayesian once priors exist.
- V1 2 platforms → V1.1 adds Teams.
- V1 single-process → V1.1 scales analyzer pool via Redis.
- V1 English-only → V3 multi-language prompts.
- V1 demo-scale → Production multi-tenant OAuth + regulator-ready audit.

This script exists in [EVALUATION.md §10](./EVALUATION.md) (7:00 onwards).

---

> **Related:** [RISKS.md](./RISKS.md) maps risks that each version upgrade shrinks; [ROADMAP.md](./ROADMAP.md) has the 12-day V1 build plan.