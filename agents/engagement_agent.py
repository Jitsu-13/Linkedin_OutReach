"""
Engagement agent.

Likes the latest 2-3 posts and posts an AI-generated comment
on one of them. Handles the full engagement flow with human-like
pacing and error resilience.
"""

from typing import Any, Dict, List, Optional, Tuple

from services.browser_service import BrowserService
from services.llm_service import LLMService
from utils.logger import logger
from utils.delays import action_delay, short_delay, scroll_delay
from utils.screenshot import capture as capture_screenshot


class EngagementAgent:
    """
    Handles post engagement: liking and AI-commenting on LinkedIn posts.

    Flow:
    1. Navigate to the user's recent activity page
    2. Like the latest 2-3 posts
    3. Generate an AI comment for one post (two-pass: draft → review)
    4. Post the comment with human-like typing
    """

    def __init__(
        self,
        browser: BrowserService,
        llm: LLMService,
        posts_to_like: int = 3,
        posts_to_comment: int = 1,
        sender_name: str = "",
        screenshot_dir: str = "./data/screenshots",
    ):
        self._browser = browser
        self._llm = llm
        self._posts_to_like = posts_to_like
        self._posts_to_comment = posts_to_comment
        self._sender_name = sender_name
        self._screenshot_dir = screenshot_dir

    async def engage_with_posts(
        self,
        profile_url: str,
        profile_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Like recent posts and comment on one.

        Args:
            profile_url: LinkedIn profile URL.
            profile_context: Extracted profile context dict.

        Returns:
            Dict with 'posts_liked' count and 'comment_text' (if any).
        """
        result = {
            "posts_liked": 0,
            "comment_text": "",
            "comment_draft": "",
        }

        try:
            # Navigate to the user's activity page
            activity_url = profile_url.rstrip("/") + "/recent-activity/all/"
            logger.info(f"👍 Navigating to activity page: {activity_url}")
            await self._browser.safe_navigate(activity_url, timeout=15000)
            await action_delay(2, 4)

            # Scroll to load posts
            await self._browser.human_scroll("down", 400)
            await scroll_delay()

            # ── Like posts ──
            liked_count = await self._like_posts()
            result["posts_liked"] = liked_count

            # ── Comment on a post ──
            if self._posts_to_comment > 0:
                comment_result = await self._comment_on_post(profile_context)
                result["comment_text"] = comment_result.get("final", "")
                result["comment_draft"] = comment_result.get("draft", "")

            # Navigate back to the profile
            await self._browser.safe_navigate(profile_url, timeout=15000)
            await action_delay(1, 3)

        except Exception as e:
            logger.error(f"Engagement error: {e}")
            await capture_screenshot(
                self._browser.page, "engagement_failed", self._screenshot_dir
            )
            # Try to navigate back to profile
            try:
                await self._browser.safe_navigate(profile_url, timeout=15000)
            except Exception:
                pass

        logger.info(
            f"  Engagement result — liked: {result['posts_liked']}, "
            f"commented: {'yes' if result['comment_text'] else 'no'}"
        )
        return result

    async def _like_posts(self) -> int:
        """
        Like the latest posts on the activity page.

        Returns the number of posts successfully liked.
        """
        liked = 0

        # Multiple selector strategies for the like button
        like_button_selectors = [
            "button.react-button__trigger[aria-label*='Like']",
            "button[aria-label*='like' i]:not([aria-pressed='true'])",
            "button.reactions-react-button:not(.react-button--active)",
            "span.react-button__text",
            "button[aria-pressed='false'] li-icon[type='like-icon']",
        ]

        # Find all like buttons on the page
        for selector in like_button_selectors:
            try:
                buttons = await self._browser.page.query_selector_all(selector)
                if buttons:
                    for i, button in enumerate(buttons):
                        if liked >= self._posts_to_like:
                            break

                        try:
                            # Check if already liked
                            aria_pressed = await button.get_attribute("aria-pressed")
                            if aria_pressed == "true":
                                continue

                            # Scroll to the button
                            await button.scroll_into_view_if_needed()
                            await short_delay(0.5, 1.5)

                            # Click to like
                            await button.click()
                            liked += 1
                            logger.info(f"  ❤️ Liked post {liked}/{self._posts_to_like}")

                            # Human-like delay between likes
                            await action_delay(3, 7)

                        except Exception as e:
                            logger.debug(f"  Could not like post {i+1}: {e}")
                            continue

                    if liked > 0:
                        break  # Stop trying other selectors if we found some
            except Exception:
                continue

        if liked == 0:
            logger.warning("Could not find any posts to like")

        return liked

    async def _comment_on_post(
        self, profile_context: Dict[str, Any]
    ) -> Dict[str, str]:
        """
        Generate and post an AI comment on the first visible post.

        Uses two-pass LLM generation (draft → review).

        Returns dict with 'draft' and 'final' comment text.
        """
        result = {"draft": "", "final": ""}

        try:
            # Extract the first post's text
            post_text = await self._get_first_post_text()
            if not post_text:
                logger.warning("No post text found to comment on")
                return result

            # Generate comment using two-pass LLM
            comment_result = await self._llm.generate_comment(
                post_text=post_text,
                profile_context=profile_context,
                sender_name=self._sender_name,
            )

            result["draft"] = comment_result.get("draft", "")
            result["final"] = comment_result.get("final", "")

            if not result["final"]:
                logger.warning("LLM returned empty comment")
                return result

            # Click the comment button on the first post
            comment_button_clicked = await self._click_comment_button()
            if not comment_button_clicked:
                logger.warning("Could not click comment button")
                return result

            await action_delay(1, 3)

            # Type the comment
            comment_input_selectors = [
                "div.ql-editor[data-placeholder='Add a comment…']",
                "div.ql-editor.ql-blank",
                "div[role='textbox'][aria-label*='comment' i]",
                "div.comments-comment-box__form div[contenteditable='true']",
                ".comments-comment-texteditor div[role='textbox']",
            ]

            typed = False
            for selector in comment_input_selectors:
                try:
                    exists = await self._browser.element_exists(selector, timeout=3000)
                    if exists:
                        await self._browser.human_click(selector)
                        await short_delay(0.3, 0.8)

                        # Type the comment character by character
                        element = await self._browser.page.wait_for_selector(
                            selector, timeout=3000
                        )
                        if element:
                            await element.type(
                                result["final"],
                                delay=80,  # Steady typing pace for comments
                            )
                            typed = True
                            break
                except Exception:
                    continue

            if not typed:
                logger.warning("Could not type comment into input field")
                return result

            await action_delay(1, 3)

            # Submit the comment
            submit_selectors = [
                "button.comments-comment-box__submit-button",
                "button[aria-label='Post comment']",
                "button.comments-comment-box__submit-button--cr",
                "button[type='submit'].artdeco-button--primary",
            ]

            for selector in submit_selectors:
                clicked = await self._browser.wait_and_click(selector, timeout=3000)
                if clicked:
                    logger.info(f"  💬 Comment posted: {result['final'][:80]}...")
                    await action_delay(2, 5)
                    return result

            logger.warning("Could not find submit button for comment")

        except Exception as e:
            logger.error(f"Comment error: {e}")
            await capture_screenshot(
                self._browser.page, "comment_failed", self._screenshot_dir
            )

        return result

    async def _get_first_post_text(self) -> str:
        """Extract text from the first visible post."""
        post_text_selectors = [
            ".feed-shared-update-v2__description .break-words span[dir='ltr']",
            ".feed-shared-inline-show-more-text span[dir='ltr']",
            ".feed-shared-text__text-view span[dir='ltr']",
            ".update-components-text span.break-words",
        ]

        for selector in post_text_selectors:
            texts = await self._browser.get_texts(selector)
            if texts:
                return texts[0][:500]  # First post, capped at 500 chars

        return ""

    async def _click_comment_button(self) -> bool:
        """Click the comment button on the first post."""
        comment_btn_selectors = [
            "button[aria-label*='Comment' i]",
            "button[aria-label*='comment' i]",
            "button.comment-button",
            "button.social-actions-button[aria-label*='comment' i]",
        ]

        for selector in comment_btn_selectors:
            try:
                buttons = await self._browser.page.query_selector_all(selector)
                if buttons:
                    await buttons[0].scroll_into_view_if_needed()
                    await short_delay(0.3, 0.8)
                    await buttons[0].click()
                    return True
            except Exception:
                continue

        return False
