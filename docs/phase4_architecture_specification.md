# AVA Phase 4 Architecture Specification
## Security, Production Hardening & Scale

**Document Version:** 1.0.1  
**Baseline Git Tag:** `phase3-accepted-frozen`  
**Baseline Git Commit:** `59edf51`  
**Status:** Under Design Review (Design-Only Milestone)  
**Target Phase:** Phase 4 Production Hardening  

---

## 1. Executive Summary & Architecture Decisions

Phase 4 hardens the validated AVA prototype into a production-grade, regulatory-compliant banking voice agent. All Phase 4 designs strictly preserve the accepted Phase 3 baseline (`phase3-accepted-frozen`, commit `59edf51`, 173/173 tests passing) and enforce non-negotiable architectural invariants:

1. **Deterministic Authority:** The KURAL Finite State Machine (FSM) remains the sole authority for state transitions, business logic, policy enforcement, and tool dispatching.
2. **LLM as Semantic Layer Only:** The LLM performs intent classification, structured entity extraction, and conversational synthesis within closed-world retrieved contexts. The LLM has zero direct access to databases, cannot issue SQL, and cannot trigger actions without deterministic KURAL validation.
3. **Voice Stack Preservation:** Sarvam Saaras v4 STT and Bulbul v3 TTS remain the primary voice pipeline.
4. **Provider-Agnostic LLM Interface:** The multi-provider contract remains swappable across Qwen 3.8 27B, GPT-OSS 20B, and Gemini 3.6 Flash, with deterministic offline fallbacks.
5. **No Premature Infrastructure:** No vector databases, microservices, or external message brokers (e.g., Kafka, Celery, Redis). Production scale and durability are achieved using PostgreSQL 16, connection pooling, and a transactional outbox pattern.
6. **Simulated Telephony Boundary:** Real PSTN/SIP trunking is strictly deferred to Phase 5. Phase 4 dialers execute within controlled simulation harnesses.

---

## 2. Threat Model & Trust Boundaries

### 2.1 System Trust Boundaries
The AVA architecture defines four distinct trust zones separated by explicit security boundaries:

```
[ UNTRUSTED ZONE ]
   │
   ├── Customer Voice Input (Browser / Microphone PCM)
   ├── Web Operator Browser (HTTP / WebSocket)
   ▼
══════════════════════════════════════════════════════════════════ [ PERIMETER GATEWAY ]
   │  TLS 1.3 Termination, Reverse Proxy, WAF, CORS/Origin Validation, Rate Limiter
   ▼
[ DEMILITARIZED ZONE (DMZ) / APPLICATION WORKERS ]
   │
   ├── FastAPI Ingestion & REST Endpoints
   ├── WebSocket Voice Orchestrator (PCM Ingestion)
   ├── Pre-LLM / Pre-Log PII Tokenizer & Redactor
   ├── KURAL Deterministic FSM Engine
   ├── Background Pacing & Callback Workers
   ▼
══════════════════════════════════════════════════════════════════ [ ISOLATED DATA TIER ]
   │  Mutual TLS, KMS/Vault Secret Ingestion, Row-Level/Blind Index Encryption
   ▼
[ SECURE INTERNAL CORE ]
   ├── PostgreSQL 16 (AES-256-GCM Envelope Encryption at Rest)
   ├── Chunk-Encrypted Audio Recording Vault (Local FS / Object Storage)
   ├── Append-Only Tamper-Evident Audit Ledger (Cryptographic HMAC Chaining)
   └── Cloud KMS / HSM (Hardware Key Encryption Key Protection)
```

### 2.2 STRIDE Threat Analysis & Mitigations

| Threat Category | Attack Vector | Potential Impact | AVA Phase 4 Mitigation |
| :--- | :--- | :--- | :--- |
| **Spoofing** | Attacker impersonates bank operator or injects rogue audio into active session. | Unauthorized access to customer records or spoofed call completion. | Asymmetric RS256 JWT with short expiry; single-use 30s WebSocket ticket bound to specific user and `session_id`; TOTP MFA for operators. |
| **Tampering** | Rogue actor or insider alters call audit logs, DND status, or campaign outcomes. | Regulatory non-compliance, concealed fraud, corrupted audit evidence. | Append-only audit table with database-level `REVOKE UPDATE, DELETE`; HMAC-SHA256 sequential hash chaining; daily offsite WORM sealing. |
| **Repudiation** | Operator denies unmasking customer PII or modifying campaign pacing. | Inability to establish regulatory accountability under RBI/DPDP guidelines. | Mandatory justification logged to immutable audit ledger prior to any PII unmasking; actor IP and timestamp cryptographically sealed. |
| **Information Disclosure** | Leakage of Aadhaar, PAN, card numbers, or customer phone via logs, LLM prompts, or database theft. | DPDP Act violations, identity theft, financial loss. | Pre-ingestion dynamic PII scrubber; AES-256-GCM envelope encryption with AAD; keyed blind indexes for lookups; no plaintext PII to external LLMs. |
| **Denial of Service** | Volumetric flooding of voice WebSockets or campaign contact queuing. | Exhaustion of server memory, voice orchestrator worker starvation. | Strict IP/session rate limiting; connection quotas; single-use WebSocket tickets; backpressure on audio queues; PgBouncer connection pooling. |
| **Elevation of Privilege** | Frontline Agent attempts campaign deletion or audit log inspection. | Unauthorized system modification, bypass of compliance controls. | Strict FastAPI RBAC dependencies (`require_role`, `require_permission`); branch-level and tenant-level attribute scoping. |

---

## 3. Explicit Data Flows & Sensitive-Data Inventory

### 3.1 Sensitive-Data Field Inventory

