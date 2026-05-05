"""Shared test fixtures for the ContextWeave daemon test suite.

All fixtures use temporary paths so tests never touch the real
``~/.contextweave/`` directory or any external services (Rule 6).
"""

from __future__ import annotations

import hashlib
import random
import sqlite3
import struct
import time
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from contextweave.config import Config
from contextweave.db import init_db
from contextweave.providers.base import ChatResult, EmbedResult, LLMProvider, ProviderError
from contextweave.server import app


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncClient:  
    """Async test client backed by a temporary SQLite database.

    Overrides module-level state in ``server`` so the real
    ``~/.contextweave/memory.db`` is never touched.
    Also resets the embedder module to avoid cross-test pollution.
    """
    from contextweave import server, embedder

    db_path: Path = tmp_path / "test.db"
    conn = init_db(db_path)

    
    old_db = server._db
    old_config = server._config
    old_provider = server._provider
    old_shutting_down = server._shutting_down
    old_start_time = server._start_time
    old_chunks = server._chunks_ingested_total
    old_ranks = server._rank_calls_total

    
    server._db = conn
    server._config = Config()
    server._provider = MockProvider()
    server._shutting_down = False
    server._start_time = time.time()
    server._chunks_ingested_total = 0
    server._rank_calls_total = 0

    
    await embedder.start_workers(server._provider, conn, n=1, max_queue_size=500)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            yield c
    finally:
        await embedder.drain_and_stop(timeout_s=2.0)
        embedder._reset()
        conn.close()
        server._db = old_db
        server._config = old_config
        server._provider = old_provider
        server._shutting_down = old_shutting_down
        server._start_time = old_start_time
        server._chunks_ingested_total = old_chunks
        server._rank_calls_total = old_ranks


@pytest.fixture
def test_db(tmp_path: Path) -> tuple:
    """Return a (connection, path) tuple for an isolated test database."""
    db_path: Path = tmp_path / "test.db"
    conn = init_db(db_path)
    yield conn, db_path  
    conn.close()


class MockProvider(LLMProvider):
    """Deterministic fake LLM provider for testing (Rule 6).

    Embed returns a consistent 768-d vector seeded from the input text.
    No network calls are ever made.
    """

    def __init__(self, *, fail_count: int = 0) -> None:
        self._fail_count: int = fail_count
        self._call_count: int = 0

    async def embed(self, text: str) -> EmbedResult:
        """Return a deterministic 768-d vector seeded from *text*."""
        self._call_count += 1
        if self._call_count <= self._fail_count:
            raise ProviderError("mock", f"simulated failure #{self._call_count}")

        seed: int = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
        rng: random.Random = random.Random(seed)
        return EmbedResult(
            embedding=[rng.gauss(0, 1) for _ in range(768)],
            model="mock",
            prompt_tokens=len(text.split()),
        )

    async def chat(self, system: str, user: str) -> ChatResult:
        """Return a canned chat response."""
        return ChatResult(
            content="mock response",
            model="mock",
            input_tokens=10,
            output_tokens=5,
        )

    async def health_check(self) -> bool:
        """Always healthy."""
        return True


@pytest.fixture
def mock_provider() -> MockProvider:
    """A deterministic mock provider that requires no network calls (Rule 6)."""
    return MockProvider()


def _sync_embed(text: str) -> list[float]:
    """Compute a deterministic 768-d embedding synchronously (no event loop needed)."""
    seed: int = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
    rng: random.Random = random.Random(seed)
    return [rng.gauss(0, 1) for _ in range(768)]


def seed_chunks(
    conn: sqlite3.Connection,
    provider_or_none: MockProvider | None = None,
    count: int = 5,
    last_seen_offset_hours: float = 0.0,
) -> list[dict]:
    """Insert *count* test chunks with embeddings into *conn*.

    Returns a list of dicts with chunk metadata for assertions.
    Uses synchronous embedding so it works both inside and outside running event loops.
    """
    now: float = time.time()
    last_seen: float = now - (last_seen_offset_hours * 3600)
    seeded: list[dict] = []

    for i in range(count):
        chunk_name: str = f"test_fn_{i}"
        file_path: str = f"/test_{i}.py"
        content: str = f"def test_fn_{i}():\n    x = {i}\n    return x"
        cid: str = hashlib.sha256(f"{file_path}:{chunk_name}".encode()).hexdigest()[:16]

        conn.execute(
            "INSERT OR REPLACE INTO chunks "
            "(id, file_path, chunk_name, chunk_type, content, language, "
            "start_line, end_line, last_seen, created_at, workspace_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, file_path, chunk_name, "function", content, "python",
             1, 3, last_seen, now, "default"),
        )

        
        row = conn.execute("SELECT rowid FROM chunks WHERE id = ?", (cid,)).fetchone()
        rowid: int = row[0]

        
        embedding: list[float] = _sync_embed(content)
        embedding_blob: bytes = struct.pack(f"{len(embedding)}f", *embedding)

        
        conn.execute("DELETE FROM chunk_vectors WHERE rowid = ?", (rowid,))
        conn.execute(
            "INSERT INTO chunk_vectors (rowid, embedding) VALUES (?, ?)",
            (rowid, embedding_blob),
        )

        seeded.append({
            "id": cid, "chunk_name": chunk_name, "file_path": file_path,
            "content": content, "rowid": rowid,
        })

    conn.commit()
    return seeded
