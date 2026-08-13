"""Percentile helpers used everywhere latencies are summarized."""
from dataclasses import dataclass, asdict
from typing import List

import numpy as np


@dataclass
class LatencyStats:
    n: int
    mean_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    stddev_ms: float

    def to_dict(self):
        return asdict(self)


def summarize(latencies_ms: List[float]) -> LatencyStats:
    if not latencies_ms:
        return LatencyStats(0, 0, 0, 0, 0, 0, 0, 0)
    arr = np.array(latencies_ms, dtype=float)
    return LatencyStats(
        n=len(arr),
        mean_ms=float(np.mean(arr)),
        p50_ms=float(np.percentile(arr, 50)),
        p95_ms=float(np.percentile(arr, 95)),
        p99_ms=float(np.percentile(arr, 99)),
        min_ms=float(np.min(arr)),
        max_ms=float(np.max(arr)),
        stddev_ms=float(np.std(arr)),
    )


def coefficient_of_variation(values: List[float]) -> float:
    """Used for the 'variance across repeated runs' rigor check (section 7)."""
    if not values:
        return 0.0
    arr = np.array(values, dtype=float)
    mean = np.mean(arr)
    return float(np.std(arr) / mean) if mean else 0.0
