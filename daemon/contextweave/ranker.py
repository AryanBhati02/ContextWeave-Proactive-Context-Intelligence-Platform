"""Ranker — semantic + recency + graph-proximity scoring for code chunks.

Score formula (Upgrade B)::

    score = (semantic_weight × semantic_score)
          + (recency_weight  × recency_score)
          + (graph_weight    × graph_score)

Where:

* ``semantic_score = 1.0 - cosine_distance``  (sqlite-vec returns distance)
* ``recency_score  = exp(-λ × hours_since_last_seen)``
* ``graph_score    = 1.0 | 0.5 | 0.0``  (import-graph hop proximity)
* ``λ = ln(2) / recency_half_life_hours``

**Renormalisation rule**: if the import_graph table has no data (new repo,
graph not yet built), ``graph_score`` defaults to ``0.0`` for every chunk and
the semantic/recency weights are renormalised so they sum to 1.0:

    sem_w′ = semantic_weight / (semantic_weight + recency_weight)
    rec_w′ = recency_weight  / (semantic_weight + recency_weight)

Default weights (Upgrade B): semantic 0.55, recency 0.30, graph 0.15.
Default half-life: 4.0 hours.
"""

from __future__ import annotations

import math
import sqlite3
import struct
import time

import structlog

from contextweave.config import RankerConfig
from contextweave.graph import graph_has_data, graph_score as _graph_score
from contextweave.models import RankedChunk, RankResponse
from contextweave.providers.base import LLMProvider, ProviderError

log: structlog.stdlib.BoundLogger = structlog.get_logger()


def _estimate_tokens(text: str) -> int:
    """Fast token estimate: words × 1.33."""
    return max(1, int(len(text.split()) * 1.33))


async def rank(
    query: str,
    top_k: int,
    workspace_id: str,
    db: sqlite3.Connection,
    provider: LLMProvider,
    config: RankerConfig,
    current_file: str = "",
) -> RankResponse:
    """Rank code chunks by semantic similarity + recency + graph proximity.

    Never raises.  Returns an empty list if no chunks exist yet or if the
    provider is unreachable.

    Parameters
    ----------
    query:
        Natural-language search query.
    top_k:
        Maximum number of chunks to return (clamped 1–20 by caller).
    workspace_id:
        Workspace scope for filtering chunks.
    db:
        SQLite connection with chunks + chunk_vectors + import_graph tables.
    provider:
        LLM provider for embedding the query.
    config:
        Ranker weights and limits from config.
    current_file:
        The file the developer is currently editing. Used as the BFS origin
        for the graph proximity score. Empty string disables graph scoring.
    """
    try:
        return await _rank_inner(
            query, top_k, workspace_id, db, provider, config, current_file
        )
    except Exception:
        log.error("ranker_unexpected_error", query=query, exc_info=True)
        return RankResponse(query=query, chunks=[], total_tokens=0)


