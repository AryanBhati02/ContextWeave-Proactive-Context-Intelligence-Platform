"""FastAPI application — the ContextWeave daemon HTTP surface.

Lifecycle
---------
* **Startup**: load config → create provider → init DB → start embed workers.
* **Shutdown**: set ``_shutting_down`` → drain embed queue → close DB.

When ``_shutting_down`` is ``True`` the mutable endpoints (``/ingest``,
``/rank``) return **503 Service Unavailable**.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import structlog
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from contextweave import __version__
from contextweave.chunker import chunk_file
from contextweave.config import Config, load_config
from contextweave.db import init_db
from contextweave.gc import (
    run_gc_sweep,
    start_gc_background_task,
    stop_gc_background_task,
)
from contextweave.models import (
    DismissResponse,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    RankResponse,
    StatusResponse,
)
from contextweave.providers import create_provider
from contextweave.providers.base import LLMProvider
from contextweave import embedder
from contextweave import ranker as ranker_mod
from contextweave import stuck_detector
from contextweave.graph import extract_imports, update_graph




_db: "import('sqlite3').Connection | None" = None  
_config: Config | None = None
_provider: LLMProvider | None = None
_shutting_down: bool = False
_start_time: float = 0.0
_chunks_ingested_total: int = 0
_rank_calls_total: int = 0

_SUPPORTED_LANGUAGES: frozenset[str] = frozenset(
    {"python", "typescript", "javascript", "go", "rust"}
)

log: structlog.stdlib.BoundLogger = structlog.get_logger()






def _configure_logging(level_name: str) -> None:
    """Configure *structlog* and stdlib logging to *level_name*."""
    level: int = getattr(logging, level_name.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        level=level,
        force=True,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.WriteLoggerFactory(),
        cache_logger_on_first_use=True,
    )






@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup → yield → shutdown."""
    global _db, _config, _provider, _shutting_down, _start_time  
    global _chunks_ingested_total, _rank_calls_total  

    _start_time = time.time()
    _chunks_ingested_total = 0
    _rank_calls_total = 0

    
    if _config is None:
        _config = load_config()

    _configure_logging(_config.daemon.log_level)

    
    if _provider is None:
        _provider = create_provider(_config)

    
    if _db is None:
        db_path: Path = Path.home() / ".contextweave" / "memory.db"
        _db = init_db(db_path)

    
    await embedder.start_workers(
        _provider,
        _db,
        n=2,
        max_queue_size=_config.daemon.max_queue_size,
    )
    await start_gc_background_task(_db, interval_hours=24.0)

    log.info(
        "daemon_started",
        version=__version__,
        host=_config.daemon.host,
        port=_config.daemon.port,
        provider=_config.provider.embed_provider,
    )

    yield  

    
    _shutting_down = True
    log.info("daemon_shutting_down")
    await stop_gc_background_task()
    await embedder.drain_and_stop(
        timeout_s=_config.daemon.shutdown_drain_timeout_s,
    )
    if _db is not None:
        _db.close()
        _db = None
    log.info("daemon_stopped")





app: FastAPI = FastAPI(
    title="ContextWeave",
    version=__version__,
    lifespan=_lifespan,
)






