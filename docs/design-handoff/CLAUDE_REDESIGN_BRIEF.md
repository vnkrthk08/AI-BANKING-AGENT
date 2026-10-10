# Claude Redesign Brief — KURAL AVA Banking Platform

**Target Designer / Architect:** Claude 3.7 / Opus / Sonnet  
**Parent Document:** [`AVA_PLATFORM_A_TO_Z_HANDOFF.md`](./AVA_PLATFORM_A_TO_Z_HANDOFF.md)  
**Screenshots Directory:** [`./screenshots/`](./screenshots/)  
**Repository:** [https://github.com/vnkrthk08/AI-BANKING-AGENT](https://github.com/vnkrthk08/AI-BANKING-AGENT)  
**Date:** October 10, 2026  

---

## 1. What You Need to Know in 2 Minutes

**KURAL AVA** is an enterprise AI Voice Agent and Operations Workspace built for automated Indian retail banking outreach (demonstrated under the fictional entity **Town Bank**). 

The platform does two critical things:
1. **Runs Real-Time AI Phone Calls:** Conducts ultra-low-latency (<800ms) voice conversations with banking customers in English, Hindi, and Tamil using Sarvam AI STT/TTS and Google Gemini 2.5 Flash, guided by **Subbu**, the conversational assistant.
2. **Manages Banking Operations:** Provides Operations Managers, Supervisors, Agents, and Compliance Officers with a full dashboard to monitor live calls, manage outreach campaigns, resolve technical support escalations, manage scheduled callbacks, and review DPDP Act regulatory audit logs.

### The Sacred Architectural Rule
> **"AI Understands; Deterministic Rules Decide."**
The Large Language Model operates strictly as an intelligence/NLU layer for intent proposal. The **KURAL Finite State Machine (FSM)** is the sole authority for state transitions, banking policy checks (RBI calling hours, no-Sunday-calls rule), credential protection (OTP/PIN redaction), and spoken responses. You must **never** bypass or replace the deterministic FSM in your redesign.

---

## 2. Who Uses the System

| User Persona | Key Screen | Primary Goal |
| :--- | :--- | :--- |
| **Operations Manager** | Executive Overview (`/executive`) & Campaigns (`/campaigns`) | Track branch outreach performance, answer rates, and launch automated call campaigns. |
| **Call Center Supervisor** | Team Board (`/team`) & Live Calls (`/live-calls`) | Monitor floor capacity, agent workloads, and listen in on active customer calls. |
| **Human Banking Agent** | My Work (`/my-work`) & Callbacks (`/callbacks`) | Handle customer issues escalated from AI calls and dial scheduled callbacks. |
| **Compliance Officer** | Compliance (`/compliance`) & Reports (`/reports`) | Verify DPDP Act 2023 consent records, audit PII masking, and schedule regulatory reports. |

---

## 3. The Core Visual & UX Problems You Need to Fix

1. **Severe Developer & Technical Clutter:**
   - The AI Voice Agent page (`/test-console`) is cluttered with developer test pills (`Turn 1 Confirm Identity`, `Turn 5 (Guard)`, `G-02 Callback`). It looks like an engineering test harness rather than an elite banking operations console.
   - Microsecond latency telemetry (`VAD ms`, `STT ms`, `FSM ms`) is displayed directly in the main view, overwhelming operators during calls.
2. **Boxy, Heavy, Dark-Slate Styling:**
   - High visual fatigue from repetitive 1px semi-transparent borders and dark navy backgrounds (`#0f172a`).
   - Lacks modern typography hierarchy, financial tabular numerals, and purposeful white space.
3. **Fragmented Navigation (14 Routes):**
   - 14 separate sidebar routes create excessive cognitive load.
   - The top bar permanently displays an oversized `<select>` dropdown to switch active roles, which is unrealistic for an enterprise role-based application.
4. **Poor Mobile & Tablet Responsiveness:**
   - Tables horizontally overflow on mobile devices (`375×812`).
   - The voice console orb and transcript get crushed on small screens.

---

## 4. Design Direction for Your Redesign

### 4.1 Aesthetic Vision: "Next-Level Institutional Banking"
- **Color Architecture:** Deep Institutional Navy (`#0a192f` / `#0f2744`) paired with a Crisp Canvas background (`#f8fafc` for light mode, `#0b1329` for dark mode).
- **Semantic Accents:**
  - Emerald Green (`#10b981`) for active voice audio, online connectivity, and verified consent.
  - Warm Amber (`#f59e0b`) for pending SLAs and silence reminder warnings.
  - Coral Rose (`#f43f5e`) for security blocks, call termination, and errors.
- **Elevation & Depth:** Replace harsh card borders with smooth subtle drop shadows, clean dividers, and comfortable card padding.
- **Typography:** Modern, clean typography (Inter / SF Pro Display) with `font-variant-numeric: tabular-nums` for timestamps, durations, and metrics.

### 4.2 Consolidated Navigation Architecture (7 Unified Hubs)

Consolidate the current 14 scattered pages into **7 purposeful operational hubs**:

```
1. 🏠 OVERVIEW (/executive)
   └── High-level KPIs, call volume trends, campaign pacing progress, active floor status.

2. 🎙️ VOICE STUDIO (/test-console)
   └── The flagship AI Voice Agent console with modern telephony controls and audio presence orb.

3. 📞 CALLS HUB (/call-log & /live-calls)
   └── Unified view combining Live Calls monitoring and Historical Call Log with recording playback.

4. 📢 CAMPAIGNS (/campaigns)
   └── Outreach campaigns, dialing pacing, target segments, and CSV contact queue import.

5. 📋 WORK & ESCALATIONS (/escalations & /callbacks)
   └── Unified operational queue combining technical support cases and scheduled callbacks.

6. 👥 TEAM ROSTER (/team & /my-work)
   └── Supervisor agent management, floor availability status, and individual agent workspace.

7. 🛡️ GOVERNANCE & AUDIT (/compliance & /system-health)
   └── DPDP Act consent ledger, PII redaction audit, infrastructure health, and scheduled reports.
```

---

## 5. Flagship AI Voice Agent Page (`/test-console`): Specific Redesign Rules

The Voice Agent console is the centerpiece of the application. Treat it with the highest priority:

### What Must Be in the Main View (Operator Workspace):
1. **Customer Context Banner:** Customer Name (`Rahul Sharma`), Customer ID (`CUST-00001`), Masked Phone (`+91 98XXX XX000`), Account Type, Language, and Verified Consent badge.
2. **Central Presence Orb:** Fluid, elegant circular audio avatar with radial wave pulses driven by real-time speech energy. Clean status caption below the orb (`Listening to customer`, `Subbu is speaking`, `Reminding customer...`).
3. **Telephony Control Bar:**
   - Prominent `Start Call` / `End Call` action button.
   - Microphone `Mute / Unmute` toggle.
   - `Barge-In / Interrupt` button.
   - Customer `Verification Checklist` (Identity, Consent, Account confirmation).
4. **Live Transcript Panel:** High-readability bi-directional conversation feed with clear distinction between `Subbu` and `Customer`, with real-time interim partial transcript streaming.

### What Must Move to a Retractable Side Drawer (Engineering Diagnostics):
- **Turn Latency Telemetry:** Detailed millisecond breakdown (VAD endpoint ms, STT ms, Gemini LLM ms, KURAL decision ms, Bulbul TTS first-chunk ms, total turn ms).
- **Latency Percentiles:** P50, P95, and P99 latency statistics.
- **Hardware Metrics:** AudioWorklet buffer sizes, audio packet counters, server frame counters.
- **Scenario Simulator:** Quick-test pills (Steps 1–9, Golden Scenarios G-02 through G-10) for automated test driving.

---

## 6. Non-Negotiable Backend Invariants You Must Preserve

When you design the frontend structure, you must maintain complete compatibility with the backend:

1. **Preserve API Endpoint Contracts:**
   - `POST /api/v1/sessions` (Create session)
   - `WS /api/v1/voice/realtime` (Streaming audio WebSocket)
   - `GET /api/calls` & `GET /api/calls/{id}/recording` (Call log & audio recordings)
   - `GET /api/campaigns` & `POST /api/campaigns/{id}/start` (Campaign pacing)
   - `GET /api/callbacks` & `POST /api/callbacks/{id}/reschedule` (Callbacks)
   - `GET /api/escalations` & `PATCH /api/escalations/{id}` (Support cases)
   - `GET /api/agents` & `PATCH /api/agents/{id}/status` (Agent availability)
   - `GET /api/compliance/summary` & `GET /api/audit` (Governance records)
2. **Preserve Zero-Leakage Credential Boundary:** Never surface raw unmasked customer phone numbers, OTPs, CVVs, or card numbers in transcripts or cards.
3. **Preserve Deterministic FSM Authority:** The frontend must never attempt to bypass the backend KURAL FSM engine or generate unapproved responses directly from an LLM.

---

## 7. Design Reference Links

- **Full Master Technical Handover:** [`docs/design-handoff/AVA_PLATFORM_A_TO_Z_HANDOFF.md`](./AVA_PLATFORM_A_TO_Z_HANDOFF.md)
- **Current Desktop Screenshots (1440×900):**
  - [Executive Overview](./screenshots/01_overview_dashboard.png)
  - [Voice Agent Console](./screenshots/02_voice_agent_page_idle.png)
  - [Call Log & History](./screenshots/03_call_log_history.png)
  - [Customer Journey](./screenshots/04_customer_journey.png)
  - [Support Escalations](./screenshots/05_escalations.png)
  - [Scheduled Callbacks](./screenshots/06_callbacks.png)
  - [Campaigns Hub](./screenshots/07_campaigns.png)
  - [Team Board](./screenshots/08_team_board.png)
  - [Agent My Work](./screenshots/09_agent_workspace_my_work.png)
  - [Live Calls](./screenshots/10_live_calls.png)
  - [Compliance & Audit](./screenshots/11_compliance_audit.png)
  - [System Health](./screenshots/12_system_health.png)
  - [Insights Analytics](./screenshots/13_insights.png)
  - [Reports & Exports](./screenshots/14_reports.png)
- **Responsive Screenshots:**
  - [Mobile Overview (375×812)](./screenshots/15_mobile_overview_375x812.png)
  - [Mobile Voice Agent (375×812)](./screenshots/16_mobile_voice_agent_375x812.png)
  - [Tablet Call Log (768×1024)](./screenshots/17_tablet_call_log_768x1024.png)
