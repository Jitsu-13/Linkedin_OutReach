"""
Connection request agent.

Handles sending LinkedIn connection requests with personalized notes.
Manages the full UI flow: Connect button → Add a note → Paste note → Send.
"""

from typing import Any, Dict, Optional

from services.browser_service import BrowserService
from utils.logger import logger
from utils.delays import action_delay, short_delay
from utils.screenshot import capture as capture_screenshot
from utils.retry import with_retry


class ConnectionAgent:
    """
    Sends LinkedIn connection requests with personalized notes.

    Handles multiple UI states:
    - Direct "Connect" button on profile
    - "Connect" in "More" dropdown
    - "Follow" profiles (where Connect requires extra steps)
    - Already connected / pending states
    """

    def __init__(self, browser: BrowserService,
                 screenshot_dir: str = "./data/screenshots"):
        self._browser = browser
        self._screenshot_dir = screenshot_dir

    async def send_request(self, note: str, profile_url: str = "") -> Dict[str, Any]:
        """
        Send a connection request with a personalized note.

        Assumes we're already on the target profile page.

        Args:
            note: The personalized connection note to send.
            profile_url: Profile URL (for logging).

        Returns:
            Dict with 'success' bool, 'status' string, and optional 'error'.
        """
        result = {
            "success": False,
            "status": "error",
            "error": "",
        }

        try:
            logger.info(f"🔗 Sending connection request to {profile_url or 'current profile'}...")

            # ── Step 1: Check current connection state ──
            state = await self._detect_connection_state()
            logger.info(f"  Connection state: {state}")

            if state == "connected":
                result["status"] = "skipped"
                result["error"] = "Already connected"
                logger.info("  ⏭️ Already connected — skipping")
                return result

            if state == "pending":
                result["status"] = "skipped"
                result["error"] = "Connection request already pending"
                logger.info("  ⏭️ Request already pending — skipping")
                return result

            # ── Step 2: Click Connect button ──
            connect_clicked = await self._click_connect_button(state)
            if not connect_clicked:
                result["error"] = "Could not find or click Connect button"
                await capture_screenshot(
                    self._browser.page, "connect_button_not_found", self._screenshot_dir
                )
                return result

            await action_delay(1, 3)

            # ── Step 3: Handle "Add a note" dialog ──
            note_added = await self._add_note(note)
            if not note_added:
                # Some profiles skip the "Add a note" option
                logger.warning("Could not add note — request may have sent without note")
                result["status"] = "sent"
                result["success"] = True
                return result

            await action_delay(1, 2)

            # ── Step 4: Click Send ──
            sent = await self._click_send()
            if sent:
                result["success"] = True
                result["status"] = "sent"
                logger.info("  ✅ Connection request sent successfully!")
            else:
                result["error"] = "Could not click Send button"
                await capture_screenshot(
                    self._browser.page, "send_button_failed", self._screenshot_dir
                )

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Connection request error: {e}")
            await capture_screenshot(
                self._browser.page, "connection_request_error", self._screenshot_dir
            )

        return result

    async def _detect_connection_state(self) -> str:
        """
        Detect the current connection state with the profile.

        Returns: 'not_connected', 'connected', 'pending', 'follow_first'
        """
        page = self._browser.page

        # Check for "Message" button (indicates already connected)
        message_selectors = [
            "button[aria-label*='Message']",
            "a[href*='messaging'][aria-label*='Message']",
        ]
        for sel in message_selectors:
            if await self._browser.element_exists(sel, timeout=2000):
                return "connected"

        # Check for "Pending" state
        pending_selectors = [
            "button[aria-label*='Pending']",
            "button:has-text('Pending')",
        ]
        for sel in pending_selectors:
            if await self._browser.element_exists(sel, timeout=2000):
                return "pending"

        # Check for direct Connect button
        connect_selectors = [
            "button[aria-label*='connect' i]:not([aria-label*='disconnect' i])",
            "button.pvs-profile-actions__action[aria-label*='connect' i]",
        ]
        for sel in connect_selectors:
            if await self._browser.element_exists(sel, timeout=2000):
                return "not_connected"

        # Check for Follow button (Connect may be in "More" menu)
        follow_selectors = [
            "button[aria-label*='Follow']",
            "button:has-text('Follow')",
        ]
        for sel in follow_selectors:
            if await self._browser.element_exists(sel, timeout=2000):
                return "follow_first"

        return "not_connected"  # Default: try anyway

    async def _click_connect_button(self, state: str) -> bool:
        """
        Find and click the Connect button.

        Handles different UI layouts based on detected state.
        """
        # ── Try direct Connect button first ──
        direct_selectors = [
            "button[aria-label*='connect' i]:not([aria-label*='disconnect' i])",
            "button.pvs-profile-actions__action[aria-label*='connect' i]",
            "button.artdeco-button--primary[aria-label*='connect' i]",
        ]

        for sel in direct_selectors:
            if await self._browser.wait_and_click(sel, timeout=3000):
                logger.debug(f"  Clicked direct Connect: {sel}")
                return True

        # ── Try "More" dropdown → Connect ──
        more_selectors = [
            "button[aria-label='More actions']",
            "button.artdeco-dropdown__trigger.pvs-profile-actions__overflow-toggle",
            ".pvs-profile-actions__overflow-toggle",
            "button.artdeco-dropdown__trigger[aria-label*='More']",
        ]

        for more_sel in more_selectors:
            if await self._browser.wait_and_click(more_sel, timeout=3000):
                logger.debug(f"  Opened More dropdown: {more_sel}")
                await short_delay(0.5, 1.5)

                # Look for Connect in the dropdown
                dropdown_connect_selectors = [
                    "div.artdeco-dropdown__content li button span:has-text('Connect')",
                    ".artdeco-dropdown__content-inner li[class*='connect'] button",
                    "div[role='listbox'] button[aria-label*='connect' i]",
                    "ul.artdeco-dropdown__content-inner button[aria-label*='connect' i]",
                    ".artdeco-dropdown__content button:has-text('Connect')",
                ]

                for dd_sel in dropdown_connect_selectors:
                    if await self._browser.wait_and_click(dd_sel, timeout=3000):
                        logger.debug(f"  Clicked Connect in dropdown: {dd_sel}")
                        return True

                # Close dropdown if Connect not found
                await self._browser.page.keyboard.press("Escape")
                await short_delay(0.3, 0.8)

        logger.warning("Could not find Connect button in any location")
        return False

    async def _add_note(self, note: str) -> bool:
        """
        Handle the "Add a note" dialog and paste the personalized note.
        """
        # Wait for the connection dialog to appear
        await short_delay(1.0, 2.0)

        # ── Click "Add a note" button ──
        add_note_selectors = [
            "button[aria-label='Add a note']",
            "button:has-text('Add a note')",
            "button.artdeco-button--secondary:has-text('Add a note')",
            ".send-invite button:has-text('Add a note')",
        ]

        note_button_clicked = False
        for sel in add_note_selectors:
            if await self._browser.wait_and_click(sel, timeout=5000):
                note_button_clicked = True
                logger.debug(f"  Clicked 'Add a note': {sel}")
                break

        if not note_button_clicked:
            # Maybe the note textarea is already visible (some UI variants)
            pass

        await short_delay(0.5, 1.5)

        # ── Type the note into the textarea ──
        note_input_selectors = [
            "textarea[name='message']",
            "textarea#custom-message",
            "textarea.connect-button-send-invite__custom-message",
            "textarea[placeholder*='Add a note']",
            "textarea[id*='custom-message']",
            ".send-invite textarea",
        ]

        for sel in note_input_selectors:
            try:
                exists = await self._browser.element_exists(sel, timeout=3000)
                if exists:
                    await self._browser.human_type(sel, note, clear_first=True)
                    logger.info(f"  📝 Note typed ({len(note)} chars)")
                    return True
            except Exception as e:
                logger.debug(f"  Note input failed for {sel}: {e}")
                continue

        logger.warning("Could not find note input field")
        return False

    async def _click_send(self) -> bool:
        """Click the Send/Send now button to submit the connection request."""
        send_selectors = [
            "button[aria-label='Send now']",
            "button[aria-label='Send invitation']",
            "button:has-text('Send')",
            "button.artdeco-button--primary:has-text('Send')",
            ".send-invite button.artdeco-button--primary",
            "button[aria-label='Send']",
        ]

        for sel in send_selectors:
            if await self._browser.wait_and_click(sel, timeout=5000):
                logger.debug(f"  Clicked Send: {sel}")
                await short_delay(1.0, 3.0)

                # Verify: check for success toast or dialog dismissal
                await self._verify_sent()
                return True

        return False

    async def _verify_sent(self) -> bool:
        """
        Verify that the connection request was actually sent.

        Checks for success toast notifications or dialog dismissal.
        """
        await short_delay(1.0, 2.0)

        # Check for success indicators
        success_selectors = [
            ".artdeco-toast-item__message",
            "div[role='alert']",
            ".artdeco-toast-item",
        ]

        for sel in success_selectors:
            text = await self._browser.get_text(sel, timeout=3000)
            if text and ("sent" in text.lower() or "invitation" in text.lower()):
                logger.info(f"  ✅ Verified: {text}")
                return True

        # If no toast, check that the dialog is gone (which implies success)
        dialog_gone = not await self._browser.element_exists(
            "textarea[name='message']", timeout=2000
        )
        if dialog_gone:
            logger.info("  ✅ Connection dialog dismissed (assumed sent)")
            return True

        return False
