"""Tests for contextweave.ranker — semantic + recency scoring."""

from __future__ import annotations

import asyncio
import hashlib
import math
import struct
import time

import pytest

from contextweave.config import RankerConfig
from contextweave import ranker as ranker_mod
from contextweave.models import RankResponse
from tests.conftest import MockProvider, seed_chunks


class TestRankerEmpty:
    """Ranker behaviour when the DB has no chunks."""

    @pytest.mark.asyncio
    async def test_ranker_returns_empty_list_when_no_chunks_in_db(
        self, test_db: tuple
    ) -> None:
        """rank() returns empty RankResponse when chunks table is empty."""
        conn, _ = test_db
        provider = MockProvider()
        config = RankerConfig()

        result: RankResponse = await ranker_mod.rank(
            query="some query",
            top_k=8,
            workspace_id="default",
            db=conn,
            provider=provider,
            config=config,
        )

        assert result.query == "some query"
        assert result.chunks == []
        assert result.total_tokens == 0


class TestRankerResults:
    """Ranker returns correct results when chunks exist."""

    @pytest.mark.asyncio
    async def test_ranker_returns_top_k_results(self, test_db: tuple) -> None:
        """rank() returns at most top_k chunks."""
        conn, _ = test_db
        provider = MockProvider()
        seed_chunks(conn, provider, count=10)
        config = RankerConfig()

        result: RankResponse = await ranker_mod.rank(
            query="test function",
            top_k=3,
            workspace_id="default",
            db=conn,
            provider=provider,
            config=config,
        )

        assert len(result.chunks) <= 3

    @pytest.mark.asyncio
    async def test_ranker_semantic_score_is_between_0_and_1(
        self, test_db: tuple
    ) -> None:
        """semantic_score is always in [0.0, 1.0]."""
        conn, _ = test_db
        provider = MockProvider()
        seed_chunks(conn, provider, count=5)
        config = RankerConfig()

        result: RankResponse = await ranker_mod.rank(
            query="test",
            top_k=8,
            workspace_id="default",
            db=conn,
            provider=provider,
            config=config,
        )

        for chunk in result.chunks:
            assert 0.0 <= chunk.semantic_score <= 1.0

    @pytest.mark.asyncio
    async def test_ranker_recency_score_is_1_for_just_accessed(
        self, test_db: tuple
    ) -> None:
        """Chunks seen just now have recency_score close to 1.0."""
        conn, _ = test_db
        provider = MockProvider()
        seed_chunks(conn, provider, count=3, last_seen_offset_hours=0.0)
        config = RankerConfig()

        result: RankResponse = await ranker_mod.rank(
            query="test fn",
            top_k=8,
            workspace_id="default",
            db=conn,
            provider=provider,
            config=config,
        )

        for chunk in result.chunks:
            assert chunk.recency_score > 0.99

    @pytest.mark.asyncio
    async def test_ranker_recency_score_decays_over_time(
        self, test_db: tuple
    ) -> None:
        """Chunks seen 4 hours ago have recency_score ≈ 0.5 (half-life)."""
        conn, _ = test_db
        provider = MockProvider()
        seed_chunks(conn, provider, count=3, last_seen_offset_hours=4.0)
        config = RankerConfig(recency_half_life_hours=4.0)

        result: RankResponse = await ranker_mod.rank(
            query="test fn",
            top_k=8,
            workspace_id="default",
            db=conn,
            provider=provider,
            config=config,
        )

        for chunk in result.chunks:
            
            assert 0.45 <= chunk.recency_score <= 0.55

    @pytest.mark.asyncio
    async def test_ranker_combined_score_formula_is_correct(
        self, test_db: tuple
    ) -> None:
        """Combined score = semantic_weight*semantic + recency_weight*recency."""
        conn, _ = test_db
        provider = MockProvider()
        seed_chunks(conn, provider, count=3)
        config = RankerConfig(semantic_weight=0.6, recency_weight=0.4)

        result: RankResponse = await ranker_mod.rank(
            query="test fn",
            top_k=8,
            workspace_id="default",
            db=conn,
            provider=provider,
            config=config,
        )

        for chunk in result.chunks:
            expected: float = round(
                0.6 * chunk.semantic_score + 0.4 * chunk.recency_score, 4
            )
            assert abs(chunk.score - expected) < 0.001

    @pytest.mark.asyncio
    async def test_ranker_logs_chunks_to_access_log(
        self, test_db: tuple
    ) -> None:
        """Chunks returned by rank() are recorded in access_log."""
        conn, _ = test_db
        provider = MockProvider()
        seeded = seed_chunks(conn, provider, count=3)
        config = RankerConfig()

        await ranker_mod.rank(
            query="test fn",
            top_k=8,
            workspace_id="default",
            db=conn,
            provider=provider,
            config=config,
        )

        log_count: int = conn.execute(
            "SELECT COUNT(*) FROM access_log"
        ).fetchone()[0]
        assert log_count > 0


class TestRankerTokenBudget:
    """Token budget enforcement."""

    @pytest.mark.asyncio
    async def test_ranker_enforces_token_budget(self, test_db: tuple) -> None:
        """Total tokens never exceeds max_context_tokens."""
        conn, _ = test_db
        provider = MockProvider()
        seed_chunks(conn, provider, count=10)
        
        config = RankerConfig(max_context_tokens=20)

        result: RankResponse = await ranker_mod.rank(
            query="test fn",
            top_k=10,
            workspace_id="default",
            db=conn,
            provider=provider,
            config=config,
        )

        assert result.total_tokens <= 20

    @pytest.mark.asyncio
    async def test_ranker_always_returns_at_least_1_chunk_even_over_budget(
        self, test_db: tuple
    ) -> None:
        """Even with budget=1, at least 1 chunk is returned."""
        conn, _ = test_db
        provider = MockProvider()
        seed_chunks(conn, provider, count=5)
        config = RankerConfig(max_context_tokens=1)

        result: RankResponse = await ranker_mod.rank(
            query="test fn",
            top_k=5,
            workspace_id="default",
            db=conn,
            provider=provider,
            config=config,
        )

        assert len(result.chunks) >= 1


class TestRankerValidation:
    """Input validation via the HTTP endpoint."""

    @pytest.mark.asyncio
    async def test_ranker_raises_400_for_empty_query(
        self, client: object
    ) -> None:
        """GET /rank with empty q returns HTTP 400."""
        from httpx import AsyncClient as AC

        c: AC = client  
        response = await c.get("/rank", params={"q": ""})
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_ranker_raises_400_for_whitespace_query(
        self, client: object
    ) -> None:
        """GET /rank with whitespace-only q returns HTTP 400."""
        from httpx import AsyncClient as AC

        c: AC = client  
        response = await c.get("/rank", params={"q": "   "})
        assert response.status_code == 400
