"""Tests for contextweave.gc stale chunk cleanup."""

from __future__ import annotations

import sqlite3
import struct
import time
from pathlib import Path

import pytest
from httpx import AsyncClient

from contextweave.db import chunk_id
from contextweave.gc import run_gc_sweep


def _insert_chunk(conn: sqlite3.Connection, file_path: str, chunk_name: str) -> str:
    """Insert a chunk with a vector and access-log row for GC tests."""
    now: float = time.time()
    cid: str = chunk_id(file_path, chunk_name)
    content: str = f"def {chunk_name}():\n    value = 1\n    return value"

    conn.execute(
        "INSERT INTO chunks "
        "(id, file_path, chunk_name, chunk_type, content, language, "
        "start_line, end_line, last_seen, created_at, workspace_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            cid,
            file_path,
            chunk_name,
            "function",
            content,
            "python",
            1,
            3,
            now,
            now,
            "default",
        ),
    )
    rowid: int = conn.execute(
        "SELECT rowid FROM chunks WHERE id = ?",
        (cid,),
    ).fetchone()[0]
    embedding: bytes = struct.pack("768f", *([0.0] * 768))
    conn.execute(
        "INSERT INTO chunk_vectors (rowid, embedding) VALUES (?, ?)",
        (rowid, embedding),
    )
    conn.execute(
        "INSERT INTO access_log (chunk_id, accessed_at) VALUES (?, ?)",
        (cid, now),
    )
    conn.commit()
    return cid


def _count_rows(conn: sqlite3.Connection, table: str) -> int:
    """Return row count for a known test table."""
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


@pytest.mark.asyncio
async def test_gc_deletes_chunks_for_nonexistent_files(test_db: tuple) -> None:
    """GC deletes stale chunk metadata, vectors, and access-log rows."""
    conn, _ = test_db
    stale_file: str = "/definitely/missing/contextweave_gc_stale.py"
    stale_id: str = _insert_chunk(conn, stale_file, "stale_fn")

    result: dict[str, int | float] = await run_gc_sweep(conn)

    assert result["files_checked"] == 1
    assert result["chunks_deleted"] == 1
    assert conn.execute("SELECT COUNT(*) FROM chunks WHERE id = ?", (stale_id,)).fetchone()[0] == 0
    assert _count_rows(conn, "chunk_vectors") == 0
    assert _count_rows(conn, "access_log") == 0


@pytest.mark.asyncio
async def test_gc_keeps_chunks_for_existing_files(test_db: tuple, tmp_path: Path) -> None:
    """GC keeps chunks whose source file still exists."""
    conn, _ = test_db
    source_file: Path = tmp_path / "live.py"
    source_file.write_text("def live_fn():\n    value = 1\n    return value\n", encoding="utf-8")
    live_id: str = _insert_chunk(conn, str(source_file), "live_fn")

    result: dict[str, int | float] = await run_gc_sweep(conn)

    assert result["files_checked"] == 1
    assert result["chunks_deleted"] == 0
    assert conn.execute("SELECT COUNT(*) FROM chunks WHERE id = ?", (live_id,)).fetchone()[0] == 1
    assert _count_rows(conn, "chunk_vectors") == 1
    assert _count_rows(conn, "access_log") == 1


@pytest.mark.asyncio
async def test_gc_returns_correct_counts(test_db: tuple, tmp_path: Path) -> None:
    """GC reports unique files checked and total chunks deleted."""
    conn, _ = test_db
    live_file: Path = tmp_path / "live.py"
    live_file.write_text("def live_fn():\n    value = 1\n    return value\n", encoding="utf-8")

    _insert_chunk(conn, str(live_file), "live_fn")
    _insert_chunk(conn, "/missing/contextweave_stale_a.py", "stale_a_one")
    _insert_chunk(conn, "/missing/contextweave_stale_a.py", "stale_a_two")
    _insert_chunk(conn, "/missing/contextweave_stale_b.py", "stale_b")

    result: dict[str, int | float] = await run_gc_sweep(conn)

    assert result["files_checked"] == 3
    assert result["chunks_deleted"] == 3
    assert isinstance(result["duration_ms"], float)
    assert _count_rows(conn, "chunks") == 1


@pytest.mark.asyncio
async def test_gc_handles_empty_db(test_db: tuple) -> None:
    """GC returns zero counts on an empty chunks table."""
    conn, _ = test_db

    result: dict[str, int | float] = await run_gc_sweep(conn)

    assert result["files_checked"] == 0
    assert result["chunks_deleted"] == 0
    assert isinstance(result["duration_ms"], float)


@pytest.mark.asyncio
async def test_gc_endpoint_returns_200(client: AsyncClient) -> None:
    """GET /gc manually triggers a sweep and returns stats."""
    from contextweave import server  

    assert server._db is not None
    _insert_chunk(server._db, "/missing/contextweave_endpoint_stale.py", "stale_fn")

    response = await client.get("/gc")

    assert response.status_code == 200
    data: dict = response.json()
    assert data["files_checked"] == 1
    assert data["chunks_deleted"] == 1
    assert isinstance(data["duration_ms"], float)
