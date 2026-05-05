"""Import graph — extracts and stores file-level import edges for ranking signal.

The graph_score function returns a proximity score between two files based on
their import relationships, used as the third term in the ranker formula::

    score = (0.55 × semantic) + (0.30 × recency) + (0.15 × graph)

Score values:

* ``1.0`` — direct import (1-hop)
* ``0.5`` — transitive import (2-hop)
* ``0.0`` — no relationship within max_hops

If the import_graph table is empty, graph_score always returns 0.0 and the
caller is expected to renormalise the semantic/recency weights to 1.0.
"""

from __future__ import annotations

import ast
import re
import sqlite3
import time
from collections import deque
from pathlib import Path

import structlog

log: structlog.stdlib.BoundLogger = structlog.get_logger()






def extract_imports(file_path: str, content: str, language: str) -> list[str]:
    """Parse import statements and return resolved file paths this file imports.

    Returns an empty list on any failure — never raises.

    Parameters
    ----------
    file_path:
        Path of the source file being parsed (used for relative resolution).
    content:
        Raw source text.
    language:
        One of ``"python"``, ``"typescript"``, ``"javascript"``.
    """
    try:
        if language == "python":
            return _parse_python_imports(file_path, content)
        if language in ("typescript", "javascript"):
            return _parse_ts_imports(file_path, content)
        return []
    except Exception:
        log.warning(
            "graph_extract_imports_error",
            file_path=file_path,
            language=language,
            exc_info=True,
        )
        return []


def update_graph(
    source_file: str,
    imported_files: list[str],
    db: sqlite3.Connection,
) -> None:
    """Upsert edges in the import_graph table.

    Deletes all existing edges for *source_file* then inserts the new set.
    Called on every ingest event so the graph stays current.

    Never raises — failures are logged and silently swallowed.
    """
    try:
        now = time.time()
        db.execute(
            "DELETE FROM import_graph WHERE source_file = ?",
            (source_file,),
        )
        for target in imported_files:
            db.execute(
                "INSERT OR REPLACE INTO import_graph "
                "(source_file, target_file, updated_at) VALUES (?, ?, ?)",
                (source_file, target, now),
            )
        db.commit()
        log.debug(
            "graph_updated",
            source_file=source_file,
            edge_count=len(imported_files),
        )
    except Exception:
        log.warning("graph_update_failed", source_file=source_file, exc_info=True)


def graph_score(
    current_file: str,
    candidate_file: str,
    db: sqlite3.Connection,
    max_hops: int = 2,
) -> float:
    """Return the import-graph proximity score between two files.

    Uses BFS up to *max_hops* depth starting from *current_file*.

    Parameters
    ----------
    current_file:
        The file the developer is currently editing (BFS origin).
    candidate_file:
        The file containing the candidate chunk being scored.
    db:
        Open SQLite connection that holds the import_graph table.
    max_hops:
        Maximum BFS depth (default 2).

    Returns
    -------
    float
        ``1.0`` direct import, ``0.5`` 2-hop, ``0.0`` otherwise.
        Always ``0.0`` on any error.
    """
    if not current_file or not candidate_file:
        return 0.0
    if current_file == candidate_file:
        return 0.0
    try:
        return _bfs_score(current_file, candidate_file, db, max_hops)
    except Exception:
        log.warning(
            "graph_score_error",
            current_file=current_file,
            candidate_file=candidate_file,
            exc_info=True,
        )
        return 0.0


def graph_has_data(db: sqlite3.Connection) -> bool:
    """Return True if the import_graph table contains at least one edge."""
    try:
        row = db.execute("SELECT 1 FROM import_graph LIMIT 1").fetchone()
        return row is not None
    except Exception:
        return False






def _bfs_score(
    current_file: str,
    candidate_file: str,
    db: sqlite3.Connection,
    max_hops: int,
) -> float:
    """BFS from current_file; return score based on hop distance to candidate."""
    visited: set[str] = {current_file}
    
    queue: deque[tuple[str, int]] = deque([(current_file, 0)])

    while queue:
        node, hops = queue.popleft()
        if hops >= max_hops:
            continue

        try:
            rows = db.execute(
                "SELECT target_file FROM import_graph WHERE source_file = ?",
                (node,),
            ).fetchall()
        except sqlite3.Error:
            return 0.0

        for row in rows:
            target: str = row[0] if isinstance(row, tuple) else row["target_file"]

            if target == candidate_file:
                distance = hops + 1
                return 1.0 if distance == 1 else 0.5

            if target not in visited:
                visited.add(target)
                queue.append((target, hops + 1))

    return 0.0






def _parse_python_imports(file_path: str, content: str) -> list[str]:
    """Parse Python import statements and resolve to file paths (best-effort)."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    module_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module_names.append(node.module)

    return _resolve_to_paths(file_path, module_names)


def _resolve_to_paths(file_path: str, module_names: list[str]) -> list[str]:
    """Convert Python module names to file paths (best-effort, never raises)."""
    source_path = Path(file_path)
    source_dir = source_path.parent

    
    root_candidates: list[Path] = [source_dir]
    p = source_dir
    for _ in range(6):
        parent = p.parent
        if parent == p:
            break
        root_candidates.append(parent)
        p = parent

    resolved: list[str] = []
    for module in module_names:
        
        rel_path = module.replace(".", "/") + ".py"

        found = False
        for root in root_candidates:
            candidate = root / rel_path
            if candidate.exists():
                resolved.append(str(candidate))
                found = True
                break

        if not found and not source_path.is_absolute():
            
            
            resolved.append(rel_path)
        

    return resolved






def _parse_ts_imports(file_path: str, content: str) -> list[str]:
    """Parse TS/JS import statements and resolve relative specifiers."""
    pattern = r"""(?:import|from)\s+['"]([^'"]+)['"]"""
    matches = re.findall(pattern, content)
    return _resolve_ts_paths(file_path, matches)


def _resolve_ts_paths(file_path: str, import_specs: list[str]) -> list[str]:
    """Resolve TypeScript import specifiers to file paths."""
    source_path = Path(file_path)
    source_dir = source_path.parent

    resolved: list[str] = []
    for spec in import_specs:
        if not spec.startswith("."):
            
            continue

        candidate_base = (source_dir / spec).resolve()

        
        matched = False
        for ext in ("", ".ts", ".tsx", ".js", ".jsx"):
            p = Path(str(candidate_base) + ext)
            if p.exists():
                resolved.append(str(p))
                matched = True
                break

        if not matched:
            
            if not source_path.is_absolute():
                
                resolved.append(str(source_dir / spec) + ".ts")
            else:
                resolved.append(str(candidate_base) + ".ts")

    return resolved
