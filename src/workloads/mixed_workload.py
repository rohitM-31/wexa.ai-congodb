"""
Concurrent mixed read/write workload (section 5.2 "Mixed workload").

Runs `concurrency` worker threads for `duration_s` seconds each, issuing
`mixed_read` or `mixed_write` calls against the adapter according to
`write_ratio` (default 0.2 == 80/20 read/write). Reports sustained
queries/second and per-call latency percentiles.

Threading (not multiprocessing/asyncio) is used because the neo4j
driver releases the GIL during network I/O, so thread-level concurrency
reflects real client concurrency without an async rewrite of the
adapter. This also means the same worker code works unmodified if
another Bolt+Cypher (or requests-based) adapter is added later.
"""
import random
import threading
import time
from dataclasses import dataclass
from typing import List

from src.adapters.base import GraphDBAdapter


@dataclass
class MixedResult:
    concurrency: int
    duration_s: float
    write_ratio: float
    total_ops: int
    ok_ops: int
    failed_ops: int
    qps: float
    latencies_ms: List[float]


def _worker(adapter: GraphDBAdapter, node_ids: List[int], regions: List[str],
            write_ratio: float, stop_at: float, latencies: list, lock: threading.Lock,
            counters: dict):
    local_latencies = []
    ok = 0
    failed = 0
    while time.perf_counter() < stop_at:
        nid = random.choice(node_ids)
        is_write = random.random() < write_ratio
        t0 = time.perf_counter()
        try:
            if is_write:
                adapter.mixed_write(nid, random.choice(regions))
            else:
                adapter.mixed_read(nid)
            ok += 1
        except Exception:
            failed += 1
        finally:
            local_latencies.append((time.perf_counter() - t0) * 1000.0)
    with lock:
        latencies.extend(local_latencies)
        counters["ok"] += ok
        counters["failed"] += failed


def run_mixed(base_adapter: GraphDBAdapter, node_ids: List[int], regions: List[str],
              concurrency: int, duration_s: float = 30.0, write_ratio: float = 0.2) -> MixedResult:
    latencies: List[float] = []
    lock = threading.Lock()
    counters = {"ok": 0, "failed": 0}
    stop_at = time.perf_counter() + duration_s

    threads = []
    for _ in range(concurrency):
        adapter = base_adapter.new_session_adapter()
        t = threading.Thread(
            target=_worker,
            args=(adapter, node_ids, regions, write_ratio, stop_at, latencies, lock, counters),
        )
        threads.append(t)

    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - start

    total = counters["ok"] + counters["failed"]
    return MixedResult(
        concurrency=concurrency,
        duration_s=wall,
        write_ratio=write_ratio,
        total_ops=total,
        ok_ops=counters["ok"],
        failed_ops=counters["failed"],
        qps=total / wall if wall > 0 else 0.0,
        latencies_ms=latencies,
    )
