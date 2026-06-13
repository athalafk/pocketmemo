"""Backend-agnostic nearest-neighbor search over embedding columns.

On PostgreSQL this defers to pgvector's ``<=>`` cosine-distance operator (with the
ivfflat index). On SQLite (or any non-pgvector backend) it loads the user's candidate
rows and ranks them by cosine distance in Python — perfectly fine for the small,
single-user data sizes of a local install.
"""

from __future__ import annotations

import math
from typing import Sequence

from sqlalchemy import select

from pocketmemo.database import DIALECT


def cosine_distance(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine distance (1 - cosine similarity), matching pgvector's ``<=>``."""
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 1.0
    return 1.0 - dot / (math.sqrt(na) * math.sqrt(nb))


async def nearest_neighbors(session, model, query_embedding, *, user_id: int, limit: int):
    """Return up to ``limit`` ``(row, distance)`` tuples for ``model``, ascending by
    cosine distance, scoped to ``user_id`` and rows that have an embedding."""
    if DIALECT == "postgresql":
        dist = model.embedding.cosine_distance(query_embedding).label("dist")
        stmt = (
            select(model, dist)
            .where(model.user_id == user_id, model.embedding.is_not(None))
            .order_by(dist)
            .limit(limit)
        )
        rows = (await session.execute(stmt)).all()
        return [(obj, (float(d) if d is not None else None)) for obj, d in rows]

    # SQLite / others: brute-force in Python.
    stmt = select(model).where(model.user_id == user_id, model.embedding.is_not(None))
    objs = (await session.execute(stmt)).scalars().all()
    scored = [(o, cosine_distance(query_embedding, o.embedding)) for o in objs]
    scored.sort(key=lambda pair: pair[1])
    return scored[:limit]
