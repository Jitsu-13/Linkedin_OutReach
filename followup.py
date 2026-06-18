"""
LinkedIn Outreach Automation — Follow-up Job Entry Point

Checks sent connection requests for acceptance or staleness:
1. Navigate to LinkedIn Sent Invitations
2. Cross-reference with local state
3. Mark accepted connections
4. Withdraw stale pending requests (> threshold days)
5. Sync updates to Google Sheets

Usage:
    python followup.py              # Run once immediately
    python followup.py --schedule   # Run on a recurring schedule (every 14 days)
"""

import asyncio
import sys
from datetime import datetime

import click

from config.settings import get_settings, PROJECT_ROOT
from utils.logger import setup_logger, logger
from services import state_service
from services.sheets_service import SheetsService
from services.browser_service import BrowserService
from agents.followup_agent import FollowupAgent


async def run_followup() -> None:
    """Execute a single follow-up check."""
    settings = get_settings()

    # ── Initialize ──
    setup_logger(
        level=settings.logging.level,
        log_file=settings.logging.file,
        rotation_mb=settings.logging.rotation_mb,
        retention_count=settings.logging.retention_count,
    )

    logger.info("=" * 60)
    logger.info("🔄 LinkedIn Outreach — Follow-up Job Starting")
    logger.info(f"   Withdraw threshold: {settings.followup.withdraw_after_days} days")
    logger.info("=" * 60)

    # Initialize database
    state_service.init_db(
        db_path=str(PROJECT_ROOT / "data" / "state.db"),
        schema_path=str(PROJECT_ROOT / "schema.sql"),
    )

    # Check if there are any sent records
    sent_records = state_service.get_records_by_status("sent")
    if not sent_records:
        logger.info("No sent records to follow up on. Exiting.")
        return

    logger.info(f"Found {len(sent_records)} sent records to check")

    # ── Connect Google Sheets ──
    sheets = None
    try:
        sheets = SheetsService(
            credentials_file=settings.google_sheets_credentials_file,
            spreadsheet_id=settings.sheets.spreadsheet_id,
            worksheet_name=settings.sheets.worksheet_name,
            columns=settings.sheets.columns.model_dump(),
        )
        sheets.connect()
    except Exception as e:
        logger.warning(f"Google Sheets connection failed: {e}")
        logger.info("Will update local state only")

    # ── Initialize browser ──
    browser = BrowserService(
        headless=settings.browser.headless,
        user_data_dir=settings.browser.user_data_dir,
        viewport_width=settings.browser.viewport_width,
        viewport_height=settings.browser.viewport_height,
        screenshot_dir=settings.browser.screenshot_dir,
    )

    try:
        await browser.start()

        # Check login
        logged_in = await browser.check_login_status()
        if not logged_in:
            logger.info("Not logged in — attempting login...")
            login_success = await browser.perform_login(
                settings.linkedin_email, settings.linkedin_password
            )
            if not login_success:
                logger.error("Login failed. Please log in manually and restart.")
                return

        # ── Run follow-up agent ──
        agent = FollowupAgent(
            browser=browser,
            withdraw_after_days=settings.followup.withdraw_after_days,
            screenshot_dir=settings.browser.screenshot_dir,
        )

        results = await agent.run_followup()

        # ── Sync to Google Sheets ──
        if sheets and results.get("details"):
            logger.info("Syncing follow-up results to Google Sheets...")
            for detail in results["details"]:
                url = detail.get("url", "")
                action = detail.get("action", "")

                if not url:
                    continue

                try:
                    row_number = sheets.find_row_by_url(url)
                    if row_number:
                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        if action == "accepted":
                            sheets.update_status(
                                row_number=row_number,
                                status="accepted",
                                accepted_at=now_str,
                            )
                        elif action == "withdrawn":
                            sheets.update_status(
                                row_number=row_number,
                                status="withdrawn",
                                withdrawn_at=now_str,
                            )
                except Exception as e:
                    logger.warning(f"Failed to update Sheet for {url}: {e}")

        # ── Print summary ──
        logger.info("\n" + "=" * 60)
        logger.info("📊 Follow-up Summary")
        logger.info("=" * 60)
        logger.info(f"  Accepted:      {results.get('accepted', 0)}")
        logger.info(f"  Withdrawn:     {results.get('withdrawn', 0)}")
        logger.info(f"  Still Pending: {results.get('still_pending', 0)}")
        logger.info(f"  Errors:        {results.get('errors', 0)}")
        logger.info("=" * 60)

    finally:
        await browser.close()


def run_scheduled(interval_days: int = 14) -> None:
    """Run the follow-up job on a recurring schedule using APScheduler."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

    settings = get_settings()
    setup_logger(
        level=settings.logging.level,
        log_file=settings.logging.file,
    )

    logger.info(f"🕐 Starting scheduled follow-up — every {interval_days} days")

    jobstores = {
        "default": SQLAlchemyJobStore(
            url=f"sqlite:///{PROJECT_ROOT / 'data' / 'scheduler.db'}"
        )
    }

    scheduler = BlockingScheduler(jobstores=jobstores)

    def _run_once():
        """Wrapper to run async followup in sync context."""
        logger.info("⏰ Scheduled follow-up triggered")
        asyncio.run(run_followup())

    scheduler.add_job(
        _run_once,
        "interval",
        days=interval_days,
        id="followup_check",
        replace_existing=True,
        next_run_time=datetime.now(),  # Run immediately on first launch
    )

    logger.info(f"Scheduler started. Next run: now, then every {interval_days} days.")
    logger.info("Press Ctrl+C to stop.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Scheduler stopped")


# ── CLI Entry Point ───────────────────────────────────────────

@click.command()
@click.option(
    "--schedule", is_flag=True,
    help="Run on a recurring schedule (default: every 14 days)"
)
@click.option(
    "--interval", default=0,
    help="Override schedule interval in days (0 = use config default)"
)
def main(schedule: bool, interval: int):
    """LinkedIn Outreach Automation — Follow-up Job"""
    settings = get_settings()
    interval_days = interval if interval > 0 else settings.followup.check_interval_days

    if schedule:
        run_scheduled(interval_days)
    else:
        asyncio.run(run_followup())


if __name__ == "__main__":
    main()
