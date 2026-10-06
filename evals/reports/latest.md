# KURAL AVA Evaluation Report — GOLDEN
**Run at:** `2026-10-06T12:48:14.813405+00:00`

## Summary Metrics
| Metric | Target | Result | Status |
|---|---|---|---|
| Calls Passed | 100% | 10/10 | PASS |
| Intent Accuracy | ≥ 95.0% | 100.0% | PASS |
| Resolver Accuracy | 100.0% | 100.0% | PASS |
| Sensitive Leakage | 0 | 0 | PASS |
| Unapproved Statements | 0 | 0 | PASS |
| False Call Endings | 0 | 0 | PASS |

## Detailed Script Results

### G-01: Happy path, customer interrupts during instructions — ✓ PASS
- Outcome: `COMPLETED_SUCCESSFULLY`
- Cases Created: `0`, Callbacks Created: `0`

### G-02: Busy -> Hinglish callback -> change time -> dashboard check — ✓ PASS
- Outcome: `CALLBACK_SCHEDULED`
- Cases Created: `0`, Callbacks Created: `1`

### G-03: OTP mid-sentence -> call continues -> update failure -> human -> callback — ✓ PASS
- Outcome: `APP_SUPPORT_CASE_CREATED`
- Cases Created: `1`, Callbacks Created: `1`

### G-04: Wrong person -> never reveals details — ✓ PASS
- Outcome: `WRONG_PARTY`
- Cases Created: `0`, Callbacks Created: `0`

### G-05: Fraud + opt-out in one sentence — ✓ PASS
- Outcome: `FRAUD_ESCALATION`
- Cases Created: `1`, Callbacks Created: `0`

### G-06: Not interested -> one benefit -> still no -> polite end — ✓ PASS
- Outcome: `CUSTOMER_DECLINED`
- Cases Created: `0`, Callbacks Created: `0`

### G-07: Questions everywhere (trust, AI, number, recording) -> still finishes — ✓ PASS
- Outcome: `COMPLETED_SUCCESSFULLY`
- Cases Created: `0`, Callbacks Created: `0`

### G-08: Ambiguous and invalid times — ✓ PASS
- Outcome: `CALLBACK_SCHEDULED`
- Cases Created: `0`, Callbacks Created: `1`

### G-09: Human request, then cancel, then opt-out + help — ✓ PASS
- Outcome: `APP_SUPPORT_CASE_CREATED`
- Cases Created: `1`, Callbacks Created: `1`

### G-10: Silence, noise and system failure — ✓ PASS
- Outcome: `IN_PROGRESS`
- Cases Created: `0`, Callbacks Created: `0`
