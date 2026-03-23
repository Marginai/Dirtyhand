"""Playwright browser lifecycle — session page for navigate → extract tool chains."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from urllib.parse import urlparse
from typing import Any

from playwright.async_api import Browser, Page, async_playwright
from playwright.sync_api import sync_playwright

from app.exceptions import AppError
from app.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class BrowserService:
    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._playwright: Any = None
        self._browser: Browser | None = None
        self._context: Any = None
        self._lock = asyncio.Lock()
        self._started = False
        self._sync_fallback = False
        # Session page for agent tool sequences (navigate then extract)
        self._session_page: Page | None = None
        # State used by sync fallback mode.
        self._sync_last_url: str | None = None
        self._sync_last_text: str | None = None

    async def start(self) -> None:
        async with self._lock:
            if self._started:
                return
            logger.info("Starting Playwright Chromium")
            try:
                self._playwright = await async_playwright().start()
            except NotImplementedError as e:
                # Some Windows runtimes do not support asyncio subprocess APIs.
                # Fall back to sync Playwright executed in a worker thread.
                logger.warning(
                    "Async Playwright unavailable (%s). Enabling sync-thread fallback mode.",
                    e,
                )
                self._sync_fallback = True
                self._started = True
                return
            self._browser = await self._playwright.chromium.launch(
                headless=self._settings.playwright_headless,
            )
            # Keep startup minimal/stable: launch browser only.
            # Pages are created directly from browser in navigate_browser().
            self._context = None
            self._started = True

    async def stop(self) -> None:
        async with self._lock:
            if self._session_page:
                try:
                    await self._session_page.close()
                except Exception:
                    pass
                self._session_page = None
            if self._context:
                try:
                    await self._context.close()
                except Exception:
                    pass
                self._context = None
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
            self._sync_fallback = False
            self._sync_last_url = None
            self._sync_last_text = None
            self._started = False
            logger.info("Playwright stopped")

    async def _ensure_browser(self) -> Browser:
        if not self._browser and not self._sync_fallback:
            await self.start()
        if self._sync_fallback:
            # In fallback mode we do not keep a persistent async browser object.
            # Return type is not used by callers in this branch.
            return None  # type: ignore[return-value]
        assert self._browser is not None
        return self._browser

    def _sync_scrape(self, url: str) -> tuple[str, str, str]:
        """
        Synchronous Playwright path used when asyncio subprocess support is unavailable.
        Returns (final_url, title, cleaned_text).
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self._settings.playwright_headless)
            page = browser.new_page()
            page.set_default_timeout(self._settings.playwright_action_timeout_ms)
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self._settings.playwright_action_timeout_ms,
            )
            final_url = page.url
            title = page.title()
            text = page.evaluate(
                """() => {
                    const s = document.querySelector('main, article, [role="main"]')
                      || document.body;
                    return s ? s.innerText : '';
                }"""
            )
            browser.close()
        cleaned = (text or "").strip()
        return final_url, title, cleaned

    def _log_action(self, action: str, *, url: str | None = None, **fields: Any) -> None:
        # Keep logs structured but simple; request_id is injected by logging_config.
        base = f"playwright_action={action}"
        if url:
            base += f" url={url}"
        if fields:
            base += " " + " ".join(f"{k}={v}" for k, v in fields.items())
        logger.info(base)

    def _allowed_domains(self) -> set[str]:
        explicit = [d.strip().lower() for d in (self._settings.playwright_allowed_domains or "").split(",") if d.strip()]
        if explicit:
            return set(explicit)
        # If allowlist enforcement is enabled but no domains were configured,
        # derive a minimal default from ORGANIZATION_URL.
        if self._settings.playwright_enforce_domain_allowlist and self._settings.organization_url:
            try:
                parsed = urlparse(self._settings.organization_url)
                if parsed.hostname:
                    return {parsed.hostname.lower()}
            except Exception:
                return set()
        return set()

    def _host_is_private(self, hostname: str) -> bool:
        # Deterministic hostname checks to reduce SSRF risk without DNS resolution.
        h = hostname.lower().strip(".")
        if h in ("localhost",):
            return True
        if h in ("127.0.0.1", "0.0.0.0", "::1"):
            return True
        try:
            ip = ipaddress.ip_address(h)
        except ValueError:
            return False
        return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast)

    def _validate_navigation_target(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise AppError("URL scheme not allowed", code="url_blocked")
        if not parsed.hostname:
            raise AppError("URL hostname missing", code="url_blocked")

        hostname = parsed.hostname.strip().lower()

        if self._settings.playwright_block_private_ips and self._host_is_private(hostname):
            raise AppError("URL host not allowed", code="url_blocked")

        allowed = self._allowed_domains()
        if self._settings.playwright_enforce_domain_allowlist:
            # If enforcing and allowlist is empty, block everything.
            if not allowed:
                raise AppError("URL host not allowed", code="url_blocked")
            # Allow exact match or subdomain match.
            if not any(hostname == d or hostname.endswith("." + d) for d in allowed):
                raise AppError("URL host not allowed", code="url_blocked")

        # Keep normalized url (drop whitespace).
        return url.strip()

    async def navigate_browser(self, url: str) -> str:
        url = url.strip()
        if not url:
            raise AppError("URL is required", code="invalid_url")
        await self._ensure_browser()
        async with self._lock:
            self._log_action("navigate_start", url=url)

            if self._session_page:
                try:
                    await self._session_page.close()
                except Exception:
                    pass
                self._session_page = None
            try:
                validated = self._validate_navigation_target(url)
                if self._sync_fallback:
                    final_url, title, text = await asyncio.to_thread(self._sync_scrape, validated)
                    _ = self._validate_navigation_target(final_url)
                    self._sync_last_url = final_url
                    self._sync_last_text = text
                    self._log_action("navigate_end", url=final_url, title=(title or "").strip()[:120])
                    return f"Navigated to {final_url}. Page title: {title}"
                assert self._browser is not None
                self._session_page = await self._browser.new_page()
                self._session_page.set_default_timeout(self._settings.playwright_action_timeout_ms)

                # Block programmatic form submission (still allows trusted/user events).
                await self._session_page.add_init_script(
                    """() => {
                        document.addEventListener('submit', (e) => {
                          try {
                            if (e && e.isTrusted === false) { e.preventDefault(); }
                          } catch (_) {}
                        }, true);
                      }"""
                )

                # Block file downloads (also covered by acceptDownloads=False).
                async def _on_download(download: Any) -> None:
                    try:
                        cancel = getattr(download, "cancel", None)
                        if callable(cancel):
                            maybe = cancel()
                            if asyncio.iscoroutine(maybe):
                                await maybe
                    except Exception:
                        # Swallow: downloads are already disabled, this is just defense-in-depth.
                        pass

                self._session_page.on("download", _on_download)

                await self._session_page.goto(
                    validated,
                    wait_until="domcontentloaded",
                    timeout=self._settings.playwright_action_timeout_ms,
                )
                final_url = self._session_page.url
                # Enforce allowlist on redirects as well.
                _ = self._validate_navigation_target(final_url)
                title = await self._session_page.title()
                self._log_action("navigate_end", url=final_url, title=(title or "").strip()[:120])
                return f"Navigated to {final_url}. Page title: {title}"
            except Exception as e:
                if isinstance(e, AppError):
                    raise
                logger.exception("navigate failed")
                if self._session_page:
                    try:
                        await self._session_page.close()
                    except Exception:
                        pass
                    self._session_page = None
                raise AppError(f"Navigation failed: {e}", code="navigation_error") from e

    async def extract_text(self) -> str:
        async with self._lock:
            if self._sync_fallback:
                if not self._sync_last_url:
                    raise AppError(
                        "No active page. Call navigate_browser first.",
                        code="no_active_page",
                    )
                cleaned = (self._sync_last_text or "").strip()
                self._log_action("extract_text_end", url=self._sync_last_url, chars=len(cleaned))
                return cleaned
            if not self._session_page:
                raise AppError(
                    "No active page. Call navigate_browser first.",
                    code="no_active_page",
                )
            try:
                self._log_action("extract_text_start", url=getattr(self._session_page, "url", None))
                text = await self._session_page.evaluate(
                    """() => {
                        const s = document.querySelector('main, article, [role="main"]')
                          || document.body;
                        return s ? s.innerText : '';
                    }"""
                )
                cleaned = (text or "").strip()
                self._log_action("extract_text_end", url=getattr(self._session_page, "url", None), chars=len(cleaned))
                return cleaned
            except Exception as e:
                logger.exception("extract_text failed")
                raise AppError(f"Extract failed: {e}", code="extract_error") from e

    async def navigate_and_extract_text(self, url: str) -> str:
        """Single-shot scrape without relying on session page."""
        await self.navigate_browser(url)
        return await self.extract_text()
