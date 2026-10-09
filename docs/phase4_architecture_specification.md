# AVA Phase 4 Architecture Specification
## Security, Production Hardening & Scale

**Document Version:** 1.0.2 (Incorporating Addendum v1.0.2-A)  
**Baseline Git Tag:** `phase3-accepted-frozen`  
**Baseline Git Commit:** `59edf51`  
**Status:** Under Final Architecture Review (Design-Only Milestone)  
**Target Phase:** Phase 4 Production Hardening  

---

## 1. Executive Summary & Architecture Decisions

Phase 4 hardens the validated AVA prototype into a production-grade, regulatory-compliant banking voice agent. All Phase 4 designs strictly preserve the accepted Phase 3 baseline (`phase3-accepted-frozen`, commit `59edf51`, 173/173 tests passing) and enforce non-negotiable architectural invariants:

1. **Deterministic Authority:** The KURAL Finite State Machine (FSM) remains the sole authority for state transitions, business logic, policy enforcement, tool dispatching, and spoken conversational turns.
2. **LLM as Semantic Layer Only:** The LLM performs intent classification and structured entity extraction within closed-world retrieved contexts. The LLM has zero direct access to databases, cannot issue SQL, cannot execute tools, and cannot trigger actions without deterministic KURAL validation.
3. **Voice Stack Preservation:** Sarvam Saaras STT and Bulbul v3 TTS remain the primary voice pipeline baseline.
4. **Provider-Agnostic LLM Interface:** The multi-provider contract remains swappable across Qwen 3.8 27B, GPT-OSS 20B, and Gemini 3.8 Flash, backed by deterministic offline fallbacks.
5. **No Premature Infrastructure:** No vector databases, microservices, or external message brokers (e.g., Kafka, Celery, Redis). Production durability and concurrency are achieved using PostgreSQL 16, connection pooling, and a transactional outbox pattern.
6. **Simulated Telephony Boundary:** Real PSTN/SIP trunking is strictly deferred to Phase 5. Phase 4 dialers execute within controlled simulation harnesses.
7. **Fail-Closed Governance:** Every security, compliance, cryptographic, or operational uncertainty fails closed. Unsafe fallback modes (such as disabling authentication, writing plaintext PII, or reverting to permissive dialing windows) are permanently prohibited.

---

## 2. Threat Model, Trust Boundaries & Voice-Provider Data Boundary

### 2.1 System Trust Boundaries & Data Flow

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
   ├── Chunk-Encrypted Audio Recording Vault (Per-Recording DEK)
   ├── Append-Only Tamper-Evident Audit Ledger (Monotonic HMAC Chaining)
   └── Cloud KMS / HSM (Hardware Key Encryption Key Protection)
```

### 2.2 Voice-Provider Data Boundary & Raw Audio Reality

A fundamental security reality in voice AI systems is that **raw audio enters the system before automated text-based redaction can execute**:

```
Customer Spoken Audio (Contains Potential Spoken OTP, Card No., PIN)
       │
       ▼
[ Web Audio PCM Stream (16kHz LINEAR16) ]
       │
       ▼ (Egress over WebSocket / TLS 1.3)
[ Speech-to-Text Engine (STT) ] ◄── MUST TRANSCRIBE BEFORE REDACTION IS POSSIBLE
       │
       ▼
Raw Text Transcript ("My OTP is 4 9 2 0 1 8")
       │
       ▼
[ KURAL Regex Redactor & PII Tokenizer ] ◄── FIRST POINT WHERE CREDENTIALS CAN BE STRIPPED
       │
       ▼
Sanitized Text ("My OTP is [REDACTED_OTP]")
       │
       ▼ (Egress to LLM)