| Table Name | Column Name | Classification | Storage Format | Encryption / Protection Mechanism | Plaintext Justification |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `customers` | `phone` | Direct PII | Encrypted String | AES-256-GCM + Blind Index (`phone_bidx`) | Plaintext prohibited. Lookups use HMAC blind index. |
| `customers` | `full_name` | Direct PII | Encrypted String | AES-256-GCM (`full_name_enc`) | Plaintext prohibited. Masked representation in cache. |
| `customers` | `email` | Direct PII | Encrypted String | AES-256-GCM (`email_enc`) | Plaintext prohibited. |
| `customers` | `customer_ref` | Internal Pseudonym | Plaintext String | Pseudorandom opaque UUID (`CUST-XXXXX`) | **Permitted Plaintext:** Non-reversible external business reference; necessary for join indexes. |
| `customers` | `dnd_status` | Operational Metadata | Plaintext Boolean | Boolean Flag (`true`/`false`) | **Permitted Plaintext:** Low sensitivity; required for high-frequency filtering in dialing queries. |
| `customers` | `account_type` | Operational Metadata | Plaintext String | Enum (`SAVINGS`, `CURRENT`) | **Permitted Plaintext:** Required for operational reporting and campaign segmentation. |
| `call_records` | `masked_phone` | Partial PII | Plaintext String | Masked display format (`+91 98XXX XX012`) | **Permitted Plaintext:** Irreversible mask retaining only prefix/last 2 digits for operator verification. |
| `call_records` | `summary` | Indirect PII | Redacted Text | Pre-persistence PII scrubber (`[REDACTED_*]`) | Plaintext prohibited if containing raw credentials or unmasked phones. |
| `call_records` | `recording_path` | Sensitive Reference | Encrypted Pointer | AES-256-GCM (`recording_path_enc`) | Plaintext prohibited. Points to chunk-encrypted audio vault. |
| `conversation_turns` | `sanitized_user_text` | Intermediate PII | Redacted Text | In-memory redaction before persistence | Plaintext credentials prohibited. Plaintext conversational text permitted after scrubbing. |
| `cases` | `key_lines`, `actions_tried`| Operational Context | Redacted JSON | In-memory redaction before persistence | Required for agent triage; stripped of financial credentials. |
| `storage/recordings/`| Audio WAV files | Biometric / Audio PII| Chunk-Encrypted | AES-256-GCM streaming encryption (64KB chunks) | Plaintext on disk prohibited. |

### 3.2 End-to-End Data Flow Map
1. **Audio Ingestion:** Customer PCM audio streams over TLS 1.3 WebSocket.
2. **Streaming Redaction:** As STT emits partial/final transcripts, raw text enters the **In-Memory PII Tokenizer**. Credentials (OTPs, PINs, cards, Aadhaar, PAN) are replaced with `[REDACTED_*]` tokens.
3. **Intent Extraction:** Sanitized text is sent to the LLM. Zero plaintext credentials leave the application boundary.
4. **Deterministic Evaluation:** KURAL FSM validates intent against current state, policy rules, and authorized actions.
5. **Database Persistence:**
   - Sensitive fields are encrypted using AES-256-GCM with Authenticated Additional Data (AAD).
   - Blind indexes are calculated via HMAC-SHA256 for exact-match searchability.
   - Domain row mutation and Outbox event record are committed in the same database transaction.
6. **Recording Storage:** In-flight audio buffers are encrypted in 64KB chunks using AES-256-GCM and written to the secure audio vault.
7. **Audit Logging:** An operations audit record is created, hash-chained with the preceding record, and persisted to the immutable audit table.

---

## 4. Authentication, Authorization & RBAC

### 4.1 Concrete Identity Architecture: Hybrid Architecture
To balance standalone enterprise on-premises deployments with enterprise bank Single Sign-On (SSO):
* **Default Internal Provider:** Argon2id / PBKDF2-HMAC-SHA256 password authentication with database-backed credential storage, user management, and salted hashes.
* **Enterprise OIDC Adapter:** Plug-and-play OpenID Connect Authorization Code Flow with PKCE for banks integrating with Keycloak, PingFederate, Okta, or Azure AD.
* **Token Structure:** Stateless JSON Web Tokens signed using asymmetric `RS256` (RSA 2048-bit minimum) or `Ed25519`. Public keys are distributed via a standard JWKS endpoint (`/.well-known/jwks.json`).

### 4.2 Token Issuance, Storage & Rotation Architecture
1. **Access Token:**
   - **Lifetime:** Exactly 15 minutes.
   - **Storage:** Stored exclusively in browser memory (JavaScript state). Never persisted to `localStorage`, `sessionStorage`, or IndexedDB.
   - **Claims:** `sub` (user_id), `username`, `role`, `branch_id`, `tenant_id`, `exp`, `iat`, `jti`.
2. **Refresh Token & Cookie Security Properties:**
   - **Lifetime:** Exactly 8 hours (configurable to shift duration).
   - **Storage Mechanism:** Transmitted in an `HttpOnly`, `SameSite=Strict`, `Secure` cookie named `__Host-ava_refresh_token` with `Path=/api/auth`.
   - **Clarification on Cookie Cryptography:** An `HttpOnly` cookie protects against client-side script extraction (XSS mitigation) and `SameSite=Strict` prevents ambient transmission during cross-site requests (CSRF mitigation). **Browsers do not encrypt cookie contents on the client filesystem.** Therefore:
     - The refresh token value is an opaque, high-entropy 256-bit cryptographically secure token (`secrets.token_urlsafe(32)`).
     - Only the **SHA-256 hash** of the token is stored in the database (`refresh_tokens` table).
     - A stolen raw cookie cannot be decrypted into database records.
