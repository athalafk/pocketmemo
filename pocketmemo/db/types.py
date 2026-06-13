"""Cross-backend column types.

PocketMemo runs on either PostgreSQL (with the pgvector extension, the default for
servers) or SQLite (a single file, for ultra-light local installs). These types let
the same models work on both:

* :class:`Embedding` — a real ``VECTOR(dim)`` pgvector column on PostgreSQL, or the
  vector stored as a JSON array of floats in ``TEXT`` on SQLite. Similarity search on
  SQLite is done in Python (see :mod:`pocketmemo.db.search`).
* :func:`json_type` — ``JSONB`` on PostgreSQL, plain JSON elsewhere.
"""

from __future__ import annotations

import json

from sqlalchemy import JSON, Float, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator


def json_type():
    """A JSON column: JSONB on PostgreSQL, generic JSON (TEXT) on SQLite/others."""
    return JSON().with_variant(JSONB(), "postgresql")


class Embedding(TypeDecorator):
    """An embedding vector that adapts to the active database backend."""

    cache_ok = True
    impl = Text

    def __init__(self, dim: int, **kw):
        self.dim = dim
        super().__init__(**kw)

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value  # pgvector accepts the Python list directly
        return json.dumps([float(x) for x in value])

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value)
        return json.loads(value)

    class comparator_factory(TypeDecorator.Comparator):
        def cosine_distance(self, other):
            """pgvector cosine-distance operator (only ever emitted on PostgreSQL)."""
            return self.op("<=>", return_type=Float)(other)
