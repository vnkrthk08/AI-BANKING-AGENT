# KURAL · SUBBU MASTER SCENARIOS, DIALOGUES & OPERATOR HANDBOOK
**Town Bank Automated Mobile Banking App Update Campaign (Demo v1.1)**
*Generated for Live Demo & Submission — October 2026*

---

## EXECUTIVE SUMMARY & STATUS OVERVIEW

| Component | Status | Verification Result |
| :--- | :--- | :--- |
| **Backend API Server** | **ONLINE** | `http://127.0.0.1:8000` (`/health` returns HTTP 200 OK) |
| **Frontend UI (Test Console & Ops)** | **ONLINE** | `http://127.0.0.1:5173/test-console` (Vite dev server running) |
| **Unit Test Suite** | **100% PASS** | 127 of 127 tests passed (`pytest -q`) |
| **Golden Call Evaluation Suite** | **100% PASS** | 10 of 10 golden calls passed gate check (`evals.run --suite golden --gate`) |
| **NLU Classification Accuracy** | **100.0%** | 60 of 60 test turns accurately classified (`evals.nlu_check`) |
| **Sensitive Data Leakage Guard** | **0 LEAKS** | Regex OTP/PIN/password/CVV filter + warn-and-continue policy active |
| **Dual Recorded Voice Sample Studio**| **READY** | Real Sarvam `bulbul:v3` WAV audio files for Subbu (`aditya`) and Priya (`priya`) |
| **Realtime Dashboard Rescheduling** | **ACTIVE** | SSE stream (`/api/events/sse`) syncs callbacks to UI live |

---

## 1. HOW KURAL BRAIN / MIND WORKS

The KURAL architecture separates **Understanding** (NLU), **Control** (FSM Decision Engine), and **Generation** (Approved Script Store):

```
       [ Customer Voice Audio / Text ]
                      │
                      ▼
        ┌───────────────────────────┐
        │  Sensitive Data Scrubber   │ ──> Masks OTP/PIN/CVV/Password (Never logged/stored)
        └───────────────────────────┘
                      │
                      ▼
        ┌───────────────────────────┐
        │    Gemini LLM Classifier  │
        │    (Few-Shot NLU Engine)  │ ──> Classifies Intent (P1..P9) & Raw Entities
        └───────────────────────────┘
                      │
                      ▼
        ┌───────────────────────────┐
        │     KURAL FSM Engine      │ ──> Strict Deterministic State Machine (Spec v1.1)
        │   (Deterministic Logic)   │     Calculates Dates (R1..R24) & Disallows Hallucination
        └───────────────────────────┘
                      │
                      ▼
        ┌───────────────────────────┐
        │   Approved Script Store   │ ──> Only emits pre-approved Subbu lines
        │ (town_bank_scripts.yaml)  │
        └───────────────────────────┘
                      │
                      ▼
        [ Streaming Audio via Sarvam TTS ]
```

> [!IMPORTANT]
> **Safety Guarantee:** The LLM is **NEVER** allowed to freely generate conversational text or decide bank policies. It only extracts intent and entities. All speech uttered by Subbu comes directly from `town_bank_scripts.yaml`.

---

## 2. ALL ACTIVE SCENARIOS IN THE BRAIN

The brain currently handles **all 10 Golden Scenarios**, the **Master 4-Minute Submission Demo**, and **49 Edge Cases**:

### A. The Master 4-Minute Demo Scenario (Spec §20)
This is the recommended path for your live presentation:
- **Turn 1 (Opening & Identity):** Subbu greets and verifies identity (`S-OPEN-01n`). Customer confirms.
- **Turn 2 (Permission):** Subbu asks if now is a good time for 2 minutes (`S-PURPOSE-01`). Customer agrees.
- **Turn 3 (App Status):** Subbu checks if app is installed (`S-APP-01`). Customer confirms.
- **Turn 4 (Update Guide):** Subbu provides store update instructions (`S-UPD-01`).
- **Turn 5 (Interruption / Question):** Customer interrupts: *"Wait, how long does this take?"* Subbu answers: *"About two minutes"* (`S-Q-HOW-LONG`) and seamlessly resumes.
- **Turn 6 (Sensitive Data Test):** Customer says: *"My OTP is 482910, do you need that?"* Subbu immediately triggers safe guardrail: *"Please don't share your OTP or PIN"* (`S-SENS-01`) and carries on without hanging up.
- **Turn 7 (Issue Capture):** Customer reports: *"It's giving error code 502 when I update."* Subbu creates support case: `APP_UPDATE_FAILURE`.
- **Turn 8 (Reschedule Callback):** Customer asks: *"Can someone call me tomorrow at 4 PM?"* Subbu resolves to tomorrow 16:00 IST via Rule R2, creates callback, and **immediately reflects it on the Dashboard Callbacks queue**.
- **Turn 9 (Polite Closing):** Subbu thanks customer with security reminder (`S-END-OK`). Call ends cleanly.

