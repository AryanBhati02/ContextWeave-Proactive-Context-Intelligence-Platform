"""Pydantic v2 models for every API request and response type."""

from __future__ import annotations

from pydantic import BaseModel


class IngestRequest(BaseModel):
    """Body of ``POST /ingest``."""

    file_path: str
    content: str
    language: str
    workspace_id: str = "default"


class IngestResponse(BaseModel):
    """Response from ``POST /ingest``."""

    status: str
    chunks: int
    stuck: bool


class RankedChunk(BaseModel):
    """A single chunk returned by the ranker."""

    id: str
    chunk_name: str
    file_path: str
    language: str
    start_line: int
    end_line: int
    content: str
    score: float
    semantic_score: float
    recency_score: float
    graph_score: float = 0.0


class RankResponse(BaseModel):
    """Response from ``GET /rank``."""

    query: str
    chunks: list[RankedChunk]
    total_tokens: int


class HealthResponse(BaseModel):
    """Response from ``GET /health`` — must never return 500."""

    status: str
    version: str
    queue_depth: int
    provider_healthy: bool
    db_healthy: bool
    chunks_total: int


class StatusResponse(BaseModel):
    """Response from ``GET /status``."""

    uptime_seconds: float
    chunks_ingested_total: int
    rank_calls_total: int
    provider: str
    queue_depth: int


class DismissResponse(BaseModel):
    """Response from ``POST /stuck/dismiss``."""

    reset: bool
