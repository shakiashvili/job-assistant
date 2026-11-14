import os
import pytest
import httpx
from playwright.sync_api import sync_playwright
from axe_playwright_python.sync_playwright import Axe

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://127.0.0.1:5173")


def _is_frontend_reachable(url: str) -> bool:
    try:
        resp = httpx.get(url, timeout=3.0)
        return resp.status_code < 500
    except Exception:
        return False


@pytest.mark.skipif(
    not _is_frontend_reachable(FRONTEND_URL),
    reason=f"Frontend dev/preview server is not running at {FRONTEND_URL}",
)
def test_frontend_performance_mobile_overflow_and_a11y():
    """
    Playwright Non-Functional E2E & Accessibility Suite:
    1. Cold load DOMContentLoaded timing < 2000ms.
    2. Zero uncaught JS/console errors.
    3. Mobile viewport (375x812) has zero horizontal scroll overflow.
    4. Zero WCAG 2.1 AA critical accessibility violations via axe-playwright-python.
    """
    console_errors = []
    page_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        page.on(
            "console",
            lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
        )
        page.on("pageerror", lambda err: page_errors.append(str(err)))

        page.goto(FRONTEND_URL, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(800)

        nav_timing = page.evaluate(
            """() => {
                const nav = performance.getEntriesByType('navigation')[0];
                return nav ? {
                    domContentLoaded: nav.domContentLoadedEventEnd - nav.startTime,
                    loadEvent: nav.loadEventEnd - nav.startTime
                } : null;
            }"""
        )
        assert nav_timing is not None, "Navigation timing entry missing"
        assert nav_timing["domContentLoaded"] < 2000, (
            f"DOMContentLoaded took {nav_timing['domContentLoaded']:.1f}ms (expected < 2000ms)"
        )

        # Accessibility scan via axe-core (WCAG 2.1 AA)
        axe = Axe()
        results = axe.run(page)
        critical_violations = [
            v for v in results.response.get("violations", [])
            if v.get("impact") == "critical"
        ]
        assert not critical_violations, (
            f"Critical accessibility violations detected: {critical_violations}"
        )

        # Mobile responsiveness (375x812 iPhone viewport) -> zero horizontal overflow
        page.set_viewport_size({"width": 375, "height": 812})
        page.wait_for_timeout(300)
        overflow = page.evaluate(
            """() => ({
                scrollWidth: document.documentElement.scrollWidth,
                innerWidth: window.innerWidth
            })"""
        )
        assert overflow["scrollWidth"] <= overflow["innerWidth"], (
            f"Horizontal overflow at 375x812: scrollWidth={overflow['scrollWidth']} > innerWidth={overflow['innerWidth']}"
        )

        assert not page_errors, f"Uncaught page errors: {page_errors}"
        assert not console_errors, f"Console errors logged: {console_errors}"

        context.close()
        browser.close()