[ Multi-Provider LLM (Qwen / GPT-OSS / Gemini) ]
```

Because customers may speak authentication credentials (OTPs, PINs, card numbers, Aadhaar) during an interaction, raw audio transmitted to an external STT service contains sensitive payment credentials. **Redacting transcripts post-STT does NOT protect raw audio in transit to or at rest within an external STT provider.**

#### Architectural Options for Voice Processing

To address this boundary honestly and rigorously, AVA defines two explicit architectural models:

* **Option A: Bank-Controlled Boundary Deployment (Canonical Requirement)**
  - The speech-to-text model is deployed entirely inside Town Bank's private VPC or on-premises security perimeter with zero external network egress.
  - **Feasibility & Availability Determination:** Sarvam Saaras is commercially offered primarily via managed cloud SaaS APIs (`api.sarvam.ai`). If an on-premises enterprise container appliance from Sarvam AI cannot be contractually certified and verified for Town Bank's infrastructure, the **approved, verified bank-controlled alternative** is an open-weights ASR engine: containerized **Faster-Whisper (Whisper-large-v3-turbo)** or **NVIDIA NeMo Conformer-CTC** hosted on Triton Inference Server within the bank's GPU cluster.
  - Zero raw audio traverses the public internet or external third-party servers. All spoken credentials remain strictly within the bank's boundary.
  - **Compliance Status:** **Option A is the ONLY architecture that inherently satisfies AVA's strict bank-data-boundary invariant and RBI master directions on digital payment data localization.**

* **Option B: Documented External-Processing Exception (SaaS Provider)**
  - Raw audio is streamed to an external cloud STT provider (Sarvam AI SaaS endpoint) over TLS 1.3, and sanitized transcripts are dispatched to cloud LLMs (Groq, Gemini).
  - Permitted **STRICTLY AND EXCLUSIVELY** under an active, formal bank compliance exception requiring:
    1. Executed Data Protection Agreement (DPA) and Business Associate Agreement with Sarvam AI and LLM vendors.
    2. Zero-Retention Guarantee: Legally binding vendor commitment that audio streams, intermediate tokens, and transcripts are processed strictly in volatile memory and never persisted, cached, or used for model training.
    3. Indian Data Localization: Vendor compute must reside strictly within Indian sovereign territory (e.g., AWS `ap-south-1` / MeitY-empanelled cloud).
    4. Written risk acceptance signed by Town Bank Chief Information Security Officer (CISO) and Legal Counsel.

**Policy Directive:** Option B is approved exclusively for synthetic testing and development evaluation. **External speech processing is strictly disabled for all real customer voice sessions until either the verified on-premises appliance (Option A) is deployed or formal bank CISO approval (Option B) is granted.**

---

## 3. Threat Analysis & Trust Boundaries (STRIDE)

| Threat Category | Attack Vector | Potential Impact | AVA Phase 4 Mitigation |
| :--- | :--- | :--- | :--- |
| **Spoofing** | Forged JWT access token or replayed WebSocket ticket. | Unauthorized access to call logs, recordings, or live operational controls. | Asymmetric RS256 JWT validation via public JWKS; single-use 30s WebSocket ticket burned atomically upon connection. |
| **Tampering** | Modification of call transcripts or audit event rows in database. | Loss of regulatory audit integrity; hiding fraud or misconduct. | Monotonic HMAC-SHA256 hash chaining on `operations_audit_events`; database triggers revoking `UPDATE`/`DELETE`; periodic WORM sealing. |
| **Repudiation** | Operator claims an unauthorized callback or PII export was automated. | Inability to attribute administrative actions during audits. | Strict RBAC context logged on every action; IP address, actor ID, and cryptographic signature captured in immutable audit ledger. |
| **Information Disclosure** | SQL injection, unencrypted database theft, or raw audio exfiltration. | Exposure of customer phone numbers, voice recordings, and conversation turns. | Column-level AES-256-GCM envelope encryption with context AAD; keyed HMAC blind indexes; per-recording 64KB chunk encryption with completion manifests. |
| **Denial of Service** | WebSocket connection exhaustion or slowloris audio streaming. | Server starvation; dropping legitimate customer voice sessions. | PgBouncer transaction pooling; per-IP rate limiting; strict 30s ticket TTL; fixed pool of audio orchestrator workers with backpressure drops. |
| **Elevation of Privilege** | Compromised agent account attempts campaign configuration or audit purge. | Unauthorized mass dialing or destruction of compliance evidence. | Explicit non-hierarchical permission matrix; strict FastAPI role dependencies; segregation of duties separating `SYSTEM_ADMIN` from customer data. |

---

## 4. Authentication, Authorization & Session Management

### 4.1 Hybrid Identity Architecture
* **Default Internal Identity:** Argon2id password hashing (`time_cost=3`, `memory_cost=65536`, `parallelism=4`) with database-backed user credentials.
* **Enterprise SSO Adapter:** OpenID Connect (OIDC) Authorization Code Flow with PKCE for enterprise bank IdPs (PingFederate, Keycloak, Azure AD).
* **Token Structure:** Stateless JSON Web Tokens signed using asymmetric `RS256` (RSA 2048-bit minimum) or `Ed25519`. Public verification keys are exposed via `/.well-known/jwks.json`.

### 4.2 Token Issuance, Refresh-Token Cookie & Session Semantics
1. **Access Token:**
   - **Lifetime:** Exactly 15 minutes.
   - **Storage:** Stored exclusively in browser memory (JavaScript state). Never written to `localStorage`, `sessionStorage`, or IndexedDB.
   - **Claims:** `sub` (user_id), `username`, `role`, `branch_id`, `tenant_id`, `family_id`, `token_version`, `exp`, `iat`, `jti`.
2. **Refresh Token & Strict Cookie Configuration:**
   - **Lifetime:** 8 hours (aligned with standard bank operator shift).
   - **Cookie Name:** `__Host-ava_refresh_token`
   - **Mandatory Cookie Attributes (RFC 6265bis):**
     - `Secure`: Mandatory (cookie sent only over TLS 1.3).
     - `HttpOnly`: Mandatory (inaccessible to JavaScript, mitigating XSS).
     - `SameSite=Strict`: Mandatory (blocks cross-site transmission, mitigating CSRF).
     - `Path=/`: Mandatory (must be exactly `/` to satisfy browser `__Host-` prefix validation).
     - `Domain`: **MUST NOT BE PRESENT** (browser rejects `__Host-` cookies containing any `Domain` attribute).
   - **Server Storage:** The database stores only the `SHA-256` hash of the refresh token in `refresh_tokens`, salted per entry.
3. **Token Family Reuse Detection & Concurrent Refresh Race Handling:**
   - Each refresh token belongs to a cryptographically unique `family_id` with a monotonic generation number.
   - **Atomic Database-Level Refresh Exchange:** To eliminate race conditions when multiple client requests hit `/api/auth/refresh` concurrently, the token exchange is serialized via database row-level locking:
     ```sql
     SELECT token_id, family_id, generation, replaced_at, revoked, next_token_id
     FROM refresh_tokens
     WHERE token_hash = :hash
     FOR UPDATE;
     ```
   - **Legitimate Concurrent Refresh Tolerance (Grace Window):**
     - When Token $T_n$ is refreshed, the server records the newly generated Token $T_{n+1}$ in `next_token_id` and sets `replaced_at = NOW()`.
     - A strict **15-second grace window** is permitted: if a concurrent in-flight request presents $T_n$ within 15 seconds of `replaced_at`, the server returns the already-issued $T_{n+1}$ and access token pair without incrementing generation or flagging an alarm.
   - **Malicious Reuse Detection & Replay Handling:** If an invalidated token is presented *after* the 15-second grace window (or if an older generation in the family is presented):
     - The event is classified as an active replay attack.
     - The entire `family_id` is immediately revoked in the database (`revoked = true`).
     - An emergency `SECURITY_ALERT` is written to the immutable audit ledger.
     - All active sessions for that user are terminated immediately.
4. **Immediate Revocation of Already-Issued Access JWTs:**
   - Stateless JWTs cannot be revoked client-side. To ensure compromised token families or locked users are barred immediately:
     - Each user record maintains an integer `token_version`.
     - Revoking a user's sessions increments `user.token_version` and publishes the revoked `family_id` / `jti` to an in-memory / database blocklist cache with a 15-minute TTL (the access token lifespan).
     - The FastAPI authentication dependency (`get_current_user`) checks the token's `family_id` against the blocklist and verifies `token.token_version == user.token_version`.
     - **Performance Classification:** Sub-millisecond JWT rejection is formally recognized as an **Unverified Performance Target** ($P_{95} < 5\text{ ms}$ via local memory LRU cache) to be empirically benchmarked and confirmed during Milestone 4.1 testing.
5. **MFA Enforcement & Recovery:**
   - **Mandatory MFA:** Privileged roles (`SYSTEM_ADMIN`, `SUPERVISOR`, `COMPLIANCE_OFFICER`) MUST configure TOTP (RFC 6238) or FIDO2 WebAuthn before accessing protected routes.
   - **Backup Recovery Codes:** 8 cryptographically random single-use backup recovery codes generated at provisioning, stored PBKDF2-hashed in the database, and invalidated upon first use.
   - **Admin Bootstrap:** Prohibit default passwords. Initial administrator provisioning occurs strictly via an offline CLI utility (`python -m kural.cli init-admin`) requiring console access, or an ephemeral single-use environment secret that expires 10 minutes after container boot.

### 4.3 Single-Use WebSocket Ticket Architecture
To prevent access tokens from leaking into web server access logs, browser history, or proxy telemetry via WebSocket query parameters:
1. **Ticket Request:** Authenticated browser issues `POST /api/auth/ws-ticket` with its Bearer JWT. Body: `{"session_id": "SES-12345"}`.
2. **Issuance:** Server validates authorization, generates a 256-bit cryptographically secure token (`secrets.token_urlsafe(32)`), and stores:
   `ticket_hash = SHA256(ticket)`, `session_id`, `user_id`, `expires_at = NOW() + 30s`, `consumed = false`.
3. **Handshake & Atomic Burn:** Client connects to `GET /ws/voice/SES-12345?ticket=<ticket>`. The server validates the hash and atomically marks `consumed = true` in a single transaction.
4. **Replay Protection:** Re-submitting the same ticket fails immediately with HTTP 403 / WebSocket code 1008.

### 4.4 Explicit Role-Based Permission Matrix (Segregation of Duties)

To enforce least privilege, hierarchical role inheritance is replaced with an explicit, non-hierarchical permission matrix. **`SYSTEM_ADMIN` is strictly segregated from customer financial data and conversation records.**

| Permission / Operation | `ANALYST` | `AGENT` | `SUPERVISOR` | `COMPLIANCE_OFFICER` | `SYSTEM_ADMIN` |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **View Aggregated Reports & KPIs** | ✅ | ❌ | ✅ | ✅ | ❌ |
| **View Assigned Call Details & Notes** | ❌ | ✅ (Assigned only) | ✅ (Region cluster) | ✅ (Read-only) | ❌ |
| **Initiate Click-to-Call / Process Callback** | ❌ | ✅ (Assigned only) | ✅ (Reassign) | ❌ | ❌ |
| **Create / Pause / Cancel Campaigns** | ❌ | ❌ | ✅ | ❌ | ❌ |
| **Manage DND Suppression Lists** | ❌ | ❌ | ❌ | ✅ | ❌ |
| **Inspect Immutable Audit Ledger** | ❌ | ❌ | ❌ | ✅ | ❌ |
| **Request Audited PII Unmasking** | ❌ | ❌ | ❌ | ✅ (Requires reason) | ❌ |
| **Manage Infrastructure, DB & Workers** | ❌ | ❌ | ❌ | ❌ | ✅ |
| **Provision Operators & Assign Roles** | ❌ | ❌ | ❌ | ❌ | ✅ |
| **Trigger Schema Migrations** | ❌ | ❌ | ❌ | ❌ | ✅ |
| **Direct Access to Customer Banking Data** | ❌ | ❌ | ❌ | ❌ | ❌ (Strictly Prohibited) |

---

## 5. Data Protection, Cryptography & Recording Vault

### 5.1 Envelope Encryption & Key Lifecycle
* **Primitive:** AES-256-GCM with 96-bit unique random nonces and 128-bit authentication tags.
* **Key Hierarchy & Granularity:**
  1. **Key Encryption Key (KEK):** Held in HSM or Cloud KMS (Google Cloud KMS / AWS KMS). Never leaves the secure module.
  2. **Table/Epoch Data Encryption Key (DEK):** 256-bit key used for database fields (customer phone, email, notes).
  3. **Per-Recording DEK:** Every audio recording generates a unique, dedicated DEK.
     - *Cryptographic Shredding Advantage:* Satisfies DPDP Act / GDPR right-to-erasure. Deleting a specific recording's DEK in KMS renders that specific audio permanently unrecoverable, without requiring destructive physical disk overwrites or impacting other customer data.
* **Ciphertext Wire Format:**
  $$\text{enc:v1}:\langle\text{key\_id}\rangle:\text{base64}(\text{Nonce}_{12} \parallel \text{Ciphertext} \parallel \text{Tag}_{16})$$
* **Authenticated Additional Data (AAD) Context Binding:**
  To prevent ciphertext transplantation attacks across rows, the AAD is bound to the entity context:
  $$\text{AAD} = \text{"customers:phone:"} \parallel \text{customer\_ref}$$
* **Plaintext Write Policy:** **Production write paths MUST NEVER fall back to plaintext.** If KMS is unreachable or encryption fails, the transaction aborts. Plaintext reading is supported strictly for one-way legacy migration from Phase 1–3 databases and is certified disabled post-cutover.

### 5.2 Keyed Blind Indexes for Searchable Encryption
* Direct exact-match SQL queries on encrypted phone numbers (`WHERE phone = :p`) would require full table scans.
* **Mechanism:** A separate Blind Index Key (BIK) in KMS computes:
  $$\text{phone\_bidx} = \text{HMAC-SHA256}(\text{BIK}, \text{NormalizeE164}(\text{phone}))$$
* Stored in the database as `phone_bidx CHAR(64) UNIQUE INDEX`. B-tree lookups execute in sub-millisecond time with zero plaintext exposure to the database engine.

### 5.3 Recording Chunk-Level Encryption & Completion Manifests
* **Streaming Chunks:** Incoming audio is encrypted in sequential 64KB chunks under the per-recording DEK.
* **Monotonic Nonce Construction:**
  $$\text{Nonce}_{\text{chunk}} = \text{BaseNonce}_{32} \parallel \text{BigEndian64}(\text{chunk\_index})$$
  Chunk index is bound into the chunk's AAD: $\text{AAD} = \text{session\_id} \parallel \text{chunk\_index}$. This eliminates nonce collision and prevents chunk reordering or splicing.
* **Authenticated Recording-Completion Manifest:**
  To detect missing or truncated trailing chunks (e.g. an attacker stripping an operator's disclosure or customer's refusal):
  - Upon clean call termination, an authenticated manifest chunk is written:
    $$\text{Manifest} = \{\text{session\_id}, \text{total\_chunks}, \text{total\_bytes}, \text{sha256\_digest}, \text{completed\_at}\}$$
  - The manifest is authenticated with an AES-GCM tag under the recording DEK.
  - The playback service checks $\text{Actual Chunks Read} == \text{Manifest.total\_chunks}$. If trailing chunks are missing, the playback engine raises `RECORDING_TRUNCATED_TAMPERED` and blocks playback.
  - Dropped or interrupted calls are explicitly flagged `STATUS = INCOMPLETE_DROPPED`, documenting the exact flushed chunk count without claiming clean completion.

### 5.4 Realistic Memory Protection
* Python strings are immutable and interned; claiming that clearing a Python string in memory guarantees erasure is technically invalid.
* Phase 4 enforces realistic memory hygiene:
  - Cryptographic keys in Python are handled strictly as mutable `bytearray` buffers and overwritten with zeros immediately after cipher instantiation.
  - High-security key management worker processes lock pages in virtual memory using `mlock` via `ctypes` to prevent swapping keys to disk.
  - Linux container core dumps are disabled via `prctl(PR_SET_DUMPABLE, 0)`.
  - Master keys (KEKs) remain strictly inside the hardware security boundary (HSM/KMS) and never enter application memory.

---

## 6. PostgreSQL Production Migration & Connection Pooling

### 6.1 Database Engine & Driver Architecture
* **Selected Driver:** `psycopg` (v3) with SQLAlchemy 2.0.
* **Dual-Engine Architecture:**
  1. **Asynchronous Engine (FastAPI Web Layer):** `create_async_engine("postgresql+psycopg_async://...")` manages HTTP requests and real-time WebSocket connection lifecycles without blocking event loops.
  2. **Synchronous Engine (Background Workers):** `create_engine("postgresql+psycopg://...")` manages background campaign pacing, outbox processors, and batch data pumps.

### 6.2 PgBouncer Connection Pool Allocation
To support high concurrency without exceeding PostgreSQL backend limits:
* **Pooling Mode:** PgBouncer in **Transaction Pooling Mode** (`pool_mode = transaction`).
* **Prepared Statements Guard:** Configured with `prepare_threshold=None` in SQLAlchemy connect arguments to eliminate collision risks across transaction-pooled connections.
* **Rigorous Pool Sizing Calculation:**
  $$\text{Total App Pool} = (N_{\text{web}} \times \text{Pool}_{\text{web}}) + (N_{\text{worker}} \times \text{Pool}_{\text{worker}}) + \text{Admin Reserve}$$
  - 4 Web Pods: Pool size 8 per pod, max overflow 4 $\to 4 \times 12 = 48$ max connections.
  - 2 Worker Pods: Pool size 5 per pod, max overflow 2 $\to 2 \times 7 = 14$ max connections.
  - Admin & Migration Reserve: 10 connections.
  - **Total Application Connections:** $48 + 14 + 10 = 72$ connections, staying well below the PostgreSQL `max_connections = 100` ceiling ($72\% \le 80\% \text{ safety threshold}$).

### 6.3 3-Stage SQLite-to-PostgreSQL Cutover Pipeline
1. **Phase A (Pre-Cutover Preparation):** PostgreSQL schema deployed via Alembic (`0001` $\to$ `0002` $\to$ Phase 4 migrations). Outbox and encryption worker processes verified against staging fixtures.
2. **Phase B (Maintenance Window & Read-Only Freeze):**
   - Outbound campaigns and callbacks are paused.
   - FastAPI server enables maintenance mode (`HTTP 503: Maintenance`).
   - SQLite database is placed into strict read-only mode via `PRAGMA query_only = ON;`. No further SQLite writes can occur.
   - A streaming data pump extracts data table-by-table using binary `COPY`, generates blind indexes, and envelope-encrypts sensitive fields.
   - **Verification Suite:**
     - 100% row-count parity across all tables.
     - SHA-256 composite checksum matching on deterministic keys (`customer_ref`, `campaign_id`, `session_id`).
     - Foreign key integrity verification.
   - **Abort Path (Pre-Cutover Only):** If verification fails, SQLite is unfrozen (`query_only = OFF`), maintenance mode is disabled, and traffic resumes on SQLite with zero data loss.
3. **Phase C (Post-Cutover Authoritative State):**
   - If verification succeeds, application configuration switches `DATABASE_URL` to PostgreSQL, background outbox workers start, and maintenance mode is removed.
   - **PostgreSQL is now authoritative.** SQLite is permanently retired and archived read-only.
   - **Post-cutover rollback to SQLite is STRICTLY FORBIDDEN**, as SQLite will lack all subsequent production writes. Disaster recovery relies exclusively on PostgreSQL streaming replicas and Point-In-Time-Recovery (PITR).

---

## 7. Transactional Outbox & Resilient Worker State Machines

### 7.1 Atomic Outbox Mutation
To prevent dual-write inconsistencies (where a database update succeeds but an external event or background job is lost):
1. Every domain mutation (e.g., callback marked due, contact dispositioned) is executed in a SQL transaction.
2. In the **exact same SQL transaction**, an outbox record is inserted into `outbox`:
   ```python
   with db.session() as s:
       contact.status = "COMPLETED"
       s.add(OutboxRow(
           outbox_id=f"OUT-{uuid4().hex[:12].upper()}",
           event_topic="campaign_contact.completed",
           payload={"contact_id": contact.contact_id, "disposition": "CLOSED"},
           idempotency_key=f"IDEMP-CONTACT-{contact.contact_id}-COMPLETED",
           status="PENDING",
           created_at=utcnow(),
       ))
       s.commit()  # Domain update and outbox event commit atomically
   ```

### 7.2 Worker Claiming, Leases & Crash Recovery
* **Pessimistic Locking Query:**
  ```sql
  SELECT outbox_id, event_topic, payload, idempotency_key, attempts
  FROM outbox
  WHERE status IN ('PENDING', 'FAILED_RETRY')
    AND (locked_until IS NULL OR locked_until < NOW())
  ORDER BY created_at ASC
  LIMIT 10
  FOR UPDATE SKIP LOCKED;
  ```
* **Lease Duration:** The claiming worker sets `status = 'PROCESSING'`, `locked_until = NOW() + INTERVAL '30 seconds'`, and `worker_id = :worker_id`.
* **Crash Recovery:** If a worker terminates abruptly, its lease expires (`locked_until < NOW()`). On the next polling cycle, a surviving worker automatically re-claims the event.

### 7.3 At-Least-Once Delivery vs. Exactly-Once Logical Effects Boundary
* **Physical Delivery Invariant:** Physical message delivery across networks, HTTP endpoints, WebSocket transports, and worker polling loops is strictly **AT-LEAST-ONCE**. Worker failures, network retries, and process restarts can result in duplicate message delivery.
* **Explicit Idempotent Transaction Boundaries:**
  "Exactly-once" business behavior is guaranteed **STRICTLY AND ONLY within explicit idempotent transaction boundaries**:
  1. **Internal Database State:** Bound by PostgreSQL ACID transactions. State transitions use atomic conditional updates:
     ```sql
     UPDATE campaign_contacts
     SET status = 'QUEUED', updated_at = NOW()
     WHERE contact_id = :cid AND status IN ('PENDING', 'RETRY_SCHEDULED')
     RETURNING contact_id;
     ```
     If an outbox event is re-processed, the conditional update matches zero rows and mutates no state.
  2. **External Dispatches & Side Effects:** Bound by an explicit, mandatory `idempotency_key` stored in `outbox.idempotency_key` and transmitted downstream via HTTP headers (`Idempotency-Key: <key>`) or gateway call request IDs. Downstream systems maintain an idempotency table; re-deliveries return the cached response with zero duplicate physical dialing or message dispatch.
* **Outside these explicit idempotent boundaries, delivery semantics remain strictly at-least-once.**
* **Dead-Letter Queue:** Events failing 5 consecutive attempts transition to `status = 'DEAD_LETTER'` with full exception preservation, unblocking queues and alerting on-call engineers.

---

## 8. Configurable India Calling Policy & Regulatory Compliance

### 8.1 Applicable Regulatory Framework
The policy engine is designed to align with the **Telecom Commercial Communications Customer Preference Regulations (TCCCPR, 2018)**, read alongside subsequent TRAI Directions, Tariff Orders, and 2021–2024 Amendments, including:
- Mandatory entity, header, and content template registration on Distributed Ledger Technology (DLT) portals.
- 140-series dialing allocations for promotional communications.
- Digital Consent Acquisition (DCA) framework and national Scrubbing System integration.
- Strict anti-harassment frequency caps and velocity limits.

### 8.2 Calling Windows & Campaign Classification
* **Important Compliance Clarification:** Calling windows and campaign classifications are **UNAPPROVED CONFIGURATION PLACEHOLDERS** until explicitly certified and signed off in writing by Town Bank Legal & Compliance:
  - Default Promotional Template (Unapproved): Strict 09:00 – 20:00 IST.
  - Default Service/Transactional Template (Unapproved): 08:00 – 21:00 IST (or scheduled callback).
* All time checks execute strictly in Indian Standard Time (IST, UTC+05:30).

### 8.3 Two-Stage Fail-Closed Enforcement
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
│     └── Validates against certified bank hours         │
│                                                        │
│  3. Real-Time DND Scrub against Registry               │
│     └── Bank DND + Telecom Category Scrub              │
│                                                        │
│  4. Frequency Capping & Velocity Limits                │
│     └── Max 3 attempts/week, Min 24h gap               │
└────────────────────────────────────────────────────────┘
            │
            ├── APPROVED ──► Proceed to Dispatch
            │
            └── REJECTED / UNRESOLVED ──► Mark DND_EXCLUDED (Fail-Closed)
```

