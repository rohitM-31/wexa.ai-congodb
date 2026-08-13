"""
Adapter for CognoDB Cloud and Neo4j AuraDB Free, via the official Neo4j
Python driver over Bolt + Cypher. This is deliberately one class
parameterized by connection details -- the whole point of CognoDB's
"drop-in Neo4j driver" design is that the same client code works
unmodified against it, so testing that claim means literally reusing
this class against both platforms rather than writing a second one.

Graph schema loaded by this adapter (see scripts/prepare_dataset.py for
how it's derived from the Netflix Kaggle CSV):

  (:Person {id, name, is_director, title_count, primary_country, primary_genre})
    -[:ACTED_WITH]-
  (:Person)

ACTED_WITH is inherently undirected (co-starring has no direction), so
it's stored once per pair (lower id -> higher id, see prepare_dataset.py)
and every query here matches it with an undirected Cypher pattern
(`-[:ACTED_WITH]-`, no arrow) rather than assuming a traversal direction
-- using a directed pattern here would silently make ~half the graph's
nodes look like dead ends for traversal, since "lower id" vs "higher id"
has nothing to do with which actor's neighborhood you're exploring from.

`_is_memgraph` is kept as a no-op flag (false for both platforms this
repo currently benchmarks) rather than deleted, so this same class can
also be pointed at self-hosted Memgraph later without a rewrite -- see
README "Scope" for the platforms this repo currently covers.
"""
import os
import time
from typing import Iterable

from neo4j import GraphDatabase

from .base import GraphDBAdapter, LoadResult, StorageFootprint


