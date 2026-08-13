"""
Common adapter interface every platform driver implements.

The harness (src/harness/run_benchmark.py) and the workload modules
(src/workloads/*) only ever talk to this interface, never to a
platform-specific driver directly. This is what makes "same logical
query on every platform" enforceable: each concrete adapter is
responsible for translating the *same* request (e.g. "traverse 2 hops
from node X") into its own query language, but the request shape and
the returned shape are identical everywhere.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass
class LoadResult:
    count: int
    seconds: float

    @property
    def throughput(self) -> float:
        return self.count / self.seconds if self.seconds > 0 else float("inf")


@dataclass
class StorageFootprint:
    stored_bytes: Optional[int] = None
    memory_bytes: Optional[int] = None
    note: str = ""


class GraphDBAdapter(ABC):
    """One instance per platform, constructed from config/platforms.yaml."""

    name: str
    display_name: str

    # -- lifecycle -----------------------------------------------------
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def reset(self) -> None:
        """Delete all nodes/edges. Called once before loading, so re-runs
        are idempotent."""

    @abstractmethod
    def create_indexes(self, index_properties: list[str]) -> None:
        """Create a uniqueness constraint/index on 'id' plus a secondary
        index on every property in index_properties (e.g. 'region')."""

    # -- loading ---------------------------------------------------------
    @abstractmethod
    def load_nodes(self, rows: Iterable[dict], batch_size: int = 1000) -> LoadResult:
        """rows: dicts with keys id, name, is_director, title_count,
        primary_country, primary_genre (see scripts/prepare_dataset.py)."""

    @abstractmethod
    def load_edges(self, rows: Iterable[dict], batch_size: int = 1000) -> LoadResult:
        """rows: dicts with keys start_id, end_id (relationship type is
        always ACTED_WITH for this dataset, undirected -- see
        adapters/bolt_cypher.py docstring)."""

    # -- read workloads ----------------------------------------------------
    @abstractmethod
    def point_lookup(self, node_id: int) -> dict:
        """Fetch a single node by its unique id (primary-key lookup)."""

    @abstractmethod
    def indexed_lookup(self, region: str, limit: int = 50) -> list:
        """Fetch nodes filtered by the secondary-indexed 'region' property."""

    @abstractmethod
    def traversal(self, start_id: int, hops: int) -> list:
        """Return the set of distinct node ids reachable in exactly `hops`
        ACTED_WITH hops (undirected) from start_id."""

    @abstractmethod
    def aggregation(self, limit: int = 20) -> list:
        """Group-by-region count over all Person nodes, ordered desc,
        top `limit` groups."""

    # -- mixed workload ------------------------------------------------
    @abstractmethod
    def mixed_read(self, node_id: int) -> None:
        """One 'read' unit of work for the mixed workload (kept cheap and
        uniform across platforms: a point lookup)."""

    @abstractmethod
    def mixed_write(self, node_id: int, new_region: str) -> None:
        """One 'write' unit of work for the mixed workload: update a
        single node's region property."""

    # -- footprint -------------------------------------------------------
    @abstractmethod
    def storage_footprint(self) -> StorageFootprint:
        """Best-effort resource usage. Return StorageFootprint(note="not
        observable") when the platform exposes nothing programmatically."""

    # -- concurrency helper ----------------------------------------------
    def new_session_adapter(self) -> "GraphDBAdapter":
        """Return an object usable from a worker thread for the mixed
        workload. Drivers that are thread-safe (e.g. neo4j.Driver) can
        just return self; adapters with non-thread-safe clients should
        open a fresh session/connection here."""
        return self
