"""
Screenshot capture utility.

Captures browser page screenshots on failures for debugging.
Screenshots are saved with timestamps and context labels.
"""

from datetime import datetime
from pathlib import Path

from utils.logger import logger


async def capture(page, context_label: str = "error",
                  screenshot_dir: str = "./data/screenshots") -> str:
    """
    Capture a screenshot of the current page state.

    Args:
        page: Playwright page object.
        context_label: Descriptive label (e.g., "profile_extraction_failed").
        screenshot_dir: Directory to save screenshots.

    Returns:
        Absolute path to the saved screenshot file.
    """
    try:
        # Ensure directory exists
        dir_path = Path(screenshot_dir)
        dir_path.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in context_label)
        filename = f"{timestamp}_{safe_label}.png"
        filepath = dir_path / filename

        # Capture
        await page.screenshot(path=str(filepath), full_page=False)

        logger.info(f"📸 Screenshot saved: {filepath}")
        return str(filepath.resolve())

    except Exception as e:
        logger.error(f"Failed to capture screenshot ({context_label}): {e}")
        return ""
