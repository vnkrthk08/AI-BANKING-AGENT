"""Browser-driven smoke test of the operations console (real backend, real browser).

Prereqs: API on :8000, Vite on :5173, users provisioned (see docs/deployment.md).
Usage: python scripts/acceptance/browser_smoke.py --user ops1 --password ... --out <dir>
"""
import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

HUBS = [("overview", "/executive"), ("voice-studio", "/test-console"), ("calls", "/calls"), ("campaigns", "/campaigns"),
        ("work-queue", "/work"), ("team", "/team"), ("governance", "/governance")]
VIEWPORTS = {"desktop": (1440, 900), "tablet": (768, 1024), "mobile": (375, 812)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5173")
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--chromium", default="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"pages": [], "server_errors": [], "console_errors": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=a.chromium, args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
        for vp, (w, h) in VIEWPORTS.items():
            ctx = browser.new_context(viewport={"width": w, "height": h}, permissions=["microphone"])
            page = ctx.new_page()
            page.on("console", lambda m: m.type == "error" and report["console_errors"].append(m.text[:200]))
            page.on("response", lambda r: r.status >= 500 and report["server_errors"].append(f"{r.status} {r.url}"))
            page.goto(a.base + "/")
            page.get_by_label("Username").fill(a.user)
            page.get_by_label("Password").fill(a.password)
            page.get_by_role("button", name="Sign in").click()
            page.wait_for_selector(".ops-user-chip", timeout=15000)
            if vp == "desktop":
                page.screenshot(path=str(out / "00_after_login.png"))
            for name, path in HUBS:
                page.goto(a.base + path)
                page.wait_for_timeout(1800)
                overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
                report["pages"].append({"viewport": vp, "page": name, "url": page.url, "horizontal_overflow": overflow})
                if vp == "desktop" or name in ("overview", "voice-studio", "work-queue"):
                    page.screenshot(path=str(out / f"{vp}_{name}.png"))
            ctx.close()
        # Login failure state
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(a.base + "/")
        page.get_by_label("Username").fill(a.user)
        page.get_by_label("Password").fill("wrong-password-123")
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_selector(".login-error", timeout=10000)
        report["login_failure_message"] = page.inner_text(".login-error")
        page.screenshot(path=str(out / "00_login_error.png"))
        browser.close()
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: (v if k != "pages" else [x for x in v if x["horizontal_overflow"] or x["page"] == "overview"]) for k, v in report.items()}, indent=1))


if __name__ == "__main__":
    main()