1. **Stage 1 (Enrollment Scrub):** Executed when contacts are uploaded or campaigns generated.
2. **Stage 2 (Pre-Dispatch Real-Time Scrub):** Executed milliseconds before the dialing worker triggers a call. If a customer registered on DND or revoked consent between enrollment and dispatch, the call is blocked immediately.
3. **Fail-Closed Principle:** If DND status, customer preference, or telecom registry connectivity cannot be conclusively verified (e.g. timeout, unresolvable number), the engine **fails closed**—the call is marked `DND_UNKNOWN_BLOCKED` and excluded from dialing.
4. **Opt-Out Precedence:** An explicit customer opt-out during a live call immediately overrides all prior consents and updates the bank's internal suppression registry in real time.
5. **Telephony Reality:** Application logic alone does NOT establish TRAI compliance. Full legal compliance requires carrier-level 140-series CLI provisioning and Access Provider DLT integration.

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
* `kural_turn_latency_first_audio_ms` (Histogram buckets: 300, 600, 900, 1200, 1500, 1800, 2500)
* `kural_turn_latency_full_ms` (Histogram buckets: 500, 1000, 1500, 2000, 2500, 3500)
* `kural_active_voice_sessions` (Gauge)
* `kural_outbox_lag_seconds` (Gauge measuring oldest unprocessed event)
* `kural_dnd_blocks_total` (Counter)

