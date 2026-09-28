"""SQLite storage and diffing.

Rows are never deleted. Every fetched posting is stored (matched or not) so
that loosening the filters later surfaces older postings exactly once.

- new:     matched = 1 and reported_date IS NULL and closed_date IS NULL
- closed:  a posting missing from a *successful* fetch of its employer
- reopen:  a closed posting that shows up again has closed_date cleared
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .models import Posting

SCHEMA = """
CREATE TABLE IF NOT EXISTS postings (
    posting_key      TEXT PRIMARY KEY,
    employer_id      TEXT NOT NULL,
    firm             TEXT NOT NULL,
    title            TEXT NOT NULL,
    location         TEXT NOT NULL DEFAULT '',
    url              TEXT NOT NULL DEFAULT '',
    source           TEXT NOT NULL,
    external_id      TEXT,
    department       TEXT NOT NULL DEFAULT '',
    posted_date      TEXT,
    first_seen       TEXT NOT NULL,
    last_seen        TEXT NOT NULL,
    closed_date      TEXT,
    matched          INTEGER NOT NULL DEFAULT 0,
    match_reasons    TEXT NOT NULL DEFAULT '',
    location_unverified INTEGER NOT NULL DEFAULT 0,
    reported_date    TEXT,
    closed_reported_date TEXT
);
CREATE INDEX IF NOT EXISTS idx_postings_employer ON postings(employer_id);
CREATE INDEX IF NOT EXISTS idx_postings_matched ON postings(matched, reported_date);

CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    run_date     TEXT NOT NULL,
    summary_json TEXT
);