3. **Token Rotation & Automated Reuse Detection:**
   - Each refresh token belongs to a `token_family_id`.
   - Upon calling `POST /api/auth/refresh`, the presented token is consumed and revoked, and a newly generated refresh token is issued within the same family.
   - If an already-revoked refresh token is presented (indicating theft and replay), the system triggers an **Automated Token Reuse Alert**:
     - The entire token family is immediately revoked in the database.
     - All active sessions for that user are terminated.
     - A `SECURITY_ALERT` is written to the immutable audit ledger.
4. **Logout & Revocation:**
   - Calling `POST /api/auth/logout` sets `revoked = true` on the token family in the database and clears the browser cookie with an expired `Set-Cookie` header.

### 4.3 CSRF, CORS & Rate Limiting Controls
* **CSRF Mitigation:** All state-changing endpoints accept authentication exclusively via the `Authorization: Bearer <token>` header, rendering ambient cross-site cookie attacks ineffective. For the cookie-based refresh and logout endpoints, strict `Origin` and `Referer` validation against the configured allowed-origin whitelist is enforced.
* **CORS Whitelist:** Explicit CORS configuration rejecting wildcard (`*`) origins when credentials are supported.
* **Rate Limiting:**
  - Login endpoint (`POST /api/auth/login`): Maximum 5 attempts per minute per IP.
  - Account lockout: 5 consecutive failed attempts trigger a 15-minute account lock with audit event generation.
* **MFA Recovery:** Operators configured with TOTP (RFC 6238) receive 8 single-use cryptographically random backup recovery codes at provisioning. Backup codes are stored hashed (PBKDF2) in the database and invalidated on first use.
* **Initial Admin Provisioning:** Production deployments prohibit hardcoded default credentials. Initial administrative provisioning occurs via an explicit CLI command (`python -m kural.cli init-admin --username <name>`) or a single-use bootstrap environment token that expires 10 minutes after container boot.

### 4.4 Single-Use WebSocket Ticket Architecture
To prevent long-lived JWTs from leaking into web server access logs, browser history, or proxy telemetry via query parameters:
1. **Ticket Request:** Authenticated browser client issues a `POST /api/auth/ws-ticket` request with its Bearer JWT. Body: `{"session_id": "SES-12345"}`.
2. **Issuance:** Server validates caller authorization for `session_id`, generates a 256-bit cryptographically random ticket (`secrets.token_urlsafe(32)`), and stores it in cache/DB with:
   - `ticket_hash = SHA256(ticket)`
   - `session_id = "SES-12345"`
   - `user_id = caller_id`
   - `expires_at = NOW() + 30 seconds`
   - `consumed = false`
3. **Transport:** Client opens WebSocket connection: `GET /ws/voice/SES-12345?ticket=<ticket>`.
4. **Validation & Atomic Burn:** Server hashes incoming ticket, checks matching `session_id`, verifies `expires_at > NOW()`, and atomically marks `consumed = true`. The ticket is burned on single use.
5. **Replay Protection:** Re-submitting the ticket fails immediately with HTTP 403 / WebSocket close code 1008.
6. **Log Redaction:** Reverse proxy (Nginx) and ASGI server (Uvicorn) logging configurations are explicitly configured to strip the query string on `/ws/voice/*` endpoints:
   ```nginx
   # Redact sensitive ticket query parameters in reverse proxy logs
   log_format redacted '$remote_addr - $remote_user [$time_local] "$request_method $uri" $status $body_bytes_sent';
   access_log /var/log/nginx/access.log redacted;
   ```

### 4.5 Role-Based & Attribute-Based Access Control Matrix

```
       [SYSTEM_ADMIN]
             │
             ├── [SUPERVISOR]
             │         │
             │         ├── [AGENT]
             │         └── [ANALYST]
             │
       [COMPLIANCE_OFFICER] (Orthogonal Audit Authority)
```

| Role | Permitted Operations | Endpoint Scope | Branch / Data Scoping |
| :--- | :--- | :--- | :--- |
| **`ANALYST`** | Read aggregate KPIs, operational summaries, anonymized metrics. | `GET /api/reports/*`, `GET /api/insights` | Organization-wide, but strictly aggregated/masked data. Zero customer PII access. |
| **`AGENT`** | View assigned calls, update call notes, process scheduled callbacks. | `GET /api/calls/{id}`, `POST /api/callbacks/{id}/resolve` | Strictly scoped to customer records where `assigned_agent_id = user.id` and `branch = user.branch`. |
| **`SUPERVISOR`** | Create/start/pause campaigns, reassign callbacks, inspect live calls. | `POST /api/campaigns/*`, `PATCH /api/callbacks/*` | Scoped to assigned region or branch cluster (`user.region`). |
| **`COMPLIANCE_OFFICER`** | Inspect audit trail, verify tamper-evidence, review DND blocks, request audited unmasking. | `GET /api/audit/*`, `POST /api/compliance/unmask` | Organization-wide read-only. Unmasking customer PII requires mandatory written audit justification. |
| **`SYSTEM_ADMIN`** | User provisioning, migration execution, system health inspection, worker config. | `POST /api/admin/*`, `GET /api/health/deep` | Infrastructure operations only. Direct access to customer banking tables prohibited. |

---

## 5. Data Protection & Cryptography

### 5.1 Envelope Encryption & Key Lifecycle
* **Cryptographic Primitive:** AES-256-GCM (Galois/Counter Mode) with 96-bit unique random nonces (IVs) and 128-bit authentication tags.
* **Key Hierarchy:**
  1. **Key Encryption Key (KEK):** Stored in Hardware Security Module (HSM) or Cloud KMS (Google Cloud KMS / AWS KMS). Never leaves the secure module.
  2. **Data Encryption Key (DEK):** 256-bit random key generated per epoch (monthly) or per tenant. DEKs are encrypted by the KEK and stored in a secure `key_store` table.