@app.middleware("http")
async def _log_requests(request: Request, call_next: object) -> JSONResponse:  
    """Log every request with method, path, status, and duration."""
    start: float = time.time()
    response = await call_next(request)  
    duration_ms: float = round((time.time() - start) * 1000, 2)
    log.debug(
        "request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )
    return response  






@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health probe — always returns 200, never 500."""
    db_healthy: bool = False
    chunks_total: int = 0
    provider_healthy: bool = False

    try:
        if _db is not None:
            cursor = _db.execute("SELECT COUNT(*) FROM chunks")
            row = cursor.fetchone()
            chunks_total = row[0] if row else 0
            db_healthy = True
    except Exception:
        log.warning("health_check_db_query_failed", exc_info=True)

    try:
        if _provider is not None:
            provider_healthy = await _provider.health_check()
    except Exception:
        pass

    status: str = "ok" if db_healthy else "degraded"
    depth: int = await embedder.queue_depth()

    return HealthResponse(
        status=status,
        version=__version__,
        queue_depth=depth,
        provider_healthy=provider_healthy,
        db_healthy=db_healthy,
        chunks_total=chunks_total,
    )


@app.post("/ingest", response_model=IngestResponse)
async def ingest(body: IngestRequest) -> IngestResponse | JSONResponse:
    """Ingest a source file: chunk it, enqueue for embedding, check stuck state."""
    global _chunks_ingested_total  

    if _shutting_down:
        return JSONResponse(
            status_code=503,
            content={"detail": "shutting_down"},
        )

    
    max_bytes: int = (_config.daemon.max_file_size_kb * 1024) if _config else 512_000
    if len(body.content.encode("utf-8")) > max_bytes:
        log.warning("ingest_file_too_large", file_path=body.file_path)
        return JSONResponse(
            status_code=413,
            content={"detail": "file_too_large"},
        )

    
    if body.language not in _SUPPORTED_LANGUAGES:
        return JSONResponse(
            status_code=422,
            content={"detail": f"unsupported language: {body.language}"},
        )

    
    chunks = chunk_file(body.file_path, body.content, body.language)

    
    for chunk in chunks:
        await embedder.enqueue(chunk, workspace_id=body.workspace_id)

    _chunks_ingested_total += len(chunks)

    
    if _db is not None:
        imports = extract_imports(body.file_path, body.content, body.language)
        update_graph(body.file_path, imports, _db)

    
    is_stuck: bool = False
    if _db is not None and _config is not None:
        is_stuck = await stuck_detector.update_activity(
            file_path=body.file_path,
            content=body.content,
            db=_db,
            config=_config.stuck_detector,
            workspace_id=body.workspace_id,
        )

    return IngestResponse(status="queued", chunks=len(chunks), stuck=is_stuck)


@app.get("/rank", response_model=RankResponse)
async def rank_endpoint(
    q: str = Query(default=""),
    top_k: int = Query(default=8, ge=1, le=20),
    current_file: str = Query(default=""),
    workspace_id: str = Query(default="default"),
) -> RankResponse:
    """Rank code chunks by semantic similarity + recency + graph proximity.

    Pass ``current_file`` (the file the developer has open) to activate the
    import-graph signal — chunks from directly imported files score higher.
    """
    global _rank_calls_total  

    if _shutting_down:
        raise HTTPException(status_code=503, detail="Daemon is shutting down")

    if not q.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    if _db is None or _provider is None or _config is None:
        raise HTTPException(status_code=503, detail="Daemon not ready")

    top_k = max(1, min(20, top_k))
    _rank_calls_total += 1

    return await ranker_mod.rank(
        query=q,
        top_k=top_k,
        workspace_id=workspace_id,
        db=_db,
        provider=_provider,
        config=_config.ranker,
        current_file=current_file,
    )


@app.get("/gc")
async def trigger_gc() -> dict[str, int | float]:
    """Manually trigger a GC sweep. Returns stats."""
    if _db is None:
        raise HTTPException(status_code=503, detail="Daemon not ready")
    return await run_gc_sweep(_db)


@app.post("/stuck/dismiss", response_model=DismissResponse)
async def dismiss_stuck(
    file_path: str = Query(default=""),
    workspace_id: str = Query(default="default"),
) -> DismissResponse:
    """Reset stuck state for a file (user clicked 'Not Stuck')."""
    if _db is not None and file_path:
        await stuck_detector.reset(
            file_path=file_path,
            db=_db,
            workspace_id=workspace_id,
        )
    return DismissResponse(reset=True)


@app.get("/status", response_model=StatusResponse)
async def status() -> StatusResponse:
    """Daemon status with uptime and counters."""
    provider_name: str = (
        _config.provider.embed_provider if _config else "unknown"
    )
    uptime: float = round(time.time() - _start_time, 2)
    depth: int = await embedder.queue_depth()

    return StatusResponse(
        uptime_seconds=uptime,
        chunks_ingested_total=_chunks_ingested_total,
        rank_calls_total=_rank_calls_total,
        provider=provider_name,
        queue_depth=depth,
    )
