"""
Profile extraction agent.

Navigates to a LinkedIn profile page and extracts visible context:
name, headline, current role, about section, recent activity,
mutual connections.

Uses multiple fallback CSS selectors for resilience against DOM changes.
"""

import json
from typing import Any, Dict, List, Optional

from services.browser_service import BrowserService
from utils.logger import logger
from utils.delays import action_delay, scroll_delay
from utils.screenshot import capture as capture_screenshot
from utils.retry import with_retry


# ── CSS Selector chains (multiple fallbacks per element) ──────

SELECTORS = {
    "name": [
        # LinkedIn's current layout (2025+) uses h2 for the profile name
        "div[aria-label*='Verified Profile'] h2",
        "div[aria-label*='Profile'] h2",
        "h2.a54c0ea5",
        "h2[class*='a54c0ea5']",
        # Older layout used h1 — keep as fallback
        "h1.text-heading-xlarge",
        "h1[class*='heading-xlarge']",
        "h1[class*='t-24']",
        ".pv-text-details__left-panel h1",
        "section.pv-top-card h1",
        ".ph5 h1",
        "main h1",
        "h2",  # broad h2 fallback
        "h1",  # broad h1 fallback
    ],
    "headline": [
        ".text-body-medium.break-words",
        "div[class*='text-body-medium'][class*='break-words']",
        ".pv-text-details__left-panel .text-body-medium",
        "div.text-body-medium",
        ".ph5 .text-body-medium",
    ],
    "location": [
        ".text-body-small.inline.t-black--light.break-words",
        "span.text-body-small.inline",
        ".pv-text-details__left-panel span.text-body-small",
    ],
    "about": [
        "#about ~ div .inline-show-more-text span[aria-hidden='true']",
        "#about ~ div .pv-shared-text-with-see-more span.visually-hidden",
        "section#about div.inline-show-more-text",
        "#about + .display-flex .inline-show-more-text span",
        ".pv-about__summary-text",
    ],
    "experience_title": [
        ".pvs-list__item--line-separated .t-bold span[aria-hidden='true']",
        "#experience ~ div .pvs-entity__path-node + div span.t-bold span",
        ".experience-section .pv-entity__summary-info h3",
    ],
    "experience_company": [
        ".pvs-list__item--line-separated .t-normal span[aria-hidden='true']",
        "#experience ~ div .t-14.t-normal span[aria-hidden='true']",
        ".experience-section .pv-entity__secondary-title",
    ],
    "mutual_connections": [
        "a[href*='mutual-connections'] span",
        ".pv-top-card--list-bullet .t-black--light",
        "span.t-black--light.t-normal",
    ],
    "connect_button": [
        "button.pvs-profile-actions__action[aria-label*='connect' i]",
        "button[aria-label*='Connect' i]",
        "button[aria-label*='connect' i]:not([aria-label*='disconnect' i])",
        ".pv-top-card-v2-ctas button[aria-label*='connect' i]",
        "li-icon[type='connect']",
    ],
    "more_button": [
        "button[aria-label='More actions']",
        "button.artdeco-dropdown__trigger.pvs-profile-actions__overflow-toggle",
        ".pvs-profile-actions__overflow-toggle",
    ],
    "activity_section": [
        "#content_collections",
        "section.pv-recent-activity-section-v2",
        "div.pv-recent-activity-section",
    ],
}


async def _try_selectors(browser: BrowserService, selector_list: List[str],
                         get_text: bool = True, timeout: int = 3000) -> str:
    """
    Try multiple CSS selectors in order, returning the first match.

    Args:
        browser: BrowserService instance.
        selector_list: List of CSS selectors to try.
        get_text: If True, return text content. If False, return 'found'/''.
        timeout: Timeout per selector attempt.

    Returns:
        Text content of the first matching element, or empty string.
    """
    for selector in selector_list:
        try:
            if get_text:
                text = await browser.get_text(selector, timeout=timeout)
                if text:
                    return text
            else:
                exists = await browser.element_exists(selector, timeout=timeout)
                if exists:
                    return "found"
        except Exception:
            continue
    return ""


