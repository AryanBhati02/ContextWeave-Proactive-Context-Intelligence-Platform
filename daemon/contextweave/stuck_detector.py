"""Stuck detector — finite state machine with SQLite persistence.

All state lives in the ``stuck_state`` table.  **Never** in a Python dict
or module-level variable (RULE 4).  If the daemon restarts after 8 minutes
of the developer being stuck, those 8 minutes are not lost.

State transitions (on every ``update_activity`` call)::

    word_diff > threshold  →  reset timer, clear notified flag, return False
    timer expired AND not notified  →  set notified, return True (ONCE)
    otherwise  →  return False
"""

from __future__ import annotations

import hashlib
import sqlite3
import time

import structlog

from contextweave.config import StuckDetectorConfig

log: structlog.stdlib.BoundLogger = structlog.get_logger()






def _content_hash(content: str) -> str:
    """Return the MD5 hex digest of *content*."""
    return hashlib.md5(content.encode()).hexdigest()


def _word_diff(old: str, new: str) -> int:
    """Count words that appear in one version but not the other.

    Whitespace-only changes and comment toggles score 0–2, well below
    the default ``min_change_tokens`` threshold of 10.
    """
    old_words: set[str] = set(old.split())
    new_words: set[str] = set(new.split())
    return len(old_words.symmetric_difference(new_words))






async def update_activity(
    file_path: str,
    content: str,
    db: sqlite3.Connection,
    config: StuckDetectorConfig,
    workspace_id: str = "default",
) -> bool:
    """Called on every ingest event.

    Returns ``True`` **only** when the stuck threshold is exceeded AND the
    user has not yet been notified for this stuck session.  Returns ``True``
    at most once per stuck session (until :func:`reset` is called or a
    significant edit is detected).

    Never raises.

    Parameters
    ----------
    file_path:
        Absolute path of the file being ingested.
    content:
        Full text content of the file.
    db:
        SQLite connection (state lives here, not in memory).
    config:
        Stuck-detector thresholds from the config file.
    """
    try:
        return _update_activity_inner(file_path, content, db, config, workspace_id)
    except Exception:
        log.warning("stuck_detector_error", file_path=file_path, exc_info=True)
        return False


def _update_activity_inner(
    file_path: str,
    content: str,
    db: sqlite3.Connection,
    config: StuckDetectorConfig,
    workspace_id: str,
) -> bool:
    """Core logic — separated so the outer function can catch all errors."""
    now: float = time.time()
    new_hash: str = _content_hash(content)
    state_key: str = _state_key(file_path, workspace_id)

    row = db.execute(
        "SELECT last_content_hash, last_significant_change, stuck_notified "
        "FROM stuck_state WHERE file_path = ?",
        (state_key,),
    ).fetchone()

    
    if row is None:
        db.execute(
            "INSERT INTO stuck_state "
            "(file_path, last_content_hash, last_significant_change, stuck_notified) "
            "VALUES (?, ?, ?, 0)",
            (state_key, new_hash, now),
        )
        db.commit()
        return False

    old_hash: str = row[0] if isinstance(row, tuple) else row["last_content_hash"]
    last_change: float = row[1] if isinstance(row, tuple) else row["last_significant_change"]
    notified: int = row[2] if isinstance(row, tuple) else row["stuck_notified"]

    
    if old_hash == new_hash:
        elapsed: float = now - last_change
        if elapsed > config.threshold_seconds and notified == 0:
            db.execute(
                "UPDATE stuck_state SET stuck_notified = 1 WHERE file_path = ?",
                (state_key,),
            )
            db.commit()
            log.info(
                "stuck_detected",
                file_path=file_path,
                workspace_id=workspace_id,
                elapsed_s=round(elapsed, 1),
            )
            return True
        return False

    
    
    
    
    
    old_content: str | None = _get_last_content(file_path, db, workspace_id)

    if old_content is not None:
        diff: int = _word_diff(old_content, content)
    else:
        
        diff = config.min_change_tokens + 1

    if diff > config.min_change_tokens:
        
        db.execute(
            "UPDATE stuck_state "
            "SET last_content_hash = ?, last_significant_change = ?, stuck_notified = 0 "
            "WHERE file_path = ?",
            (new_hash, now, state_key),
        )
        db.commit()
        return False

    
    db.execute(
        "UPDATE stuck_state SET last_content_hash = ? WHERE file_path = ?",
        (new_hash, state_key),
    )
    db.commit()

    elapsed = now - last_change
    if elapsed > config.threshold_seconds and notified == 0:
        db.execute(
            "UPDATE stuck_state SET stuck_notified = 1 WHERE file_path = ?",
            (state_key,),
        )
        db.commit()
        log.info(
            "stuck_detected",
            file_path=file_path,
            workspace_id=workspace_id,
            elapsed_s=round(elapsed, 1),
        )
        return True

    return False


def _state_key(file_path: str, workspace_id: str) -> str:
    """Return the persisted stuck-state key for a file/workspace pair."""
    if workspace_id == "default":
        return file_path
    return f"{workspace_id}:{file_path}"


def _get_last_content(
    file_path: str,
    db: sqlite3.Connection,
    workspace_id: str = "default",
) -> str | None:
    """Retrieve the most-recent chunk content for *file_path* (for diffing)."""
    row = db.execute(
        "SELECT content FROM chunks WHERE file_path = ? AND workspace_id = ? "
        "ORDER BY last_seen DESC LIMIT 1",
        (file_path, workspace_id),
    ).fetchone()
    if row is None:
        return None
    return row[0] if isinstance(row, tuple) else row["content"]


async def reset(
    file_path: str,
    db: sqlite3.Connection,
    workspace_id: str = "default",
) -> None:
    """Reset stuck state for *file_path*.

    Called when the user clicks "Not Stuck" in the VS Code panel.
    Sets ``stuck_notified = 0`` and ``last_significant_change = now()``.
    """
    now: float = time.time()
    state_key: str = _state_key(file_path, workspace_id)
    db.execute(
        "UPDATE stuck_state "
        "SET stuck_notified = 0, last_significant_change = ? "
        "WHERE file_path = ?",
        (now, state_key),
    )
    db.commit()
    log.info("stuck_reset", file_path=file_path, workspace_id=workspace_id)
