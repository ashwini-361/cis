# AGENTS.md — Instructions for AI Coding Agents Working on This Repo

> **Purpose:** Onboarding for any AI agent (opencode, Cursor, Claude Code, etc.) modifying this repository. Every agent must read this file before touching `app/`, `tests/`, `data/`, or `docs/`. Suppress duplicating work, re-deriving plans, or drifting from the established contract.
> **Scope:** Coding conventions, contract hard rules, lint/typecheck commands, and the docs-first culture.

---

## 0. Read These First

In order:

1. [`README.md`](./README.md) — entry point and PDF deliverables map.
2. [`docs/APPROACH.md`](./docs/APPROACH.md) — the multi-signal fusion thesis.
3. [`docs/DATA_CONTRACT.md`](./docs/DATA_CONTRACT.md) — the wire-level schema every analyzer implements.
4. [`docs/SIGNALS.md`](./docs/SIGNALS.md) — per-signal spec for the analyzer you're editing.
5. [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) — system shape and module graph.
6. [`docs/ROADMAP.md`](./docs/ROADMAP.md) — phase plan and do-done criteria.

If you skip the contract doc, you will accidentally break the wire format and CI will catch you. Always re-read the schema in [`docs/DATA_CONTRACT.md`](./docs/DATA_CONTRACT.md) before adding fields.

---

## 1. Project Layout

```
cis/
├── app/                  # Python source (FastAPI app + analyzers + fusion)
├── docs/                 # Documentation set (12 files)
├── data/recordings/      # Mock JSON scenarios + labeled data
├── data/weights/         # `weights.json` + tuning outputs
├── scripts/              # `run_accuracy.py`, `tune.py`
├── tests/                # pytest suites (unit/contract/integration/e2e)
├── web/                  # React dashboard (Vite + TS + Tailwind)
└── keys/                 # gitignored OAuth credentials
```

Modifying docs is allowed and expected when changing the contract; modifying any analyzer requires updating the relevant signal doc in [`docs/SIGNALS.md`](./docs/SIGNALS.md).

---

## 2. Coding Conventions

- **Python ≥ 3.12** with type hints required on every function signature.
- **Pydantic v2** for all wire schemas. Models are `frozen=True` unless explicitly mutable state.
- **`async def`** for everything that does I/O or bus work. Never `time.sleep` in an analyzer — use `asyncio.sleep`. The realtime ticker uses `asyncio.sleep`.
- **snake_case** throughout Python and JSON. Never camelCase.
- **No mutable globals**. Inject everything via constructor (analyzers take `weights: WeightTable` in `initialize()`).
- **Docstrings** on every public class / function: one-line summary + args + return.
- **No comments in code** unless asked — the docs explain *why*; code explains *what*.
- **`ruff`** for linting, **`mypy`** for type-checking. Both run in CI.

### 2.1 Python style example

```python
"""Metadata analyzer: emits name_similarity, email_match, device_name evidence."""
from typing import Iterable
from pydantic import BaseModel
from app.schema import Event, Evidence
from app.analyzers.base import Analyzer


class MetadataAnalyzer(Analyzer):
    """Owns name_similarity (0.15), email_match (0.30), device_name (0.00)."""

    def __init__(self) -> None:
        self.candidate_name: str | None = None
        self.candidate_email: str | None = None

    @property
    def feature(self) -> str:
        return "name_similarity"   # primary feature; secondary emitted as different features

    @property
    def source(self) -> str:
        return "metadata_analyzer"

    def initialize(self, weights, session) -> None:
        # read metadata on SESSION_START
        ...

    async def on_event(self, event: Event) -> list[Evidence]:
        ...
```

### 2.2 React / TypeScript style
- **TypeScript strict mode** in `web/tsconfig.json`.
- Functional components only.
- Tailwind utility classes; no styled-components.
- Recharts for the timeline.
- WebSocket hook in `src/useVerdictStream.ts` — single source of truth.

---

## 3. Hard Contract Rules (Must Not Violate)

Re-stated from [`docs/DATA_CONTRACT.md §3.4 and §8.1`](./docs/DATA_CONTRACT.md). CI enforces via `tests/test_contract.py`.

