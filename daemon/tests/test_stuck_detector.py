"""Tests for contextweave.stuck_detector — FSM with SQLite persistence."""

from __future__ import annotations

import sqlite3
import time

import pytest

from contextweave.config import StuckDetectorConfig
from contextweave import stuck_detector
from contextweave.db import init_db


def _cfg(threshold_s: int = 600, min_tokens: int = 10) -> StuckDetectorConfig:
    """Build a StuckDetectorConfig with custom thresholds."""
    return StuckDetectorConfig(
        threshold_seconds=threshold_s,
        min_change_tokens=min_tokens,
    )


def _set_state(
    conn: sqlite3.Connection,
    file_path: str,
    content_hash: str,
    last_change: float,
    notified: int = 0,
) -> None:
    """Directly insert a stuck_state row for testing persisted state."""
    conn.execute(
        "INSERT OR REPLACE INTO stuck_state "
        "(file_path, last_content_hash, last_significant_change, stuck_notified) "
        "VALUES (?, ?, ?, ?)",
        (file_path, content_hash, last_change, notified),
    )
    conn.commit()


class TestBasicBehaviour:
    """Core FSM transitions."""

    @pytest.mark.asyncio
    async def test_stuck_detector_returns_false_before_threshold(
        self, test_db: tuple
    ) -> None:
        """First call always returns False (not stuck yet)."""
        conn, _ = test_db
        config = _cfg(threshold_s=600)

        result: bool = await stuck_detector.update_activity(
            file_path="/a.py",
            content="def foo():\n    return 1",
            db=conn,
            config=config,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_stuck_detector_returns_true_after_threshold(
        self, test_db: tuple
    ) -> None:
        """Returns True when elapsed > threshold and not yet notified."""
        conn, _ = test_db
        config = _cfg(threshold_s=600)
        file_path: str = "/b.py"
        content: str = "def bar():\n    return 2"

        
        from contextweave.stuck_detector import _content_hash
        old_time: float = time.time() - 601
        _set_state(conn, file_path, _content_hash(content), old_time, notified=0)

        result: bool = await stuck_detector.update_activity(
            file_path=file_path,
            content=content,
            db=conn,
            config=config,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_stuck_detector_returns_false_if_already_notified(
        self, test_db: tuple
    ) -> None:
        """Returns False when already notified (won't fire twice per session)."""
        conn, _ = test_db
        config = _cfg(threshold_s=600)
        file_path: str = "/c.py"
        content: str = "def baz():\n    return 3"

        from contextweave.stuck_detector import _content_hash
        old_time: float = time.time() - 700
        _set_state(conn, file_path, _content_hash(content), old_time, notified=1)

        result: bool = await stuck_detector.update_activity(
            file_path=file_path,
            content=content,
            db=conn,
            config=config,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_stuck_detector_resets_on_significant_change(
        self, test_db: tuple
    ) -> None:
        """Significant edit resets timer and returns False."""
        conn, _ = test_db
        config = _cfg(threshold_s=600, min_tokens=5)
        file_path: str = "/d.py"
        old_content: str = "def foo():\n    return 1"
        new_content: str = "def foo():\n    x = 999\n    y = 888\n    z = 777\n    return x + y + z"

        from contextweave.stuck_detector import _content_hash
        old_time: float = time.time() - 700
        _set_state(conn, file_path, _content_hash(old_content), old_time, notified=1)

        
        now: float = time.time()
        conn.execute(
            "INSERT INTO chunks (id, file_path, chunk_name, chunk_type, content, "
            "language, start_line, end_line, last_seen, created_at) "
            "VALUES ('abc123', ?, 'foo', 'function', ?, 'python', 1, 3, ?, ?)",
            (file_path, old_content, now, now),
        )
        conn.commit()

        result: bool = await stuck_detector.update_activity(
            file_path=file_path,
            content=new_content,
            db=conn,
            config=config,
        )

        assert result is False

        
        row = conn.execute(
            "SELECT last_significant_change, stuck_notified FROM stuck_state WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        assert row[1] == 0  

    @pytest.mark.asyncio
    async def test_stuck_detector_ignores_whitespace_only_changes(
        self, test_db: tuple
    ) -> None:
        """Whitespace-only edits don't reset the stuck timer."""
        conn, _ = test_db
        config = _cfg(threshold_s=600, min_tokens=10)
        file_path: str = "/e.py"
        base_content: str = "def foo():\n    return 1"
        whitespace_content: str = "def foo():  \n    return 1\n"

        from contextweave.stuck_detector import _content_hash
        old_time: float = time.time() - 700

        
        now: float = time.time()
        conn.execute(
            "INSERT INTO chunks (id, file_path, chunk_name, chunk_type, content, "
            "language, start_line, end_line, last_seen, created_at) "
            "VALUES ('ws123', ?, 'foo', 'function', ?, 'python', 1, 2, ?, ?)",
            (file_path, base_content, now, now),
        )
        conn.commit()
        _set_state(conn, file_path, _content_hash(base_content), old_time, notified=0)

        result: bool = await stuck_detector.update_activity(
            file_path=file_path,
            content=whitespace_content,
            db=conn,
            config=config,
        )

        
        assert result is True


class TestReset:
    """Reset behaviour."""

    @pytest.mark.asyncio
    async def test_stuck_detector_reset_clears_notified_flag(
        self, test_db: tuple
    ) -> None:
        """reset() clears stuck_notified and refreshes last_significant_change."""
        conn, _ = test_db
        file_path: str = "/f.py"

        from contextweave.stuck_detector import _content_hash
        old_time: float = time.time() - 700
        _set_state(conn, file_path, _content_hash("old"), old_time, notified=1)

        before: float = time.time()
        await stuck_detector.reset(file_path=file_path, db=conn)

        row = conn.execute(
            "SELECT stuck_notified, last_significant_change FROM stuck_state WHERE file_path = ?",
            (file_path,),
        ).fetchone()

        assert row[0] == 0
        assert row[1] >= before


class TestPersistence:
    """CRITICAL: state survives daemon restarts (RULE 4)."""

    @pytest.mark.asyncio
    async def test_stuck_detector_state_survives_daemon_restart(
        self, tmp_path: object
    ) -> None:
        """State written to DB is read correctly by a new connection.

        Simulates: daemon runs → gets stuck state → daemon restarts →
        new connection reads persisted state and fires notification.
        """
        from pathlib import Path

        db_path: Path = tmp_path / "persist_test.db"  
        config = _cfg(threshold_s=600)
        file_path: str = "/persist.py"
        content: str = "def main():\n    pass\n    # end"

        
        conn1: sqlite3.Connection = init_db(db_path)
        from contextweave.stuck_detector import _content_hash
        stuck_start: float = time.time() - 601  
        _set_state(conn1, file_path, _content_hash(content), stuck_start, notified=0)
        conn1.close()

        
        conn2: sqlite3.Connection = init_db(db_path)
        result: bool = await stuck_detector.update_activity(
            file_path=file_path,
            content=content,   
            db=conn2,
            config=config,
        )
        conn2.close()

        
        assert result is True


class TestWordDiff:
    """Word diff calculation."""

    def test_stuck_detector_word_diff_counts_correctly(self) -> None:
        """_word_diff returns the correct symmetric word difference count."""
        from contextweave.stuck_detector import _word_diff

        old: str = "def foo bar baz"
        new: str = "def foo qux"
        
        assert _word_diff(old, new) == 3

    def test_stuck_detector_word_diff_identical_strings(self) -> None:
        """Identical strings have zero word diff."""
        from contextweave.stuck_detector import _word_diff

        text: str = "def foo():\n    return 1"
        assert _word_diff(text, text) == 0

    def test_stuck_detector_word_diff_whitespace_change(self) -> None:
        """Whitespace-only changes produce a small diff (< 10)."""
        from contextweave.stuck_detector import _word_diff

        old: str = "def foo():\n    return 1"
        new: str = "def foo():  \n    return 1  \n"
        assert _word_diff(old, new) < 10