CREATE TABLE IF NOT EXISTS run_employers (
    run_id       INTEGER NOT NULL REFERENCES runs(id),
    employer_id  TEXT NOT NULL,
    status       TEXT NOT NULL,           -- ok | error | skipped
    fetched      INTEGER NOT NULL DEFAULT 0,
    matched      INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    PRIMARY KEY (run_id, employer_id)
);
"""


@dataclass
class StoredPosting:
    posting_key: str
    employer_id: str
    firm: str
    title: str
    location: str
    url: str
    source: str
    first_seen: str
    last_seen: str
    closed_date: str | None
    matched: bool
    match_reasons: str
    location_unverified: bool
    reported_date: str | None
    department: str = ""
    posted_date: str | None = None

    def to_dict(self) -> dict:
        return {
            "firm": self.firm,
            "title": self.title,
            "location": self.location,
            "url": self.url,
            "source": self.source,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "closed_date": self.closed_date,
            "posted_date": self.posted_date,
            "location_unverified": self.location_unverified,
            "employer_id": self.employer_id,
        }


@dataclass
class SyncResult:
    inserted: int = 0
    updated: int = 0
    reopened: list[str] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # -- runs ---------------------------------------------------------------

    def start_run(self, started_at: str, run_date: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (started_at, run_date) VALUES (?, ?)", (started_at, run_date)
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, finished_at: str, summary: dict) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, summary_json = ? WHERE id = ?",
            (finished_at, json.dumps(summary), run_id),
        )
        self.conn.commit()

    def record_employer(
        self, run_id: int, employer_id: str, status: str, fetched: int, matched: int, error: str | None
    ) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO run_employers VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, employer_id, status, fetched, matched, error),
        )
        self.conn.commit()

    # -- postings -----------------------------------------------------------

    def sync_employer(
        self,
        employer_id: str,
        postings: list[tuple[Posting, bool, str, bool]],
        today: date,
    ) -> SyncResult:
        """Upsert this employer's current postings and close the ones that vanished.

        Call only after a *successful* fetch; a failed fetch must not close
        anything. ``postings`` is (posting, matched, reasons, location_unverified).
        """
        day = today.isoformat()
        result = SyncResult()
        seen: set[str] = set()
        with self.conn:
            for p, matched, reasons, unverified in postings:
                key = p.key
                if key in seen:
                    continue
                seen.add(key)
                row = self.conn.execute(
                    "SELECT closed_date FROM postings WHERE posting_key = ?", (key,)
                ).fetchone()
                if row is None:
                    self.conn.execute(
                        """INSERT INTO postings (posting_key, employer_id, firm, title, location,
                               url, source, external_id, department, posted_date, first_seen,
                               last_seen, matched, match_reasons, location_unverified)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (key, employer_id, p.firm, p.title, p.location, p.url, p.source,
                         p.external_id, p.department, p.posted_date, day, day,
                         int(matched), reasons, int(unverified)),
                    )
                    result.inserted += 1
                else:
                    if row["closed_date"] is not None:
                        result.reopened.append(key)
                    self.conn.execute(
                        """UPDATE postings SET firm = ?, title = ?, location = ?, url = ?,
                               department = ?, posted_date = COALESCE(?, posted_date),
                               last_seen = ?, closed_date = NULL, closed_reported_date = NULL,
                               matched = ?, match_reasons = ?, location_unverified = ?
                           WHERE posting_key = ?""",
                        (p.firm, p.title, p.location, p.url, p.department,
                         p.posted_date, day, int(matched), reasons, int(unverified), key),
                    )
                    result.updated += 1

            open_rows = self.conn.execute(
                "SELECT posting_key FROM postings WHERE employer_id = ? AND closed_date IS NULL",
                (employer_id,),
            ).fetchall()
            for r in open_rows:
                if r["posting_key"] not in seen:
                    self.conn.execute(
                        "UPDATE postings SET closed_date = ? WHERE posting_key = ?",
                        (day, r["posting_key"]),
                    )
                    result.closed.append(r["posting_key"])
        return result

    def new_matches(self) -> list[StoredPosting]:
        return self._query(
            """SELECT * FROM postings
               WHERE matched = 1 AND reported_date IS NULL AND closed_date IS NULL
               ORDER BY firm, title"""
        )

    def newly_closed_matches(self) -> list[StoredPosting]:
        """Matched postings we previously reported that have since closed."""
        return self._query(
            """SELECT * FROM postings
               WHERE matched = 1 AND reported_date IS NOT NULL
                 AND closed_date IS NOT NULL AND closed_reported_date IS NULL
               ORDER BY firm, title"""
        )

    def mark_reported(self, new_keys: list[str], closed_keys: list[str], today: date) -> None:
        day = today.isoformat()
        with self.conn:
            self.conn.executemany(
                "UPDATE postings SET reported_date = ? WHERE posting_key = ?",
                [(day, k) for k in new_keys],
            )
            self.conn.executemany(
                "UPDATE postings SET closed_reported_date = ? WHERE posting_key = ?",
                [(day, k) for k in closed_keys],
            )

    def list_postings(self, status: str = "open", matched_only: bool = True) -> list[StoredPosting]:
        where = []
        if matched_only:
            where.append("matched = 1")
        if status == "open":
            where.append("closed_date IS NULL")
        elif status == "closed":
            where.append("closed_date IS NOT NULL")
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        return self._query(f"SELECT * FROM postings {clause} ORDER BY first_seen DESC, firm, title")

    def _query(self, sql: str, params: tuple = ()) -> list[StoredPosting]:
        rows = self.conn.execute(sql, params).fetchall()
        return [
            StoredPosting(
                posting_key=r["posting_key"],
                employer_id=r["employer_id"],
                firm=r["firm"],
                title=r["title"],
                location=r["location"],
                url=r["url"],
                source=r["source"],
                first_seen=r["first_seen"],
                last_seen=r["last_seen"],
                closed_date=r["closed_date"],
                matched=bool(r["matched"]),
                match_reasons=r["match_reasons"],
                location_unverified=bool(r["location_unverified"]),
                reported_date=r["reported_date"],
                department=r["department"],
                posted_date=r["posted_date"],
            )
            for r in rows
        ]
