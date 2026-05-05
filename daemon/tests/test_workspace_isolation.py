"""Tests for multi-workspace chunk and rank isolation."""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient


async def _wait_for_workspace_rows(expected_count: int) -> list[dict]:
    """Wait briefly for embed workers to persist expected workspace rows."""
    from contextweave import server  

    assert server._db is not None
    for _ in range(40):
        rows = server._db.execute(
            "SELECT id, file_path, chunk_name, workspace_id FROM chunks "
            "ORDER BY workspace_id, file_path, chunk_name"
        ).fetchall()
        if len(rows) >= expected_count:
            return [dict(row) for row in rows]
        await asyncio.sleep(0.05)
    return [dict(row) for row in rows]


def _function_source(name: str, value: int) -> str:
    """Return a three-line Python function for ingestion."""
    return f"def {name}():\n    value = {value}\n    return value"


@pytest.mark.asyncio
async def test_workspace_isolation_chunks_from_different_workspaces_dont_mix(
    client: AsyncClient,
) -> None:
    """Chunks from different workspace IDs are persisted in separate scopes."""
    await client.post(
        "/ingest",
        json={
            "file_path": "/workspace-a/app.py",
            "content": _function_source("alpha", 1),
            "language": "python",
            "workspace_id": "workspace_a",
        },
    )
    await client.post(
        "/ingest",
        json={
            "file_path": "/workspace-b/app.py",
            "content": _function_source("beta", 2),
            "language": "python",
            "workspace_id": "workspace_b",
        },
    )

    rows: list[dict] = await _wait_for_workspace_rows(2)

    assert {row["workspace_id"] for row in rows} == {"workspace_a", "workspace_b"}
    assert {
        (row["workspace_id"], row["file_path"], row["chunk_name"]) for row in rows
    } == {
        ("workspace_a", "/workspace-a/app.py", "alpha"),
        ("workspace_b", "/workspace-b/app.py", "beta"),
    }


@pytest.mark.asyncio
async def test_workspace_isolation_rank_only_returns_chunks_from_same_workspace(
    client: AsyncClient,
) -> None:
    """Rank results are filtered to the requested workspace_id."""
    await client.post(
        "/ingest",
        json={
            "file_path": "/workspace-a/search.py",
            "content": _function_source("shared_query_a", 10),
            "language": "python",
            "workspace_id": "rank_a",
        },
    )
    await client.post(
        "/ingest",
        json={
            "file_path": "/workspace-b/search.py",
            "content": _function_source("shared_query_b", 20),
            "language": "python",
            "workspace_id": "rank_b",
        },
    )
    await _wait_for_workspace_rows(2)

    response = await client.get(
        "/rank",
        params={"q": "shared query", "top_k": 8, "workspace_id": "rank_a"},
    )

    assert response.status_code == 200
    chunks: list[dict] = response.json()["chunks"]
    assert chunks
    assert {chunk["file_path"] for chunk in chunks} == {"/workspace-a/search.py"}


@pytest.mark.asyncio
async def test_workspace_id_defaults_to_default_when_not_specified(
    client: AsyncClient,
) -> None:
    """Ingest requests without workspace_id keep the existing default scope."""
    response = await client.post(
        "/ingest",
        json={
            "file_path": "/default/app.py",
            "content": _function_source("default_scope", 3),
            "language": "python",
        },
    )

    assert response.status_code == 200
    rows: list[dict] = await _wait_for_workspace_rows(1)
    assert rows == [
        {
            "id": rows[0]["id"],
            "file_path": "/default/app.py",
            "chunk_name": "default_scope",
            "workspace_id": "default",
        }
    ]


@pytest.mark.asyncio
async def test_multiple_workspaces_can_ingest_same_file_path_independently(
    client: AsyncClient,
) -> None:
    """The same file path and chunk name can exist in multiple workspaces."""
    file_path = "/shared/path/app.py"
    content = _function_source("same_name", 4)

    await client.post(
        "/ingest",
        json={
            "file_path": file_path,
            "content": content,
            "language": "python",
            "workspace_id": "same_a",
        },
    )
    await client.post(
        "/ingest",
        json={
            "file_path": file_path,
            "content": content,
            "language": "python",
            "workspace_id": "same_b",
        },
    )

    rows: list[dict] = await _wait_for_workspace_rows(2)

    assert len(rows) == 2
    assert {row["workspace_id"] for row in rows} == {"same_a", "same_b"}
    assert {row["file_path"] for row in rows} == {file_path}
    assert {row["chunk_name"] for row in rows} == {"same_name"}
    assert len({row["id"] for row in rows}) == 2