1. **No analyzer imports another analyzer.** Communication is via the event bus only.
2. **One feature per analyzer.** Two analyzers sharing a feature key → contract test fails.
3. **Analyzers are idempotent** on event re-runs with same `envelope.sequence`.
4. **Analyzers are deterministic** for a given input sequence (seed any RNGs).
5. **Evidence.score ∈ [0.0, 1.0]**. Out-of-range → instant test failure.
6. **Evidence.weight must equal** the value in `weights.json` for that feature at init time.
7. **Evidence.reason is non-empty** and ≤ 240 chars.
8. **Evidence.ts is monotonic** per `(source, participant_id)`.
9. **Evidence.expires_at > Evidence.ts** if set; sticky (`None`) only for signals explicitly marked sticky in `docs/SIGNALS.md`.
10. **Evidence.raw_payload must NOT be persisted** — drop before writing to Postgres.
11. **No `time.time()` calls in analyzers** — use `event.envelope.ts` only. Mock replay fidelity depends on this.
12. **No analyzer mutates `ParticipantState`** — the realtime ticker owns state.

---

## 4. Lint, Typecheck, Test Commands

Before pushing always run:

```powershell
# Python
uv run ruff check .
uv run mypy app/
uv run pytest -v --cov=app --cov-report=term-missing

# TypeScript (web/)
cd web
npm run lint       # biome or eslint depending on web/eslint.config.js
npm run typecheck  # tsc --noEmit
npm run build      # ensures donut still bundles
cd ..

# Specifically the contract tests
uv run pytest tests/test_contract.py -v
```

If any of those fail, fix BEFORE commit. No `--no-verify` pushes.

---

## 5. Working Through a Feature Request — Standard Workflow

When asked to add a feature or fix a bug:

1. **Re-read the relevant doc** in [`docs/`](./docs/) first. If the doc says the system does X and the user asks for not-X, you should clarify with the user before proceeding.
2. **Update the doc** if the contract changes. The doc IS the spec; the code follows.
3. **Add or modify the analyzer** per the per-signal spec.
4. **Add or modify tests** — every public function has at least one test.
5. **Run the lint + typecheck + tests** per §4.
6. **Update [`docs/CHANGELOG.md`](./docs/) (create on first change)** with the user-visible delta.
7. **Commit** only when explicitly asked by the user. The repo's git config is not set up; ask first.

---

## 6. Common Anti-Patterns Agents Tend Toward — DO NOT

| Anti-pattern | Why it breaks |
|---|---|
| Adding a hardcoded weight to an analyzer instead of reading from `weights.json` | The fusion engine reads `weights.json`; analyzer-supplied weights are display-only in `Evidence.weight`. |
| Putting `await asyncio.sleep(5)` inside an analyzer's `on_event` | Blocks the bus. Use `on_tick` for periodic work. |
| Storing audio bytes to Postgres | Privacy violation — see [`docs/PLATFORM_INTEGRATION.md §5`](./docs/PLATFORM_INTEGRATION.md). |
| Importing `transcript_role_analyzer` from `metadata_analyzer` to "share logic" | Contract violation — §3.1 above. |
| Modifying `app/schema.py` without bumping schema version | Breaks persisted verdicts in Postgres. |
| Changing default weights without running `scripts/run_accuracy.py` first | Regression goes unnoticed. |
| Emitting `Evidence.reason` longer than 240 chars | Dashboard rendering breaks. |
| Treating mock recordings as authoritative ground truth for generalization claims | Real-platform demos are existence proofs only — see [`docs/EVALUATION.md §7.1`](./docs/EVALUATION.md). |
| Adding a new analyzer feature without registering it in `weights.json` | `WeightMissingError` at analyzer init → session fails to start. |
| Skipping docs when adding a new analyzer | Downstream contributors won't know how to extend or tune the new signal. |

---

## 7. How to Add a New Signal

Sequential checklist:

1. **Spec it in [`docs/SIGNALS.md`](./docs/SIGNALS.md)** — define `feature`, `source`, weight, sticky/decaying, scoring curve, edge cases, calibration data, false-positive risk. ~80 lines.
2. **Register the weight** in `data/weights/weights.json` (default 0.00 if uncertain).
3. **Create the analyzer class** in `app/analyzers/<name>.py`, subclassing `Analyzer` from `app/analyzers/base.py`.
4. **Wire the analyzer in** `app/main.py`'s session bootstrap.
5. **Write unit tests** in `tests/test_analyzers/test_<name>.py`.
6. **Add a labelled recording scenario** under `data/recordings/` if the signal enables a new kind of edge case.
7. **Update [`docs/MOCK_DATA_FORMAT.md`](./docs/MOCK_DATA_FORMAT.md)** only if you're introducing a new `EventType` or payload field.
8. **Update [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) §3 module graph** if component count changes.
9. **Re-run `scripts/run_accuracy.py`** to verify baseline metrics unchanged or improved.
10. **Update [`README.md`](./README.md)** Docs Index row if a new doc was added at root or `/docs/`.

---

## 8. How to Add a New Platform Adapter

Sequential checklist:

1. **Spec it in [`docs/PLATFORM_INTEGRATION.md`](./docs/PLATFORM_INTEGRATION.md)** — Auth flow, webhook payload → `Event` mapping, per-participant audio capture plan.
2. **Create the adapter class** in `app/ingest/<platform>.py`, subclassing `IngestAdapter` from `app/ingest/base.py`.
3. **Implement `start_session`, `stream_events`, `end_session`**.
4. **Webhook receiver** (if applicable) in `app/api/routes.py` under `/<platform>/webhook`.
5. **HMAC signature verification** test in `tests/test_<platform>_webhook.py` using synthetic test vectors.
6. **Integration test** with mocked OAuth token response (no real platform calls in CI).
7. **Update [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) §3.1 ingest table** to include the new platform.

---

## 9. Git Conventions (When Committing)

The repo is fresh — no commits yet. When commits are made:

- One logical change per commit. Don't mix a new analyzer with a refactor.
- Commit message format: `<type>(<scope>): <subject>` where type ∈ {feat, fix, docs, refactor, test, chore, chore(wc)}.
- Example: `feat(analyzers): add transcript_role analyzer with Qwen provider` — body explains motivation, links to PDF requirement or docs section if relevant.
- Never commit secrets. `.env`, `keys/*.json`, OAuth tokens stay git-ignored.
- Pre-commit hook runs `ruff check`, `mypy app/`, `pytest tests/test_contract.py`. Configure yourself in `.pre-commit-config.yaml`.

---

## 10. CI Pipeline (`.github/workflows/ci.yml`)

On every push and PR:

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      redis: ...
      postgres: ...
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: mypy app/
      - run: pytest -v --cov=app --cov-report=xml
      - uses: codecov/codecov-action@v4
      - run: cd web && npm ci && npm run typecheck && npm run build
```

CI fail blocks merge. Local pre-push equivalent: `scripts/check.ps1` (forwarder to lint + typecheck + tests).

---

## 11. Where to Ask Questions

- **Spec ambiguity** — re-read [`docs/DATA_CONTRACT.md`](./docs/DATA_CONTRACT.md), [`docs/SIGNALS.md`](./docs/SIGNALS.md), [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md).
- **PDF requirements** — original PDF at `../Sherlock Internship Challenge.pdf` (parent folder). Use the PDF Reader MCP `read_pdf` to query text.
- **Production Sherlock system behavior** — not available; treat the PDF as the only source of truth.
- **Test failures** — check the test's docstring; tests are written to enforce the contract docs.

---

## 12. Hard Rule: Don't Surprise the User

- Don't push to `git` unless explicitly asked.
- Don't update `weights.json` default values without running `scripts/run_accuracy.py` and reviewing the result with the user.
- Don't modify the `docs/DATA_CONTRACT.md` schema without bumping the schema version in [`docs/DATA_CONTRACT.md §11`](./docs/DATA_CONTRACT.md).
- Don't enable a disabled-by-default analyzer without first disclosing the reason in a doc update.

---

## 13. Change Log for This File

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-07-09 | Initial AGENTS.md for v1.0 of the cis repo. |
