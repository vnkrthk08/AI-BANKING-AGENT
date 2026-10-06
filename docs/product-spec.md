# Product Specification & Operational Scope

## System Overview
KURAL (Knowledge-driven Unified Response & Assistance Layer) is the deterministic policy and decision layer powering AVA, an outbound banking voice assistant. The operations console provides bank operations teams with observability over synthetic outbound calls, follow-up workflows, quality assurance, and compliance governance.

Core architectural principle: **AI understands; KURAL decides.**

## Target Personas

- **Operations Managers**: Monitor campaign-level performance, conversion rates, disposition distributions, unit costs, and SLA adherence trends.
- **Supervisors**: Real-time queue supervision, agent workload balancing, live call monitoring, and escalation resolution.
- **Human Support Agents**: Dedicated case workspace to manage customer callbacks, review automated turn histories, and log case outcomes.
- **Compliance Auditors**: Inspect customer consent records, data boundary enforcement, PII redaction audit logs, and regulatory export packages.

## Product Capabilities & Boundary Enforcement

1. **Deterministic State Enforcement**: All conversation transitions, business actions (case creation, callback booking), and knowledge retrieval are strictly controlled by KURAL's deterministic finite state machine (FSM). LLMs are restricted to semantic intent classification proposals.
2. **Privacy & Redaction Boundary**: Customer authentication secrets (OTP, PIN, passwords, CVV/CVC) and PII are screened and redacted prior to persistence or model egress.
3. **Audit Trail**: Every customer turn, intent classification, policy authorization, state transition, and terminal disposition writes an immutable audit record.
4. **Operations Console**: Desktop-first management dashboard built for Indian banking operations (IST timezone, synthetic masked customer IDs, localized workflows).

## Operating Constraints

- Outbound calling window strictly bounded to compliant banking hours (09:00 - 21:00 IST).
- All customer identifiers, phone numbers, and account records displayed in the UI are synthetic and masked (e.g., `+91 98XXX XX231`, `CUST-00042`).
- Safe fallback mechanism: Any provider timeout, malformed payload, or API failure automatically defaults to deterministic phrase-based intent classification.
