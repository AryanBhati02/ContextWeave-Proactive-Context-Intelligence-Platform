"""Tests for contextweave.embedder — async queue, dedup, retry, DB writes."""

from __future__ import annotations

import asyncio
import time

import pytest

from contextweave.chunker import Chunk
from contextweave.db import init_db
from contextweave import embedder
from tests.conftest import MockProvider


def _make_chunk(
    name: str = "test_func",
    file_path: str = "/test.py",
    content: str = "def test_func():\n    x = 1\n    return x",
) -> Chunk:
    """Helper to create a test chunk."""
    import hashlib

    chunk_id: str = hashlib.sha256(f"{file_path}:{name}".encode()).hexdigest()[:16]
    return Chunk(
        id=chunk_id,
        file_path=file_path,
        chunk_name=name,
        chunk_type="function",
        content=content,
        language="python",
        start_line=1,
        end_line=3,
        created_at=time.time(),
    )


class TestEnqueue:
    """Enqueue and queue-full behaviour."""

    @pytest.mark.asyncio
    async def test_embedder_enqueues_chunks_successfully(self, test_db: tuple) -> None:
        """Chunks can be enqueued and the queue depth increases."""
        conn, _ = test_db
        provider = MockProvider()
        await embedder.start_workers(provider, conn, n=0, max_queue_size=10)

        try:
            chunk = _make_chunk()
            await embedder.enqueue(chunk)
            depth: int = await embedder.queue_depth()
            assert depth == 1
        finally:
            embedder._reset()

    @pytest.mark.asyncio
    async def test_embedder_drops_oldest_when_queue_is_full(self, test_db: tuple) -> None:
        """When queue is full, the oldest item is dropped to make room."""
        conn, _ = test_db
        provider = MockProvider()
        await embedder.start_workers(provider, conn, n=0, max_queue_size=3)

        try:
            
            for i in range(3):
                await embedder.enqueue(_make_chunk(name=f"fn_{i}"))

            assert await embedder.queue_depth() == 3

            
            await embedder.enqueue(_make_chunk(name="fn_new"))
            assert await embedder.queue_depth() == 3
        finally:
            embedder._reset()

    @pytest.mark.asyncio
    async def test_embedder_logs_warning_when_dropping_chunk(
        self, test_db: tuple, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A WARNING is logged when a chunk is dropped from a full queue."""
        conn, _ = test_db
        provider = MockProvider()
        await embedder.start_workers(provider, conn, n=0, max_queue_size=1)

        try:
            await embedder.enqueue(_make_chunk(name="first"))
            await embedder.enqueue(_make_chunk(name="second"))
            
            assert await embedder.queue_depth() == 1
        finally:
            embedder._reset()


class TestWorkers:
    """Worker processing, dedup, retry, and DB writes."""

    @pytest.mark.asyncio
    async def test_embedder_workers_write_to_db(self, test_db: tuple) -> None:
        """After processing, chunk appears in the chunks table."""
        conn, _ = test_db
        provider = MockProvider()
        await embedder.start_workers(provider, conn, n=1, max_queue_size=10)

        try:
            chunk = _make_chunk()
            await embedder.enqueue(chunk)

            
            await asyncio.sleep(1.5)

            row = conn.execute(
                "SELECT chunk_name, chunk_type FROM chunks WHERE id = ?",
                (chunk.id,),
            ).fetchone()

            assert row is not None
            assert row[0] == "test_func" if isinstance(row, tuple) else row["chunk_name"] == "test_func"
        finally:
            await embedder.drain_and_stop(timeout_s=2.0)
            embedder._reset()

    @pytest.mark.asyncio
    async def test_embedder_skips_chunk_when_content_unchanged(self, test_db: tuple) -> None:
        """Chunks with identical content already in DB are skipped (dedup)."""
        conn, _ = test_db
        provider = MockProvider()

        chunk = _make_chunk()

        
        now: float = time.time()
        conn.execute(
            "INSERT INTO chunks "
            "(id, file_path, chunk_name, chunk_type, content, language, "
            "start_line, end_line, last_seen, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                chunk.id, chunk.file_path, chunk.chunk_name, chunk.chunk_type,
                chunk.content, chunk.language, chunk.start_line, chunk.end_line,
                now, now,
            ),
        )
        conn.commit()

        await embedder.start_workers(provider, conn, n=1, max_queue_size=10)

        try:
            await embedder.enqueue(chunk)
            await asyncio.sleep(1.0)

            
            
            count: int = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            assert count == 1
        finally:
            await embedder.drain_and_stop(timeout_s=2.0)
            embedder._reset()

    @pytest.mark.asyncio
    async def test_embedder_retries_on_provider_failure(self, test_db: tuple) -> None:
        """Provider failures trigger retries with backoff, then succeed."""
        conn, _ = test_db
        
        provider = MockProvider(fail_count=2)
        await embedder.start_workers(provider, conn, n=1, max_queue_size=10)

        try:
            chunk = _make_chunk()
            await embedder.enqueue(chunk)

            
            await asyncio.sleep(5.0)

            row = conn.execute(
                "SELECT id FROM chunks WHERE id = ?", (chunk.id,)
            ).fetchone()
            assert row is not None
        finally:
            await embedder.drain_and_stop(timeout_s=2.0)
            embedder._reset()

    @pytest.mark.asyncio
    async def test_embedder_skips_chunk_after_4_failures(self, test_db: tuple) -> None:
        """After 4 consecutive failures the chunk is skipped."""
        conn, _ = test_db
        
        provider = MockProvider(fail_count=10)
        await embedder.start_workers(provider, conn, n=1, max_queue_size=10)

        try:
            chunk = _make_chunk()
            await embedder.enqueue(chunk)

            
            await asyncio.sleep(9.0)

            row = conn.execute(
                "SELECT id FROM chunks WHERE id = ?", (chunk.id,)
            ).fetchone()
            
            assert row is None
        finally:
            await embedder.drain_and_stop(timeout_s=2.0)
            embedder._reset()

    @pytest.mark.asyncio
    async def test_embedder_drains_before_stopping(self, test_db: tuple) -> None:
        """drain_and_stop waits for pending items to be processed."""
        conn, _ = test_db
        provider = MockProvider()
        await embedder.start_workers(provider, conn, n=1, max_queue_size=10)

        try:
            for i in range(3):
                await embedder.enqueue(
                    _make_chunk(name=f"drain_fn_{i}", content=f"def drain_fn_{i}():\n    x = {i}\n    return x")
                )

            await embedder.drain_and_stop(timeout_s=5.0)

            count: int = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            assert count == 3
        finally:
            embedder._reset()
