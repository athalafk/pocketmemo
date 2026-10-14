"""End-to-end tests of the SQLite backend: adaptive Embedding/JSON columns,
brute-force vector search, and foreign-key enforcement."""

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from pocketmemo.database import DIALECT, SessionLocal, engine
from pocketmemo.db.search import nearest_neighbors
from pocketmemo.models import Base, Memory, User
from pocketmemo.services import conversation, memory


@pytest_asyncio.fixture
async def schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


async def test_backend_is_sqlite():
    assert DIALECT == "sqlite"


async def test_embedding_roundtrip_and_nearest_neighbors(schema):
    async with SessionLocal() as session:
        user = User(telegram_id=1, language="en")
        session.add(user)
        await session.flush()
        session.add_all(
            [
                Memory(user_id=user.id, content="parked at B17", embedding=[1.0, 0.0, 0.0, 0.0]),
                Memory(user_id=user.id, content="cat is named Milo", embedding=[0.0, 1.0, 0.0, 0.0]),
                Memory(user_id=user.id, content="parked at A28", embedding=[0.96, 0.1, 0.0, 0.0]),
            ]
        )
        await session.commit()

    async with SessionLocal() as session:
        rows = await nearest_neighbors(
            session, Memory, [1.0, 0.0, 0.0, 0.0], user_id=1, limit=3
        )

    contents = [m.content for m, _ in rows]
    assert contents[0] == "parked at B17"          # closest
    assert rows[-1][0].content == "cat is named Milo"  # farthest

    # Embedding survived the JSON round-trip as a list of floats.
    assert isinstance(rows[0][0].embedding, list)
    assert rows[0][0].embedding[0] == pytest.approx(1.0)
    # json_type column round-trips to a dict.
    assert isinstance(rows[0][0].extra_data, dict)


async def test_foreign_keys_are_enforced(schema):
    """The SQLite PRAGMA must reject a child row with no parent user."""
    with pytest.raises(IntegrityError):
        async with SessionLocal() as session:
            session.add(Memory(user_id=999999, content="orphan"))
            await session.commit()


async def test_agent_memory_retrieval_filters_distance_and_owner(schema, monkeypatch):
    async with SessionLocal() as session:
        owner = User(telegram_id=101, language="en")
        other = User(telegram_id=102, language="en")
        session.add_all([owner, other])
        await session.flush()
        session.add_all([
            Memory(user_id=owner.id, content="near", embedding=[1.0, 0.0, 0.0, 0.0]),
            Memory(user_id=owner.id, content="far", embedding=[0.0, 1.0, 0.0, 0.0]),
            Memory(user_id=owner.id, content="no embedding"),
            Memory(user_id=other.id, content="other user's fact", embedding=[1.0, 0.0, 0.0, 0.0]),
        ])
        await session.commit()
    embed = AsyncMock(return_value=[1.0, 0.0, 0.0, 0.0])
    monkeypatch.setattr(memory.llm, "embed_query", embed)

    rows = await memory.search_memories(owner, " query ", limit=5)

    assert [row.content for row in rows] == ["near"]
    embed.assert_awaited_once_with("query")
    assert await memory.search_memories(owner, "query", limit=0) == []
    assert await memory.search_memories(owner, "  ") == []
    assert embed.await_count == 1


async def test_memory_delete_cuts_off_only_owners_history(schema):
    async with SessionLocal() as session:
        owner = User(telegram_id=201, language="en")
        other = User(telegram_id=202, language="en")
        session.add_all([owner, other])
        await session.flush()
        fact = Memory(user_id=owner.id, content="old fact")
        session.add(fact)
        await session.commit()
    await conversation.save_turn(owner.id, "user", "old question")
    await conversation.save_turn(owner.id, "assistant", "old fact")
    await conversation.save_turn(other.id, "user", "unrelated question")

    await memory.delete_memory(other, fact.id)
    assert len(await conversation.get_recent_history(owner.id)) == 2
    await memory.delete_memory(owner, fact.id)

    assert await memory.get_all_memories(owner) == []
    assert await conversation.get_recent_history(owner.id) == []
    assert await conversation.get_recent_history(other.id) == [
        {"role": "user", "content": "unrelated question"},
    ]
