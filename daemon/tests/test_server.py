"""Tests for contextweave.server — health, stubs, shutdown behaviour."""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient


async def _wait_for_chunk_rows(file_path: str) -> list[dict]:
    """Wait briefly for embed workers to persist chunks for a file."""
    from contextweave import server  

    assert server._db is not None
    for _ in range(20):
        rows = server._db.execute(
            "SELECT chunk_name, chunk_type, language FROM chunks "
            "WHERE file_path = ? ORDER BY chunk_name",
            (file_path,),
        ).fetchall()
        if rows:
            return [dict(row) for row in rows]
        await asyncio.sleep(0.05)
    return []


class TestHealth:
    """GET /health endpoint tests."""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client: AsyncClient) -> None:
        """Health endpoint always returns HTTP 200."""
        response = await client.get("/health")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_returns_all_required_fields(self, client: AsyncClient) -> None:
        """Response body contains every field defined in HealthResponse."""
        response = await client.get("/health")
        data: dict = response.json()

        required_fields: set[str] = {
            "status",
            "version",
            "queue_depth",
            "provider_healthy",
            "db_healthy",
            "chunks_total",
        }
        assert required_fields.issubset(data.keys())

    @pytest.mark.asyncio
    async def test_health_status_is_ok_or_degraded(self, client: AsyncClient) -> None:
        """Status field is always one of 'ok' or 'degraded'."""
        response = await client.get("/health")
        data: dict = response.json()

        assert data["status"] in ("ok", "degraded")

    @pytest.mark.asyncio
    async def test_health_version_matches(self, client: AsyncClient) -> None:
        """Version in health response matches the package version."""
        response = await client.get("/health")
        data: dict = response.json()

        assert data["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_health_never_returns_500(self, client: AsyncClient) -> None:
        """Health must never return a 5xx even if DB is broken."""
        from contextweave import server

        
        original_db = server._db
        server._db = None

        try:
            response = await client.get("/health")
            assert response.status_code == 200
            assert response.json()["status"] == "degraded"
        finally:
            server._db = original_db

    @pytest.mark.asyncio
    async def test_health_db_healthy_true_with_valid_db(self, client: AsyncClient) -> None:
        """db_healthy is True when the test DB is properly initialised."""
        response = await client.get("/health")
        data: dict = response.json()

        assert data["db_healthy"] is True

    @pytest.mark.asyncio
    async def test_health_provider_healthy_with_mock(self, client: AsyncClient) -> None:
        """provider_healthy is True when a working provider is configured."""
        response = await client.get("/health")
        data: dict = response.json()

        assert data["provider_healthy"] is True


class TestIngest:
    """POST /ingest endpoint tests."""

    @pytest.mark.asyncio
    async def test_ingest_returns_queued(self, client: AsyncClient) -> None:
        """POST /ingest chunks the file and returns status='queued'."""
        response = await client.post(
            "/ingest",
            json={
                "file_path": "/a.py",
                "content": "def hello():\n    x = 1\n    return x",
                "language": "python",
            },
        )

        assert response.status_code == 200
        data: dict = response.json()
        assert data["status"] == "queued"
        assert data["chunks"] >= 1
        assert data["stuck"] is False

    @pytest.mark.asyncio
    async def test_ingest_rejects_unsupported_language(self, client: AsyncClient) -> None:
        """POST /ingest returns 422 for unsupported languages."""
        response = await client.post(
            "/ingest",
            json={"file_path": "/a.rb", "content": "def main; end", "language": "ruby"},
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_ingest_accepts_go(self, client: AsyncClient) -> None:
        """POST /ingest accepts Go files and queues their chunks."""
        response = await client.post(
            "/ingest",
            json={
                "file_path": "/main.go",
                "content": "package main\n\nfunc Add(a int, b int) int {\n    total := a + b\n    return total\n}",
                "language": "go",
            },
        )

        assert response.status_code == 200
        data: dict = response.json()
        assert data["status"] == "queued"
        assert data["chunks"] == 1
        rows: list[dict] = await _wait_for_chunk_rows("/main.go")
        assert rows == [
            {"chunk_name": "Add", "chunk_type": "function", "language": "go"},
        ]

    @pytest.mark.asyncio
    async def test_ingest_accepts_rust(self, client: AsyncClient) -> None:
        """POST /ingest accepts Rust files and persists impl method chunks."""
        response = await client.post(
            "/ingest",
            json={
                "file_path": "/counter.rs",
                "content": (
                    "struct Counter { value: i32 }\n\n"
                    "impl Counter {\n"
                    "    fn inc(&mut self, delta: i32) -> i32 {\n"
                    "        self.value += delta;\n"
                    "        self.value\n"
                    "    }\n"
                    "}"
                ),
                "language": "rust",
            },
        )

        assert response.status_code == 200
        data: dict = response.json()
        assert data["status"] == "queued"
        assert data["chunks"] == 1
        rows: list[dict] = await _wait_for_chunk_rows("/counter.rs")
        assert rows == [
            {"chunk_name": "Counter::inc", "chunk_type": "method", "language": "rust"},
        ]

    @pytest.mark.asyncio
    async def test_ingest_rejects_oversized_file(self, client: AsyncClient) -> None:
        """POST /ingest returns 413 for files exceeding max_file_size_kb."""
        huge_content: str = "x = 1\n" * 200_000  
        response = await client.post(
            "/ingest",
            json={"file_path": "/big.py", "content": huge_content, "language": "python"},
        )

        assert response.status_code == 413

    @pytest.mark.asyncio
    async def test_rank_returns_200_for_valid_query(self, client: AsyncClient) -> None:
        """GET /rank returns 200 with empty chunks when DB has no data."""
        response = await client.get("/rank", params={"q": "test query"})

        assert response.status_code == 200
        data: dict = response.json()
        assert data["query"] == "test query"
        assert data["chunks"] == []
        assert data["total_tokens"] == 0

    @pytest.mark.asyncio
    async def test_rank_returns_400_for_empty_query(self, client: AsyncClient) -> None:
        """GET /rank returns 400 when query is empty or whitespace."""
        response = await client.get("/rank", params={"q": ""})
        assert response.status_code == 400

        response2 = await client.get("/rank", params={"q": "   "})
        assert response2.status_code == 400

    @pytest.mark.asyncio
    async def test_stuck_dismiss_stub(self, client: AsyncClient) -> None:
        """POST /stuck/dismiss returns reset=true."""
        response = await client.post("/stuck/dismiss")

        assert response.status_code == 200
        assert response.json()["reset"] is True

    @pytest.mark.asyncio
    async def test_status_returns_uptime(self, client: AsyncClient) -> None:
        """GET /status returns uptime and counters."""
        response = await client.get("/status")

        assert response.status_code == 200
        data: dict = response.json()
        assert data["uptime_seconds"] >= 0
        assert "chunks_ingested_total" in data
        assert "rank_calls_total" in data
        assert data["provider"] == "ollama"
        assert data["queue_depth"] >= 0


class TestShutdownBehaviour:
    """Endpoints return 503 when the daemon is shutting down."""

    @pytest.mark.asyncio
    async def test_ingest_503_during_shutdown(self, client: AsyncClient) -> None:
        """POST /ingest returns 503 when _shutting_down is True."""
        from contextweave import server

        server._shutting_down = True
        try:
            response = await client.post(
                "/ingest",
                json={"file_path": "/a.py", "content": "x", "language": "python"},
            )
            assert response.status_code == 503
        finally:
            server._shutting_down = False

    @pytest.mark.asyncio
    async def test_rank_503_during_shutdown(self, client: AsyncClient) -> None:
        """GET /rank returns 503 when _shutting_down is True."""
        from contextweave import server

        server._shutting_down = True
        try:
            response = await client.get("/rank", params={"q": "x"})
            assert response.status_code == 503
        finally:
            server._shutting_down = False
