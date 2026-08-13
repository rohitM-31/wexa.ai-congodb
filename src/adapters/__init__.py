from .base import GraphDBAdapter, LoadResult, StorageFootprint
from .bolt_cypher import BoltCypherAdapter


def build_adapter(platform_key: str, cfg: dict) -> GraphDBAdapter:
    """cfg is the 'cognodb' entry from config/platforms.yaml. This repo is
    scoped to CognoDB Cloud only (see README) -- the adapter interface in
    base.py is still generic so other Bolt+Cypher-speaking platforms (Neo4j
    Aura, Memgraph, etc.) can be added back by dropping in another adapter
    module and branching on cfg['adapter'] here, exactly as bolt_cypher.py
    already demonstrates."""
    kind = cfg["adapter"]
    if kind != "bolt_cypher":
        raise ValueError(
            f"Unknown adapter kind '{kind}'. This repo only ships the "
            f"bolt_cypher adapter (CognoDB Cloud). See README to add others."
        )
    return BoltCypherAdapter(platform_key, cfg)