### 9.3 Empirical Load Test Specifications
All concurrency claims are categorized as **TARGETS** until empirically validated on production infrastructure:
* **Target SLO:** 100 concurrent bidirectional voice sessions per node at $P_{95}$ Time-to-First-Audio $< 1,800\text{ ms}$.
* **Tier 1 (Internal Architecture Benchmark):** High-fidelity mocked STT/TTS/LLM providers measuring pure KURAL FSM, PostgreSQL, outbox, and WebSocket server capacity.
* **Tier 2 (End-to-End Live Provider Benchmark):** Real external APIs under live provider quota limits (10–20 concurrent calls).

---

## 10. Security, Incident Response & Tamper-Evident Ledger

### 10.1 Cryptographic Tamper-Evident Audit Ledger
* **Monotonic Sequence & HMAC Hash Chaining:**
  Each record in `operations_audit_events` contains an immutable hash chaining link:
  $$\text{Hash}_n = \text{HMAC-SHA256}\Big(\text{AuditKey},\; \text{Hash}_{n-1} \parallel \text{Seq}_n \parallel \text{Timestamp}_n \parallel \text{Actor}_n \parallel \text{Action}_n \parallel \text{Resource}_n \parallel \text{Detail}_n\Big)$$
* **Concurrent Sequencing Architecture:**
  To prevent transaction serialization bottlenecks on audit insertion, sequence generation uses a dedicated PostgreSQL sequence paired with row-level locks on a singleton `audit_head` record, ensuring strict monotonic sequencing without table-level locking.
