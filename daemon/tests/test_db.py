"""Tests for contextweave.db — schema, WAL, foreign keys, sqlite-vec."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from contextweave.db import chunk_id, init_db


class TestInitDb:
    """Database initialisation and schema tests."""

    def test_db_creates_all_tables(self, tmp_path: Path) -> None:
        """All five tables are created (chunks, access_log, stuck_state, import_graph + virtual)."""
        conn: sqlite3.Connection = init_db(tmp_path / "test.db")

        tables: list[str] = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'vec_%'"
            ).fetchall()
        ]

        assert "chunks" in tables
        assert "access_log" in tables
        assert "stuck_state" in tables
        assert "import_graph" in tables
        conn.close()

    def test_db_creates_chunk_vectors_virtual_table(self, tmp_path: Path) -> None:
        """The vec0 virtual table for embeddings exists."""
        conn: sqlite3.Connection = init_db(tmp_path / "test.db")

        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chunk_vectors'"
        ).fetchall()

        assert len(rows) == 1
        conn.close()

    def test_db_creates_all_indices(self, tmp_path: Path) -> None:
        """All six indices are created."""
        conn: sqlite3.Connection = init_db(tmp_path / "test.db")

        indices: set[str] = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name LIKE 'idx_%'"
            ).fetchall()
        }

        expected: set[str] = {
            "idx_chunks_file",
            "idx_chunks_lang",
            "idx_chunks_workspace",
            "idx_access_recent",
            "idx_chunks_seen",
            "idx_graph_source",
        }
        assert expected.issubset(indices)
        conn.close()

    def test_db_enables_wal_mode(self, tmp_path: Path) -> None:
        """WAL journal mode is enabled."""
        conn: sqlite3.Connection = init_db(tmp_path / "test.db")

        mode: str = conn.execute("PRAGMA journal_mode").fetchone()[0]

        assert mode.lower() == "wal"
        conn.close()

    def test_db_enables_foreign_keys(self, tmp_path: Path) -> None:
        """Foreign key enforcement is turned on."""
        conn: sqlite3.Connection = init_db(tmp_path / "test.db")

        fk: int = conn.execute("PRAGMA foreign_keys").fetchone()[0]

        assert fk == 1
        conn.close()

    def test_db_creates_directory_if_not_exists(self, tmp_path: Path) -> None:
        """Parent directories are created automatically."""
        deep_path: Path = tmp_path / "a" / "b" / "c" / "test.db"
        assert not deep_path.parent.exists()

        conn: sqlite3.Connection = init_db(deep_path)

        assert deep_path.exists()
        conn.close()

    def test_db_chunk_type_constraint(self, tmp_path: Path) -> None:
        """The CHECK constraint on chunk_type rejects invalid values."""
        conn: sqlite3.Connection = init_db(tmp_path / "test.db")
        import time

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO chunks "
                "(id, file_path, chunk_name, chunk_type, content, language, "
                "start_line, end_line, last_seen, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("id1", "/a.py", "fn", "invalid_type", "x", "python", 1, 5, time.time(), time.time()),
            )
        conn.close()


class TestChunkId:
    """Deterministic chunk ID generation."""

    def test_db_chunk_id_is_deterministic(self) -> None:
        """Same (file_path, chunk_name) always produces the same 16-char hex ID."""
        id1: str = chunk_id("/src/app.py", "main")
        id2: str = chunk_id("/src/app.py", "main")

        assert id1 == id2
        assert len(id1) == 16

    def test_db_chunk_id_differs_for_different_inputs(self) -> None:
        """Different inputs produce different IDs."""
        id1: str = chunk_id("/a.py", "foo")
        id2: str = chunk_id("/b.py", "foo")

        assert id1 != id2


class TestSqliteVecGuard:
    """Fail-fast when sqlite-vec is missing."""

    def test_db_fails_fast_if_sqlite_vec_not_available(self, tmp_path: Path) -> None:
        """SystemExit(1) is raised when sqlite_vec cannot be imported."""
        with patch.dict("sys.modules", {"sqlite_vec": None}):
            with pytest.raises(SystemExit) as exc_info:
                init_db(tmp_path / "no_vec.db")

            assert exc_info.value.code == 1
