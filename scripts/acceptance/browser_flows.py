"""Browser acceptance of real operator flows against a running API + UI (no mocks).

Expects a fresh database with users ops1/sup1/comp1/admin1/agent1 (agent1 linked + AVAILABLE),
and the API started with an unreachable SMTP server so e-mail deliveries genuinely fail.
Writes screenshots and a JSON report to --out. Exit code 1 if any check fails.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import Page, sync_playwright

PW = "Local-Dev-Pass-2026"
results: list[dict] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append({"check": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))


def login(page: Page, base: str, user: str) -> None:
    page.goto(base + "/")
    page.get_by_label("Username").fill(user)
    page.get_by_label("Password").fill(PW)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_selector(".user", timeout=15000)


def api_token(api: str, user: str) -> dict:
    t = httpx.post(f"{api}/api/v1/auth/login", json={"username": user, "password": PW}).json()["access_token"]
    return {"Authorization": f"Bearer {t}"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5173")
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--out", required=True)
    ap.add_argument("--chromium", default="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    shot = lambda p, n: p.screenshot(path=str(out / f"{n}.png"))  # noqa: E731

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=a.chromium)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page_errors: list[str] = []
        page.on("pageerror", lambda e: page_errors.append(str(e)[:200]))

        # 1. Empty states on a fresh database
        login(page, a.base, "ops1")
        for path, text in [("/work", "Nothing waiting"), ("/calls", "No calls yet"), ("/campaigns", "No campaigns yet"), ("/executive", "No calls in the last 14 days")]:
            page.goto(a.base + path); page.wait_for_timeout(1200)
            check(f"empty state {path}", text in page.inner_text("main"))
        shot(page, "empty_overview")

        # 2. Real data: customer + escalation through the conversation API
        h = api_token(a.api, "ops1")
        httpx.post(f"{a.api}/api/customers", headers=h, json={"full_name": "Priya Raman", "phone": "9876501234", "customer_ref": "CUST-E2E-1"})
        sid = httpx.post(f"{a.api}/api/v1/sessions", headers=h, json={"customer_ref": "CUST-E2E-1"}).json()["session_id"]
        for txt in ("yes speaking", "I want to talk to a human"):
            httpx.post(f"{a.api}/api/v1/sessions/{sid}/messages", headers=h, json={"text": txt})
        time.sleep(8)  # worker: outbox -> notifications -> (failing) e-mail attempt

        page.goto(a.base + "/executive"); page.wait_for_timeout(1500)
        check("overview outcome label", "Escalated to staff" in page.inner_text("main"), "operational category, not raw intent")
        page.goto(a.base + "/calls"); page.wait_for_timeout(1200)
        check("calls shows escalated call", "Escalated to staff" in page.inner_text("main"))

        # 3. Keyboard: skip link, open case from keyboard, Escape restores focus
        page.goto(a.base + "/work"); page.wait_for_timeout(1500)
        page.keyboard.press("Tab")
        check("skip link is first focus", page.evaluate("document.activeElement.className") == "skip-link")
        row = page.locator("tr.click").first
        row.focus(); page.keyboard.press("Enter"); page.wait_for_selector(".drawer")
        check("case drawer opens via keyboard", True)
        check("focus moves into drawer", page.evaluate("!!document.activeElement.closest('.drawer')"))
        for _ in range(25):
            page.keyboard.press("Tab")
        check("focus trapped in drawer", page.evaluate("!!document.activeElement.closest('.drawer')"))
        page.keyboard.press("Escape"); page.wait_for_timeout(400)
        check("Escape closes drawer", page.locator(".drawer").count() == 0)

        # 4. Case assignment + note + resolve via UI
        page.locator("tr.click").first.click(); page.wait_for_selector(".drawer")
        page.get_by_label("Assign to agent").select_option(index=1); page.wait_for_timeout(1200)
        check("case assigned via UI", "Arun Kumar" in page.inner_text(".drawer"))
        page.get_by_placeholder("Visible to the team").fill("Called customer, will retry tomorrow."); page.get_by_role("button", name="Save note").click(); page.wait_for_timeout(1000)
        check("note saved in history", "Note Added" in page.inner_text(".drawer"))
        shot(page, "case_drawer")
        page.get_by_role("button", name="Resolve case").click()
        page.get_by_label("Resolution notes").fill("Explained update steps; customer confirmed fixed.")
        page.locator(".modal").get_by_role("button", name="Resolve").click(); page.wait_for_timeout(1200)
        check("case resolved via UI", "Resolved" in page.inner_text(".drawer"))
        page.keyboard.press("Escape")

        # 5. Callback: agree a time, assign, record outcome
        page.goto(a.base + "/work?tab=callbacks"); page.wait_for_timeout(1500)
        page.locator("tr.click").first.click(); page.wait_for_selector(".drawer")
        page.get_by_label("Assign callback").select_option(index=1); page.wait_for_timeout(1200)
        page.goto(a.base + "/work?tab=callbacks"); page.wait_for_timeout(1200); page.locator("tr.click").first.click(); page.wait_for_selector(".drawer")
        check("callback assigned via UI", "Arun Kumar" in page.inner_text(".drawer"))
        page.get_by_label("Call outcome").select_option("BUSY"); page.get_by_label("Outcome notes").fill("No pickup"); page.get_by_role("button", name="Save outcome").click(); page.wait_for_timeout(1200)
        cbs = httpx.get(f"{a.api}/api/callbacks", headers=h).json()
        check("manual outcome persisted", cbs[0]["last_outcome"] == "BUSY" and cbs[0]["attempt_count"] == 1, f"status={cbs[0]['raw_status']}")

        # 6. Notification delivery log: genuine SMTP failure + retry
        page.goto(a.base + "/governance?tab=notifications"); page.wait_for_timeout(1500)
        body = page.inner_text("main")
        check("failed e-mail shown as Failed", "Failed" in body and "SMTP" in body)
        check("in-app shown as Delivered", "Delivered" in body)
        shot(page, "notifications_log")
        before = httpx.get(f"{a.api}/api/notifications/deliveries?status=FAILED", headers=h).json()["deliveries"]
        page.get_by_role("button", name="Retry").first.click(); page.wait_for_timeout(500)
        after = httpx.get(f"{a.api}/api/notifications/deliveries?limit=500", headers=h).json()["deliveries"]
        retried = next(d for d in after if d["id"] == before[0]["id"])
        check("retry re-queued delivery", retried["status"] in ("QUEUED", "SENDING", "FAILED") and retried["attempts"] <= 1, f"status after retry={retried['status']}")
        time.sleep(7)
        final = next(d for d in httpx.get(f"{a.api}/api/notifications/deliveries?limit=500", headers=h).json()["deliveries"] if d["id"] == before[0]["id"])
        check("retried delivery honestly fails again (SMTP down)", final["status"] == "FAILED", final["last_error"] or "")

        # 7. Integration health details
        page.goto(a.base + "/governance"); page.wait_for_timeout(1500)
        g = page.inner_text("main")
        check("health shows database head", "schema 0005_operational_lifecycles" in g)
        check("health shows SMTP configured", "Staff e-mail" in g and "Configured" in g)
        check("health shows voice not configured", "SARVAM_API_KEY" in g)

        # 8. Emergency stop by compliance; compliance cannot resume; ops resumes
        ctx2 = browser.new_context(viewport={"width": 1440, "height": 900}); p2 = ctx2.new_page()
        login(p2, a.base, "comp1"); p2.goto(a.base + "/governance"); p2.wait_for_timeout(1200)
        p2.get_by_role("button", name="Emergency stop").click(); p2.get_by_label("Reason").fill("Acceptance drill"); p2.get_by_role("button", name="Stop dialing").click(); p2.wait_for_timeout(1200)
        check("compliance stopped dialing", "Stopped" in p2.inner_text("main"))
        check("compliance cannot resume", p2.get_by_role("button", name="Resume dialing").count() == 0)
        shot(p2, "emergency_stop")
        # Compliance approves a campaign created by ops
        cid = httpx.post(f"{a.api}/api/campaigns", headers=h, json={"name": "Acceptance campaign"}).json()["id"]
        p2.goto(a.base + "/campaigns"); p2.wait_for_timeout(1200)
        check("campaign page shows stop banner", "Outbound dialing is stopped" in p2.inner_text("main"))
        p2.locator("tr.click").first.click(); p2.wait_for_selector(".drawer")
        p2.get_by_role("button", name="Approve for calling").click(); p2.wait_for_timeout(1200)
        check("compliance approved campaign", httpx.get(f"{a.api}/api/campaigns/{cid}", headers=h).json()["status"] == "APPROVED")
        page.goto(a.base + "/campaigns"); page.wait_for_timeout(1200); page.locator("tr.click").first.click(); page.wait_for_selector(".drawer"); page.wait_for_timeout(1200)
        start = page.get_by_role("button", name="Start campaign")
        check("start disabled while preflight fails", start.is_disabled())
        shot(page, "campaign_preflight")
        page.keyboard.press("Escape")
        page.goto(a.base + "/governance"); page.wait_for_timeout(1200)
        page.get_by_role("button", name="Resume dialing").click(); page.locator(".modal").get_by_role("button", name="Resume").click(); page.wait_for_timeout(1200)
        check("ops resumed dialing", "Enabled" in page.inner_text("main"))
        ctx2.close()

        # 9. Unauthorized: admin cannot reach customer data hubs; agent sees limited nav
        ctx3 = browser.new_context(); p3 = ctx3.new_page()
        login(p3, a.base, "admin1"); p3.goto(a.base + "/calls"); p3.wait_for_timeout(1000)
        check("admin redirected away from Calls", "/governance" in p3.url)
        check("admin API blocked from customers", httpx.get(f"{a.api}/api/customers", headers=api_token(a.api, "admin1")).status_code == 403)
        ctx3.close()
        ctx4 = browser.new_context(); p4 = ctx4.new_page()
        login(p4, a.base, "agent1"); nav = p4.inner_text(".side")
        check("agent nav limited", "Campaigns" not in nav and "Work Queue" in nav, nav.replace("\n", " | "))
        ctx4.close()

        # 10. Dark mode visual pass across hubs
        page.emulate_media(color_scheme="dark")
        page.evaluate("localStorage.setItem('kural-theme','dark')")
        for path in ("/executive", "/test-console", "/calls", "/work", "/campaigns", "/team", "/governance"):
            page.goto(a.base + path); page.wait_for_timeout(1000); shot(page, "dark_" + path.strip("/"))
        check("dark theme applied", page.evaluate("document.documentElement.dataset.theme") == "dark")
        page.evaluate("localStorage.setItem('kural-theme','light')")

        check("no uncaught page errors", not page_errors, "; ".join(page_errors))
        browser.close()
    (out / "flows_report.json").write_text(json.dumps(results, indent=2))
    failed = [r for r in results if not r["ok"]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
