"""
Google Sheets integration service.

Reads target LinkedIn URLs and writes back status/notes/timestamps.
Uses gspread with service account authentication.
"""

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import gspread
from google.oauth2.service_account import Credentials

from utils.logger import logger

# Google API scopes
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Rate limiting: Google Sheets API allows ~100 requests per 100 seconds
_MIN_REQUEST_INTERVAL = 1.1  # seconds between API calls


class SheetsService:
    """
    Google Sheets read/write service.

    Handles authentication, target reading, and status updates
    with built-in rate limiting.
    """

    def __init__(self, credentials_file: str, spreadsheet_id: str,
                 worksheet_name: str = "Targets",
                 columns: Optional[Dict[str, str]] = None):
        self._credentials_file = credentials_file
        self._spreadsheet_id = spreadsheet_id
        self._worksheet_name = worksheet_name
        self._columns = columns or {}
        self._client: Optional[gspread.Client] = None
        self._worksheet: Optional[gspread.Worksheet] = None
        self._last_request_time: float = 0
        self._header_row: List[str] = []
        self._col_index: Dict[str, int] = {}  # column_name -> 1-indexed column number

    def connect(self) -> None:
        """Authenticate and open the target spreadsheet."""
        creds_path = Path(self._credentials_file)
        if not creds_path.exists():
            raise FileNotFoundError(
                f"Google Sheets credentials file not found: {self._credentials_file}\n"
                f"See README.md for setup instructions."
            )

        credentials = Credentials.from_service_account_file(
            str(creds_path), scopes=_SCOPES
        )
        self._client = gspread.authorize(credentials)

        try:
            spreadsheet = self._client.open_by_key(self._spreadsheet_id)
            self._worksheet = spreadsheet.worksheet(self._worksheet_name)
        except gspread.SpreadsheetNotFound:
            raise ValueError(
                f"Spreadsheet with ID '{self._spreadsheet_id}' not found. "
                f"Make sure the service account email has access."
            )
        except gspread.WorksheetNotFound:
            raise ValueError(
                f"Worksheet '{self._worksheet_name}' not found in the spreadsheet."
            )

        # Read header row and build column index
        self._rate_limit()
        self._header_row = self._worksheet.row_values(1)
        self._col_index = {
            header.strip().lower(): idx + 1
            for idx, header in enumerate(self._header_row)
        }

        logger.info(
            f"Connected to Google Sheet: {self._spreadsheet_id} / {self._worksheet_name} "
            f"({len(self._header_row)} columns)"
        )

    def _rate_limit(self) -> None:
        """Enforce minimum interval between API requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.time()

    def _get_col_number(self, column_key: str) -> int:
        """
        Get the 1-indexed column number for a column key.

        Uses the column mapping from config, falling back to direct header match.
        """
        # Try mapped column name first
        col_name = self._columns.get(column_key, column_key).strip().lower()
        if col_name in self._col_index:
            return self._col_index[col_name]

        # Try the key itself
        if column_key.strip().lower() in self._col_index:
            return self._col_index[column_key.strip().lower()]

        raise KeyError(
            f"Column '{column_key}' (mapped to '{col_name}') not found in sheet headers: "
            f"{self._header_row}"
        )

    # ── Read Operations ───────────────────────────────────────

    def read_targets(self) -> List[Dict[str, Any]]:
        """
        Read all target rows from the sheet.

        Returns a list of dicts with column headers as keys.
        Adds a '_row_number' key for update operations.
        """
        self._rate_limit()
        all_records = self._worksheet.get_all_records()

        targets = []
        for idx, record in enumerate(all_records):
            # Row number is idx + 2 (1 for header, 1 for 0-index)
            record["_row_number"] = idx + 2

            # Normalize keys to lowercase
            normalized = {k.strip().lower(): v for k, v in record.items()}
            normalized["_row_number"] = record["_row_number"]
            targets.append(normalized)

        logger.info(f"Read {len(targets)} targets from Google Sheet")
        return targets

    def read_unprocessed_targets(self) -> List[Dict[str, Any]]:
        """
        Read targets that haven't been processed yet.

        Filters for rows where the status column is empty or 'pending'.
        """
        all_targets = self.read_targets()
        status_key = self._columns.get("status", "status").strip().lower()

        unprocessed = [
            t for t in all_targets
            if not t.get(status_key) or t.get(status_key, "").strip().lower() == "pending"
        ]

        logger.info(
            f"Found {len(unprocessed)} unprocessed targets "
            f"(out of {len(all_targets)} total)"
        )
        return unprocessed

    # ── Write Operations ──────────────────────────────────────

    def update_row(self, row_number: int, updates: Dict[str, Any]) -> None:
        """
        Update specific cells in a row.

        Args:
            row_number: 1-indexed row number in the sheet.
            updates: Dict of {column_key: value} to update.
        """
        for col_key, value in updates.items():
            try:
                col_number = self._get_col_number(col_key)
                self._rate_limit()
                self._worksheet.update_cell(row_number, col_number, str(value))
                logger.debug(f"Updated row {row_number}, col '{col_key}' = '{value}'")
            except KeyError as e:
                logger.warning(f"Skipping column update: {e}")
            except Exception as e:
                logger.error(f"Failed to update row {row_number}, col '{col_key}': {e}")

    def update_status(self, row_number: int, status: str,
                      note_used: str = "", sent_at: str = "",
                      accepted_at: str = "", withdrawn_at: str = "",
                      comment_posted: str = "", posts_liked: str = "") -> None:
        """
        Convenience method to update all outreach-related columns for a row.
        """
        updates = {"status": status}
        if note_used:
            updates["note_used"] = note_used
        if sent_at:
            updates["sent_at"] = sent_at
        if accepted_at:
            updates["accepted_at"] = accepted_at
        if withdrawn_at:
            updates["withdrawn_at"] = withdrawn_at
        if comment_posted:
            updates["comment_posted"] = comment_posted
        if posts_liked:
            updates["posts_liked"] = posts_liked

        self.update_row(row_number, updates)
        logger.info(f"Sheet row {row_number} updated: status={status}")

    def batch_update_statuses(self, updates: List[Dict[str, Any]]) -> None:
        """
        Batch update multiple rows.

        Args:
            updates: List of dicts, each containing '_row_number' and update fields.
        """
        for update in updates:
            row_number = update.pop("_row_number", None)
            if row_number:
                self.update_row(row_number, update)

        logger.info(f"Batch updated {len(updates)} rows in Google Sheet")

    # ── Utility ───────────────────────────────────────────────

    def find_row_by_url(self, linkedin_url: str) -> Optional[int]:
        """
        Find the row number for a given LinkedIn URL.

        Returns the 1-indexed row number, or None if not found.
        """
        url_col = self._get_col_number("url")
        self._rate_limit()

        try:
            cell = self._worksheet.find(linkedin_url, in_column=url_col)
            return cell.row if cell else None
        except gspread.exceptions.CellNotFound:
            return None

    def ensure_columns_exist(self) -> None:
        """
        Ensure all required output columns exist in the sheet.

        Adds missing columns to the right of existing ones.
        """
        required_output_cols = ["status", "note_used", "sent_at",
                                "accepted_at", "withdrawn_at",
                                "comment_posted", "posts_liked"]

        existing_lower = [h.strip().lower() for h in self._header_row]

        for col_name in required_output_cols:
            mapped_name = self._columns.get(col_name, col_name)
            if mapped_name.strip().lower() not in existing_lower:
                # Add the column
                next_col = len(self._header_row) + 1
                self._rate_limit()
                self._worksheet.update_cell(1, next_col, mapped_name)
                self._header_row.append(mapped_name)
                self._col_index[mapped_name.strip().lower()] = next_col
                logger.info(f"Added missing column '{mapped_name}' at position {next_col}")