---

### B. The 10 Golden Eval Scenarios (G-01 to G-10)

| ID | Scenario Title | Key Behaviors Verified |
| :--- | :--- | :--- |
| **G-01** | Happy Path with Interruption | Customer interrupts during instructions; Subbu answers question and resumes app guide. |
| **G-02** | Busy → Hinglish Callback → Reschedule | Customer says *"Abhi busy hoon, kal 4 baje call karo"*, then changes to *"Actually 5 baje"*. Subbu moves time in-place (`S-CB-MOVED`). |
| **G-03** | Sensitive OTP Guardrail & Case Creation | Customer blurts out OTP *"My OTP is 894312"*; Subbu warns and continues, captures update crash, creates case and callback. |
| **G-04** | Wrong Person / Not Available | Customer says *"Wrong number, he passed away"* or *"Rahul isn't here"*; Subbu offers condolences/polite end without revealing details. |
| **G-05** | Fraud Report + Opt-out | Customer reports unauthorized debit; Subbu immediately gives emergency fraud hotline instructions (`S-FRAUD-01..03`) and logs case. |
| **G-06** | Not Interested (Single Push) | Customer declines; Subbu explains 1 single benefit (`S-DECLINE-01`); customer declines again; Subbu closes politely (`S-DECLINE-END`). |
| **G-07** | Trust & Security Inquiries | Customer asks *"Are you AI? How do I know you're Town Bank?"*; Subbu validates AI identity and directs to card phone number. |
| **G-08** | Ambiguous & Invalid Times | Customer asks for 11 PM (outside 9 AM–8 PM) or Sunday; Subbu suggests next valid business window. |
| **G-09** | Human Escalation with Cancellation | Customer requests human agent, then cancels callback request; Subbu acknowledges cancellation cleanly (`S-CB-CANCELLED`). |
| **G-10** | Line Silence & Noise | Silence triggers gentle prompt (`S-SIL-01`); repeat silence offers callback or hangs up gracefully. |

---

## 3. COMPLETE DIALOGUE CATALOGUE (Every Line Subbu Can Speak)

All lines below reside in `kural/knowledge/content/town_bank_scripts.yaml`. You can rephrase any line by following the template in Section 5.

### 1. Opening & Identity Verification
- `S-OPEN-01`: *"Hi, this is Subbu, Town Bank's automated assistant. Am I speaking with Rahul?"*
- `S-OPEN-01n`: *"Hi, this is Subbu, Town Bank's automated assistant. Am I speaking with the account holder?"*
- `S-REASK-ID`: *"Am I speaking with Rahul?"*
- `S-ID-REFUSE-01`: *"That's fair. I can only discuss this with Rahul, and I won't ask for any PIN or OTP. Is this Rahul?"*
- `S-ID-REFUSE-END`: *"No problem. You can always reach Town Bank on the number on your card. Goodbye."*
- `S-NOTAVAIL-01`: *"Thanks for letting me know. I'll try Rahul another time — have a good day."*
- `S-WRONG-01`: *"Sorry for the trouble. I'll update our records — have a good day."*

### 2. Purpose & Permission
- `S-PURPOSE-01`: *"Thanks, Rahul. I'm calling about a quick update to your Town Bank mobile app — is now a good time for two minutes?"*
- `S-PERM-OK`: *"Great, thanks."*
- `S-REASK-PERM`: *"Is now an okay time?"*
- `S-REC-01`: *"Just so you know, this call may be recorded for quality and security."*

