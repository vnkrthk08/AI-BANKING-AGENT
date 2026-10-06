# Prototype architecture

```text
Customer text
  -> safety screening and sanitization
  -> Gemini intent proposal (no tools, records, or customer identity)
  -> Pydantic validation against KURAL Intent
  -> deterministic KURAL FSM and policy/action allow-list
  -> KURAL-approved response, case/callback, and audit
```

Gemini is the semantic intent-understanding provider. **Gemini does not control KURAL actions.** It receives only the sanitized latest utterance and returns an intent/confidence proposal. It has no tools or database access and cannot create cases, callbacks, state transitions, policy decisions, or customer-facing responses. KURAL owns validation, policy, transitions, approved knowledge, and actions. Sensitive-input screening runs before provider invocation. Timeouts, provider errors, missing configuration, and invalid responses fall back to the deterministic phrase detector; fallback logs contain safe metadata only.

Provider selection uses `LLM_PROVIDER`; this milestone supports `gemini`. `GEMINI_API_KEY` and `GEMINI_MODEL` are read from process environment or the ignored root `.env`. The official `google-genai` SDK is used. To make one real development request explicitly, run `python scripts/gemini_smoke.py`; it is excluded from the automated suite. Automated tests use mocks and do not spend API quota. The mock bank exposes only `customer_ref`, `app_installed`, and `app_version` from synthetic fixtures.

KURAL depends on the domain-level `KuralRepository`/transaction contract. The SQLAlchemy adapter maps sessions, turns, cases, callbacks, and audit events to storage; Alembic owns schema changes. SQLite is the no-service development default and test database. Set `DATABASE_URL` to the PostgreSQL URL in `.env` to use Compose PostgreSQL. Callback rows are recorded but not dispatched to a telephony or human-support system.