* **Verification & Tamper Detection:**
  An automated verification worker walks the chain checking that:
  1. $\text{Seq}_n == \text{Seq}_{n-1} + 1$ (detects deleted or dropped audit events).
  2. $\text{Hash}_n == \text{HMAC}(\text{AuditKey}, \dots)$ (detects modified record content).
  Any gap or mismatch raises an immediate high-priority compliance alert.
* **External Sealing:** Every 24 hours, the latest sequence hash is digitally signed and exported to Write-Once-Read-Many (WORM) storage (AWS S3 Object Lock / cloud immutable storage).

---

## 11. Revised Secure Rollback & Recovery Procedures by Milestone

**Core Invariant:** All production rollback paths that disable authentication, allow plaintext writes, revert to permissive calling, or fall back to stale SQLite databases are **PERMANENTLY REMOVED**. Every failure fails closed, preserves forensic evidence, and requires controlled operator recovery.

| Milestone | Rollback / Failure Trigger | Secure Technical Recovery Procedure |
| :--- | :--- | :--- |
| **M4.1 (RBAC/Auth)** | Authentication defect blocks valid operator access or voice connections. | **STRICT FAIL-CLOSED:** Never disable authentication or open routes.<br>1. Utilize offline break-glass administrator account (`python -m kural.cli init-admin`) with physical console access.<br>2. Roll forward via atomic bugfix or roll back application container to previous authenticated release binary after confirming token table compatibility.<br>3. If token validation is broken, return HTTP 401/403 and WebSocket 1008, preserve audit logs, and require operator intervention. |
| **M4.2 (Encryption/PII)** | KMS key unwrap failure, DEK mismatch, or ciphertext corruption. | **STRICT FAIL-CLOSED:** Never fall back to writing plaintext PII or unencrypted audio.<br>1. Write operations abort immediately with transaction rollback.<br>2. Trigger automated failover to standby KEK / KMS endpoint.<br>3. If unrecoverable, halt affected ingestion workers, preserve raw ciphertexts and KMS transaction IDs for forensic analysis, and alert SecOps on-call. |
| **M4.3 (PostgreSQL/Outbox)** | Database connection loss or outbox worker stall post-cutover. | **NO SQLITE ROLLBACK:** SQLite is permanently retired post-cutover.<br>1. Failover to PostgreSQL hot-standby streaming replica.<br>2. Outbox worker stalls recover automatically as lease timeouts (`locked_until < NOW()`) expire.<br>3. Persistent poison-pill messages are routed to `DEAD_LETTER` with payload preservation, alerting on-call without blocking queues. |
| **M4.4 (Policy/Audit)** | Compliance policy misconfiguration blocks valid service callbacks, or audit chain breaks. | **STRICT FAIL-CLOSED:** Never widen calling windows or permit dialing on error.<br>1. Revert policy configuration ONLY to a previously certified, compliance-signed policy version (e.g. `policy_v1.0.yaml`), never to an unvetted permissive default.<br>2. If audit chain verification fails, freeze affected operator accounts, export current chain state for compliance review, and alert CISO. |
| **M4.5 (Telemetry/Scale)** | High-concurrency load induces memory pressure or connection exhaustion. | **CONTROLLED THROTTLING:** Reverting blindly to commit `59edf51` is prohibited due to schema incompatibility.<br>1. Apply operational throttling: scale down worker concurrency, reduce PgBouncer max pool, and disable non-essential OpenTelemetry trace exporters.<br>2. Scale application container pods horizontally.<br>3. Code rollbacks require deploying a container that matches the active database schema and encryption version. |