### 3. Customer Inquiry / Trust Handlers (Can Be Triggered Anywhere)
- `S-Q-AI`: *"Yes, I'm an automated assistant from Town Bank — not a person."*
- `S-Q-WHO`: *"I'm Subbu, Town Bank's automated assistant."*
- `S-Q-WHY`: *"We're helping customers make sure their Town Bank app is up to date — it keeps it secure and working smoothly."*
- `S-Q-HOW-LONG`: *"About two minutes."*
- `S-Q-WHAT-NEED`: *"Nothing confidential — just a minute to check your app is updated."*
- `S-Q-NUMBER`: *"It's the number registered with your Town Bank account."*
- `S-Q-RECORDING`: *"This call isn't being recorded, though a text summary is kept for our records."*
- `S-TRUST-01`: *"It's a genuine Town Bank service call, and I'll never ask for your PIN, OTP or password. If you'd prefer, you can hang up and call the number on the back of your card."*

### 4. App Status & Guided Steps
- `S-APP-01`: *"Is the Town Bank app installed on your phone?"*
- `S-APP-02`: *"Have you updated it in the last few days?"*
- `S-UPTODATE-01`: *"Perfect, then you're already up to date."*
- `S-INSTALL-01`: *"You can get it from the Play Store or App Store — search 'Town Bank' and install the one published by Town Bank."*
- `S-UPD-01`: *"It's quick — open the Play Store or App Store, search 'Town Bank', and tap Update if you see it."*
- `S-UPD-02`: *"Take your time — tell me once it's done, or if anything goes wrong."*
- `S-UPD-OK`: *"Perfect, you're all set."*
- `S-WAIT-01`: *"No rush, I'm still here."*

### 5. Troubleshooting & Support Escalation
- `S-ISSUE-01`: *"Is there anything else you're having trouble with in the app?"*
- `S-DIAG-UPD-01`: *"What happens when you try — do you see an error, or does it just not start?"*
- `S-DIAG-STORAGE`: *"That usually means the phone's low on space; clearing a few large files or unused apps often fixes it."*
- `S-DIAG-LOGIN-01`: *"Okay — please don't tell me your password or OTP. Is it showing an error, or just not accepting the login?"*
- `S-HUMAN-01`: *"Of course — I'll arrange for someone from our support team to call you."*
- `S-HUMAN-ISSUE`: *"I'm sorry you're dealing with that. I'll have someone from our support team follow up with you."*
- `S-CASE-REF`: *"Your reference is {short_ref}."*

### 6. Callback Scheduling & Rescheduling
- `S-BUSY-01` / `S-CB-ASK`: *"No problem. When would be a better time to call you back?"*
- `S-CB-ASK-TIME`: *"What time on {day} works for you?"*
- `S-CB-PAST`: *"That time's already passed today — would {suggestion} work?"*
- `S-CB-WINDOW`: *"We can call between 9 AM and 8 PM — would {suggestion} work?"*
- `S-CB-SUNDAY`: *"We don't call on Sundays — would {monday_suggestion} work?"*
- `S-CB-CONFIRM`: *"So that's {spoken_datetime} — does that work?"*
- `S-CB-DONE`: *"Done — we'll call you {spoken_datetime}."*
- `S-CB-MOVED`: *"Sure — moved to {spoken_datetime}. Does that work?"*
- `S-CB-CANCELLED`: *"Okay, I've cancelled that callback."*

### 7. Safety & Sensitive Guardrails (Highest Priority P1 & P2)
- `S-SENS-01`: *"Please don't share your OTP, PIN, password or CVV with me — Town Bank will never ask for those on a call."*
- `S-SENS-INTERRUPT`: *"Sorry to interrupt — please don't share that code with me."*
- `S-SENS-CONT`: *"That's okay, we can carry on."*
- `S-FRAUD-01`: *"I'm sorry — that sounds worrying, and it's important to act quickly."*
- `S-FRAUD-02`: *"Please call Town Bank's official helpline on the number on your card, or block your card from the official app, right away."*
- `S-FRAUD-03`: *"I've also flagged this for our team to follow up with you urgently."*

### 8. Opt-Out & Closings
- `S-OPTOUT-01`: *"Understood — I'll make sure you're not called about this again."*
- `S-DECLINE-01`: *"I understand. The update mainly keeps the app secure and working properly — would you like the quick steps, or shall I leave it there?"*
- `S-DECLINE-END`: *"No problem at all. Thanks for your time, and have a good day."*
- `S-END-OK`: *"Thanks for your time, Rahul. And remember, Town Bank will never ask for your PIN or OTP on a call. Have a good day!"*

