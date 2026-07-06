"""Unit: consolidation clustering (M07). Pure cosine + greedy clustering; no DB/embedder."""

import pytest

from argus.memory.consolidate import _cosine, cluster

pytestmark = pytest.mark.unit


def test_cosine_identical_and_orthogonal() -> None:
    assert _cosine([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == pytest.approx(1.0)
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cluster_groups_near_duplicates() -> None:
    items = [("a", [1.0, 0.0, 0.0]), ("b", [0.99, 0.01, 0.0]), ("c", [0.0, 1.0, 0.0])]
    groups = sorted(sorted(g) for g in cluster(items, threshold=0.9))
    assert ["a", "b"] in groups
    assert ["c"] in groups


def test_cluster_all_distinct_stay_singletons() -> None:
    items = [("a", [1.0, 0.0, 0.0]), ("b", [0.0, 1.0, 0.0]), ("c", [0.0, 0.0, 1.0])]
    assert all(len(g) == 1 for g in cluster(items, threshold=0.9))


def test_cluster_all_identical_merge() -> None:
    items = [("a", [1.0, 0.0]), ("b", [1.0, 0.0]), ("c", [1.0, 0.0])]
    clusters = cluster(items, threshold=0.9)
    assert len(clusters) == 1 and sorted(clusters[0]) == ["a", "b", "c"]
