"""
Browser automation service using Playwright with stealth patches.

Provides a persistent browser context that reuses sessions across runs,
human-like interaction methods, and anti-detection measures.
"""

import asyncio
import random
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Error as PlaywrightError,
)
from playwright_stealth import stealth_async

from utils.logger import logger
from utils.delays import short_delay, typing_delay_ms
from utils.screenshot import capture as capture_screenshot
from utils.retry import with_retry


class BrowserService:
    """
    Stealth browser automation service.

    Key features:
    - Persistent context (cookies/session survive restarts)
    - playwright-stealth patches on every page
    - Human-like mouse movement, clicking, and typing
    - Headed mode by default (less detectable)
    """

    def __init__(
        self,
        headless: bool = False,
        user_data_dir: str = "./browser_data",
        viewport_width: int = 1366,
        viewport_height: int = 768,
        screenshot_dir: str = "./data/screenshots",
        typing_delay_min_ms: int = 50,
        typing_delay_max_ms: int = 150,
    ):
        self._headless = headless
        self._user_data_dir = user_data_dir
        self._viewport_width = viewport_width
        self._viewport_height = viewport_height
        self._screenshot_dir = screenshot_dir
        self._typing_min = typing_delay_min_ms
        self._typing_max = typing_delay_max_ms

        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    async def start(self) -> Page:
        """
        Launch browser with persistent context and stealth patches.

        Returns the main page object.
        """
        # Ensure browser data directory exists
        Path(self._user_data_dir).mkdir(parents=True, exist_ok=True)

        self._playwright = await async_playwright().start()

        # Launch persistent context — saves cookies/localStorage between runs
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=self._user_data_dir,
            headless=self._headless,
            viewport={"width": self._viewport_width, "height": self._viewport_height},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-infobars",
                "--no-first-run",
            ],
            ignore_default_args=["--enable-automation"],
        )

        # Use existing page or create new one
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = await self._context.new_page()

        # Apply stealth patches
        await stealth_async(self._page)

        logger.info(
            f"Browser started — headless={self._headless}, "
            f"viewport={self._viewport_width}x{self._viewport_height}, "
            f"user_data_dir={self._user_data_dir}"
        )
        return self._page

    async def new_page(self) -> Page:
        """Create a new page with stealth patches applied."""
        if not self._context:
            raise RuntimeError("Browser not started. Call start() first.")

        page = await self._context.new_page()
        await stealth_async(page)
        return page

    @property
    def page(self) -> Page:
        """Get the current main page."""
        if not self._page:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._page

    # ── Navigation ────────────────────────────────────────────

    @with_retry(max_attempts=3, retry_on=(PlaywrightError, TimeoutError))
    async def safe_navigate(self, url: str, wait_until: str = "domcontentloaded",
                            timeout: int = 30000) -> None:
        """
        Navigate to a URL with retry logic and screenshot on failure.
        """
        logger.info(f"Navigating to: {url}")
        try:
            await self._page.goto(url, wait_until=wait_until, timeout=timeout)
            await short_delay(1.0, 2.5)
            logger.debug(f"Navigation complete: {url}")
        except Exception as e:
            logger.error(f"Navigation failed: {url} — {e}")
            await capture_screenshot(self._page, f"nav_failed", self._screenshot_dir)
            raise

    # ── Human-like interactions ───────────────────────────────

    async def human_click(self, selector: str, timeout: int = 10000) -> None:
        """
        Click an element with human-like mouse movement.

        Moves the mouse to a random point within the element's bounding box
        before clicking, simulating natural mouse movement.
        """
        try:
            element = await self._page.wait_for_selector(selector, timeout=timeout)
            if not element:
                raise PlaywrightError(f"Element not found: {selector}")

            # Get element bounding box
            box = await element.bounding_box()
            if box:
                # Click at a random point within the element
                x = box["x"] + random.uniform(box["width"] * 0.2, box["width"] * 0.8)
                y = box["y"] + random.uniform(box["height"] * 0.2, box["height"] * 0.8)

                # Move mouse with small random steps to simulate human movement
                await self._page.mouse.move(x, y, steps=random.randint(5, 15))
                await asyncio.sleep(random.uniform(0.1, 0.3))
                await self._page.mouse.click(x, y)
            else:
                # Fallback: direct click
                await element.click()

            logger.debug(f"Clicked: {selector}")

        except Exception as e:
            logger.warning(f"Click failed on '{selector}': {e}")
            raise

    async def human_type(self, selector: str, text: str,
                         clear_first: bool = True, timeout: int = 10000) -> None:
        """
        Type text into an input field with human-like speed variations.

        Each keystroke has a random delay to simulate natural typing.
        """
        try:
            element = await self._page.wait_for_selector(selector, timeout=timeout)
            if not element:
                raise PlaywrightError(f"Element not found: {selector}")

            if clear_first:
                await element.click()
                await self._page.keyboard.press("Control+a")
                await asyncio.sleep(random.uniform(0.1, 0.3))

            # Type character by character with random delays
            for char in text:
                await element.type(char, delay=typing_delay_ms(self._typing_min, self._typing_max))

            logger.debug(f"Typed {len(text)} chars into: {selector}")

        except Exception as e:
            logger.warning(f"Typing failed on '{selector}': {e}")
            raise

    async def human_scroll(self, direction: str = "down",
                           amount: int = 0) -> None:
        """
        Scroll the page with human-like behavior.

        Args:
            direction: 'down' or 'up'
            amount: Pixels to scroll. 0 = random amount (300-700px).
        """
        if amount == 0:
            amount = random.randint(300, 700)

        if direction == "up":
            amount = -amount

        await self._page.mouse.wheel(0, amount)
        await asyncio.sleep(random.uniform(0.5, 1.5))
        logger.debug(f"Scrolled {direction} by {abs(amount)}px")

    # ── Element interaction helpers ───────────────────────────

    async def wait_and_click(self, selector: str, timeout: int = 10000) -> bool:
        """Wait for element to appear, then click it. Returns True if successful."""
        try:
            await self._page.wait_for_selector(selector, timeout=timeout)
            await self.human_click(selector, timeout=timeout)
            return True
        except Exception:
            return False

    async def element_exists(self, selector: str, timeout: int = 3000) -> bool:
        """Check if an element exists on the page."""
        try:
            element = await self._page.wait_for_selector(selector, timeout=timeout)
            return element is not None
        except Exception:
            return False

    async def get_text(self, selector: str, timeout: int = 5000) -> str:
        """Get text content of an element. Returns empty string if not found."""
        try:
            element = await self._page.wait_for_selector(selector, timeout=timeout)
            if element:
                return (await element.text_content() or "").strip()
        except Exception:
            pass
        return ""

    async def get_texts(self, selector: str) -> list:
        """Get text content of all matching elements."""
        try:
            elements = await self._page.query_selector_all(selector)
            texts = []
            for el in elements:
                text = await el.text_content()
                if text and text.strip():
                    texts.append(text.strip())
            return texts
        except Exception:
            return []

    # ── LinkedIn-specific helpers ─────────────────────────────

    async def check_login_status(self) -> bool:
        """
        Check if the user is currently logged in to LinkedIn.

        Returns True if logged in, False if login page is shown.
        """
        try:
            await self.safe_navigate("https://www.linkedin.com/feed/", timeout=15000)
            await asyncio.sleep(2)

            # Check for feed indicators
            current_url = self._page.url
            if "/login" in current_url or "/checkpoint" in current_url:
                return False

            # Look for navigation elements that indicate logged-in state
            nav_exists = await self.element_exists(
                'nav[aria-label="Primary"]', timeout=5000
            )
            return nav_exists

        except Exception as e:
            logger.warning(f"Login check failed: {e}")
            return False

    async def perform_login(self, email: str, password: str) -> bool:
        """
        Perform LinkedIn login.

        Note: This is used only for initial login. Subsequent runs
        reuse the session via persistent browser context.
        """
        try:
            await self.safe_navigate("https://www.linkedin.com/login")
            await asyncio.sleep(2)

            # Type email
            await self.human_type('#username', email)
            await short_delay(0.5, 1.5)

            # Type password
            await self.human_type('#password', password)
            await short_delay(0.5, 1.0)

            # Click sign in
            await self.human_click('button[type="submit"]')

            # Wait for redirect
            await asyncio.sleep(5)

            # Check if login was successful
            current_url = self._page.url
            if "/feed" in current_url or "/mynetwork" in current_url:
                logger.info("✅ LinkedIn login successful")
                return True

            # Check for verification/CAPTCHA
            if "/checkpoint" in current_url:
                logger.warning(
                    "⚠️  LinkedIn requires verification (CAPTCHA/2FA). "
                    "Please complete it manually in the browser window."
                )
                # Wait for manual intervention (up to 5 minutes)
                for _ in range(60):
                    await asyncio.sleep(5)
                    current_url = self._page.url
                    if "/feed" in current_url or "/mynetwork" in current_url:
                        logger.info("✅ Manual verification completed, login successful")
                        return True

                logger.error("Login timed out waiting for manual verification")
                return False

            logger.error(f"Login may have failed. Current URL: {current_url}")
            return False

        except Exception as e:
            logger.error(f"Login error: {e}")
            await capture_screenshot(self._page, "login_failed", self._screenshot_dir)
            return False

    async def detect_captcha_or_restriction(self) -> bool:
        """
        Check if LinkedIn is showing a CAPTCHA or account restriction page.

        Returns True if automation should pause.
        """
        current_url = self._page.url
        page_text = await self._page.content()

        restriction_indicators = [
            "/checkpoint/",
            "security verification",
            "unusual activity",
            "restricted",
            "captcha",
            "verify your identity",
        ]

        for indicator in restriction_indicators:
            if indicator in current_url.lower() or indicator in page_text.lower():
                logger.warning(f"🛑 Restriction detected: '{indicator}' found")
                await capture_screenshot(
                    self._page, "restriction_detected", self._screenshot_dir
                )
                return True

        return False

    # ── Cleanup ───────────────────────────────────────────────

    async def close(self) -> None:
        """Gracefully close the browser."""
        try:
            if self._context:
                await self._context.close()
            if self._playwright:
                await self._playwright.stop()
            logger.info("Browser closed")
        except Exception as e:
            logger.warning(f"Error closing browser: {e}")
