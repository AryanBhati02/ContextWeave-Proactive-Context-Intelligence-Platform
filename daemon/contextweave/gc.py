"""Garbage collection for stale chunks from deleted or renamed files."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

import structlog

log: structlog.stdlib.BoundLogger = structlog.get_logger()

_background_task: asyncio.Task[None] | None = None


async def run_gc_sweep(db: sqlite3.Connection) -> dict[str, int | float]:
    """Delete chunks for files that no longer exist on the filesystem.

    Returns ``{"files_checked": int, "chunks_deleted": int, "duration_ms": float}``.
    Never raises. Logs all deletions at INFO level.
    """
    start: float = time.time()
    files_checked: int = 0
    chunks_deleted: int = 0

    try:
        cursor = db.execute("SELECT DISTINCT file_path FROM chunks")
        all_paths: list[str] = [row[0] for row in cursor.fetchall()]
        files_checked = len(all_paths)

        for file_path in all_paths:
            if Path(file_path).exists():
                continue

            stale_rows = db.execute(
                "SELECT rowid FROM chunks WHERE file_path = ?",
                (file_path,),
            ).fetchall()
            stale_rowids: list[int] = [row[0] for row in stale_rows]

            for rowid in stale_rowids:
                db.execute("DELETE FROM chunk_vectors WHERE rowid = ?", (rowid,))

            cursor = db.execute("DELETE FROM chunks WHERE file_path = ?", (file_path,))
            deleted_for_file: int = cursor.rowcount if cursor.rowcount > 0 else 0
            chunks_deleted += deleted_for_file
            log.info(
                "gc_deleted_stale_chunks",
                file_path=file_path,
                count=deleted_for_file,
            )

        db.commit()

    except Exception:
        log.warning("gc_sweep_failed", exc_info=True)
        try:
            db.rollback()
        except sqlite3.Error:
            pass

    duration_ms: float = round((time.time() - start) * 1000, 1)
    log.info(
        "gc_sweep_complete",
        files_checked=files_checked,
        chunks_deleted=chunks_deleted,
        duration_ms=duration_ms,
    )

    return {
        "files_checked": files_checked,
        "chunks_deleted": chunks_deleted,
        "duration_ms": duration_ms,
    }


async def start_gc_background_task(
    db: sqlite3.Connection,
    interval_hours: float = 24.0,
) -> None:
    """Start a background task that runs a GC sweep every ``interval_hours``."""
    global _background_task  

    if _background_task is not None and not _background_task.done():
        return

    async def _loop() -> None:
        while True:
            await asyncio.sleep(interval_hours * 3600)
            await run_gc_sweep(db)

    _background_task = asyncio.create_task(_loop())
    log.info("gc_background_task_started", interval_hours=interval_hours)


async def stop_gc_background_task() -> None:
    """Stop the background GC task if it is running."""
    global _background_task  

    if _background_task is None:
        return

    _background_task.cancel()
    try:
        await _background_task
    except asyncio.CancelledError:
        pass
    _background_task = None
    log.info("gc_background_task_stopped")
