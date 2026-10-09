# AGENTS.md — Repository Engineering Rules & Operational Guidelines

This document establishes the permanent engineering invariants, operational standards, and safety boundaries for all human developers and autonomous AI coding agents working on the **KURAL AVA** codebase.

---

## 1. Core Architectural Invariants & Phase Boundaries

1. **Deterministic Authority Principle ("AI Understands; Deterministic Rules Decide"):**
   - The KURAL Finite State Machine (FSM) is the **sole authority** for conversation state transitions, business actions (ticket escalation, callback scheduling), policy validation, and spoken responses.
   - Large Language Models (LLMs) operate strictly as an intelligence/NLU layer for intent proposal and entity extraction. The LLM must **never** directly invoke tools, mutate database state, execute code, or generate unapproved conversational turns in regulated banking workflows.
2. **Preservation of Accepted Phase 1–3 Baselines:**
   - **Phase 1 (Voice & Streaming Baseline):** Real-time WebSocket audio orchestration, Sarvam Saaras STT, Bulbul v3 TTS, Web Audio streaming, and sub-1.5s latency budgets must remain intact. Do not replace providers or install alternative media frameworks (e.g., Pipecat) without explicit architectural authorization.
   - **Phase 2 (Context, Grounding & Safety):** Context-aware multi-turn dialogues, closed-world knowledge grounding (demo banking data only; no fabricated regulatory claims), regex credential interception, and multi-provider LLM abstractions must remain protected.
   - **Phase 3 (Bank Operations & Telephony Automation):** Relational persistence, Alembic migrations, customer management, campaign pacing, callback scheduling, role-based dashboard workflows, and CSV import/export sanitization must remain protected.
3. **Phase 4 Implementation Gate:**
   - **No Phase 4 implementation without explicit architecture approval.**
   - All Phase 4 specifications in `docs/phase4_architecture_specification.md` are **DESIGN-ONLY**.
   - Agents must not write Phase 4 code, introduce external authentication providers, deploy Redis/Kafka/Celery, alter database schemas, or modify production telephony interfaces until a formal Phase 4 implementation phase is explicitly initiated by the user.

---

## 2. Git Safety, Release-Tag Protection & Commit Discipline

1. **Immutable Release Tags:**
   - Release tags (`phase1-accepted-frozen`, `phase2-accepted-frozen`, `v0.2.0`, `phase3-accepted-frozen`, `v0.3.0`) are permanent milestone anchors.
   - **NEVER** delete, move, recreate, retag, or force-push over existing Git tags.
   - When inspecting tags, always verify peeled commit targets via `git show-ref --tags -d` or `git rev-parse <tag>^{commit}`.
2. **Conventional & Scoped Commits:**
   - Follow standard Conventional Commits format: `feat(...)`, `fix(...)`, `docs(...)`, `chore(...)`, `test(...)`, `refactor(...)`.
   - Keep commits atomic and narrowly focused. Never bundle cleanup patches, documentation edits, and feature implementations into a single mixed commit.
3. **Linear & Clean History:**
   - Maintain a clean linear history on published branches (`main`).
   - Never run destructive rebases or history rewriting (`git push --force`) on shared repository branches.
   - Ensure the working tree is completely clean before and after every operational step.

---

## 3. Mandatory Pre-Commit Diff Review

Before staging or committing any modification, agents **must** perform a thorough line-by-line review of `git diff` and `git diff --cached`:

1. **Verify Change Scope:** Ensure every changed line is directly required for the current task.
2. **Detect Unintended Artifacts:** Check that no debugging statements (`console.log`, `print`), temporary scratch files, or unwanted formatting changes leaked into the diff.
3. **Verify File Targeting:** Stage files explicitly (`git add <path>`) or review the full index before committing with `git add -A`.
4. **Preserve Comments & Formatting:** Maintain existing comments, type annotations, and docstrings unless explicitly instructed to revise them.

---

## 4. File Naming, Directory Organization & Temporary Files

1. **Naming Conventions:**
   - **Python:** Lowercase snake_case for modules, functions, and scripts (`run_phase1_acceptance.py`, `customer_service.py`).
   - **TypeScript / React:** PascalCase for React components and pages (`AgentWorkspacePage.tsx`, `CallDetailDrawer.tsx`); camelCase for hooks, services, and utilities (`dashboardApi.ts`, `useRole.ts`).
   - **Documentation:** Lowercase kebab-case or snake_case with clear markdown extensions (`docs/scenarios_and_dialogues.md`, `docs/architecture.md`).