---

## 12. Revised Milestones & Concrete Acceptance Tests

```
[ M4.1: RBAC & Auth ] ──► [ M4.2: Data Security & PII ] ──► [ M4.3: PostgreSQL & Outbox ]
                                                                      │
[ M4.5: Scale, Load & Gates ] ◄── [ M4.4: Telemetry, Policy & Audit ] ┘
```

### Milestone 4.1: Authentication, Authorization & RBAC
* **Concrete Acceptance Tests:**
  1. `test_cookie_host_prefix_compliance`: Verifies `Set-Cookie` header includes `__Host-` prefix, `Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/`, and NO `Domain`.
  2. `test_refresh_token_concurrent_atomic_exchange`: Verifies parallel refresh requests using row-level locking return the single generated token without generation divergence or family revocation.
  3. `test_refresh_token_concurrent_grace_window`: Verifies concurrent refresh requests within 15 seconds succeed without triggering reuse alerts.
  4. `test_refresh_token_family_reuse_revocation`: Verifies presenting a revoked refresh token after 15 seconds immediately invalidates the entire token family and terminates sessions.
  5. `test_jwt_revocation_latency_benchmark`: Measures empirical $P_{95}$ latency of JWT rejection following `token_version` increment, validating against the target SLO.
  6. `test_system_admin_pii_access_blocked`: Verifies `SYSTEM_ADMIN` role receives HTTP 403 on `/api/calls/{id}`, `/api/recordings/{id}`, and customer tables.
  7. `test_single_use_websocket_ticket_burn`: Verifies that connecting twice with the same ticket fails on the second attempt with WebSocket code 1008.