class BoltCypherAdapter(GraphDBAdapter):
    def __init__(self, platform_key: str, cfg: dict):
        self.name = platform_key
        self.display_name = cfg.get("display_name", platform_key)
        self.cfg = cfg
        uri = os.environ.get(cfg["uri_env"])
        user = os.environ.get(cfg["user_env"], "neo4j")
        password = os.environ.get(cfg["password_env"])
        if not uri or password is None:
            raise RuntimeError(
                f"[{platform_key}] missing env vars {cfg['uri_env']}/{cfg['password_env']}. "
                f"Copy .env.example to .env and fill them in."
            )
        self._uri, self._user, self._password = uri, user, password
        self.driver = None
        # Memgraph doesn't like Neo4j's "IF NOT EXISTS" constraint dialect
        # in older versions; flag it so create_indexes() branches. No-op
        # for CognoDB, kept so this adapter still works if pointed at
        # Memgraph later (see module docstring).
        self._is_memgraph = "memgraph" in platform_key.lower()

    def connect(self) -> None:
        self.driver = GraphDatabase.driver(self._uri, auth=(self._user, self._password))
        self.driver.verify_connectivity()

    def close(self) -> None:
        if self.driver:
            self.driver.close()

    def new_session_adapter(self):
        # neo4j.Driver is thread-safe; each call opens its own Session.
        return self

    # -- schema ----------------------------------------------------------
    def reset(self) -> None:
        with self.driver.session() as s:
            # Batched delete so we don't blow the free tier's memory on a
            # single giant transaction against a ~300k-edge graph.
            while True:
                result = s.run(
                    "MATCH (n) WITH n LIMIT 10000 DETACH DELETE n RETURN count(n) AS c"
                )
                deleted = result.single()["c"]
                if deleted == 0:
                    break

    def create_indexes(self, index_properties: list[str]) -> None:
        with self.driver.session() as s:
            if self._is_memgraph:
                s.run("CREATE CONSTRAINT ON (p:Person) ASSERT p.id IS UNIQUE")
                for prop in index_properties:
                    if prop == "id":
                        continue
                    s.run(f"CREATE INDEX ON :Person({prop})")
            else:
                s.run(
                    "CREATE CONSTRAINT person_id_unique IF NOT EXISTS "
                    "FOR (p:Person) REQUIRE p.id IS UNIQUE"
                )
                for prop in index_properties:
                    if prop == "id":
                        continue
                    s.run(
                        f"CREATE INDEX person_{prop}_idx IF NOT EXISTS "
                        f"FOR (p:Person) ON (p.{prop})"
                    )

    # -- loading -----------------------------------------------------------
    def load_nodes(self, rows: Iterable[dict], batch_size: int = 1000) -> LoadResult:
        return self._batched_write(
            rows, batch_size,
            "UNWIND $batch AS row "
            "CREATE (p:Person {id: row.id, name: row.name, "
            "is_director: row.is_director, title_count: row.title_count, "
            "primary_country: row.primary_country, primary_genre: row.primary_genre})",
        )

    def load_edges(self, rows: Iterable[dict], batch_size: int = 1000) -> LoadResult:
        return self._batched_write(
            rows, batch_size,
            "UNWIND $batch AS row "
            "MATCH (a:Person {id: row.start_id}), (b:Person {id: row.end_id}) "
            "CREATE (a)-[:ACTED_WITH]->(b)",
        )

    def _batched_write(self, rows: Iterable[dict], batch_size: int, query: str) -> LoadResult:
        count = 0
        batch = []
        t0 = time.perf_counter()
        with self.driver.session() as s:
            for row in rows:
                batch.append(row)
                if len(batch) >= batch_size:
                    s.run(query, batch=batch).consume()
                    count += len(batch)
                    batch = []
            if batch:
                s.run(query, batch=batch).consume()
                count += len(batch)
        return LoadResult(count=count, seconds=time.perf_counter() - t0)

    # -- reads -----------------------------------------------------------
    def point_lookup(self, node_id: int) -> dict:
        with self.driver.session() as s:
            rec = s.run("MATCH (p:Person {id: $id}) RETURN p", id=node_id).single()
            return dict(rec["p"]) if rec else {}

    def indexed_lookup(self, region: str, limit: int = 50) -> list:
        # NOTE: parameter is named `region` to match the generic harness
        # interface (base.py / workloads / run_benchmark.py all use that
        # name), but for this dataset the actual graph property queried
        # is `primary_country` -- see module docstring / README dataset
        # section for why. "region" here is just a Python identifier,
        # not a claim about what's stored.
        with self.driver.session() as s:
            res = s.run(
                "MATCH (p:Person {primary_country: $region}) RETURN p.id AS id LIMIT $limit",
                region=region, limit=limit,
            )
            return [r["id"] for r in res]

    def traversal(self, start_id: int, hops: int) -> list:
        # Fixed-length traversal via explicit hop count, DISTINCT endpoints.
        # Undirected pattern -- see module docstring for why ACTED_WITH
        # must be matched without an arrow.
        pattern = "-[:ACTED_WITH]-()" * (hops - 1) + "-[:ACTED_WITH]-(m)"
        query = f"MATCH (p:Person {{id: $id}}){pattern} WHERE m.id <> $id RETURN DISTINCT m.id AS id"
        with self.driver.session() as s:
            res = s.run(query, id=start_id)
            return [r["id"] for r in res]

    def aggregation(self, limit: int = 20) -> list:
        with self.driver.session() as s:
            res = s.run(
                "MATCH (p:Person) RETURN p.primary_country AS region, count(*) AS cnt "
                "ORDER BY cnt DESC LIMIT $limit",
                limit=limit,
            )
            return [(r["region"], r["cnt"]) for r in res]

    # -- mixed workload ------------------------------------------------
    def mixed_read(self, node_id: int) -> None:
        with self.driver.session() as s:
            s.run("MATCH (p:Person {id: $id}) RETURN p.id", id=node_id).consume()

    def mixed_write(self, node_id: int, new_region: str) -> None:
        # Again, `new_region` is the generic harness parameter name; the
        # property actually written is `primary_country`.
        with self.driver.session() as s:
            s.run(
                "MATCH (p:Person {id: $id}) SET p.primary_country = $region",
                id=node_id, region=new_region,
            ).consume()

    # -- footprint -------------------------------------------------------
    def storage_footprint(self) -> StorageFootprint:
        # apoc.monitor.store() is NOT in the curated APOC-Core subset Aura
        # (and CognoDB, which follows the same Neo4j-compatible surface)
        # pre-installs (see https://neo4j.com/docs/aura/apoc/), so we try
        # progressively cheaper options rather than assuming a full
        # self-hosted APOC install:
        #   1. apoc.monitor.store() -- self-hosted Neo4j/Docker only, gives
        #      real on-disk byte sizes when it's available.
        #   2. apoc.meta.stats() -- likelier to be supported; doesn't give
        #      bytes, but gives node/relationship/property counts we can
        #      report alongside any console-reported size.
        #   3. give up honestly rather than silently report nothing useful.
        try:
            with self.driver.session() as s:
                rec = s.run(
                    "CALL apoc.monitor.store() YIELD stringStoreSize, totalStoreSize "
                    "RETURN totalStoreSize AS bytes"
                ).single()
                if rec:
                    return StorageFootprint(stored_bytes=rec["bytes"], note="via apoc.monitor.store()")
        except Exception:
            pass
        try:
            with self.driver.session() as s:
                rec = s.run("CALL apoc.meta.stats() YIELD nodeCount, relCount, labelCount "
                             "RETURN nodeCount, relCount, labelCount").single()
                if rec:
                    return StorageFootprint(
                        note=f"apoc.monitor.store() unavailable on this platform; "
                             f"apoc.meta.stats() reports {rec['nodeCount']} nodes, "
                             f"{rec['relCount']} relationships, {rec['labelCount']} labels. "
                             f"For actual byte size, use the platform's console/dashboard."
                    )
        except Exception:
            pass
        return StorageFootprint(note="not observable via Bolt on this platform's free tier "
                                      "(no APOC / admin endpoint); report console-displayed size if any.")