class ProfileAgent:
    """
    Extracts structured profile context from a LinkedIn profile page.

    Navigates to the profile, scrolls to load dynamic content,
    and extracts key fields using fallback selector chains.
    """

    def __init__(self, browser: BrowserService, screenshot_dir: str = "./data/screenshots"):
        self._browser = browser
        self._screenshot_dir = screenshot_dir

    @with_retry(max_attempts=2, retry_on=(Exception,))
    async def extract_context(self, profile_url: str) -> Dict[str, Any]:
        """
        Navigate to a LinkedIn profile and extract all visible context.

        Args:
            profile_url: Full LinkedIn profile URL.

        Returns:
            Dict with keys: name, headline, current_role, company,
            about_snippet, mutual_connections, recent_posts, raw_url
        """
        logger.info(f"🔍 Extracting profile context: {profile_url}")

        # Navigate and wait for full page load (not just DOM parse)
        await self._browser.safe_navigate(profile_url, timeout=60000, wait_until="load")

        # Give React time to render components after the load event
        await action_delay(4, 6)

        # Wait up to 30s for the name element (h2 on new layout, h1 on old)
        try:
            await self._browser.page.wait_for_selector("h1, h2", timeout=30000)
            logger.debug("Name heading found — page rendered")
        except Exception:
            logger.warning("Name heading not found after 30s — extracting whatever is available")

        await action_delay(1, 2)

        # Check for restriction/CAPTCHA
        if await self._browser.detect_captcha_or_restriction():
            raise RuntimeError("CAPTCHA or restriction detected on profile page")

        # Scroll down to load dynamic content
        await self._browser.human_scroll("down", 400)
        await scroll_delay()
        await self._browser.human_scroll("down", 400)
        await scroll_delay()

        # ── Extract fields ──
        context: Dict[str, Any] = {"raw_url": profile_url}

        # Name
        context["name"] = await _try_selectors(self._browser, SELECTORS["name"])
        if not context["name"]:
            logger.warning("Could not extract name — taking screenshot")
            await capture_screenshot(
                self._browser.page, "name_extraction_failed", self._screenshot_dir
            )

        # Headline
        context["headline"] = await _try_selectors(self._browser, SELECTORS["headline"])

        # Location
        context["location"] = await _try_selectors(self._browser, SELECTORS["location"])

        # About section
        # May need to scroll to it first
        about_text = await _try_selectors(self._browser, SELECTORS["about"])
        context["about_snippet"] = about_text[:500] if about_text else ""

        # Current role (first experience entry)
        context["current_role"] = await _try_selectors(
            self._browser, SELECTORS["experience_title"]
        )
        context["company"] = await _try_selectors(
            self._browser, SELECTORS["experience_company"]
        )

        # Mutual connections
        mutual_text = await _try_selectors(
            self._browser, SELECTORS["mutual_connections"]
        )
        context["mutual_connections"] = self._parse_mutual_count(mutual_text)

        # Recent posts (get from activity section)
        context["recent_posts"] = await self._extract_recent_posts(profile_url)

        logger.info(
            f"  Profile extracted — name='{context.get('name', '')}', "
            f"headline='{context.get('headline', '')[:50]}...', "
            f"posts={len(context.get('recent_posts', []))}"
        )

        return context

    async def _extract_recent_posts(self, profile_url: str) -> List[str]:
        """
        Extract text snippets from the user's recent posts.

        Navigates to the activity page to find posts.
        """
        posts = []
        try:
            # Navigate to the activity/posts section
            activity_url = profile_url.rstrip("/") + "/recent-activity/all/"
            await self._browser.safe_navigate(activity_url, timeout=45000, wait_until="load")
            await action_delay(3, 5)

            # Scroll to load posts
            await self._browser.human_scroll("down", 500)
            await scroll_delay()

            # Try to extract post text
            post_selectors = [
                "span[data-testid='expandable-text-box']",
                ".feed-shared-update-v2__description .break-words span[dir='ltr']",
                ".feed-shared-inline-show-more-text span[dir='ltr']",
                ".feed-shared-text__text-view span[dir='ltr']",
                ".update-components-text span.break-words",
                "span.break-words.tvm-parent-container",
            ]

            for selector in post_selectors:
                texts = await self._browser.get_texts(selector)
                if texts:
                    posts = [t[:300] for t in texts[:5]]  # Cap at 5 posts, 300 chars each
                    break

            # Navigate back to the profile
            await self._browser.safe_navigate(profile_url, timeout=45000, wait_until="load")
            await action_delay(1, 3)

        except Exception as e:
            logger.warning(f"Could not extract recent posts: {e}")
            # Navigate back to profile on failure
            try:
                await self._browser.safe_navigate(profile_url, timeout=45000, wait_until="load")
            except Exception:
                pass

        logger.debug(f"  Extracted {len(posts)} recent posts")
        return posts

    @staticmethod
    def _parse_mutual_count(text: str) -> int:
        """Parse mutual connection count from text like '12 mutual connections'."""
        if not text:
            return 0
        import re
        match = re.search(r"(\d+)", text)
        return int(match.group(1)) if match else 0
