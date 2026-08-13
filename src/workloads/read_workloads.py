"""
Timed read workloads: 1/2/3-hop traversal, point lookup, indexed lookup,
aggregation. Each function warms up the platform first (untimed calls,
default 10), then times `iterations` calls (default 100+, per the
assignment's "≥100 iterations after warm-up" guidance) and returns the
raw per-call latencies in milliseconds, which the harness both stores
raw (for repeated-run variance analysis) and summarizes with
common/stats.py.
"""
import random
import time
from typing import List

from src.adapters.base import GraphDBAdapter


def _timed(fn, *args) -> float:
    t0 = time.perf_counter()
    fn(*args)
    return (time.perf_counter() - t0) * 1000.0


def time_traversal(adapter: GraphDBAdapter, start_nodes: List[int], hops: int,
                    iterations: int = 100, warmup: int = 10) -> List[float]:
    picks = [random.choice(start_nodes) for _ in range(warmup + iterations)]
    for sid in picks[:warmup]:
        adapter.traversal(sid, hops)
    return [_timed(adapter.traversal, sid, hops) for sid in picks[warmup:]]


def time_point_lookup(adapter: GraphDBAdapter, node_ids: List[int],
                       iterations: int = 100, warmup: int = 10) -> List[float]:
    picks = [random.choice(node_ids) for _ in range(warmup + iterations)]
    for nid in picks[:warmup]:
        adapter.point_lookup(nid)
    return [_timed(adapter.point_lookup, nid) for nid in picks[warmup:]]


def time_indexed_lookup(adapter: GraphDBAdapter, regions: List[str],
                         iterations: int = 100, warmup: int = 10) -> List[float]:
    picks = [random.choice(regions) for _ in range(warmup + iterations)]
    for r in picks[:warmup]:
        adapter.indexed_lookup(r)
    return [_timed(adapter.indexed_lookup, r) for r in picks[warmup:]]


def time_aggregation(adapter: GraphDBAdapter,
                      iterations: int = 100, warmup: int = 10) -> List[float]:
    for _ in range(warmup):
        adapter.aggregation()
    return [_timed(adapter.aggregation) for _ in range(iterations)]