2. **Directory Placement:**
   - Production FastAPI backend code: `app/` and `kural/`.
   - Production React frontend code: `frontend/src/`.
   - Formal architecture specifications: `docs/`.
   - Automated test suites: `tests/`.
   - Acceptance and diagnostic scripts: `scripts/acceptance/` and `scripts/diagnostics/`.
   - Alembic database migrations: `migrations/versions/`.
3. **Strict Temporary File Exclusion:**
   - Never commit backup files (`*.bak`), temporary caches (`*.tmp`, `*.swp`), or OS metadata (`.DS_Store`, `Thumbs.db`).
   - Never commit local SQLite databases (`*.db`, `*.sqlite`, `kural_local.db`) or local audio storage directories (`storage/`, `artifacts/`).
   - Always ensure root and frontend `.gitignore` files contain active exclusion rules for these patterns.

---

## 5. Secret Handling & Customer Data Protection

1. **Zero-Leakage Boundary:**
   - Intercept and redact sensitive authentication credentials (OTP, PIN, passwords, CVV/CVC, card numbers) **before** storage, before logging, and before sending payloads to LLM providers.
   - Credentials must never be reflected in operational logs, persisted to SQLite/Postgres databases, or surfaced in UI transcripts.
2. **Customer Data Anonymization:**
   - Customer phone numbers must be masked in transit and in UI responses (e.g., `+91 ••••• ••123`).
   - Never log raw customer transcripts, phone numbers, or account details in debug or warning logs. Background workers and orchestrators must log only sanitized identifiers (e.g., `session_id`, `campaign_id`).
3. **Credential & Environment Security:**
   - Never commit API keys (`GEMINI_API_KEY`, `SARVAM_API_KEY`, `GROQ_API_KEY`), database passwords, or `.env` files into source control.
   - Maintain `.env.example` templates with placeholder values and descriptive configuration guidance.

---

## 6. Documentation & Configuration Consistency

1. **Version Synchronization:**
   - All version indicators across the repository must remain strictly synchronized:
     - `pyproject.toml` (`version = "0.3.0"`)
     - `app/main.py` (`FastAPI(version="0.3.0")`)
     - `frontend/package.json` (`"version": "0.3.0"`)
     - `README.md` badges and specification tables
2. **Multi-Provider Transparency:**
   - Keep the LLM provider interface swappable (`LLM_PROVIDER`: `gemini`, `groq`, `openrouter`, `mock`).
   - Accurately document supported model candidates (`gemini-3.8-flash`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`) without hard-coding proprietary vendor locks into KURAL domain logic.
3. **Frontend Live vs. Mock Separation:**
   - Default `frontend/.env.example` to `VITE_DASHBOARD_API_MODE=live`.
   - Live mode must communicate with FastAPI endpoints (`/api/*`) and surface actionable connection errors when the backend is unreachable. Live mode must **never** silently fall back to synthetic mock data, masking backend failures.
   - Mock mode (`VITE_DASHBOARD_API_MODE=mock`) is reserved for standalone offline frontend demonstration.

---

## 7. Testing, Builds, Migrations & Honest Reporting

1. **Mandatory Test Verification:**
   - Every backend modification must be validated with the complete Pytest regression suite:
     ```bash
     pytest tests/ -v
     ```
   - All tests must pass (173/173 baseline).
2. **Mandatory Frontend Build Verification:**
   - Every frontend modification must be validated with the TypeScript compiler and Vite production build:
     ```bash
     npm run build  # in frontend/
     ```
   - Must complete with zero TypeScript type errors and successful asset generation.
3. **Database Migration Verifiability:**
   - Every database schema change must be accompanied by a reproducible Alembic revision script in `migrations/versions/`.
   - Bidirectional migration tests (`upgrade head` -> `downgrade -1` -> `upgrade head`) must pass cleanly.
4. **Transparent & Honest Reporting:**
   - Autonomous agents must report exact test counts, pass/fail counts, execution durations, and warning summaries truthfully.
   - Never suppress errors, skip failed assertions, or fabricate performance metrics.
   - If warnings appear, investigate and resolve them if straightforward (e.g., configuration flags); otherwise, document their exact third-party upstream source.
