"""SQLite database layer with sqlite-vec vector search.

The database lives at ``~/.contextweave/memory.db`` by default.
WAL mode and foreign keys are enabled on every connection.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import structlog

from contextweave.config import Config

log: structlog.stdlib.BoundLogger = structlog.get_logger()


_connection: sqlite3.Connection | None = None





_SCHEMA: str = """
CREATE TABLE IF NOT EXISTS chunks (
    id           TEXT PRIMARY KEY,
    file_path    TEXT NOT NULL,
    chunk_name   TEXT NOT NULL,
    chunk_type   TEXT NOT NULL CHECK(chunk_type IN ('function','class','method','module')),
    content      TEXT NOT NULL,
    language     TEXT NOT NULL,
    start_line   INTEGER NOT NULL,
    end_line     INTEGER NOT NULL,
    last_seen    REAL NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL,
    workspace_id TEXT NOT NULL DEFAULT 'default'
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors
    USING vec0(embedding FLOAT[768]);

CREATE TABLE IF NOT EXISTS access_log (
    chunk_id    TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    accessed_at REAL NOT NULL,
    PRIMARY KEY (chunk_id, accessed_at)
);

CREATE TABLE IF NOT EXISTS stuck_state (
    file_path               TEXT PRIMARY KEY,
    last_content_hash       TEXT NOT NULL,
    last_significant_change REAL NOT NULL,
    stuck_notified          INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS import_graph (
    source_file TEXT NOT NULL,
    target_file TEXT NOT NULL,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (source_file, target_file)
);

CREATE INDEX IF NOT EXISTS idx_chunks_file      ON chunks(file_path);
CREATE INDEX IF NOT EXISTS idx_chunks_lang      ON chunks(language);
CREATE INDEX IF NOT EXISTS idx_chunks_workspace ON chunks(workspace_id);
CREATE INDEX IF NOT EXISTS idx_access_recent    ON access_log(accessed_at DESC);
CREATE INDEX IF NOT EXISTS idx_chunks_seen      ON chunks(last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_graph_source     ON import_graph(source_file);
"""






def chunk_id(file_path: str, chunk_name: str) -> str:
    """Deterministic chunk ID: first 16 hex chars of SHA-256(file_path:chunk_name)."""
    return hashlib.sha256(f"{file_path}:{chunk_name}".encode()).hexdigest()[:16]


def _load_sqlite_vec(conn: sqlite3.Connection) -> None:
    """Load the sqlite-vec extension into *conn*.

    Raises :class:`SystemExit` with code 1 if the extension is not installed.
    """
    try:
        import sqlite_vec  
    except ImportError as exc:
        log.error(
            "sqlite_vec_not_installed",
            instructions="Install with:  pip install sqlite-vec",
        )
        raise SystemExit(1) from exc

    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    log.debug("sqlite_vec_loaded")






def init_db(db_path: Path) -> sqlite3.Connection:
    """Create (or open) the database at *db_path* and apply the full schema.

    * Enables WAL journal mode for concurrent reads.
    * Enables foreign-key enforcement.
    * Loads the ``sqlite-vec`` extension for vector search.
    * Creates all tables, virtual tables, and indices.

    Parameters
    ----------
    db_path:
        Filesystem path for the SQLite database file.

    Returns
    -------
    sqlite3.Connection
        A ready-to-use database connection.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn: sqlite3.Connection = sqlite3.connect(
        str(db_path),
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row

    
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    
    _load_sqlite_vec(conn)

    
    conn.executescript(_SCHEMA)
    conn.commit()

    log.info("db_initialized", path=str(db_path))
    return conn


def get_db(config: Config) -> sqlite3.Connection:
    """Return the singleton database connection, creating it if necessary.

    Parameters
    ----------
    config:
        Application configuration (used to derive the DB path on first call).

    Returns
    -------
    sqlite3.Connection
        The shared database connection.
    """
    global _connection  

    if _connection is None:
        db_path: Path = Path.home() / ".contextweave" / "memory.db"
        _connection = init_db(db_path)

    return _connection


def close_db() -> None:
    """Close the singleton connection if it is open."""
    global _connection  

    if _connection is not None:
        _connection.close()
        _connection = None
        log.info("db_closed")
