"""Tests for contextweave.graph — Upgrade B.

Covers:
  - Python import extraction
  - TypeScript import extraction
  - Syntax-error handling
  - DB edge upsert & replacement
  - graph_score: direct, 2-hop, none, circular, DB error
  - edge cases: empty file, same file self-score, missing graph table
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from contextweave.graph import (
    extract_imports,
    graph_score,
    update_graph,
    graph_has_data,
    _parse_python_imports,
    _parse_ts_imports,
)






@pytest.fixture()
def mem_db() -> sqlite3.Connection:
    """In-memory SQLite DB with the import_graph table."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE import_graph (
            source_file TEXT NOT NULL,
            target_file TEXT NOT NULL,
            updated_at  REAL NOT NULL,
            PRIMARY KEY (source_file, target_file)
        )
        """
    )
    conn.commit()
    return conn


def _seed_edges(db: sqlite3.Connection, edges: list[tuple[str, str]]) -> None:
    """Insert edges directly (bypasses update_graph for targeted test setup)."""
    now = time.time()
    for src, tgt in edges:
        db.execute(
            "INSERT OR REPLACE INTO import_graph (source_file, target_file, updated_at) "
            "VALUES (?, ?, ?)",
            (src, tgt, now),
        )
    db.commit()






def test_graph_extracts_python_imports_correctly(tmp_path: Path) -> None:
    """extract_imports returns resolved paths for standard Python imports."""
    
    pkg = tmp_path / "myapp"
    pkg.mkdir()
    (pkg / "utils.py").touch()
    (pkg / "models.py").touch()

    source = pkg / "main.py"
    content = """\
import os
import myapp.utils
from myapp import models
from myapp.models import User
"""
    source.write_text(content)

    result = extract_imports(str(source), content, "python")

    
    
    assert any("utils.py" in p for p in result), f"utils.py missing from {result}"
    assert any("models.py" in p for p in result), f"models.py missing from {result}"






def test_graph_extracts_typescript_imports_correctly() -> None:
    """extract_imports resolves relative TS imports; skips node_modules."""
    content = """\
import React from 'react';
import { useState } from 'react';
import { helper } from './utils';
import type { Config } from '../config';
"""
    
    result = extract_imports("src/components/Button.tsx", content, "typescript")

    
    assert not any("react" in p for p in result)
    
    assert any("utils" in p for p in result)
    assert any("config" in p for p in result)






def test_graph_returns_empty_list_on_syntax_error() -> None:
    """extract_imports swallows SyntaxError and returns []."""
    broken = "def foo(:\n    pass\n"
    result = extract_imports("broken.py", broken, "python")
    assert result == []






def test_graph_update_stores_edges_in_db(mem_db: sqlite3.Connection) -> None:
    """update_graph writes one row per imported file."""
    update_graph("app/main.py", ["app/utils.py", "app/models.py"], mem_db)

    rows = mem_db.execute(
        "SELECT target_file FROM import_graph WHERE source_file = 'app/main.py'"
    ).fetchall()
    targets = {r[0] for r in rows}
    assert targets == {"app/utils.py", "app/models.py"}






def test_graph_update_replaces_old_edges_on_re_ingest(
    mem_db: sqlite3.Connection,
) -> None:
    """Second call to update_graph removes stale edges from the first call."""
    update_graph("app/main.py", ["app/old.py"], mem_db)
    update_graph("app/main.py", ["app/new.py"], mem_db)

    rows = mem_db.execute(
        "SELECT target_file FROM import_graph WHERE source_file = 'app/main.py'"
    ).fetchall()
    targets = {r[0] for r in rows}

    assert "app/old.py" not in targets, "stale edge should be deleted"
    assert "app/new.py" in targets, "new edge should be present"






def test_graph_score_returns_1_for_direct_import(mem_db: sqlite3.Connection) -> None:
    """Direct import yields score 1.0."""
    _seed_edges(mem_db, [("a.py", "b.py")])
    score = graph_score("a.py", "b.py", mem_db)
    assert score == 1.0






def test_graph_score_returns_05_for_2_hop_import(mem_db: sqlite3.Connection) -> None:
    """Transitive 2-hop import yields score 0.5."""
    _seed_edges(mem_db, [("a.py", "b.py"), ("b.py", "c.py")])
    score = graph_score("a.py", "c.py", mem_db)
    assert score == 0.5






def test_graph_score_returns_0_for_no_relationship(mem_db: sqlite3.Connection) -> None:
    """Unrelated files yield score 0.0."""
    _seed_edges(mem_db, [("a.py", "b.py")])
    score = graph_score("a.py", "z.py", mem_db)
    assert score == 0.0






def test_graph_score_handles_circular_imports_without_infinite_loop(
    mem_db: sqlite3.Connection,
) -> None:
    """BFS visited-set prevents infinite loop on circular dependency graphs."""
    
    _seed_edges(mem_db, [("a.py", "b.py"), ("b.py", "c.py"), ("c.py", "a.py")])

    
    score = graph_score("a.py", "b.py", mem_db)
    assert score == 1.0  

    score2 = graph_score("a.py", "c.py", mem_db)
    assert score2 == 0.5  






def test_graph_score_returns_0_on_db_error() -> None:
    """graph_score swallows any sqlite3.Error and returns 0.0 safely."""
    bad_conn = sqlite3.connect(":memory:")
    bad_conn.close()  

    score = graph_score("a.py", "b.py", bad_conn)
    assert score == 0.0






def test_graph_has_data_returns_false_when_empty(mem_db: sqlite3.Connection) -> None:
    assert graph_has_data(mem_db) is False


def test_graph_has_data_returns_true_after_insert(mem_db: sqlite3.Connection) -> None:
    _seed_edges(mem_db, [("a.py", "b.py")])
    assert graph_has_data(mem_db) is True






def test_graph_extract_imports_unsupported_language_returns_empty() -> None:
    result = extract_imports("main.rb", "require 'rails'", "ruby")
    assert result == []






def test_graph_update_with_empty_list_clears_edges(mem_db: sqlite3.Connection) -> None:
    """Passing an empty imported_files list removes existing edges."""
    update_graph("app/main.py", ["app/utils.py"], mem_db)
    update_graph("app/main.py", [], mem_db)  

    rows = mem_db.execute(
        "SELECT * FROM import_graph WHERE source_file = 'app/main.py'"
    ).fetchall()
    assert rows == []






def test_graph_score_returns_0_when_current_file_empty(
    mem_db: sqlite3.Connection,
) -> None:
    _seed_edges(mem_db, [("a.py", "b.py")])
    score = graph_score("", "b.py", mem_db)
    assert score == 0.0






def test_graph_score_returns_0_for_same_file(mem_db: sqlite3.Connection) -> None:
    _seed_edges(mem_db, [("a.py", "a.py")])  
    score = graph_score("a.py", "a.py", mem_db)
    assert score == 0.0
