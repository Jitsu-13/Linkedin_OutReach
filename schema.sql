-- ============================================================
-- LinkedIn Outreach Automation — Local State Schema (SQLite)
-- ============================================================

CREATE TABLE IF NOT EXISTS outreach_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    linkedin_url    TEXT NOT NULL UNIQUE,
    
    -- Profile context (extracted from LinkedIn)
    name            TEXT,
    headline        TEXT,
    current_role    TEXT,
    company         TEXT,
    about_snippet   TEXT,
    mutual_connections INTEGER DEFAULT 0,
    profile_context TEXT,           -- Full JSON blob of all extracted info
    
    -- LLM-generated content
    note_draft      TEXT,           -- First LLM pass (raw draft)
    note_reviewed   TEXT,           -- Second LLM pass (quality-reviewed)
    note_final      TEXT,           -- After jitter applied (what was actually sent)
    note_char_limit INTEGER DEFAULT 300,
    comment_draft   TEXT,           -- AI-generated comment draft
    comment_final   TEXT,           -- Final comment after review
    
    -- Engagement tracking
    posts_liked     INTEGER DEFAULT 0,
    post_commented  INTEGER DEFAULT 0,  -- 0 or 1
    
    -- Status workflow: pending -> sent -> accepted/withdrawn/error
    status          TEXT DEFAULT 'pending' 
                    CHECK(status IN ('pending','sent','accepted','withdrawn','error','skipped')),
    error_message   TEXT,
    screenshot_path TEXT,
    
    -- Timestamps
    sent_at         TIMESTAMP,
    accepted_at     TIMESTAMP,
    withdrawn_at    TIMESTAMP,
    last_checked_at TIMESTAMP,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for quick lookups during follow-up checks
CREATE INDEX IF NOT EXISTS idx_status ON outreach_records(status);
CREATE INDEX IF NOT EXISTS idx_sent_at ON outreach_records(sent_at);

-- Trigger to auto-update the updated_at timestamp
CREATE TRIGGER IF NOT EXISTS trg_updated_at
    AFTER UPDATE ON outreach_records
    FOR EACH ROW
BEGIN
    UPDATE outreach_records SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.id;
END;
