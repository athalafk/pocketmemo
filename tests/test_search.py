"""Pure-math tests for the cosine-distance used by the SQLite vector search."""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.dialects import postgresql

from pocketmemo.db.search import cosine_distance
from pocketmemo.db import search
from pocketmemo.services import memory


def test_identical_vectors_distance_zero():
    assert cosine_distance([1, 2, 3], [1, 2, 3]) == pytest.approx(0.0, abs=1e-9)


def test_orthogonal_vectors_distance_one():
    assert cosine_distance([1, 0], [0, 1]) == pytest.approx(1.0)


def test_opposite_vectors_distance_two():
    assert cosine_distance([1, 0], [-1, 0]) == pytest.approx(2.0)


def test_zero_vector_is_safe():
    # No division-by-zero; treated as maximally dissimilar.
    assert cosine_distance([0, 0], [1, 1]) == 1.0


def test_closer_vector_has_smaller_distance():
    query = [1.0, 0.0]
    near = cosine_distance(query, [0.9, 0.1])
    far = cosine_distance(query, [0.1, 0.9])
    assert near < far


async def test_agent_retrieval_uses_scoped_postgresql_vector_query(monkeypatch):
    near = SimpleNamespace(content="relevant fact")
    far = SimpleNamespace(content="unrelated fact")
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        all=lambda: [(near, 0.1), (far, 0.9)],
    )))
    session_context = AsyncMock()
    session_context.__aenter__.return_value = session
    monkeypatch.setattr(search, "DIALECT", "postgresql")
    monkeypatch.setattr(memory, "SessionLocal", MagicMock(return_value=session_context))
    monkeypatch.setattr(memory.llm, "embed_query", AsyncMock(return_value=[1.0, 0.0, 0.0, 0.0]))

    rows = await memory.search_memories(SimpleNamespace(id=17), "fact", limit=3)

    assert rows == [near]
    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "<=>" in str(compiled)
    assert "IS NOT NULL" in str(compiled)
    assert "LIMIT" in str(compiled)
    assert compiled.params["user_id_1"] == 17
    assert 3 in compiled.params.values()