* **Ciphertext Wire Format:**
  $$\text{enc:v1}:\langle\text{key\_id}\rangle:\text{base64}(\text{Nonce}_{12} \parallel \text{Ciphertext} \parallel \text{Tag}_{16})$$
* **Authenticated Additional Data (AAD):**
  To prevent **Ciphertext Transplantation Attacks** (where an attacker moves an encrypted phone number from one customer's row to another), the AAD is bound to the encryption context:
  $$\text{AAD} = \text{"customers:phone:"} \parallel \text{customer\_ref}$$
  If a ciphertext is transplanted to a different row, AES-GCM tag verification fails immediately.
* **Key Rotation:** Periodic rotation updates the KEK in KMS. DEKs are re-wrapped under the new KEK without requiring full re-encryption of all database tables. Re-encryption of table records occurs lazily or via background compaction.
* **Backup Protection:** Database backups are encrypted with a separate offsite backup public key before export.

### 5.2 Searchable Encryption via Keyed Blind Indexes
Because encrypted fields (`AES-256-GCM`) produce non-deterministic ciphertexts due to unique nonces, direct SQL exact-match queries (`WHERE phone = :p`) would require full table decryption.
* **Blind Index Design:**
  - A dedicated, cryptographically separate **Blind Index Key (BIK)** is generated and held in KMS.
  - The blind index is calculated as:
    $$\text{phone\_bidx} = \text{HMAC-SHA256}(\text{BIK}, \text{NormalizeE164}(\text{phone}))$$
  - Stored in the database as a fixed-length string: `phone_bidx CHAR(64) UNIQUE INDEX`.
  - The plaintext phone is stored envelope-encrypted in `phone_enc TEXT`.
* **Query Execution:**
  ```sql
  -- Search executes against the one-way HMAC blind index with zero plaintext exposure
  SELECT customer_ref, phone_enc FROM customers WHERE phone_bidx = :calculated_bidx;
  ```
  The database never learns the customer's phone number, yet index lookups execute in sub-millisecond B-Tree time.

### 5.3 Recording Chunk-Level Encryption
Call recording WAV files represent sensitive voice biometric data and must never sit in plaintext on disk:
* **Streaming AES-256-GCM:** Incoming audio streams are encrypted in sequential 64KB chunks.
* **Nonce Uniqueness & Reorder Protection:**
  Each chunk uses a dedicated nonce derived from a session base nonce and a 64-bit chunk sequence counter. The chunk counter is bound into the chunk's AAD:
  $$\text{AAD}_{\text{chunk}} = \text{session\_id} \parallel \text{chunk\_index}$$
  This prevents an attacker from reordering, truncating, or splicing audio chunks.
* **Handling Interrupted Writes:**
  If a call drops or the process terminates abruptly, all chunks written up to the failure point remain fully authentic and decryptable up to the last flushed chunk.
* **Decryption Authorization:** Playback endpoints (`GET /api/recordings/{session_id}`) require authenticated `AGENT` (assigned call), `SUPERVISOR`, or `COMPLIANCE_OFFICER` roles with explicit audit logging of every stream access.

### 5.4 Pre-Ingestion Redaction & Memory Protection
* **Redaction Pipeline:** String tokenizer executes immediately upon receiving text from STT or HTTP input. Sensitive patterns (12-digit Aadhaar, 10-char PAN, 16-digit Card Numbers, OTPs/PINs) are stripped *before* strings are passed to:
  1. Internal log formatters (`logging`).
  2. External AI providers (Sarvam, Groq, Gemini).
  3. Database turn persistence (`conversation_turns`).
  4. CSV/PDF export generation.
* **Memory & Secret Handling Realities:**
  Python strings are immutable and interned; claiming to reliably overwrite or zero Python string objects in memory is technically inaccurate. Phase 4 implements realistic, enterprise-grade memory protection:
  - Cryptographic keys are handled strictly as mutable `bytearray` buffers and cleared (`buffer[:] = b'\x00' * len(buffer)`) immediately after cipher instantiation.
  - Process memory core dumps are disabled in Linux container environments via `prctl(PR_SET_DUMPABLE, 0)`.
  - Exception handlers strictly suppress stack frame locals from dumping secrets into error logs.

### 5.5 Retention, Legal Holds & Cryptographic Shredding
* **Standard Retention:** Operational call records and audio recordings are retained for 180 days (or 3 years if associated with a financial dispute, aligning with RBI circular guidelines).
* **Legal Holds:** Records flagged with `legal_hold = true` are immune from automated purge workers.
* **Cryptographic Shredding:** To satisfy DPDP Act erasure requests, the specific DEK associated with a customer or epoch is destroyed, rendering all historical ciphertexts permanently unrecoverable without requiring destructive database vacuuming.

---

## 6. PostgreSQL Migration & Production Data Architecture

### 6.1 Database Engine & Driver Selection: `psycopg` (v3)
* **Selected Driver:** `psycopg` (v3) with SQLAlchemy 2.0.
* **Technical Justification:**
  - `psycopg` v3 provides a modern, fully typed Python 3 interface with native connection pooling, binary protocol support, and high-performance `COPY` operations for bulk customer imports.
  - Unlike `asyncpg` (which requires non-standard dialect handling and complicates mixed sync/async workers), `psycopg` v3 supports both synchronous workers and asynchronous FastAPI route handlers seamlessly.
  - Legacy `psycopg2` is rejected due to lack of native typing and older C-extension memory architectures.

### 6.2 PgBouncer Compatibility & Pool Architecture
To support 100+ concurrent voice connections without exhausting PostgreSQL backend processes:
* **Pooling Mode:** PgBouncer in **Transaction Pooling Mode** (`pool_mode = transaction`).
* **Prepared Statements Guard:** Because transaction pooling reallocates backend server connections between transactions, server-side prepared statements can cause collisions. SQLAlchemy is configured with:
  ```python
  engine = create_engine(
      "postgresql+psycopg://...",
      connect_args={"prepare_threshold": None},  # Disable named server-side prepared statements
      pool_size=20,
      max_overflow=10,
      pool_timeout=30.0,
      pool_recycle=1800,
  )
  ```
* **Pool Sizing Calculation:**
  $$\text{Total App Pool} = (\text{Web Workers} \times \text{Concurrency}) + (\text{Background Workers} \times \text{Threads})$$
  $$\text{Target Backend Connections} \le \text{PostgreSQL max\_connections} \times 0.8$$
  With 4 web workers (pool 10) + 3 background workers (pool 5), total application connections = 55, well within standard 100-connection PostgreSQL allocations.

### 6.3 SQLite-to-PostgreSQL Migration Pipeline
1. **Schema Deployment:** Target PostgreSQL database is initialized via Alembic (`0001_initial` $\to$ `0002_phase2_phase3_operations` $\to$ Phase 4 migrations).
2. **Streaming Data Pump:** A dedicated migration script streams data table-by-table using binary `COPY`:
   - Migrates `customers`, `campaigns`, `campaign_contacts`, `sessions`, `conversation_turns`, `cases`, `callbacks`, `call_records`, `agents`, `report_schedules`, `operations_audit_events`.
   - Generates blind indexes (`phone_bidx`) and envelope-encrypts sensitive fields during migration.
3. **Sequence & Identity Reset:** Auto-incrementing sequences are reset to `MAX(id) + 1` via `SELECT setval(...)`.
4. **Consistency Verification:**
   - Row-count equality across all tables.
   - SHA-256 checksum matching on deterministic composite keys (`customer_ref`, `campaign_id`, `session_id`).
   - Foreign key integrity verification.
5. **Rollback Strategy:** Source SQLite database remains read-only for 7 days post-migration. If PostgreSQL fails verification, application config reverts to SQLite via single environment variable change (`DATABASE_URL`).

### 6.4 Conditional Monthly Partitioning Analysis
Partitioning adds operational complexity (e.g., foreign keys cannot reference partitioned tables without composite keys, and global unique indexes are restricted).
* **Partitioning Decision Threshold:**
  - **Volume < 10,000,000 rows/year:** Monthly partitioning is **NOT ENABLED**. Standard composite B-Tree indexes on `(started_at DESC, campaign_id)` and `(session_id, turn_order)` yield sub-5ms query times.
  - **Volume $\ge$ 10,000,000 rows/year:** Conditional partitioning is activated for `conversation_turns`, `call_records`, and `operations_audit_events` using `PARTITION BY RANGE (timestamp)`.
* **Partition Requirements if Activated:**
  - Primary keys must include partition key: `PRIMARY KEY (call_id, started_at)`.
  - Foreign keys from child tables must include composite references.
  - Automated worker provisions partitions 2 months in advance.

---

## 7. Transactional Outbox & Resilient Worker State Machines

### 7.1 Atomic Outbox Mutation
To prevent dual-write inconsistencies (where a database update succeeds but an external event or background job is lost):
1. Any domain state transition (e.g., customer callback requested, campaign contact dispositioned) is executed in a SQL transaction.
2. In the **exact same SQL transaction**, an outbox record is inserted into the `outbox` table:
   ```python
   with db.session() as s:
       contact.status = "COMPLETED"
       s.add(OutboxRow(
           outbox_id=f"OUT-{uuid4().hex[:12].upper()}",
           event_topic="campaign_contact.completed",
           payload={"contact_id": contact.contact_id, "disposition": "CLOSED"},
           status="PENDING",
           created_at=utcnow(),
       ))
       s.commit()  # Both domain update and event commit atomically
   ```

### 7.2 Worker Claiming, Leases & Crash Recovery
* **PostgreSQL Worker Claiming Query:**
  Workers claim batches using pessimistic locking and skip-locked concurrency:
  ```sql
  SELECT outbox_id, event_topic, payload
  FROM outbox
  WHERE status = 'PENDING'
    AND (locked_until IS NULL OR locked_until < NOW())
  ORDER BY created_at ASC
  LIMIT 10
  FOR UPDATE SKIP LOCKED;
  ```
* **Lease Duration:** When claimed, the worker sets `status = 'PROCESSING'`, `locked_until = NOW() + INTERVAL '30 seconds'`, and `worker_id = :worker_id`.
* **Crash Recovery:** If a worker process terminates abruptly mid-task, its lease expires (`locked_until < NOW()`). On the next polling cycle, a surviving worker automatically re-claims the event.
* **At-Least-Once Delivery & Deduplication:**
  All outbox events carry an immutable `outbox_id` and domain `idempotency_key`. Consumers verify if `outbox_id` has already been processed before executing side effects.
* **Dead-Letter Queue:** Events failing after 5 attempts are marked `status = 'DEAD_LETTER'`, alerting operations without blocking worker queues.

### 7.3 Ephemeral UI Event Bus vs Durable Outbox
* **Clarification:** The existing in-process `event_bus.py` is strictly an ephemeral in-memory pub/sub for updating the browser dashboard via WebSockets (`/events/ws`). **It is not durable storage.**
* **Architectural Separation:** Durable operational workflows (retrying failed calls, pacing outbound queues, triggering webhook notifications) are driven exclusively by the database-backed `outbox` table and persistent worker polling, never by the ephemeral UI event bus.

### 7.4 Race-Free State Machines for Campaign & Callback Workers
* **Campaign Dialing State Machine:**
  $$\text{PENDING} \xrightarrow{\text{Pacing Claim}} \text{QUEUED} \xrightarrow{\text{Pre-Dispatch Check}} \text{RINGING} \xrightarrow{\text{Outcome}} \begin{cases} \text{COMPLETED} \\ \text{RETRY\_SCHEDULED} \\ \text{FAILED} \\ \text{DND\_EXCLUDED} \end{cases}$$
  To prevent concurrent worker collisions, state transitions use atomic conditional updates:
  ```sql
  UPDATE campaign_contacts
  SET status = 'QUEUED', updated_at = NOW()
  WHERE contact_id = :cid AND status IN ('PENDING', 'RETRY_SCHEDULED')
  RETURNING contact_id;
  ```
* **Simulation Boundaries Preserved:** Campaign workers simulate call progress using randomized outcome matrices and timer intervals. No PSTN / SIP telephony is introduced in Phase 4.

---

## 8. Configurable India Calling Policy & Customer Preferences

### 8.1 Configurable Compliance Engine Architecture
The hardcoded 09:00–20:00 rule from previous phases is replaced with a versioned, configurable rules engine aligning with the **Telecom Commercial Communications Customer Preference Regulations (TCCCPR, 2018)** and Town Bank compliance directives.

```
[ OUTBOUND CALL REQUEST ]
            │
            ▼
┌────────────────────────────────────────────────────────┐
│             KURAL COMPLIANCE POLICY ENGINE             │
│                                                        │
│  1. Check Campaign Classification                      │
│     ├── Service / Informational / Transactional        │
│     └── Commercial / Promotional / Adoption            │
│                                                        │
│  2. Evaluate Allowed Calling Window (IST)              │
│     ├── Service: 08:00 – 21:00 (or scheduled callback) │
│     └── Promotional: Strict 09:00 – 20:00              │
│                                                        │
│  3. Real-Time DND Scrub against Registry               │
│     └── Global Bank DND + Telecom Category Scrub       │
│                                                        │
│  4. Frequency Capping & Velocity Limits                │
│     └── Max 3 attempts/week, Min 24h gap               │
└────────────────────────────────────────────────────────┘
            │
            ├── APPROVED ──► Proceed to Dispatch
            │
            └── REJECTED / UNKNOWN ──► Mark DND_EXCLUDED (Fail-Closed)
```

### 8.2 Two-Stage Enforcement: Enrollment & Pre-Dispatch
1. **Enrollment Scrub:** Executed when contacts are uploaded or enrolled into a campaign. Matches against the national/bank DND registry.
2. **Pre-Dispatch Real-Time Scrub:** Executed immediately before the dialing worker initiates an outbound call (seconds prior to connection). If a customer updated their preference between enrollment and dispatch, the call is blocked immediately.

### 8.3 Fail-Closed Policy & Audit Evidence
* **Fail-Closed Principle:** If the DND status or customer preference cannot be conclusively determined (e.g., database timeout, unresolvable phone format), the policy engine **fails closed**—the contact is marked `DND_UNKNOWN_BLOCKED` and excluded from dialing.
* **Audit Evidence:** Every dispatch evaluation logs an immutable record with:
  `policy_version`, `campaign_category`, `customer_tz`, `evaluated_at_utc`, `decision` (`ALLOWED` / `BLOCKED`), `reason`.
* **Production Gate:** Compliance sign-off by Town Bank legal/compliance officers is a mandatory deployment gate prior to production traffic.

---

## 9. Observability, Telemetry & Empirical Load Testing

### 9.1 Precision Turn Telemetry ($T_0 \to T_8$)
To prevent misleading latency claims, Phase 4 explicitly distinguishes between **Time-to-First-Audio** (user perceived latency) and **Full Turn Completion** (backend persistence and metrics calculation):

$$\text{User Perceived Latency} = T_6 - T_0 \quad (\text{Target: } P_{50} < 1,200\text{ ms}, P_{95} < 1,800\text{ ms})$$
$$\text{Full Turn Latency} = T_8 - T_0 \quad (\text{Target: } P_{50} < 1,800\text{ ms}, P_{95} < 2,500\text{ ms})$$

```
T0: User Speech Start (VAD detects voice)
 │
T1: Silence Detected (VAD End-of-Turn)
 │
T2: STT Transcript Finalized (Sarvam Saaras v4)
 │
T3: Intent Extracted & FSM Validated (KURAL Deterministic Policy)
 │
T4: LLM Generation Started (Streaming first token)
 │
T5: Policy Check Confirmed (Safety & Tool Authorization)
 │
T6: TTS First Audio Chunk Generated (Sarvam Bulbul v3) ◄── [ TIME TO FIRST AUDIO ]
 │
T7: Audio Played to User (WebSocket transfer complete)
 │
T8: Database Persistence Completed (Turns, Outbox, Audit) ◄── [ FULL TURN COMPLETION ]
```

### 9.2 Prometheus Metrics Exporter (`/metrics`)
Exported in standard OpenMetrics format:
* `kural_turn_latency_first_audio_ms` (Histogram with buckets: 300, 600, 900, 1200, 1500, 1800, 2500)
* `kural_turn_latency_full_ms` (Histogram with buckets: 500, 1000, 1500, 2000, 2500, 3500)
* `kural_active_voice_sessions` (Gauge)
* `kural_barge_in_events_total` (Counter)
* `kural_policy_violations_total` (Counter)
* `kural_outbox_lag_seconds` (Gauge measuring oldest unprocessed event)

### 9.3 Empirical Load Test Specifications
All load test claims are explicitly categorized as **TARGETS** until validated on production-grade infrastructure:

* **Target SLOs:**
  - 100 concurrent bidirectional voice sessions per node.
  - $P_{50}$ Time-to-First-Audio $< 1,200 \text{ ms}$; $P_{95} < 1,800 \text{ ms}$.
  - System availability target: 99.95% uptime.
* **Test Harness Environment:**
  - Standard Benchmark Node: 8 vCPU, 16 GB RAM, Linux kernel 6.x, 1 Gbps networking.
  - Database: Dedicated PostgreSQL 16 instance with SSD storage (minimum 3,000 IOPS).
* **Load Test Scenarios (k6):**
  1. **Warm-Up Test:** 10 concurrent calls ramping over 2 minutes. Verifies connection pools and TTS WebSocket pre-warming.
  2. **Sustained Concurrency Test:** 100 concurrent active sessions running multi-turn scripts for 30 minutes. Measures memory stability, CPU utilization, and $P_{95}$ latency.
  3. **Spike Test:** Sudden ramp from 10 to 150 concurrent sessions over 30 seconds. Verifies rate limiters, backpressure, and recovery without process crashes.
  4. **Soak Test:** 50 concurrent sessions sustained for 4 hours. Validates zero memory leaks and stable garbage collection.
  5. **Worker Failure Injection:** Abrupt SIGKILL sent to background workers during high outbox load. Verifies lease expiration and zero duplicate dispatching.
* **Mocked vs Live Integration Distinction:**
  - *Tier 1 (Internal Architecture Benchmark):* Executed using high-fidelity mocked Sarvam/LLM providers. Measures pure KURAL FSM, PostgreSQL, outbox, and WebSocket server capacity.
  - *Tier 2 (End-to-End Live Provider Benchmark):* Executed against real external Sarvam and Groq/Gemini APIs under provider rate limits (typically 10-20 concurrent calls depending on API quota).

---

## 10. Security, Incident Response & Tamper-Evident Ledger

### 10.1 Cryptographic Tamper-Evident Audit Ledger
* **Monotonic Sequence & Hash Chaining:**
  Each record in `operations_audit_events` contains an immutable SHA-256 hash chaining link:
  $$\text{Hash}_n = \text{HMAC-SHA256}\Big(\text{AuditKey},\; \text{Hash}_{n-1} \parallel \text{Seq}_n \parallel \text{Timestamp}_n \parallel \text{Actor}_n \parallel \text{Action}_n \parallel \text{Resource}_n \parallel \text{Detail}_n\Big)$$
* **Database Privilege Hardening:**
  The runtime application user (`ava_app`) is granted strictly:
  ```sql
  GRANT SELECT, INSERT ON operations_audit_events TO ava_app;
  REVOKE UPDATE, DELETE, TRUNCATE ON operations_audit_events FROM ava_app, PUBLIC;
  ```
  Database-level triggers raise unconditional exceptions on any `UPDATE` or `DELETE` attempt.
* **External Sealing:** Every 24 hours, the latest sequence hash is digitally signed and pushed to an external Write-Once-Read-Many (WORM) storage bucket or immutable cloud log, preventing retroactive manipulation even by database administrators.

### 10.2 Incident Response Playbooks

| Incident Scenario | Detection Signal | Immediate Automated Action | Operational Resolution Procedure |
| :--- | :--- | :--- | :--- |
| **KMS Key Compromise** | Alert from Cloud KMS / Security Operations Center. | Freeze key access; switch to standby key version in configuration. | Re-encrypt DEKs using new KEK; revoke compromised key version; audit all decrypt events. |
| **Database Compromise** | Unauthorized connection or anomalous query patterns. | Revoke compromised database credentials; sever connection pool. | Failover to isolated replica; verify audit ledger hash integrity; restore from encrypted point-in-time backup. |
| **Outbox Queue Backlog** | `kural_outbox_lag_seconds` exceeds 60 seconds. | Alert on-call engineers; auto-scale worker concurrency. | Inspect dead-letter queue; check for slow external dependencies; adjust pacing limits. |
| **External AI Provider Outage**| Consecutive Sarvam or LLM timeouts ($> 3$ failures). | Immediate automated fallback to local deterministic KURAL rules. | Switch to secondary provider candidate (e.g., Qwen $\to$ GPT-OSS $\to$ Gemini) or alert caller that speech service is degraded. |
| **Unauthorized Audio Access** | Rapid spike in `/api/recordings/{id}` 403s. | IP rate limiter blocks source address for 60 minutes. | Security team reviews audit logs; verify encryption key access logs; invalidate active sessions. |

---

## 11. Revised Milestones & Definitions of Done

```
[ M4.1: RBAC & Auth ] ──► [ M4.2: Data Security & PII ] ──► [ M4.3: PostgreSQL & Outbox ]
                                                                      │
[ M4.5: Scale, Load & Gates ] ◄── [ M4.4: Telemetry, Policy & Audit ] ┘
```

### Milestone 4.1: Authentication, Authorization & RBAC
* **Dependencies:** None.
* **Definition of Done:**
  - [ ] Asymmetric RS256 JWT access tokens and secure `HttpOnly` refresh token cookies implemented.
  - [ ] Refresh token rotation and reuse detection with family revocation verified.
  - [ ] 5 operational roles (`ANALYST`, `AGENT`, `SUPERVISOR`, `COMPLIANCE_OFFICER`, `SYSTEM_ADMIN`) mapped and enforced via FastAPI dependencies.
  - [ ] Single-use 30s WebSocket ticket issued via authenticated REST API and burned on connection.
  - [ ] Automated tests prove unauthorized access, role escalation, and expired token rejection.

### Milestone 4.2: Data Protection, Cryptography & PII
* **Dependencies:** M4.1.
* **Definition of Done:**
  - [ ] AES-256-GCM envelope encryption implemented with table/record AAD context.
  - [ ] Keyed blind indexes (`HMAC-SHA256`) implemented for searchability on phone/email.
  - [ ] 64KB chunk-level streaming encryption implemented for audio recordings.
  - [ ] Dynamic PII tokenizer sanitizes credentials before logging, LLM dispatch, or export.
  - [ ] Audited compliance unmasking endpoint operational with mandatory written justification.

### Milestone 4.3: PostgreSQL Migration & Durable Outbox
* **Dependencies:** M4.2.
* **Definition of Done:**
  - [ ] `psycopg` (v3) engine and PgBouncer transaction-pooling configuration implemented.
  - [ ] SQLite-to-PostgreSQL data pump script verified with row-count and checksum parity.
  - [ ] Transactional outbox worker operational using `SELECT ... FOR UPDATE SKIP LOCKED`.
  - [ ] Worker crash recovery verified via simulated lease expiration tests.
  - [ ] Zero duplicate dispatches verified under concurrent worker execution.

### Milestone 4.4: Compliance Policy Engine & Tamper-Evident Ledger
* **Dependencies:** M4.3.
* **Definition of Done:**
  - [ ] Configurable TCCCPR 2018 calling policy engine replaces hardcoded hours.
  - [ ] Pre-dispatch real-time DND scrub and fail-closed validation verified.
  - [ ] Monotonic HMAC-SHA256 hash chaining active on `operations_audit_events`.
  - [ ] Audit verification script detects intentional row tampering with 100% accuracy.
  - [ ] OpenMetrics Prometheus `/metrics` exporter tracking $T_0 \to T_8$ milestones.

### Milestone 4.5: Empirical Load Testing & CI/CD Security Gates
* **Dependencies:** M4.4.
* **Definition of Done:**
  - [ ] k6 load test scripts written for warm-up, sustained (100 concurrent target), spike, and soak.
  - [ ] Benchmark executed and accurately labeled (mocked vs live provider).
  - [ ] Static typing (`mypy --strict`), AST security scan (`bandit`), and dependency audit clean.
  - [ ] Full regression suite passing with zero regressions across Phase 1, Phase 2, and Phase 3.

---

## 12. Decision Log

### 12.1 Mandatory Decisions (Non-Negotiable)
1. **FSM Supremacy:** KURAL FSM remains the sole business and state authority. The LLM cannot write to the database or trigger unvetted actions.
2. **Deterministic Token Burn:** Voice WebSocket tickets are single-use, 30-second TTL, and burned atomically on handshake.
3. **No Unencrypted PII at Rest:** All direct PII in database and disk audio must be envelope-encrypted with AES-256-GCM and AAD.
4. **Fail-Closed DND:** Outbound calls are blocked if preference/DND status cannot be verified.
5. **No Telephony in Phase 4:** PSTN/SIP integration remains strictly deferred to Phase 5.

### 12.2 Architectural Recommendations
1. **Driver:** Standardize on `psycopg` v3 for all PostgreSQL operations to avoid dialect fragmentation.
2. **Partitioning:** Defer table partitioning until annual volume exceeds 10M rows to avoid composite key complexity.
3. **Blind Indexing:** Use HMAC-SHA256 with an isolated KMS key for exact-match customer search.

### 12.3 Explicit Assumptions
1. **Deployment Platform:** Production environment will provide Linux container orchestration (Kubernetes / Docker) with Cloud KMS or Vault integration.
2. **Network Perimeter:** Production deployment will include a TLS 1.3 terminating reverse proxy (Nginx / Cloud Load Balancer) handling initial DDoS filtering.
3. **Provider Quotas:** Live provider testing is bounded by Sarvam and Groq API rate limits; 100 concurrent session targets will be benchmarked using mock provider harnesses.

### 12.4 Deferred Work (Strictly Phase 5)
1. Real PSTN / SIP trunking and telephony carrier integration.
2. Dual-channel telephonic audio mixing (telephony carrier audio fork).
3. Live carrier-grade speech packet jitter buffers.

---

## 13. Rollback Strategy by Milestone

| Milestone | Rollback Trigger | Technical Rollback Procedure |
| :--- | :--- | :--- |
| **M4.1 (RBAC/Auth)** | Authentication regressions block valid dashboard operations or voice connections. | Set `REQUIRE_AUTH=false` in environment configuration to restore permissive Phase 3 mode; revert API dependency decorators. |
| **M4.2 (Encryption/PII)**| Decryption failure or corrupted ciphertext prevents record loading. | Read unencrypted fallback supported by `enc:v1:` prefix check; restore DEK from KMS key history; revert to plaintext write mode if needed. |
| **M4.3 (PostgreSQL/Outbox)**| Database connectivity failures or PgBouncer pool exhaustion. | Revert `DATABASE_URL` environment variable to source SQLite file (`kural_local.db`); stop PostgreSQL worker process. |
| **M4.4 (Policy/Audit)** | Compliance policy incorrectly blocks valid customer service callbacks. | Revert active policy configuration YAML to default permissive service window; outbox processes resume. |
| **M4.5 (Telemetry/Scale)**| Load testing uncovers memory leak or deadlock under load. | Scale down worker concurrency to 1; disable non-essential OpenTelemetry trace exporters; revert to commit `59edf51`. |

---

## 14. Production Risks Requiring Bank / Compliance Sign-Off

The following items are technical specifications that require explicit review and sign-off by Town Bank governance authorities prior to production deployment:

1. **TRAI Campaign Classification Sign-Off:** Written confirmation from bank compliance regarding whether app-adoption campaigns are categorized as "Service/Informational" (08:00–21:00) or "Commercial/Promotional" (strict 09:00–20:00).
2. **KMS Key Custody Agreement:** Agreement on whether master encryption keys (KEKs) reside in Town Bank's internal HSM, Google Cloud KMS, or AWS KMS.
3. **Audit Retention & Legal Hold Policy:** Sign-off on the 180-day standard purge window versus the 3-year financial dispute hold requirement.
4. **External AI Data Processing Addendum:** Formal regulatory clearance confirming that transmitting sanitized, credential-scrubbed conversational transcripts to Sarvam AI and Groq complies with bank data localization rules.
