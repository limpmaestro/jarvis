"""Web tools using Playwright (headless Chromium)."""

from __future__ import annotations

from typing import Any

from jarvis.tools.registry import tool
from jarvis.utils.logging import get_logger

log = get_logger("tools.web")


async def _new_browser():
    # Import lazily so tests don't need Playwright installed.
    from playwright.async_api import async_playwright

    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True)
    return p, browser


@tool(
    name="web.fetch",
    description=(
        "Fetch a URL with a headless browser, then return cleaned article "
        "text (readability) and the page title. Use this for any web "
        "content; do not invent URLs."
    ),
    risk="low",
)
async def web_fetch(url: str, timeout_ms: int = 20000) -> dict[str, Any]:
    from readability import Document  # type: ignore[import-untyped]

    p, browser = await _new_browser()
    try:
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        html = await page.content()
        title = await page.title()
    finally:
        await browser.close()
        await p.stop()

    try:
        doc = Document(html)
        article_html = doc.summary(html_partial=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("readability_failed", error=str(exc))
        article_html = html[:8000]

    # Strip tags cheaply.
    from bs4 import BeautifulSoup

    text = BeautifulSoup(article_html, "lxml").get_text("\n", strip=True)
    if len(text) > 8000:
        text = text[:8000] + "\n[... truncated ...]"
    return {"ok": True, "url": url, "title": title, "text": text}


@tool(
    name="web.search",
    description=(
        "Search DuckDuckGo and return the top 8 results (title, url, snippet). "
        "Use as a starting point; follow up with web.fetch for full content."
    ),
    risk="low",
)
async def web_search(query: str) -> dict[str, Any]:
    p, browser = await _new_browser()
    try:
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(
            f"https://duckduckgo.com/html/?q={query}",
            timeout=20000,
            wait_until="domcontentloaded",
        )
        # DuckDuckGo HTML results live in `.result`.
        items = await page.eval_on_selector_all(
            ".result",
            """nodes => nodes.slice(0, 8).map(n => ({
                title: (n.querySelector('.result__title') || {}).innerText || '',
                url: (n.querySelector('.result__a') || {}).href || '',
                snippet: (n.querySelector('.result__snippet') || {}).innerText || ''
            }))""",
        )
    finally:
        await browser.close()
        await p.stop()
    return {"ok": True, "query": query, "results": items}
