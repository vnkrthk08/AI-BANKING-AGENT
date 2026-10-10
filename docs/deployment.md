# KURAL AVA — Deployment & Operations Runbook

## 1. Components
| Process | Command | Notes |
|---|---|---|
| API | `uvicorn app.main:app` | Stateless; scale horizontally. `KURAL_RUN_WORKERS=false` in production. |
| Workers | `python -m kural.workers` | Outbox → notifications, e-mail/SMS delivery, SLA monitor, callback executor, campaign dialer. All claims are leased in the database, so several replicas and restarts are safe. |
| Web | nginx serving `frontend/dist` | Proxies `/api` (including WebSockets) to the API. |
| PostgreSQL 16 | — | Production database. SQLite is for local development and tests only (production startup refuses SQLite). |

## 2. Local development
```bash
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev,postgres]"
cp .env.example .env            # leave DATABASE_URL=sqlite:///./kural_local.db for quick local work
KURAL_NEW_USER_PASSWORD='choose-a-strong-pass' python -m kural.cli create-user \
    --username ops1 --role OPS_MANAGER --email ops1@bank.local --full-name "Ops One"
KURAL_NEW_USER_PASSWORD='...' python -m kural.cli create-user --username agent1 --role AGENT \
    --email agent1@bank.local --full-name "Agent One" --agent --languages English,Hindi
uvicorn app.main:app --port 8000          # migrations run automatically outside production
cd frontend && npm ci && npm run dev       # http://localhost:5173
```
No customers, agents, campaigns or calls are seeded. Add customers (Calls hub or `POST /api/customers`, CSV import) before starting a Voice Studio call.

## 3. Production (Docker Compose reference)
```bash
cp .env.example .env   # APP_ENV=production, KURAL_MASTER_KEY, POSTGRES_*, provider credentials
docker compose up -d --build   # postgres -> migrate (alembic upgrade head) -> api + worker -> web:8080
```
Startup **fails closed** in production when: `KURAL_MASTER_KEY` is missing/default/short, `DATABASE_URL` is SQLite, `TELEPHONY_PROVIDER=sandbox`, Exotel is configured without `TELEPHONY_WEBHOOK_TOKEN`, or `KURAL_PUBLIC_BASE_URL` is not HTTPS.

### TLS / reverse proxy
Terminate TLS at the load balancer or an edge nginx (`listen 443 ssl http2`, HSTS), forward to `web:8080`. The refresh cookie is `__Host-`, `Secure`, `HttpOnly`, `SameSite=Strict` — the UI must be served over HTTPS (or `localhost` during development). WebSocket upgrade headers must be forwarded for `/api/v1/voice/realtime` and `/api/events/*`.

### Health
* `GET /health` — liveness (process + DB reachable).
* `GET /health/ready` — readiness: DB reachable, schema at Alembic head, auth cache synchronised. Returns 503 otherwise.
* `GET /api/system/health` (authenticated) — per-component truth: database/schema, LLM, STT, TTS, telephony, e-mail, SMS, workers, emergency-stop state.
* `GET /metrics` — Prometheus.

## 4. Database
* Migrations: `alembic upgrade head` (release step). Verified bidirectional (`upgrade head → downgrade base → upgrade head`) on PostgreSQL 16 and SQLite.
* Backup: `pg_dump -Fc -d kural > kural-$(date +%F).dump`; restore: `pg_restore -c -d kural kural-YYYY-MM-DD.dump`, then `alembic upgrade head`. Test restores regularly.
* Pool: 60 + 12 overflow per process (see `kural/persistence/database.py`); size PostgreSQL `max_connections` accordingly.

## 5. Runbooks
**Voice not working** — `/api/system/health` → STT/TTS must be `CONFIGURED` (`SARVAM_API_KEY`). The browser shows "Voice service is unavailable" and offers typed chat when the speech provider connection fails; check API logs for `Realtime voice connection failed error_type=…`. Microphone permission is requested by the browser; HTTPS is required outside localhost.

**Callbacks not dialling** — Due callbacks auto-dial only when *all* gates pass: `KURAL_OUTBOUND_AUTODIAL_ENABLED=true`, telephony configured, emergency stop off, customer not DND, inside the calling window (default 09:00–19:00 IST, no Sundays/holidays) and the number on `TELEPHONY_DIAL_ALLOWLIST` outside production. Otherwise the callback becomes **DUE** with the blocking reason in `last_outcome`, and the assigned agent/supervisors are notified to call manually. A callback whose dial outcome was never reported is **reconciled with the provider** after its 10-minute lease expires — never re-dialled blindly.

**Rescheduling** — every reschedule increments `version`; dispatch records the version it dialled. A reschedule while a dial is in progress is rejected (409/422) to avoid overlapping attempts.

**Emergency stop** — Campaigns hub / `POST /api/system/dialing {"stopped": true, "reason": "…"}` (Ops, Supervisor, Compliance, Admin). Resuming requires Ops Manager or Admin. Stop releases queued campaign contacts immediately; it is persisted, so it survives restarts and applies to every worker.

**Notifications** — Delivery log: Governance → Notifications (`GET /api/notifications/deliveries`). Statuses: `DELIVERED` (in-app inbox), `QUEUED`, `SENDING`, `SENT` (accepted by SMTP/SMS gateway — not a handset/inbox receipt), `FAILED` (after bounded exponential retries; retry from the log), `NOT_CONFIGURED`, `SKIPPED` (recipient has no address). Messages created while a channel was unconfigured are not sent retroactively.

**Telephony webhooks** — Exotel status callback URL: `${KURAL_PUBLIC_BASE_URL}/api/v1/telephony/webhooks?token=${TELEPHONY_WEBHOOK_TOKEN}` (set automatically on dial). Duplicates are ignored via `telephony_events.dedupe_key`; late non-terminal events never reopen a completed call.

**Live transfer** — Not available via Exotel's REST API; the API reports `TRANSFER_UNSUPPORTED`. KURAL therefore never tells a customer a human is joining; it raises a case and a callback request instead. Bridging requires an Exotel Connect applet in the call flow (external setup).

## 6. Security notes
* Every `/api` route requires a bearer token and an RBAC permission (`kural/security/rbac.py`). WebSocket/SSE streams use 30-second single-use tickets. `SYSTEM_ADMIN` cannot read customer data, transcripts or recordings.
* Customer phone numbers are masked (`+91 ••••• ••123`) in every API response, export and notification; raw numbers stay inside the dialer.
* Credentials (OTP/PIN/CVV/card/Aadhaar/passwords) are redacted before persistence, logging and LLM calls. Transcripts are not written to logs.
* Recording is off by default (`KURAL_CALL_RECORDING_ENABLED`); enable only with an approved disclosure and retention policy. Recording access is audited.
* Login is throttled (8 failures / 5 min per user+IP). Accounts are provisioned only by `SYSTEM_ADMIN` or the CLI; there are no default passwords.