### Milestone 4.2: Data Protection, Cryptography & PII
* **Concrete Acceptance Tests:**
  1. `test_envelope_encryption_aad_tamper_rejection`: Verifies modifying the AAD context (`customer_ref`) causes AES-GCM tag verification failure.
  2. `test_per_recording_dek_cryptographic_shredding`: Verifies destroying a recording's DEK renders its audio unrecoverable while all other recordings remain decryptable.
  3. `test_recording_manifest_truncation_detection`: Verifies stripping trailing 64KB audio chunks is detected by manifest validation, raising `RECORDING_TRUNCATED_TAMPERED`.
  4. `test_plaintext_write_rejection`: Verifies repository layer rejects any write operation without `enc:v1:` envelope in production mode.
  5. `test_blind_index_deterministic_search`: Verifies exact-match customer lookup via HMAC blind index matches plaintext without full-table decryption.

### Milestone 4.3: PostgreSQL Migration & Durable Outbox
* **Concrete Acceptance Tests:**
  1. `test_sqlite_cutover_consistency`: Verifies 100% row-count parity and composite SHA-256 hash matching during data pump migration.
  2. `test_outbox_atomic_commit`: Verifies domain state mutation and outbox event commit in the exact same transaction; simulating a rollback leaves neither.
  3. `test_outbox_worker_crash_recovery`: Verifies an uncompleted outbox lease is safely claimed and processed by a surviving worker after lease expiry.
  4. `test_at_least_once_idempotent_dispatch`: Verifies that re-dispatching an outbox event with the same `idempotency_key` produces zero duplicate side effects.
  5. `test_outbox_idempotent_external_side_effect_deduplication`: Verifies that replaying an outbox event with a duplicate `idempotency_key` against the telephony gateway simulation produces zero duplicate dial requests.
  6. `test_connection_pool_bounds_under_load`: Verifies total application connection usage stays within the 72-connection allocation under maximum concurrency.

### Milestone 4.4: Compliance Policy Engine & Tamper-Evident Ledger
* **Concrete Acceptance Tests:**
  1. `test_pre_dispatch_dnd_fail_closed`: Verifies that a simulated telecom DND registry timeout blocks outbound dialing immediately.
  2. `test_opt_out_realtime_precedence`: Verifies customer opt-out during a call instantly overrides campaign enrollment.
  3. `test_real_customer_voice_external_stt_block`: Verifies that the voice orchestrator strictly blocks session initialization if real customer mode is set and external STT is configured without on-premises certification.
  4. `test_audit_hash_chain_gap_detection`: Verifies deleting or modifying an audit row causes the chain verification utility to pinpoint the exact tampered sequence index.
  5. `test_metrics_t0_to_t8_telemetry`: Verifies Prometheus `/metrics` correctly differentiates between Time-to-First-Audio ($T_6$) and Full Turn Completion ($T_8$).

### Milestone 4.5: Empirical Load Testing & Production Security Gates
* **Concrete Acceptance Tests:**
  1. `test_mypy_strict_clean`: Verifies zero static typing errors across all backend modules.
  2. `test_bandit_ast_security_clean`: Verifies zero high/medium security vulnerabilities detected via AST analysis.
  3. `test_k6_sustained_concurrency_slo`: Executes Tier 1 benchmark verifying 100 concurrent sessions maintain $P_{95}$ Time-to-First-Audio $< 1,800\text{ ms}$.
  4. `test_phase1_to_phase3_full_regression`: Verifies 100% of Phase 1–3 regression tests (173/173) pass cleanly.

---

## 13. Decision Log

### 13.1 Non-Negotiable Invariants
1. **FSM Supremacy:** KURAL FSM is the sole authority for state, policy, and spoken turns. LLMs are confined strictly to intent and entity classification.
2. **Fail-Closed Everything:** Security, authentication, encryption, and calling policy fail closed. Unsafe rollbacks (plaintext fallbacks, unauthenticated access) are permanently prohibited.
3. **No Unencrypted PII at Rest:** All PII in database and disk audio must be envelope-encrypted with AES-256-GCM and context AAD.
4. **Strict Post-Cutover Single Authority:** PostgreSQL is the sole authoritative store post-cutover. Reverting to SQLite is strictly forbidden.
5. **No Production Telephony in Phase 4:** Carrier SIP/PSTN trunking remains strictly deferred to Phase 5.