---

## 4. HOW RESCHEDULE & REAL-TIME DASHBOARD SYNC WORK

Whenever a customer asks to schedule or change a callback:
1. **Natural Language Date Resolution:** Resolves phrases like `"kal shaam 4 baje"`, `"tomorrow at 5 PM"`, or `"next Monday"` using strict IST banking rules (9 AM to 8 PM, excluding Sundays).
2. **Idempotent In-Place Update:** If a callback is already booked for this session, it updates the **same record** (increments version and reschedule count) rather than duplicating.
3. **SSE Real-time Event:** The backend broadcasts `callback.updated` via `/api/events/sse`.
4. **Instant Dashboard Reflection:** The React Operations Dashboard (`/callbacks` and `/overview`) is hooked up via `EventSource`. When the event fires, the UI refreshes immediately:
   - Rescheduled count increments.
   - Shows badge: `"Moved from Tuesday 4:00 PM → Tuesday 5:00 PM"`.
   - SLA countdown adjusts dynamically.

---

## 5. FORMAT FOR PROVIDING REPHRASED LINES & NEW SCENARIOS

If you want to customize any dialogue or give more phrases, you can simply edit or provide lines in either of the two formats below:

### Format A: YAML Script Line Override (for changing what Subbu speaks)
File location: `kural/knowledge/content/town_bank_scripts.yaml`

```yaml
scripts:
  S-OPEN-01:
    text: "Your primary line here"
    rephrase: false # Set true if minor wording flexibility is permitted
    variants:
      - "Alternative wording variant 1"
      - "Alternative wording variant 2"

  S-CB-DONE:
    text: "Done — we will call you on {spoken_datetime}."
    rephrase: false
```

### Format B: Few-Shot NLU Example (for teaching the LLM new customer phrases)
File location: `kural/nlu/examples/town_bank_app_update.v1.jsonl`

```json
{"turn_id": 61, "state": "CALLBACK_BOOKING", "user_text": "bhai kal 4 baje call kar sakte ho?", "expected": {"intent": "CALLBACK", "priority": "P6", "entities": {"time_expression": "tomorrow at 4pm"}}}
{"turn_id": 62, "state": "IDENTITY_CHECK", "user_text": "haan bhai main hi bol raha hoon", "expected": {"intent": "AFFIRM", "priority": "P7", "entities": {}}}
{"turn_id": 63, "state": "UPDATE_HELP", "user_text": "play store pe download error 404 dikha raha hai", "expected": {"intent": "UPDATE_FAILURE", "priority": "P5", "entities": {"issue_code": "APP_UPDATE_FAILURE"}}}
```

---

## 6. RECORDED VOICE SAMPLES STUDIO (Test Console)

In the **Test Console** (`http://127.0.0.1:5173/test-console`), a **Voice Studio** widget allows you to play high-fidelity audio samples directly from the browser:

1. **Subbu (Male, Indian English, Aditya):**
   - File: `/samples/voice_subbu_male.wav`
   - Spoken Line: *"Hi, this is Subbu, Town Bank's automated assistant. Am I speaking with the account holder? I am calling about a quick update to your mobile banking app."*
2. **Priya (Female, Indian English, Support Specialist):**
   - File: `/samples/voice_priya_female.wav`
   - Spoken Line: *"Hello from Town Bank Customer Support. I have received your app update escalation case and I am following up on your requested callback."*

---

## 7. OPERATOR DEMO CHECKLIST & URLS

1. **Open Test Console:** Navigate to `http://127.0.0.1:5173/test-console`.
2. **Reset Demo Data:** Click the **Reset Demo Data** button in the top right to start with a clean slate.
3. **Play Audio Samples:** Click **Play Subbu Sample** and **Play Priya Sample** to demonstrate voice quality.
4. **Answer Call:** Click **Answer Call** or use the interactive simulation pills (e.g. Master 4-Min Demo turns 1–9) to progress through the conversation.
5. **Verify Dashboard:** Open a second tab at `http://127.0.0.1:5173/callbacks` to observe callbacks and reschedules updating in real-time.
