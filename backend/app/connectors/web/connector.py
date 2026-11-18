"""Connecteur Web Application — Playwright, parcours contraints (docs/08).

- Seuls les parcours déclarés dans la config source sont exécutables (pas de navigation libre).
- Chaque étape produit un statut réel ; screenshots et erreurs JS collectés.
- Les tests interactifs peuvent modifier des données : permission approved-tests (docs/05).
- Import Playwright paresseux : absent => erreur explicite, jamais de faux succès.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse, urljoin

from ..ssrf import validate_url

MAX_STEPS = 30
MAX_CONSOLE_ERRORS = 50


class WebConnector:
    def __init__(self, config: dict[str, Any], secrets: dict[str, Any]):
        self.base_url = str(config.get("base_url", "")).rstrip("/")
        self.journeys: list[dict[str, Any]] = list(config.get("journeys", []))
        self.timeout_s = float(config.get("timeout_s", 15))
        self.allow_private = bool(config.get("allow_private_host", False))

    def _journey(self, journey_id: str) -> dict[str, Any] | None:
        return next((j for j in self.journeys if j.get("id") == journey_id), None)

    def _url_allowed(self, url: str) -> None:
        hosts = {urlparse(self.base_url).hostname or ""}
        validate_url(url, hosts, allow_private=self.allow_private, method="GET")

    async def test_connection(self) -> tuple[bool, str]:
        try:
            async_playwright = _import_playwright()
        except ImportError as exc:
            return False, f"playwright_not_installed: {exc}"
        try:
            self._url_allowed(self.base_url)
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(self.base_url, timeout=self.timeout_s * 1000)
                title = await page.title()
                await browser.close()
            return True, f"page joignable — titre: {title!r}"
        except Exception as exc:  # noqa: BLE001
            return False, f"connection_failed: {type(exc).__name__}: {exc}"

    async def discover(self) -> dict[str, Any]:
        return {
            "connector": "web",
            "base_url": self.base_url,
            "journeys": [
                {"id": j.get("id"), "name": j.get("name"), "steps": len(j.get("steps", []))}
                for j in self.journeys
            ],
        }

    async def run_journey(self, journey_id: str) -> dict[str, Any]:
        """Exécute un parcours contraint, collecte trace + captures (docs/08)."""
        journey = self._journey(journey_id)
        if journey is None:
            raise ValueError(f"parcours non déclaré ou inconnu: {journey_id}")
        steps_def = journey.get("steps", [])[:MAX_STEPS]
        async_playwright = _import_playwright()

        trace_steps: list[dict[str, Any]] = []
        console_errors: list[str] = []
        screenshots: dict[str, bytes] = {}
        t0 = time.monotonic()

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1280, "height": 720})
            page.on(
                "pageerror",
                lambda err: len(console_errors) < MAX_CONSOLE_ERRORS and console_errors.append(str(err)),
            )
            page.on(
                "console",
                lambda msg: (len(console_errors) < MAX_CONSOLE_ERRORS and msg.type == "error"
                             and console_errors.append(msg.text)),
            )
            for i, step in enumerate(steps_def):
                step_result = await self._run_step(page, i, step)
                trace_steps.append(step_result)
                if step_result.get("screenshot"):
                    try:
                        screenshots[f"step_{i}.png"] = await page.screenshot(type="png")
                    except Exception:  # capture non bloquante
                        pass
            await page.close()
            await browser.close()

        duration_ms = int((time.monotonic() - t0) * 1000)
        passed = all(s.get("status") == "pass" for s in trace_steps) and bool(trace_steps)
        return {
            "journey_id": journey_id,
            "journey_name": journey.get("name", journey_id),
            "steps": trace_steps,
            "console_errors": console_errors,
            "all_passed": passed,
            "duration_ms": duration_ms,
        }

    async def _run_step(self, page, i: int, step: dict[str, Any]) -> dict[str, Any]:
        action = step.get("action")
        out: dict[str, Any] = {"index": i, "action": action, "status": "pass"}
        t = time.monotonic()
        try:
            if action == "goto":
                url = urljoin(self.base_url + "/", str(step.get("url", "/")))
                self._url_allowed(url)
                resp = await page.goto(url, timeout=self.timeout_s * 1000)
                out["url"] = url
                out["http_status"] = resp.status if resp else None
                expect_status = step.get("expect_status")
                if expect_status is not None and (resp is None or resp.status != expect_status):
                    out["status"] = "fail"
                    out["reason"] = f"statut attendu {expect_status}, observé {resp.status if resp else 'none'}"
            elif action == "click":
                await page.click(step["selector"], timeout=self.timeout_s * 1000)
                out["selector"] = step["selector"]
            elif action == "fill":
                await page.fill(step["selector"], str(step.get("text", "")), timeout=self.timeout_s * 1000)
                out["selector"] = step["selector"]
            elif action == "expect_text":
                await page.wait_for_selector(f"text={step.get('text', '')}", timeout=self.timeout_s * 1000)
                out["text"] = step.get("text")
            elif action == "expect_selector":
                await page.wait_for_selector(step["selector"], timeout=self.timeout_s * 1000)
                out["selector"] = step["selector"]
            elif action == "wait":
                await page.wait_for_timeout(min(int(step.get("ms", 200)), 5000))
            else:
                out["status"] = "fail"
                out["reason"] = f"action inconnue: {action}"
        except Exception as exc:  # noqa: BLE001
            out["status"] = "fail"
            out["reason"] = f"{type(exc).__name__}: {exc}"
        out["latency_ms"] = int((time.monotonic() - t) * 1000)
        return out

    async def close(self) -> None:
        return None


def _import_playwright():
    """Retourne la factory async_playwright ; erreur explicite si non installé."""
    try:
        from playwright.async_api import async_playwright

        return async_playwright
    except ImportError as exc:
        raise ImportError(
            "playwright absent — installer avec: uv sync --extra web && uv run playwright install chromium"
        ) from exc