async def _rank_inner(
    query: str,
    top_k: int,
    workspace_id: str,
    db: sqlite3.Connection,
    provider: LLMProvider,
    config: RankerConfig,
    current_file: str,
) -> RankResponse:
    """Core ranking logic — 3-term formula."""
    now: float = time.time()

    
    
    
    use_graph: bool = bool(current_file) and graph_has_data(db)

    
    if use_graph:
        sem_w = config.semantic_weight
        rec_w = config.recency_weight
        gph_w = getattr(config, "graph_weight", 0.15)
    else:
        
        base = config.semantic_weight + config.recency_weight
        sem_w = config.semantic_weight / base if base > 0 else 0.55
        rec_w = config.recency_weight / base if base > 0 else 0.45
        gph_w = 0.0

    
    try:
        embed_result = await provider.embed(query)
    except ProviderError as exc:
        log.warning("ranker_embed_failed", error=str(exc))
        return RankResponse(query=query, chunks=[], total_tokens=0)

    query_embedding: list[float] = embed_result.embedding
    embedding_blob: bytes = struct.pack(f"{len(query_embedding)}f", *query_embedding)

    
    try:
        ann_rows = db.execute(
            "SELECT v.rowid, v.distance "
            "FROM chunk_vectors v "
            "JOIN chunks c ON c.rowid = v.rowid "
            "WHERE v.embedding MATCH ? "
            "AND v.k = ? "
            "AND c.workspace_id = ? "
            "ORDER BY v.distance",
            (embedding_blob, config.candidate_pool, workspace_id),
        ).fetchall()
    except sqlite3.OperationalError:
        log.warning("ranker_ann_search_failed", exc_info=True)
        return RankResponse(query=query, chunks=[], total_tokens=0)

    if not ann_rows:
        return RankResponse(query=query, chunks=[], total_tokens=0)

    
    lambda_decay: float = math.log(2) / config.recency_half_life_hours
    scored: list[tuple[RankedChunk, float]] = []

    for ann_row in ann_rows:
        rowid: int = ann_row[0] if isinstance(ann_row, tuple) else ann_row["rowid"]
        distance: float = ann_row[1] if isinstance(ann_row, tuple) else ann_row["distance"]

        chunk_row = db.execute(
            "SELECT id, chunk_name, file_path, language, start_line, end_line, "
            "content, last_seen FROM chunks WHERE rowid = ? AND workspace_id = ?",
            (rowid, workspace_id),
        ).fetchone()

        if chunk_row is None:
            continue

        if isinstance(chunk_row, tuple):
            cid, cname, fpath, lang, sl, el, content, last_seen = chunk_row
        else:
            cid = chunk_row["id"]
            cname = chunk_row["chunk_name"]
            fpath = chunk_row["file_path"]
            lang = chunk_row["language"]
            sl = chunk_row["start_line"]
            el = chunk_row["end_line"]
            content = chunk_row["content"]
            last_seen = chunk_row["last_seen"]

        
        semantic_score: float = max(0.0, min(1.0, 1.0 - distance))
        hours_ago: float = max(0.0, (now - last_seen) / 3600.0)
        recency_score: float = math.exp(-lambda_decay * hours_ago)
        g_score: float = (
            _graph_score(current_file, fpath, db) if use_graph else 0.0
        )

        combined: float = (
            sem_w * semantic_score
            + rec_w * recency_score
            + gph_w * g_score
        )

        ranked = RankedChunk(
            id=cid,
            chunk_name=cname,
            file_path=fpath,
            language=lang,
            start_line=sl,
            end_line=el,
            content=content,
            score=round(combined, 4),
            semantic_score=round(semantic_score, 4),
            recency_score=round(recency_score, 4),
            graph_score=round(g_score, 4),
        )
        scored.append((ranked, combined))

    
    scored.sort(key=lambda x: x[1], reverse=True)

    
    top_chunks: list[RankedChunk] = [s[0] for s in scored[:top_k]]

    
    
    total_tokens: int = sum(_estimate_tokens(c.content) for c in top_chunks)

    while total_tokens > config.max_context_tokens and len(top_chunks) > 1:
        removed: RankedChunk = top_chunks.pop()
        total_tokens -= _estimate_tokens(removed.content)

    
    for chunk in top_chunks:
        try:
            db.execute(
                "INSERT OR IGNORE INTO access_log (chunk_id, accessed_at) VALUES (?, ?)",
                (chunk.id, now),
            )
        except sqlite3.IntegrityError:
            pass
    try:
        db.commit()
    except sqlite3.Error:
        log.warning("ranker_access_log_commit_failed", exc_info=True)

    log.info(
        "rank_complete",
        query=query,
        candidates=len(ann_rows),
        returned=len(top_chunks),
        total_tokens=total_tokens,
        use_graph=use_graph,
        workspace_id=workspace_id,
    )

    return RankResponse(
        query=query,
        chunks=top_chunks,
        total_tokens=total_tokens,
    )
