# KURAL AVA — Autonomous Banking Voice & Operations Agent

[![CI & Golden Evals](https://github.com/vnkrthk08/AI-BANKING-AGENT/actions/workflows/evals.yml/badge.svg)](https://github.com/vnkrthk08/AI-BANKING-AGENT/actions/workflows/evals.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![React 18](https://img.shields.io/badge/React-18-61DAFB.svg)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178C6.svg)](https://www.typescriptlang.org/)

KURAL (Knowledge-driven Unified Response & Assistance Layer) is an enterprise conversational AI decision engine paired with AVA, an outbound voice banking persona. 

The core architectural invariant is **"AI Understands; Deterministic Rules Decide"**: semantic language models are strictly confined to intent proposal. All conversation state transitions, business actions (support ticket creation, callback scheduling), and spoken responses are governed by a deterministic, mathematically verifiable Finite State Machine (FSM).

---

## Architectural Overview

```
                                  INBOUND CHANNEL
                       (WebRTC / Telephony / WebSocket)
                                      │
                                      ▼
                        ┌───────────────────────────┐
                        │    Streaming STT Layer    │  (Sarvam Saaras / Web Speech)
                        └─────────────┬─────────────┘
                                      │
                                      ▼
                        ┌───────────────────────────┐
                        │  Safety & Privacy Screen  │  Regex & credential filters
                        │ (Zero-Leakage Boundary)   │  Blocks OTP/PIN/CVV before storage or LLM
                        └─────────────┬─────────────┘
                                      │
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
        ┌───────────────────────┐           ┌───────────────────────┐
        │   NLU Intent Engine   │           │ Deterministic Fallback│  Timeout, network,
        │ (Gemini 1.5/Flash)    │           │ (Heuristic Classifier)│  or API failure
        └───────────┬───────────┘           └───────────┬───────────┘
                    │                                   │
                    └─────────────────┬─────────────────┘
                                      │ Intent Proposal & Confidence
                                      ▼
                        ┌───────────────────────────┐
                        │   KURAL Decision Layer    │
                        │ ───────────────────────── │
                        │  • Deterministic FSM      │  Validates allowed transitions
                        │  • Policy Gatekeeper      │  Authorizes transactional actions
                        │  • Approved Fact Store    │  Selects compliant responses
                        └─────────────┬─────────────┘
                                      │
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
        ┌───────────────────────┐           ┌───────────────────────┐
        │  Streaming TTS Layer  │           │ ACID Audit Repository │
        │  (Sarvam Bulbul v3)   │           │ (SQLAlchemy / Postgres│
        └───────────────────────┘           │  Append-Only Log)     │
                                            └───────────────────────┘
```

### Key Architectural Tenets

1. **Decoupled Reasoning & Execution**: Language models never execute tools, mutate database state, or generate arbitrary, unapproved customer-facing text in regulated flows. LLMs propose structured intent classifications; KURAL authorizes actions.
2. **Zero Credential Leakage**: Customer credentials (OTP, PIN, passwords, CVV/CVC) are intercepted by strict regex pre-processors. Credentials are never written to disk, sent to third-party model providers, or reflected in operational dashboards.
3. **Deterministic Fallbacks**: If external API calls exceed configured latency budgets, fail authentication, or return schema violations, the system instantly degrades to a local heuristic classifier without disrupting the active voice session.
4. **Append-Only Immutable Auditing**: Every customer turn, sanitization marker, classification event, state transition, and operational mutation writes an append-only audit record to preserve regulatory compliance and operational trace integrity.

---

## Repository Structure

```
├── app/                  # FastAPI web application, routes, and WebSocket endpoints
│   ├── main.py           # Application factory, middleware, and router bindings
│   └── routers/          # REST & WebSocket route handlers
├── kural/                # Core domain logic and deterministic engine
│   ├── audit/            # Structured audit event definitions and loggers
│   ├── cases/            # Support case domain entities and ticketing models
│   ├── conversation/     # Deterministic FSM engine, intent resolver, and session lifecycle
│   ├── gateway/          # Synthetic bank integration fixtures and isolation layer
│   ├── knowledge/        # Approved response dictionaries and script storage
│   ├── nlu/              # Prompt builders, schemas, and semantic classifiers
│   ├── persistence/      # SQLAlchemy 2.0 repositories, tables, and connection managers
│   ├── policy/           # Safety screening, authorization rules, and action allow-lists
│   ├── privacy/          # PII redactors, transcript sanitizers, and pattern scrubbers
│   ├── providers/        # Vendor-agnostic provider abstractions (Gemini, Sarvam)
│   ├── scheduling/       # Natural language date/time parser and calendar resolver
│   ├── services/         # Domain services (callbacks, ticketing, event bus)
│   └── voice/            # Real-time WebSocket audio orchestrator (PCM / STT / TTS)
├── frontend/             # Enterprise bank operations dashboard (React + TypeScript)
│   ├── src/
│   │   ├── charts/       # Operational analytics and KPI visualization widgets
│   │   ├── components/   # Design system (drawers, tables, filters, audio stage)
│   │   ├── config/       # RBAC permission matrix (Ops, Supervisor, Agent, Auditor)
│   │   ├── hooks/        # Role context and reactive state managers
│   │   ├── pages/        # Views (Live Calls, Escalations, Callbacks, Compliance)
│   │   ├── providers/    # Audio STT/TTS web adapters
│   │   └── services/     # Typed API client and client-side data exporters
├── evals/                # Automated evaluation harness and regression suites
│   ├── golden/           # Golden conversation test scenarios (G-01 to G-10)
│   ├── twists/           # Adversarial perturbations (code-switching, ambient noise, interruptions)
│   ├── leak_scan.py      # Automated credential and PII leakage scanner
│   ├── runner.py         # Multi-turn conversation simulation runner
│   └── run.py            # CI evaluation entry point with pass/fail quality gates
├── docs/                 # Architectural specifications and interface contracts
│   ├── architecture.md   # Detailed runtime flow and security boundaries
│   ├── dashboard-api.md  # Typed OpenAPI contract for operations backend
│   ├── dialogue-flows.md # Complete FSM state transition matrices and scripts
│   ├── product-spec.md   # Persona definitions, operational boundaries, and SLAs
│   └── scope.md          # Technical bounds and regulatory compliance scope
├── migrations/           # Alembic database schema migrations
├── scripts/              # Standalone verification and integration smoke tests
└── tests/                # Pytest unit tests, integration tests, and property checks
```

---

## Technical Specifications

| Dimension | Specification |
|---|---|
| **Backend Runtime** | Python 3.11+ / FastAPI / Pydantic v2 / Uvicorn |
| **Persistence Layer** | SQLAlchemy 2.0 (PostgreSQL / SQLite fallback) / Alembic |
| **NLU & Intent Recognition** | Google Gemini (Structured Schema) + Deterministic Keyword Heuristics |
| **Speech Processing** | Sarvam AI (Saaras STT, Bulbul v3 Streaming TTS) / Web Audio API |
| **Frontend Framework** | React 18 / TypeScript 5.6 / Vite / Tailwind CSS |
| **Quality & Evaluation** | Pytest / Hypothesis (Property Testing) / Multi-Turn Golden Evals |

---

## Configuration

System configuration is driven by standard environment variables (managed via `.env`):

| Variable | Description | Default / Example |
|---|---|---|
| `APP_NAME` | Service identifier | `KURAL AVA` |
| `GEMINI_API_KEY` | Google Gemini API key for intent classification | *(Secret)* |
| `GEMINI_MODEL` | Target Gemini model identifier | `gemini-3.8-flash` |
| `LLM_PROVIDER` | Active LLM adapter (`gemini`, `mock`) | `gemini` |
| `SARVAM_API_KEY` | Sarvam AI API subscription key for Indian voice models | *(Secret)* |
| `DATABASE_URL` | SQLAlchemy connection string | `postgresql+psycopg://...` / `sqlite:///kural_local.db` |

---

## Quality Assurance & Verification

The repository enforces automated validation across multiple testing layers:

### 1. Deterministic Unit & Property Tests
Comprehensive unit tests verify state machine immutability, PII masking, authorization logic, and persistence invariants:
```bash
pytest tests/ -v
```
*Includes property-based testing via `hypothesis` to fuzz boundary inputs against credential redaction engines.*

### 2. Multi-Turn Golden Conversation Evals
The evaluation framework simulates multi-turn customer calls against standardized golden test scenarios (`evals/golden/*.yaml`):
```bash
python -m evals.run --suite golden --gate
```
Gating criteria enforce:
- 100% call completion without invalid state traps
- $\ge 95\%$ intent classification precision
- 0 unapproved or hallucinated statements
- 0 credential / sensitive data leaks

### 3. Credential & Secret Leakage Audits
An automated scanner inspects session transcripts and audit events to guarantee zero raw credentials (OTP, PIN, passwords, account numbers) exist in storage:
```bash
python -m evals.leak_scan --from-run latest
```

---

## Detailed Documentation

Comprehensive architectural and domain specifications are cataloged in the [`docs/`](docs/) directory:

- [System Architecture & Security Boundaries](docs/architecture.md)
- [Dialogue Flows & State Machine Specifications](docs/dialogue-flows.md)
- [Product Specifications & Operational Scope](docs/product-spec.md)
- [Operations Dashboard API Contract](docs/dashboard-api.md)
- [Technical Scope & Regulatory Boundaries](docs/scope.md)

---

## License

Internal Enterprise Banking Prototype. All rights reserved.
