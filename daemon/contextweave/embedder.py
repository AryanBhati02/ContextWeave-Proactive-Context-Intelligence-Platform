"""Async background embedder — queues chunks and writes vectors to SQLite.

Architecture
------------
* One :class:`asyncio.Queue` (max 500 items by default).
* *n* worker tasks (default 2) that loop: dequeue → dedup → embed → write.
* When queue is full the **oldest** item is dropped (newest are most valuable).
* Retry policy on provider failure: 0 s → 1 s → 2 s → 4 s, then skip.
* Graceful shutdown: :func:`drain_and_stop` waits for the queue to empty.
"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import struct
import time
from dataclasses import dataclass
from typing import Sequence

import structlog

from contextweave.chunker import Chunk
from contextweave.providers.base import LLMProvider, ProviderError

log: structlog.stdlib.BoundLogger = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class QueuedChunk:
    """Chunk plus workspace scope for embedding and DB writes."""

    chunk: Chunk
    workspace_id: str




_queue: asyncio.Queue[QueuedChunk] | None = None
_workers: list[asyncio.Task[None]] = []
_stop_event: asyncio.Event | None = None
_provider: LLMProvider | None = None
_db: sqlite3.Connection | None = None
_max_queue_size: int = 500

_RETRY_DELAYS: Sequence[float] = (0, 1, 2, 4)






async def enqueue(chunk: Chunk, workspace_id: str = "default") -> None:
    """Add *chunk* to the embedding queue.  Never raises.

    If the queue is full (``max_queue_size`` items) the **oldest** item
    is dropped — newest chunks are more likely to be queried soon.
    """
    if _queue is None:
        log.warning("embedder_not_started")
        return

    if _queue.full():
        try:
            dropped: QueuedChunk = _queue.get_nowait()
            log.warning(
                "queue_full_dropping_oldest",
                file_path=dropped.chunk.file_path,
                chunk_name=dropped.chunk.chunk_name,
                workspace_id=dropped.workspace_id,
            )
            _queue.task_done()
        except asyncio.QueueEmpty:
            pass

    try:
        _queue.put_nowait(QueuedChunk(chunk=chunk, workspace_id=workspace_id))
    except asyncio.QueueFull:
        log.warning("queue_still_full", chunk_id=chunk.id)


async def start_workers(
    provider: LLMProvider,
    db_conn: sqlite3.Connection,
    n: int = 2,
    max_queue_size: int = 500,
) -> None:
    """Start *n* background worker tasks.  Called once at daemon startup."""
    global _queue, _workers, _stop_event, _provider, _db, _max_queue_size  

    _provider = provider
    _db = db_conn
    _max_queue_size = max_queue_size
    _stop_event = asyncio.Event()
    _queue = asyncio.Queue(maxsize=max_queue_size)
    _workers = [asyncio.create_task(_worker(i)) for i in range(n)]

    log.info("embedder_workers_started", count=n, max_queue_size=max_queue_size)


async def drain_and_stop(timeout_s: float = 10.0) -> None:
    """Drain remaining items and stop workers within *timeout_s* seconds."""
    if _stop_event is None:
        return

    log.info("embedder_draining_queue", remaining=_queue.qsize() if _queue else 0)
    _stop_event.set()

    try:
        await asyncio.wait_for(
            asyncio.gather(*_workers, return_exceptions=True),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        log.warning("embedder_drain_timeout", timeout_s=timeout_s)
        for task in _workers:
            task.cancel()

    log.info("embedder_stopped")


async def queue_depth() -> int:
    """Return the current number of items waiting in the queue."""
    if _queue is None:
        return 0
    return _queue.qsize()






def _reset() -> None:
    """Reset all module state.  For testing only."""
    global _queue, _workers, _stop_event, _provider, _db  

    for task in _workers:
        if not task.done():
            task.cancel()
    _workers = []
    _queue = None
    _stop_event = None
    _provider = None
    _db = None






async def _worker(worker_id: int) -> None:
    """Background worker: dequeue → dedup → embed → write."""
    assert _queue is not None
    assert _stop_event is not None

    log.debug("embedder_worker_started", worker_id=worker_id)

    while True:
        
        if _stop_event.is_set() and _queue.empty():
            break

        try:
            queued: QueuedChunk = await asyncio.wait_for(_queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue

        try:
            chunk: Chunk = queued.chunk
            
            if _is_content_unchanged(chunk, queued.workspace_id):
                log.debug("chunk_skipped_unchanged", chunk_id=chunk.id)
                continue

            
            embedding: list[float] | None = await _embed_with_retry(chunk)
            if embedding is None:
                continue

            
            _write_to_db(chunk, embedding, queued.workspace_id)
            log.debug(
                "chunk_embedded",
                chunk_id=chunk.id,
                chunk_name=chunk.chunk_name,
                file_path=chunk.file_path,
                workspace_id=queued.workspace_id,
            )
        except Exception:
            log.error(
                "embedder_worker_unexpected_error",
                chunk_id=queued.chunk.id,
                workspace_id=queued.workspace_id,
                exc_info=True,
            )
        finally:
            _queue.task_done()

    log.debug("embedder_worker_stopped", worker_id=worker_id)






def _workspace_chunk_id(chunk: Chunk, workspace_id: str) -> str:
    """Return the DB chunk ID scoped to a workspace."""
    if workspace_id == "default":
        return chunk.id
    return hashlib.sha256(
        f"{workspace_id}:{chunk.file_path}:{chunk.chunk_name}".encode()
    ).hexdigest()[:16]


def _is_content_unchanged(chunk: Chunk, workspace_id: str) -> bool:
    """Return ``True`` if chunk already exists in DB with identical content."""
    if _db is None:
        return False
    try:
        scoped_id: str = _workspace_chunk_id(chunk, workspace_id)
        row = _db.execute(
            "SELECT content FROM chunks WHERE id = ?", (scoped_id,)
        ).fetchone()
        if row is not None:
            return row[0] == chunk.content if isinstance(row, tuple) else row["content"] == chunk.content
    except sqlite3.Error:
        log.warning("dedup_check_failed", chunk_id=chunk.id, exc_info=True)
    return False


async def _embed_with_retry(chunk: Chunk) -> list[float] | None:
    """Embed *chunk* with exponential backoff (0, 1, 2, 4 s).

    Returns the embedding vector, or ``None`` after 4 failures.
    """
    assert _provider is not None

    for attempt, delay in enumerate(_RETRY_DELAYS):
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            result = await _provider.embed(chunk.content)
            return result.embedding
        except ProviderError as exc:
            log.warning(
                "embed_retry",
                attempt=attempt + 1,
                max_attempts=len(_RETRY_DELAYS),
                chunk_id=chunk.id,
                error=str(exc),
            )

    log.error(
        "embed_failed_after_retries",
        chunk_id=chunk.id,
        file_path=chunk.file_path,
        chunk_name=chunk.chunk_name,
    )
    return None


def _write_to_db(
    chunk: Chunk,
    embedding: list[float],
    workspace_id: str = "default",
) -> None:
    """Write chunk metadata and embedding vector in a single transaction."""
    assert _db is not None

    now: float = time.time()
    scoped_id: str = _workspace_chunk_id(chunk, workspace_id)
    embedding_blob: bytes = struct.pack(f"{len(embedding)}f", *embedding)

    try:
        
        old_row = _db.execute(
            "SELECT rowid FROM chunks WHERE id = ?", (scoped_id,)
        ).fetchone()
        if old_row is not None:
            old_rowid: int = old_row[0] if isinstance(old_row, tuple) else old_row["rowid"]
            _db.execute("DELETE FROM chunk_vectors WHERE rowid = ?", (old_rowid,))

        _db.execute(
            "INSERT OR REPLACE INTO chunks "
            "(id, file_path, chunk_name, chunk_type, content, language, "
            "start_line, end_line, last_seen, created_at, workspace_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                scoped_id,
                chunk.file_path,
                chunk.chunk_name,
                chunk.chunk_type,
                chunk.content,
                chunk.language,
                chunk.start_line,
                chunk.end_line,
                now,
                chunk.created_at,
                workspace_id,
            ),
        )

        new_rowid: int = _db.execute(
            "SELECT rowid FROM chunks WHERE id = ?", (scoped_id,)
        ).fetchone()[0]

        _db.execute(
            "INSERT INTO chunk_vectors (rowid, embedding) VALUES (?, ?)",
            (new_rowid, embedding_blob),
        )
        _db.commit()

    except sqlite3.Error:
        log.error("db_write_failed", chunk_id=chunk.id, exc_info=True)
        try:
            _db.rollback()
        except sqlite3.Error:
            pass
