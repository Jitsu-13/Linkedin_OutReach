"""
LinkedIn Outreach Automation — Main Entry Point

Executes the outreach pipeline:
1. Read targets from Google Sheets
2. Extract profile context via browser automation
3. Like posts + AI comment
4. Generate two-pass personalized notes with jitter
5. Send connection requests
6. Log everything to local state + Google Sheets

Usage:
    python main.py [OPTIONS]

Options:
    --limit N       Max profiles to process (default: from config, usually 25)
    --dry-run       Run the full pipeline but skip actual LinkedIn actions
    --char-limit N  Override character limit for notes (200 or 300)
    --skip-engage   Skip post engagement (liking/commenting)
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

import click

from config.settings import get_settings, PROJECT_ROOT
from utils.logger import setup_logger, logger
from utils.delays import profile_delay, pause_on_error
from utils.screenshot import capture as capture_screenshot
from services import state_service
from services.sheets_service import SheetsService
from services.browser_service import BrowserService
from services.llm_service import LLMService
from agents.profile_agent import ProfileAgent
from agents.engagement_agent import EngagementAgent
from agents.connection_agent import ConnectionAgent


async def run_outreach(
    limit: int = 0,
    dry_run: bool = False,
    char_limit: int = 0,
    skip_engage: bool = False,
) -> None:
    """
    Main outreach pipeline.

    Args:
        limit: Max profiles to process (0 = use config default).
        dry_run: If True, skip actual LinkedIn interactions.
        char_limit: Override character limit for notes.
        skip_engage: If True, skip liking/commenting.
    """
    settings = get_settings()

    # ── Initialize ──
    setup_logger(
        level=settings.logging.level,
        log_file=settings.logging.file,
        rotation_mb=settings.logging.rotation_mb,
        retention_count=settings.logging.retention_count,
    )

    logger.info("=" * 60)
    logger.info("🚀 LinkedIn Outreach Automation — Starting")
    logger.info(f"   Dry run: {dry_run}")
    logger.info(f"   LLM: {settings.llm.provider}/{settings.llm.model}")
    logger.info("=" * 60)

    # Initialize database
    state_service.init_db(
        db_path=str(PROJECT_ROOT / "data" / "state.db"),
        schema_path=str(PROJECT_ROOT / "schema.sql"),
    )

    # Resolve limits
    max_requests = limit if limit > 0 else settings.linkedin.max_requests_per_run
    note_char_limit = char_limit if char_limit > 0 else settings.llm.default_char_limit

    # ── Connect to Google Sheets ──
    sheets = None
    try:
        sheets = SheetsService(
            credentials_file=settings.google_sheets_credentials_file,
            spreadsheet_id=settings.sheets.spreadsheet_id,
            worksheet_name=settings.sheets.worksheet_name,
            columns=settings.sheets.columns.model_dump(),
        )
        sheets.connect()
        sheets.ensure_columns_exist()
    except Exception as e:
        logger.error(f"Google Sheets connection failed: {e}")
        logger.info("Continuing without Sheets integration (local state only)")
        sheets = None

    # ── Read targets ──
    targets = []
    if sheets:
        try:
            targets = sheets.read_unprocessed_targets()
        except Exception as e:
            logger.error(f"Failed to read targets from Sheets: {e}")

    if not targets:
        logger.warning("No unprocessed targets found. Nothing to do.")
        return

    targets = targets[:max_requests]
    logger.info(f"Processing {len(targets)} targets (limit: {max_requests})")

    # ── Initialize LLM service ──
    llm = LLMService(
        provider=settings.llm.provider,
        model=settings.llm.model,
        api_key=settings.llm_api_key,
        temperature=settings.llm.temperature,
        review_temperature=settings.llm.review_temperature,
        default_char_limit=note_char_limit,
        nvidia_base_url=settings.llm.nvidia_base_url,
        openrouter_base_url=settings.llm.openrouter_base_url,
    )

    # LLM health check
    logger.info("Checking LLM connectivity...")
    if not await llm.health_check():
        logger.error("LLM health check failed. Check your API key and provider settings.")
        return

    # ── Initialize browser ──
    browser = BrowserService(
        headless=settings.browser.headless,
        user_data_dir=settings.browser.user_data_dir,
        viewport_width=settings.browser.viewport_width,
        viewport_height=settings.browser.viewport_height,
        screenshot_dir=settings.browser.screenshot_dir,
        typing_delay_min_ms=settings.linkedin.typing_delay_min_ms,
        typing_delay_max_ms=settings.linkedin.typing_delay_max_ms,
    )

    # ── Initialize agents ──
    profile_agent = ProfileAgent(browser, settings.browser.screenshot_dir)
    engagement_agent = EngagementAgent(
        browser=browser,
        llm=llm,
        posts_to_like=settings.linkedin.posts_to_like,
        posts_to_comment=settings.linkedin.posts_to_comment,
        sender_name=settings.sender_name,
        screenshot_dir=settings.browser.screenshot_dir,
    )
    connection_agent = ConnectionAgent(browser, settings.browser.screenshot_dir)

    # ── Counters ──
    stats = {
        "processed": 0,
        "sent": 0,
        "skipped": 0,
        "errors": 0,
        "consecutive_errors": 0,
    }

    try:
        # Start browser
        if not dry_run:
            await browser.start()

            # Check login status
            logged_in = await browser.check_login_status()
            if not logged_in:
                logger.info("Not logged in — attempting login...")
                login_success = await browser.perform_login(
                    settings.linkedin_email, settings.linkedin_password
                )
                if not login_success:
                    logger.error(
                        "❌ Login failed. Please log in manually in the browser window "
                        "that opened, then restart the script."
                    )
                    return

        # ── Process each target ──
        for i, target in enumerate(targets):
            profile_url = target.get("profile_url", "")
            row_number = target.get("_row_number", 0)
            target_name = target.get("name", "Unknown")

            if not profile_url:
                logger.warning(f"Target {i+1}: Missing LinkedIn URL — skipping")
                continue

            logger.info(f"\n{'='*50}")
            logger.info(f"📋 Target {i+1}/{len(targets)}: {target_name}")
            logger.info(f"   URL: {profile_url}")
            logger.info(f"{'='*50}")

            try:
                # ── Check if already processed ──
                existing = state_service.get_record(profile_url)
                if existing and existing.get("status") in ("sent", "accepted"):
                    logger.info(f"  ⏭️ Already processed (status: {existing['status']}) — skipping")
                    stats["skipped"] += 1
                    continue

                # Create/update pending record
                state_service.upsert_record(profile_url, status="pending", name=target_name)

                if dry_run:
                    logger.info("  [DRY RUN] Would process this profile")
                    # Still generate the note for testing
                    profile_context = {
                        "name": target_name,
                        "headline": target.get("headline", ""),
                        "company": target.get("company", ""),
                        "current_role": target.get("current_role", ""),
                    }
                    note_result = await llm.generate_note(
                        profile_context=profile_context,
                        sender_context=settings.sender_context,
                        sender_name=settings.sender_name,
                        char_limit=note_char_limit,
                    )
                    logger.info(f"  [DRY RUN] Generated note: {note_result['final']}")
                    stats["processed"] += 1
                    continue

                # ── Step 1: Extract profile context ──
                logger.info("  Step 1: Extracting profile context...")
                profile_context = await profile_agent.extract_context(profile_url)

                # Save context to state
                state_service.update_profile_context(
                    profile_url,
                    name=profile_context.get("name", target_name),
                    headline=profile_context.get("headline", ""),
                    current_role=profile_context.get("current_role", ""),
                    company=profile_context.get("company", ""),
                    about_snippet=profile_context.get("about_snippet", ""),
                    mutual_connections=profile_context.get("mutual_connections", 0),
                    profile_context=profile_context,
                )

                # ── Step 2: Engage with posts ──
                engagement_result = {"posts_liked": 0, "comment_text": "", "comment_draft": ""}
                if not skip_engage:
                    logger.info("  Step 2: Engaging with posts...")
                    engagement_result = await engagement_agent.engage_with_posts(
                        profile_url, profile_context
                    )
                else:
                    logger.info("  Step 2: Skipped engagement (--skip-engage)")

                # ── Step 3: Generate personalized note ──
                logger.info("  Step 3: Generating personalized note (two-pass + jitter)...")
                note_result = await llm.generate_note(
                    profile_context=profile_context,
                    sender_context=settings.sender_context,
                    sender_name=settings.sender_name,
                    char_limit=note_char_limit,
                )

                # ── Step 4: Send connection request ──
                logger.info("  Step 4: Sending connection request...")
                send_result = await connection_agent.send_request(
                    note=note_result["final"],
                    profile_url=profile_url,
                )

                # ── Step 5: Update state ──
                if send_result["success"]:
                    state_service.mark_sent(
                        linkedin_url=profile_url,
                        note_draft=note_result["draft"],
                        note_reviewed=note_result["reviewed"],
                        note_final=note_result["final"],
                        posts_liked=engagement_result.get("posts_liked", 0),
                        comment_final=engagement_result.get("comment_text", ""),
                        char_limit=note_char_limit,
                    )
                    stats["sent"] += 1
                    stats["consecutive_errors"] = 0

                    # Update Google Sheet
                    if sheets and row_number:
                        try:
                            sheets.update_status(
                                row_number=row_number,
                                status="sent",
                                note_used=note_result["final"],
                                sent_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                comment_posted=engagement_result.get("comment_text", "")[:100],
                                posts_liked=str(engagement_result.get("posts_liked", 0)),
                            )
                        except Exception as e:
                            logger.warning(f"Failed to update Sheet row {row_number}: {e}")

                elif send_result["status"] == "skipped":
                    state_service.mark_skipped(profile_url, send_result.get("error", ""))
                    stats["skipped"] += 1

                    if sheets and row_number:
                        try:
                            sheets.update_status(
                                row_number=row_number,
                                status="skipped",
                                note_used=send_result.get("error", ""),
                            )
                        except Exception as e:
                            logger.warning(f"Failed to update Sheet: {e}")
                else:
                    state_service.mark_error(
                        profile_url,
                        send_result.get("error", "Unknown error"),
                    )
                    stats["errors"] += 1
                    stats["consecutive_errors"] += 1

                stats["processed"] += 1

                # ── Safety: pause on consecutive errors ──
                if stats["consecutive_errors"] >= settings.linkedin.max_errors_before_pause:
                    logger.warning(
                        f"Hit {stats['consecutive_errors']} consecutive errors — pausing"
                    )
                    await pause_on_error(settings.linkedin.pause_duration_minutes)
                    stats["consecutive_errors"] = 0

                # ── Safety: check for CAPTCHA after each profile ──
                if await browser.detect_captcha_or_restriction():
                    logger.error("🛑 CAPTCHA/restriction detected — stopping automation")
                    break

                # ── Wait between profiles ──
                if i < len(targets) - 1:  # Don't wait after the last one
                    await profile_delay(
                        settings.linkedin.delay_min_seconds,
                        settings.linkedin.delay_max_seconds,
                    )

            except Exception as e:
                logger.error(f"Error processing {target_name}: {e}")
                state_service.mark_error(profile_url, str(e))
                stats["errors"] += 1
                stats["consecutive_errors"] += 1

                if not dry_run:
                    try:
                        await capture_screenshot(
                            browser.page, f"error_{target_name[:20]}", settings.browser.screenshot_dir
                        )
                    except Exception:
                        pass

    finally:
        # Close browser
        if not dry_run:
            await browser.close()

    # ── Print summary ──
    logger.info("\n" + "=" * 60)
    logger.info("📊 Outreach Run Summary")
    logger.info("=" * 60)
    logger.info(f"  Processed: {stats['processed']}")
    logger.info(f"  Sent:      {stats['sent']}")
    logger.info(f"  Skipped:   {stats['skipped']}")
    logger.info(f"  Errors:    {stats['errors']}")
    logger.info("=" * 60)

    # Print state summary
    summary = state_service.get_summary()
    if summary:
        logger.info("📦 Local State Summary:")
        for status, count in summary.items():
            logger.info(f"  {status}: {count}")


# ── CLI Entry Point ───────────────────────────────────────────

@click.command()
@click.option("--limit", default=0, help="Max profiles to process (0 = use config default)")
@click.option("--dry-run", is_flag=True, help="Run pipeline without actual LinkedIn actions")
@click.option("--char-limit", default=0, help="Override note character limit (200 or 300)")
@click.option("--skip-engage", is_flag=True, help="Skip post engagement (liking/commenting)")
def main(limit: int, dry_run: bool, char_limit: int, skip_engage: bool):
    """LinkedIn Outreach Automation — Connection Request Pipeline"""
    asyncio.run(run_outreach(
        limit=limit,
        dry_run=dry_run,
        char_limit=char_limit,
        skip_engage=skip_engage,
    ))


if __name__ == "__main__":
    main()
