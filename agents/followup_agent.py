"""
Follow-up agent.

Scheduled every 14 days to:
1. Check LinkedIn "Sent Invitations" for acceptance/pending status
2. Withdraw requests still pending after the configured threshold
3. Update local state + sync to Google Sheets
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from services.browser_service import BrowserService
from services import state_service
from utils.logger import logger
from utils.delays import action_delay, short_delay
from utils.screenshot import capture as capture_screenshot


# LinkedIn Sent Invitations URL
SENT_INVITATIONS_URL = "https://www.linkedin.com/mynetwork/invitation-manager/sent/"


class FollowupAgent:
    """
    Checks sent invitations and manages stale connection requests.

    Strategy for acceptance detection:
    - Navigate to Sent Invitations page
    - For each pending record in local state:
      - If person is found in sent list → still pending
      - If person is NOT in sent list → likely accepted (or withdrawn by them)
    - Requests older than threshold are withdrawn via the UI
    """

    def __init__(
        self,
        browser: BrowserService,
        withdraw_after_days: int = 14,
        screenshot_dir: str = "./data/screenshots",
    ):
        self._browser = browser
        self._withdraw_after_days = withdraw_after_days
        self._screenshot_dir = screenshot_dir

    async def run_followup(self) -> Dict[str, Any]:
        """
        Execute the full follow-up check.

        Returns:
            Dict with counts: 'accepted', 'withdrawn', 'still_pending', 'errors'
        """
        results = {
            "accepted": 0,
            "withdrawn": 0,
            "still_pending": 0,
            "errors": 0,
            "details": [],
        }

        logger.info("🔄 Starting follow-up check...")

        # Get all records with status='sent'
        sent_records = state_service.get_records_by_status("sent")
        if not sent_records:
            logger.info("No pending sent requests to follow up on")
            return results

        logger.info(f"Found {len(sent_records)} sent records to check")

        # Navigate to Sent Invitations page
        try:
            await self._browser.safe_navigate(SENT_INVITATIONS_URL, timeout=20000)
            await action_delay(2, 4)
        except Exception as e:
            logger.error(f"Could not navigate to Sent Invitations: {e}")
            results["errors"] = len(sent_records)
            return results

        # Load all sent invitations by scrolling
        sent_names = await self._load_all_sent_invitations()
        logger.info(f"Loaded {len(sent_names)} names from Sent Invitations page")

        # Check each pending record
        for record in sent_records:
            name = record.get("name", "")
            url = record.get("linkedin_url", "")

            try:
                # Check if the person is in the sent invitations list
                is_pending = self._is_name_in_list(name, sent_names)

                if is_pending:
                    # Check if it's been long enough to withdraw
                    stale = state_service.get_stale_sent_records(self._withdraw_after_days)
                    stale_urls = [r["linkedin_url"] for r in stale]

                    if url in stale_urls:
                        # Withdraw the request
                        withdrawn = await self._withdraw_invitation(name)
                        if withdrawn:
                            state_service.mark_withdrawn(url)
                            results["withdrawn"] += 1
                            results["details"].append({
                                "name": name, "url": url, "action": "withdrawn"
                            })
                            logger.info(f"  ↩️ Withdrawn: {name}")
                        else:
                            results["still_pending"] += 1
                            results["details"].append({
                                "name": name, "url": url, "action": "withdraw_failed"
                            })
                    else:
                        results["still_pending"] += 1
                        results["details"].append({
                            "name": name, "url": url, "action": "still_pending"
                        })
                        logger.info(f"  ⏳ Still pending: {name}")
                else:
                    # Not in sent list → likely accepted
                    state_service.mark_accepted(url)
                    results["accepted"] += 1
                    results["details"].append({
                        "name": name, "url": url, "action": "accepted"
                    })
                    logger.info(f"  🤝 Accepted: {name}")

                await action_delay(1, 3)

            except Exception as e:
                logger.error(f"Error checking {name}: {e}")
                results["errors"] += 1
                results["details"].append({
                    "name": name, "url": url, "action": "error", "error": str(e)
                })

        # Summary
        logger.info(
            f"Follow-up complete — "
            f"accepted: {results['accepted']}, "
            f"withdrawn: {results['withdrawn']}, "
            f"still_pending: {results['still_pending']}, "
            f"errors: {results['errors']}"
        )

        return results

    async def _load_all_sent_invitations(self) -> List[str]:
        """
        Scroll through the Sent Invitations page and collect all names.

        Returns a list of names found in sent invitations.
        """
        names = []
        previous_count = 0
        max_scrolls = 20  # Safety limit

        for _ in range(max_scrolls):
            # Extract names from current view
            name_selectors = [
                ".invitation-card__title span",
                ".invitation-card__name",
                ".mn-invitation-list__item .invitation-card__title",
                ".mn-person-info__name",
                "span.mn-connection-card__name",
            ]

            for selector in name_selectors:
                texts = await self._browser.get_texts(selector)
                if texts:
                    names.extend(texts)
                    break

            # Check if we've loaded new content
            if len(names) == previous_count:
                break  # No new content loaded
            previous_count = len(names)

            # Scroll down
            await self._browser.human_scroll("down", 600)
            await action_delay(1, 2)

        # Deduplicate
        return list(set(names))

    def _is_name_in_list(self, target_name: str, name_list: List[str]) -> bool:
        """
        Check if a name appears in the sent invitations list.

        Uses fuzzy matching — matches on first name + last name or partial matches.
        """
        if not target_name:
            return False

        target_lower = target_name.lower().strip()
        target_parts = target_lower.split()

        for name in name_list:
            name_lower = name.lower().strip()
            # Exact match
            if target_lower == name_lower:
                return True
            # First + last name match
            if len(target_parts) >= 2:
                if target_parts[0] in name_lower and target_parts[-1] in name_lower:
                    return True
            # Single name partial match
            elif target_parts[0] in name_lower:
                return True

        return False

    async def _withdraw_invitation(self, name: str) -> bool:
        """
        Withdraw a sent invitation by finding and clicking the Withdraw button.

        Args:
            name: Name of the person whose invitation to withdraw.

        Returns:
            True if successfully withdrawn.
        """
        try:
            # Find the invitation card for this person
            # We need to match the name and find the associated Withdraw button
            cards = await self._browser.page.query_selector_all(
                ".invitation-card, .mn-invitation-list__item"
            )

            for card in cards:
                card_text = await card.text_content()
                if card_text and name.lower() in card_text.lower():
                    # Found the card — look for Withdraw button
                    withdraw_btn = await card.query_selector(
                        "button[aria-label*='Withdraw' i], "
                        "button:has-text('Withdraw')"
                    )
                    if withdraw_btn:
                        await withdraw_btn.click()
                        await short_delay(0.5, 1.5)

                        # Confirm withdrawal dialog
                        confirm_selectors = [
                            "button[aria-label*='Withdraw' i].artdeco-button--primary",
                            "button.artdeco-modal__confirm-dialog-btn:has-text('Withdraw')",
                            "button:has-text('Withdraw'):not([aria-label*='cancel' i])",
                        ]

                        for sel in confirm_selectors:
                            if await self._browser.wait_and_click(sel, timeout=3000):
                                logger.info(f"  ↩️ Invitation withdrawn for {name}")
                                await short_delay(1.0, 2.0)
                                return True

            logger.warning(f"Could not find/withdraw invitation for {name}")
            return False

        except Exception as e:
            logger.error(f"Withdraw error for {name}: {e}")
            await capture_screenshot(
                self._browser.page, f"withdraw_failed_{name[:20]}", self._screenshot_dir
            )
            return False
