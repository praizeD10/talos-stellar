"""X (Twitter) channel adapter — browser-based posting via Stagehand."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from rich.console import Console

from talos_agent.adapters.base import BaseSocialAdapter, ChannelCapabilities, PublishResult

if TYPE_CHECKING:
    from talos_agent.browser.session import BrowserSession
    from talos_agent.config import Settings

console = Console()

_CHAR_LIMIT = 280
_LOGIN_URL = "https://x.com/i/flow/login"
_HOME_URL = "https://x.com/home"
_MENTIONS_URL = "https://x.com/notifications/mentions"
_SEARCH_URL = "https://x.com/search?q={query}&src=typed_query&f=live"
_PROFILE_URL = "https://x.com/{username}"


class XAdapter(BaseSocialAdapter):
    """Publishes to X (Twitter) using Stagehand browser automation."""

    channel_name = "X"

    def __init__(self, browser: BrowserSession, settings: Settings) -> None:
        self._browser = browser
        self._settings = settings
        self._logged_in = False
        self._cookie_dismissed = False

    # ── Capabilities ─────────────────────────────────────────

    def get_capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(
            char_limit=_CHAR_LIMIT,
            supports_media=True,
            supports_threads=True,
            supports_replies=True,
            supports_search=True,
            supports_mentions=True,
            supports_analytics=True,
        )

    # ── Auth ─────────────────────────────────────────────────

    async def _dismiss_cookie_banner(self) -> None:
        try:
            await self._browser.act(
                "Click the 'Accept all cookies' button at the bottom of the page. "
                "It is a dark button with white text that says 'Accept all cookies'."
            )
            await asyncio.sleep(2)
        except Exception:
            pass

    async def _ensure_login(self) -> None:
        if self._logged_in:
            return

        if not self._settings.x_username or not self._settings.x_password:
            console.print("[yellow]X credentials not configured — skipping login.[/yellow]")
            return

        console.print("[dim]Checking X login status...[/dim]")
        await self._browser.goto(_HOME_URL)
        await asyncio.sleep(3)

        if not self._cookie_dismissed:
            await self._dismiss_cookie_banner()
            self._cookie_dismissed = True

        page_info = await self._browser.extract(
            "Is the user logged in to X/Twitter? "
            "If you see a compose/post box or timeline feed → logged_in: true. "
            "If you see a login form, sign-in button, or 'Sign in' text → logged_in: false.",
            schema={"type": "object", "properties": {"logged_in": {"type": "boolean"}}, "required": ["logged_in"]},
        )
        if isinstance(page_info, dict) and page_info.get("logged_in"):
            console.print("[green]Already logged in to X.[/green]")
            self._logged_in = True
            return

        console.print("[bold]Logging in to X...[/bold]")
        await self._browser.goto(_LOGIN_URL)
        await asyncio.sleep(4)

        await self._browser.act(
            f"Click on the username or email input field and type: {self._settings.x_username}"
        )
        await asyncio.sleep(2)
        await self._browser.act("Click the Next button")
        await asyncio.sleep(4)

        # X sometimes requests email/phone verification before the password step
        check = await self._browser.extract(
            "What is the current page asking for? "
            "email or phone verification → type: 'verification'. "
            "password field → type: 'password'. "
            "something else → type: 'other'.",
            schema={"type": "object", "properties": {"type": {"type": "string"}}, "required": ["type"]},
        )
        page_type = check.get("type", "other") if isinstance(check, dict) else "other"
        if page_type == "verification" and self._settings.x_email:
            await self._browser.act(
                f"Click on the input field and type: {self._settings.x_email}"
            )
            await asyncio.sleep(1)
            await self._browser.act("Click the Next button")
            await asyncio.sleep(4)

        await self._browser.act(
            f"Click on the password input field and type: {self._settings.x_password}"
        )
        await asyncio.sleep(1)
        await self._browser.act("Click the Log in button")
        await asyncio.sleep(5)

        post_login = await self._browser.extract(
            "Is the user now logged in to X/Twitter? "
            "If you see a timeline, home feed, or compose button → logged_in: true. "
            "Otherwise → logged_in: false.",
            schema={"type": "object", "properties": {"logged_in": {"type": "boolean"}}, "required": ["logged_in"]},
        )
        if isinstance(post_login, dict) and post_login.get("logged_in"):
            console.print("[bold green]Successfully logged in to X.[/bold green]")
            self._logged_in = True
        else:
            console.print("[red]X login may have failed — continuing anyway.[/red]")

    # ── Publishing ───────────────────────────────────────────

    # Playwright selectors for X's compose UI (kept in one place so they're easy to update)
    _COMPOSE_SELECTORS = [
        '[data-testid="tweetTextarea_0"]',
        '[aria-label="Post text"]',
        'div[contenteditable="true"][role="textbox"]',
    ]
    _SUBMIT_SELECTORS = [
        '[data-testid="tweetButtonInline"]',
        '[data-testid="tweetButton"]',
        'button[type="submit"]:has-text("Post")',
    ]

    async def _compose_via_selectors(self, content: str) -> bool:
        """
        Fallback: open compose dialog and post via Playwright selectors.
        Returns True if the tweet was submitted, False otherwise.
        """
        pw, browser, page = await self._browser.get_playwright_page()
        if page is None:
            return False

        try:
            # Try clicking the compose/tweet button in the sidebar first
            compose_btn = page.locator('[data-testid="SideNav_NewTweet_Button"]')
            if compose_btn.count():
                compose_btn.first.click()
                await asyncio.sleep(2)

            # Find the compose text area
            box = None
            for sel in self._COMPOSE_SELECTORS:
                loc = page.locator(sel)
                if loc.count():
                    box = loc.first
                    break

            if box is None:
                console.print("[yellow]X selector fallback: compose box not found.[/yellow]")
                return False

            box.click()
            await asyncio.sleep(0.5)
            box.type(content, delay=30)
            await asyncio.sleep(1)

            # Submit
            for sel in self._SUBMIT_SELECTORS:
                btn = page.locator(sel)
                if btn.count() and btn.first.is_enabled():
                    btn.first.click()
                    await asyncio.sleep(4)
                    return True

            console.print("[yellow]X selector fallback: submit button not found.[/yellow]")
            return False
        except Exception as exc:
            console.print(f"[yellow]X selector fallback error: {exc}[/yellow]")
            return False
        finally:
            try:
                browser.close()
                pw.stop()
            except Exception:
                pass

    async def post(self, content: str, **kwargs) -> PublishResult:
        valid, error = self.validate_content(content)
        if not valid:
            return PublishResult(status="failed", channel=self.channel_name, content=content, error=error)

        await self._ensure_login()
        await self._dismiss_cookie_banner()

        # --- Primary path: keyboard shortcut ---
        keyboard_ok = False
        try:
            await self._browser.keyboard_press("n")
            await asyncio.sleep(2)
            await self._browser.keyboard_type(content)
            await asyncio.sleep(1)
            await self._browser.keyboard_press("Control+Enter")
            await asyncio.sleep(4)
            keyboard_ok = True
        except Exception as exc:
            console.print(f"[yellow]X keyboard path failed ({type(exc).__name__}: {exc}), trying selector fallback.[/yellow]")

        # --- Check whether the dialog is still open ---
        if keyboard_ok:
            verify = await self._browser.extract(
                "Is there a compose tweet dialog/modal currently open on the page? "
                "If no dialog is open and you see the timeline → dialog_open: false. "
                "If the compose dialog is still visible with text → dialog_open: true.",
                schema={"type": "object", "properties": {"dialog_open": {"type": "boolean"}}, "required": ["dialog_open"]},
            )
            dialog_open = bool(verify.get("dialog_open")) if isinstance(verify, dict) else True

            if not dialog_open:
                return PublishResult(status="posted", channel=self.channel_name, content=content)

            # Dismiss the stale dialog before trying the fallback
            console.print("[yellow]Keyboard path: dialog still open, switching to selector fallback.[/yellow]")
            try:
                await self._browser.act("Press the Escape key")
                await asyncio.sleep(1)
                await self._browser.act("Click the 'Discard' button if it appears")
                await asyncio.sleep(1)
            except Exception:
                pass

        # --- Fallback path: Playwright selectors ---
        await self._browser.goto(_HOME_URL)
        await asyncio.sleep(2)

        posted = await self._compose_via_selectors(content)
        if posted:
            return PublishResult(status="posted", channel=self.channel_name, content=content)

        return PublishResult(
            status="failed",
            channel=self.channel_name,
            content=content,
            error="Post failed — both keyboard shortcut and selector fallback were unable to submit the tweet.",
        )

    async def reply(self, target_url: str, content: str, **kwargs) -> PublishResult:
        await self._ensure_login()
        await self._browser.goto(target_url)
        await asyncio.sleep(2)
        await self._browser.act("Click the reply button")
        await self._browser.act(f"Type the following reply: {content}")
        await self._browser.act("Click the Reply button to post")
        return PublishResult(
            status="posted",
            channel=self.channel_name,
            content=content,
            metadata={"target_url": target_url},
        )

    # ── Discovery ────────────────────────────────────────────

    async def get_mentions(self, **kwargs) -> list[dict]:
        await self._ensure_login()
        await self._browser.goto(_MENTIONS_URL)
        await asyncio.sleep(2)
        result = await self._browser.extract(
            "Extract the latest 10 mentions: author handle, text content, tweet URL, and timestamp"
        )
        return result if isinstance(result, list) else []

    async def search(self, query: str, **kwargs) -> list[dict]:
        await self._ensure_login()
        await self._browser.goto(_SEARCH_URL.format(query=query))
        await asyncio.sleep(2)
        results = await self._browser.extract(
            "Extract the top 10 posts: author handle, text content, engagement (likes, reposts), and tweet URL"
        )
        return results if isinstance(results, list) else []

    # ── Analytics ────────────────────────────────────────────

    async def get_post_performance(self, content_snippet: str, **kwargs) -> dict:
        await self._ensure_login()
        username = self._settings.x_username
        if not username:
            return {"error": "X username not configured"}
        await self._browser.goto(_PROFILE_URL.format(username=username))
        await asyncio.sleep(3)
        metrics = await self._browser.extract(
            f"Find the tweet that contains text similar to: '{content_snippet[:80]}'. "
            "Extract: likes (number), reposts/retweets (number), replies (number), "
            "views/impressions (number), and the tweet URL. "
            "If not found, return found: false.",
            schema={
                "type": "object",
                "properties": {
                    "found": {"type": "boolean"},
                    "likes": {"type": "integer"},
                    "reposts": {"type": "integer"},
                    "replies": {"type": "integer"},
                    "impressions": {"type": "integer"},
                    "tweet_url": {"type": "string"},
                },
                "required": ["found"],
            },
        )
        return metrics if isinstance(metrics, dict) else {"found": False}

    async def get_profile_stats(self, **kwargs) -> dict:
        await self._ensure_login()
        username = self._settings.x_username
        if not username:
            return {"error": "X username not configured"}
        await self._browser.goto(_PROFILE_URL.format(username=username))
        await asyncio.sleep(3)
        stats = await self._browser.extract(
            "Extract the profile stats: followers count (number), following count (number), "
            "total posts count (number).",
            schema={
                "type": "object",
                "properties": {
                    "followers": {"type": "integer"},
                    "following": {"type": "integer"},
                    "total_posts": {"type": "integer"},
                },
                "required": ["followers"],
            },
        )
        return stats if isinstance(stats, dict) else {"error": "Could not extract profile stats"}
