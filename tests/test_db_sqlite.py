"""End-to-end tests of the SQLite backend: adaptive Embedding/JSON columns,
brute-force vector search, and foreign-key enforcement."""

import pytest
import pytest_asyncio

from pocketmemo.database import DIALECT, SessionLocal, engine
from pocketmemo.db.search import nearest_neighbors
from pocketmemo.models import Base, Memory, User


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
    with pytest.raises(Exception):
        async with SessionLocal() as session:
            session.add(Memory(user_id=999999, content="orphan"))
            await session.commit()
