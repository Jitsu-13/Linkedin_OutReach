"""
Human-like delay generators.

Provides random pause functions calibrated to avoid LinkedIn's
bot-detection heuristics. All delays use uniform random distribution.
"""

import asyncio
import random

from utils.logger import logger


async def profile_delay(min_seconds: int = 120, max_seconds: int = 300) -> float:
    """
    Wait between profile automation cycles.

    This is the primary anti-detection delay: 120–300 seconds (configurable)
    between processing each LinkedIn profile.

    Returns the actual delay used (for logging).
    """
    delay = random.uniform(min_seconds, max_seconds)
    logger.info(f"⏳ Profile delay: waiting {delay:.1f}s before next profile")
    await asyncio.sleep(delay)
    return delay


async def action_delay(min_seconds: int = 2, max_seconds: int = 8) -> float:
    """
    Wait between in-page actions (click, scroll, type).

    Simulates human think-time between interactions on the same page.
    """
    delay = random.uniform(min_seconds, max_seconds)
    logger.debug(f"⏳ Action delay: {delay:.1f}s")
    await asyncio.sleep(delay)
    return delay


async def short_delay(min_seconds: float = 0.5, max_seconds: float = 2.0) -> float:
    """
    Brief pause for rapid sequential actions (e.g., after clicking a button,
    waiting for a dialog to appear).
    """
    delay = random.uniform(min_seconds, max_seconds)
    await asyncio.sleep(delay)
    return delay


def typing_delay_ms(min_ms: int = 50, max_ms: int = 150) -> int:
    """
    Return a random per-keystroke delay in milliseconds.

    Used by browser_service.human_type() for realistic typing speed.
    """
    return random.randint(min_ms, max_ms)


async def scroll_delay() -> float:
    """Wait after scrolling to simulate reading content."""
    delay = random.uniform(1.5, 4.0)
    await asyncio.sleep(delay)
    return delay


async def pause_on_error(minutes: int = 30) -> None:
    """
    Extended pause when too many errors occur.

    Safety mechanism: if automation hits consecutive failures,
    pause for a configurable duration before retrying.
    """
    logger.warning(f"🛑 Error threshold reached — pausing for {minutes} minutes")
    await asyncio.sleep(minutes * 60)
    logger.info("▶️  Resuming after error pause")
