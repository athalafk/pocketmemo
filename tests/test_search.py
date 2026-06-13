"""Pure-math tests for the cosine-distance used by the SQLite vector search."""

import pytest

from pocketmemo.db.search import cosine_distance


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