### 13.2 Architectural Decisions Changed in v1.0.2
* **Decision 1 (Rollbacks):** Removed all unsafe rollback modes (`REQUIRE_AUTH=false`, plaintext PII writes, permissive calling policy, SQLite fallback post-cutover, blind git checkouts). Replaced with fail-closed procedures, break-glass admin, and schema-compatible roll-forwards.
* **Decision 2 (Voice Boundary):** Documented raw audio containing credentials prior to STT. Formally defined Option A (bank-controlled boundary) as canonical, with open-weights Faster-Whisper / Triton as the verified on-prem fallback. Defined Option B (external SaaS) as restricted to synthetic testing pending bank CISO approval.
* **Decision 3 (Cookies & Sessions):** Corrected `__Host-` cookie configuration to `Path=/` with no `Domain`. Added atomic row locking with 15-second grace window for concurrent refreshes and immediate JWT revocation via `token_version` (target SLO $P_{95} < 5\text{ ms}$).
* **Decision 4 (Cryptography):** Selected per-recording DEKs for cryptographic shredding. Added authenticated recording-completion manifests to detect chunk truncation. Documented realistic Python memory guarantees.
* **Decision 5 (Cutover & Outbox):** Defined 3-phase maintenance freeze for SQLite cutover. Distinguished at-least-once outbox delivery from exactly-once side effects via idempotency keys. Unified `psycopg` v3 async and sync engines with 72-connection pool limits.
* **Decision 6 (RBAC & Audit):** Replaced hierarchical inheritance with explicit permission matrix strictly separating `SYSTEM_ADMIN` from customer data. Added mandatory MFA for privileged roles and non-blocking monotonic audit sequencing.
* **Decision 7 (Regulatory):** Referenced comprehensive TCCCPR framework and subsequent amendments. Marked calling hours as unapproved placeholders requiring bank legal sign-off. Emphasized carrier DLT integration requirements.

---

## 14. Outstanding Decisions Requiring Bank / Governance Approval

The following items are formal governance gates that require written sign-off by Town Bank authorities prior to initiating production deployment:

1. **Voice-Provider STT Processing Model:** Written approval from Bank CISO selecting between on-premises container deployment (Option A: Sarvam on-prem or Faster-Whisper Triton) or formal cloud SaaS exception (Option B with zero-retention DPA).
2. **TRAI Calling Windows & Campaign Categories:** Formal written sign-off by Bank Legal & Compliance on operational calling hours and campaign classifications (Service vs Promotional).
3. **KMS Key Custody Agreement:** Written agreement on whether master encryption keys (KEKs) reside in Town Bank's internal HSM, Google Cloud KMS, or AWS KMS.
4. **Audit Retention & Purge Policy:** Sign-off on the 180-day standard retention window versus the 3-year financial dispute hold requirement.
5. **Telephony Carrier & DLT Registration:** Selection of licensed Access Provider for 140-series CLI allocation and enterprise DLT portal registration.

---

## 15. Architecture Addendum v1.0.2-A: Final Focused Clarifications

This addendum formalizes the three focused resolutions approved during the final Phase 4 v1.0.2 architecture review:

### 15.1 Speech Processing Feasibility & Bank-Controlled Invariant
1. **Commercial Availability Reality:** Proprietary Sarvam Saaras STT is commercially offered primarily via managed multi-tenant cloud APIs (`api.sarvam.ai`). Dedicated on-premises container appliances require specialized vendor infrastructure partnerships that remain unverified for the initial deployment.
2. **Approved Verified Alternative:** If an on-premises Sarvam container cannot be verified and certified prior to production deployment, Town Bank mandates deployment of an open-weights, bank-hosted ASR model within its private VPC:
   - **Primary Engine:** Containerized **Faster-Whisper (Whisper-large-v3-turbo / medium.en)** or **NVIDIA NeMo Conformer-CTC** running on Triton Inference Server in the bank's private GPU cluster.
   - **Zero Egress:** Audio never leaves the bank network; spoken credentials remain strictly inside the bank perimeter.
3. **Operational Policy:** External speech processing via Sarvam cloud APIs remains **STRICTLY DISABLED for all real customer voice sessions**. It is approved exclusively for synthetic testing until either the verified on-premises appliance is deployed or formal bank CISO approval is granted.

### 15.2 Race-Safe Refresh Grace Window & Measured JWT Revocation Target
1. **Atomic Token Exchange:** Parallel refresh requests are serialized using database row-level locking (`SELECT ... FOR UPDATE` on `refresh_tokens`). The first arrival issues token $T_{n+1}$, marks $T_n$ with `replaced_at = NOW()`, and records `next_token_id`.
2. **Replay vs. Grace Window:**
   - In-flight requests presenting $T_n$ within the 15-second grace window receive the already-issued $T_{n+1}$ without triggering security alerts.
   - Any presentation of $T_n$ *after* 15 seconds (or presentation of an older generation) is treated as an active replay attack, immediately revoking the entire `family_id` and all associated user sessions.
3. **JWT Revocation Latency Target:** Sub-millisecond JWT rejection is formally recognized as an **Unverified Latency Target** ($P_{95} < 5\text{ ms}$ via local memory cache). It will be empirically benchmarked under production load in Milestone 4.1 rather than assumed without measurement.

### 15.3 Exactly-Once Logical Effects vs. At-Least-Once Delivery Semantics
1. **Physical Delivery Semantics:** All transport and queue mechanics operate strictly under **at-least-once delivery semantics**.
2. **Logical Effects Scope:** Exactly-once business effects are achieved **strictly within explicit idempotent transaction boundaries**:
   - Internal state transitions: Enforced via PostgreSQL ACID conditional updates (`WHERE status = 'EXPECTED'`).
   - External telephony & webhooks: Enforced via mandatory `idempotency_key` propagation and downstream deduplication tables.
3. **Boundary Rule:** Anywhere outside these explicit boundaries, systems must assume at-least-once delivery and implement idempotent handlers.
