# Known Limitations & Manual Intervention Points

## 1. Acceptance Detection (Heuristic — Not Guaranteed)

**Limitation:** LinkedIn provides no public API to check whether a connection request has been accepted. The follow-up agent infers acceptance by checking whether the person's name is still present on the "Sent Invitations" page: if they're gone from the list, we infer they accepted.

**False positive scenarios:**
- The recipient withdrew your request → incorrectly marked as "accepted"
- Name matching fails (common names, partial matches, name changes) → status not updated

**Workaround:** The local `profile_context` JSON stores the full name. The `_is_name_in_list` matcher uses first + last name matching with case-insensitive fuzzy comparison. For high-value contacts, verify acceptance manually in LinkedIn's "My Network" → "Manage" tab.

**Manual toggle:** Update the `status` column directly in your Google Sheet or run:
```sql
UPDATE outreach_records SET status = 'accepted', accepted_at = CURRENT_TIMESTAMP
WHERE linkedin_url = 'https://www.linkedin.com/in/person/';
```

---

## 2. LinkedIn DOM Selector Fragility

**Limitation:** LinkedIn regularly updates its React component tree, CSS class names, and ARIA labels. Hardcoded CSS selectors (`agents/profile_agent.py`, `agents/connection_agent.py`, `agents/engagement_agent.py`) will eventually break.

**Detection:** Failed extractions result in empty fields and a screenshot saved to `data/screenshots/`. Check logs for `Could not extract name` or similar warnings.

**Manual fix:**
1. Open LinkedIn in a browser (DevTools → Inspect)
2. Find the updated selector for the broken element
3. Add it to the appropriate selector list in the relevant agent file
4. The code tries selectors in order — new selectors can be prepended to take priority

---

## 3. Initial Login (Manual Step)

**Limitation:** The script cannot automate the initial LinkedIn login if LinkedIn presents a CAPTCHA, 2FA prompt, or "unusual activity" verification.

**Required manual step on first run:**
1. Run `python main.py` — a Chrome window opens
2. If the automatic login fails and LinkedIn shows a verification screen, complete it manually
3. The script waits up to 5 minutes for you to finish
4. After manual login, the session is saved to `browser_data/` and subsequent runs are fully automatic

---

## 4. CAPTCHA / Account Restriction

**Limitation:** If LinkedIn detects bot-like behavior (too many requests, pattern detection, IP flags), it may show a CAPTCHA or temporarily restrict the account. The script detects these and halts immediately.

**Manual intervention required:**
1. Check `data/screenshots/restriction_detected_*.png` to confirm the restriction type
2. If CAPTCHA: open Chrome manually, navigate to LinkedIn, complete the CAPTCHA
3. If account restricted: wait 24–48 hours before resuming automation
4. Reduce `max_requests_per_run` and increase `delay_min/max_seconds` in `config/config.yaml`

---

## 5. LinkedIn Daily / Weekly Request Limits

**Limitation:** LinkedIn enforces soft limits on connection requests:
- Standard accounts: ~20–30 requests/day
- LinkedIn Premium: up to ~100 requests/day
- Weekly cap: varies by account age and activity history

**Detection:** LinkedIn silently ignores requests that exceed limits or shows a "You've reached the weekly invitation limit" dialog.

**Workaround:** Keep `max_requests_per_run` at 25 or below. Spread runs across multiple days. The pipeline can be restarted — already-processed URLs (status `sent`) are skipped automatically.

---

## 6. "Connect" Button Not Found / Profile in "Follow" Mode

**Limitation:** Some LinkedIn profiles (content creators, public figures) show a "Follow" button instead of "Connect." The "Connect" option may be hidden in the "More" dropdown, or unavailable entirely.

**Current behavior:** The agent tries direct Connect → More dropdown → Connect. If neither works, the profile is marked as `error` and skipped. A screenshot is saved.

**Manual workaround:** If you specifically need to connect with these profiles, do so manually in LinkedIn and update the sheet status to `sent` manually.

---

## 7. Post Engagement Selector Reliability

**Limitation:** The engagement agent (`engagement_agent.py`) uses CSS selectors to find like buttons and comment input fields on the activity page. These selectors are fragile for the same reason as above.

**Current behavior:** If no posts are found to like, `posts_liked = 0` is logged with a warning. If comment posting fails, `comment_text = ""` is logged. The main connection flow continues regardless.

---

## 8. LLM Note Length Enforcement

**Limitation:** LLMs may occasionally return notes slightly over the configured character limit. The code applies a hard truncation with graceful word-boundary cutting, but the truncation point may occasionally produce awkward sentence endings.

**Mitigation already in place:** 
- Both the draft and review prompts specify the character limit explicitly
- Post-generation enforcement clips to the limit at the last complete word
- Jitter is applied after the limit check and re-enforces the limit if jitter adds characters

---

## 9. Docker + Headed Mode

**Limitation:** The default configuration runs the browser in headed (visible) mode, which requires a display server. Docker containers do not have a display by default.

**Workaround options:**
1. **Set headless mode in config:** `browser: headless: true` (less stealthy but works in Docker)
2. **X11 forwarding (Linux):** Uncomment the X11 lines in `docker-compose.yml` and set `DISPLAY`
3. **Run locally instead of Docker** (recommended for production use with headed mode)

---

## 10. Google Sheets Rate Limiting

**Limitation:** The Sheets API allows ~100 requests per 100 seconds per project. The `SheetsService._rate_limit()` method enforces a 1.1-second minimum between calls, which is conservative but adequate for runs of ≤25 profiles.

For very large batches, use `batch_update_statuses()` or reduce run frequency.

---

## 11. APScheduler Persistence (Follow-up Job)

**Limitation:** The APScheduler stores the next scheduled run time in `data/scheduler.db`. If the file is deleted, the scheduler resets and runs immediately on the next start, then waits the full interval again.

**Impact:** Benign — it just causes an immediate extra run.

---

## 12. No Multi-account Support

**Limitation:** The pipeline is designed for a single LinkedIn account. The `browser_data/` directory stores a single persistent session. Running multiple accounts requires separate project directories with separate `browser_data/` paths.

---

## Summary Table

| # | Limitation | Severity | Manual Step Required? |
|---|-----------|----------|----------------------|
| 1 | Acceptance detection is heuristic | Medium | Occasionally |
| 2 | DOM selectors may break after LinkedIn updates | High | Yes (update selectors) |
| 3 | Initial login may need manual intervention | Low | First run only |
| 4 | CAPTCHA / restriction stops automation | High | Yes (complete CAPTCHA) |
| 5 | LinkedIn daily request limits | Medium | Tune config |
| 6 | Follow-only profiles can't receive Connect | Low | Manual connect |
| 7 | Post engagement selectors fragile | Low | No (graceful skip) |
| 8 | LLM note truncation edge cases | Low | No |
| 9 | Docker + headed mode | Low | Tune config |
| 10 | Sheets API rate limits | Low | No |
| 11 | Scheduler resets if DB deleted | Low | No |
| 12 | Single account only | Low | Separate directories |
