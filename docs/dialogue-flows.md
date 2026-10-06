# Dialogue Specification & Conversation Flows

## 1. Architectural Architecture: Hybrid NLU & Deterministic State Machine

```
[Customer Audio / Text]
       │
       ▼
1. Streaming STT ────────► Real-time transcription into text stream
       │
       ▼
2. Safety Screener ──────► Regex & sanitization screening blocks OTP, PIN, Passwords BEFORE storage or LLM
       │
       ▼
3. Gemini NLU ───────────► Semantic classification proposes INTENT (e.g., BUSY, APP_UPDATE_ISSUE)
       │
       ▼
4. KURAL Deterministic ──► Validates transition against allowable states, authorizes actions & selects compliant wording
   FSM Engine
       │
       ▼
5. Streaming TTS ────────► Synthesizes approved banking dialogue in real-time
```

- **Semantic Intent Proposal**: Language models propose candidate intents based on natural language input.
- **Deterministic Validation**: KURAL validates candidate intents against strict state transition tables and action authorization policies.
- **Approved Knowledge**: Spoken output is retrieved exclusively from verified, approved response sets.

---

## 2. Conversation Stages & State Machine Transitions

### Stage 0: Outbound Connection & Mandatory Disclosure
- **State**: `DISCLOSURE` ➔ `IDENTITY_CHECK`
- **Assistant Prompt**:
  > *"Hello, I’m AVA, an automated assistant calling on behalf of your bank. Am I speaking with the customer?"*
- **Branching Logic**:
  - **Affirmative** (*"Yes", "Speaking", "Yes I am"*): Transition to `PERMISSION`.
  - **Busy / Deferral** (*"I'm busy", "Call me later"*): Transition to `CALLBACK_BOOKING`.
  - **Negative / Wrong Party** (*"No", "Wrong number", "Not the customer"*): Immediate graceful termination (`ENDED`).
  - **Identity Inquiries** (*"Who is calling?"*): Deliver identity disclosure and re-prompt.
  - **Credential Disclosure** (*Customer speaks OTP/PIN*): Trigger security defense block and close session.

### Stage 1: Permission & Availability Check
- **State**: `PERMISSION`
- **Assistant Prompt**:
  > *"Thank you. Is now a convenient time to discuss the mobile app update?"*
- **Branching Logic**:
  - **Affirmative**: Transition to `APP_STATUS`.
  - **Busy**: Transition to `CALLBACK_BOOKING`.
  - **Explicit Callback Request**: Record callback request and transition to `ENDED`.
  - **Decline**: Acknowledge preference and transition to `ENDED`.

### Stage 2: Application Installation Verification
- **State**: `APP_STATUS`
- **Assistant Prompt**:
  > *"Is the demo bank app installed on your device?"*
- **Branching Logic**:
  - **Installed**: Provide official app store update guidance and transition to `UPDATE_HELP`.
  - **Not Installed**: Provide installation instructions and transition to `ENDED`.
  - **Ambiguous Response**: Prompt customer for clarification or offer human assistance.

### Stage 3: Update Verification & Troubleshooting
- **State**: `UPDATE_HELP`
- **Branching Logic**:
  - **Update Succeeded**: Confirm completion, log resolution, and transition to `ENDED`.
  - **Update Failed / Issue Encountered**: Transition to `ISSUE_CAPTURE` to arrange human follow-up.

### Stage 4: Issue Capture & Ticket Dispatch
- **State**: `ISSUE_CAPTURE`
- **Assistant Prompt**:
  > *"Would you like me to request human follow-up for the update problem?"*
- **Branching Logic**:
  - **Affirmative**: Execute atomic transaction creating `APP_UPDATE_CASE` and `REQUEST_CALLBACK`; transition to `ENDED`.
  - **Negative**: Provide official banking support channels and transition to `ENDED`.

### Stage 5: Callback Booking
- **State**: `CALLBACK_BOOKING`
- **Assistant Prompt**:
  > *"No problem. Would you like a callback?"*
- **Branching Logic**:
  - **Affirmative**: Record scheduled callback timestamp, confirm details, and transition to `ENDED`.
  - **Negative**: Provide standard support contact numbers and transition to `ENDED`.

---

## 3. Global Interruption & Safety Policy Handlers

The following policies execute globally across all conversation states:

| Event Type | Sample Utterance | System Action | Terminal State |
|---|---|---|---|
| **Credential Protection** | *"My OTP is 123456"* | Sanitize secret, log security audit marker, warn customer, and terminate call immediately | `ENDED` |
| **Fraud Report** | *"I think this is a scam"* | Advise customer to contact official card services immediately; record escalation event | `FRAUD_ESCALATION` |
| **Human Support Request** | *"Connect me to an agent"* | Route to human escalation queue with transcript context | `HUMAN_ESCALATION` |
| **Do-Not-Call (DNC) / Opt-Out** | *"Stop calling me"* | Record opt-out in compliance register and terminate immediately | `OPT_OUT` |
| **Identity / Bot Disclosure** | *"Are you an AI?"* | Deliver statutory automated assistant disclosure and resume prior state | *Resumes State* |
| **Wrong Party Contact** | *"Wrong number"* | Log misdialed contact record and terminate without disclosing account data | `ENDED` |
| **Acoustic Low Confidence** | *(Unintelligible / Noise)* | Request repetition with fallback counter increment | *Repeats Prompt* |
| **Turn Silence / Timeout** | *(No response detected)* | Deliver re-engagement prompt; escalate after threshold | *Repeats Prompt* |
