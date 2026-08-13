#!/usr/bin/env python3
"""
One-command benchmark runner for a single platform.

    python -m src.harness.run_benchmark --platform cognodb

Loads the prepared dataset (scripts/prepare_dataset.py output), creates
indexes, measures ingest throughput, runs the warmed-up read workloads
(1/2/3-hop traversal, point lookup, indexed lookup, aggregation) for
>=100 iterations each, sweeps the mixed read/write workload across the
requested concurrency levels, captures whatever storage/footprint info
the platform exposes, and writes one JSON file to results/<platform>.json.

Run it once per platform: `make bench-cognodb`, `make bench-neo4j_aura_free`
(see README), or `./run_all.sh` to run the full dataset-build +
both-platform benchmark + report pipeline in one shot.
"""
import argparse
import csv
import json
import os
import random
import sys
import time
from datetime import datetime, timezone

import yaml
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.adapters import build_adapter
from src.common.stats import summarize
from src.workloads.read_workloads import (
    time_traversal, time_point_lookup, time_indexed_lookup, time_aggregation,
)
from src.workloads.mixed_workload import run_mixed


def load_platform_config(config_path: str, platform_key: str) -> dict:
    with open(config_path, encoding="utf-8") as f:
        all_cfg = yaml.safe_load(f)
    if platform_key not in all_cfg:
        raise SystemExit(f"Unknown platform '{platform_key}'. Options: {list(all_cfg.keys())}")
    cfg = all_cfg[platform_key]
    specs = cfg.get("specs", {})

    # Two independent TODO checks, because YAML comments (# TODO verify...)
    # are stripped by the parser and never show up in the parsed value --
    # a numeric field with a trailing "# TODO" comment would silently pass
    # a check that only looks for literal string values. So:
    #   1. any *value* that is literally the string "TODO" (covers fields
    #      like `region: "TODO"`, which are meant to stay unfilled string
    #      placeholders until set).
    #   2. an explicit `specs.verified: true` flag that must be set by hand
    #      once you've actually checked the platform's current advertised
    #      resources -- this is what actually gates numeric fields like
    #      vcpu/ram_gb/disk_gb, since "0.5" with a "# TODO" comment next to
    #      it is indistinguishable from a real value to a machine.
    literal_todos = [k for k, v in specs.items() if isinstance(v, str) and v.strip().upper() == "TODO"]
    if isinstance(cfg.get("region"), str) and cfg["region"].strip().upper() == "TODO":
        literal_todos.append("region")
    if literal_todos:
        raise SystemExit(
            f"[{platform_key}] config/platforms.yaml still has literal 'TODO' fields {literal_todos}. "
            f"Fill them in before running the benchmark -- see README 'Fairness / same resources everywhere'."
        )
    if not specs.get("verified", False):
        raise SystemExit(
            f"[{platform_key}] config/platforms.yaml specs.verified is not set to true. "
            f"This platform's vcpu/ram_gb/disk_gb values have NOT been confirmed against the "
            f"platform's current advertised free-tier resources -- check them (specs can drift "
            f"over time) and set `specs.verified: true` once you have, so RESULTS.md is never "
            f"paired with a guessed hardware spec. See README 'Fairness / same resources everywhere'."
        )
    return cfg


def read_csv_rows(path: str, transform):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            yield transform(row)


def load_dataset_rows(sample_dir: str):
    """nodes.csv columns (see scripts/prepare_dataset.py):
    id, name, is_director, title_count, primary_country, primary_genre.
    `primary_country` is passed through the adapter's generic 'region'
    parameter name -- see bolt_cypher.py docstring for why."""
    nodes_path = os.path.join(sample_dir, "nodes.csv")
    edges_path = os.path.join(sample_dir, "edges.csv")

    def node_transform(row):
        return {
            "id": int(row[0]), "name": row[1], "is_director": int(row[2]),
            "title_count": int(row[3]), "primary_country": row[4], "primary_genre": row[5],
        }

    def edge_transform(row):
        return {"start_id": int(row[0]), "end_id": int(row[1])}

    return (
        lambda: read_csv_rows(nodes_path, node_transform),
        lambda: read_csv_rows(edges_path, edge_transform),
    )


def collect_regions(sample_dir: str, cap: int = 5000) -> list:
    """Distinct `primary_country` values, used for the indexed-lookup
    workload and the mixed-workload writes (see load_dataset_rows note
    above for the 'region' naming)."""
    regions = set()
    with open(os.path.join(sample_dir, "nodes.csv"), newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)
        for i, row in enumerate(reader):
            regions.add(row[4])
            if i > cap:
                break
    return sorted(regions) or ["unknown"]


def collect_node_ids(sample_dir: str, cap: int = 20000) -> list:
    ids = []
    with open(os.path.join(sample_dir, "nodes.csv"), newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)
        for i, row in enumerate(reader):
            ids.append(int(row[0]))
            if i > cap:
                break
    return ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", required=True)
    ap.add_argument("--config", default="config/platforms.yaml")
    ap.add_argument("--data", default="data/sample")
    ap.add_argument("--results-dir", default="results")
    ap.add_argument("--load-batch-size", type=int, default=1000)
    ap.add_argument("--read-iterations", type=int, default=100)
    ap.add_argument("--warmup", type=int, default=10)
    ap.add_argument("--mixed-duration", type=float, default=30.0)
    ap.add_argument("--mixed-concurrency", default="1,10,40")
    ap.add_argument("--mixed-write-ratio", type=float, default=0.2)
    ap.add_argument("--skip-mixed", action="store_true")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    random.seed(args.seed)

    load_dotenv()

    cfg = load_platform_config(args.config, args.platform)
    manifest_path = os.path.join(args.data, "manifest.json")
    if not os.path.exists(manifest_path):
        raise SystemExit(f"No dataset found at {args.data}. Run scripts/download_dataset.py "
                          f"and scripts/prepare_dataset.py first.")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    with open(os.path.join(args.data, "start_nodes.json"), encoding="utf-8") as f:
        start_nodes = json.load(f)

    node_rows_fn, edge_rows_fn = load_dataset_rows(args.data)
    regions = collect_regions(args.data)
    sample_node_ids = collect_node_ids(args.data)

    print(f"=== {cfg.get('display_name', args.platform)} ===")
    adapter = build_adapter(args.platform, cfg)
    adapter.connect()

    try:
        print("Resetting database...")
        adapter.reset()

        print("Creating indexes:", cfg.get("index_properties", []))
        adapter.create_indexes(cfg.get("index_properties", []))

        print("Loading nodes...")
        node_load = adapter.load_nodes(node_rows_fn(), batch_size=args.load_batch_size)
        print(f"  {node_load.count:,} nodes in {node_load.seconds:.1f}s "
              f"({node_load.throughput:,.0f} nodes/s)")

        print("Loading edges...")
        edge_load = adapter.load_edges(edge_rows_fn(), batch_size=args.load_batch_size)
        print(f"  {edge_load.count:,} edges in {edge_load.seconds:.1f}s "
              f"({edge_load.throughput:,.0f} edges/s)")

        results = {
            "platform": args.platform,
            "display_name": cfg.get("display_name", args.platform),
            "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "region": cfg.get("region"),
            "specs": cfg.get("specs", {}),
            "dataset_manifest": manifest,
            "config": {
                "read_iterations": args.read_iterations,
                "warmup": args.warmup,
                "mixed_duration_s": args.mixed_duration,
                "mixed_write_ratio": args.mixed_write_ratio,
                "load_batch_size": args.load_batch_size,
                "random_seed": args.seed,
            },
            "loading": {
                "nodes": {"count": node_load.count, "seconds": node_load.seconds,
                          "throughput_per_s": node_load.throughput},
                "relationships": {"count": edge_load.count, "seconds": edge_load.seconds,
                                   "throughput_per_s": edge_load.throughput},
                "total_wall_clock_s": node_load.seconds + edge_load.seconds,
            },
            "traversals": {},
            "lookups": {},
            "aggregation": {},
            "mixed_workload": [],
            "footprint": {},
            "caveats": [],
        }

        for hops in (1, 2, 3):
            print(f"Timing {hops}-hop traversal ({args.warmup} warmup + {args.read_iterations} measured)...")
            lat = time_traversal(adapter, start_nodes, hops,
                                  iterations=args.read_iterations, warmup=args.warmup)
            results["traversals"][f"{hops}_hop"] = {
                "stats": summarize(lat).to_dict(), "raw_ms": lat,
            }

        print("Timing point lookup...")
        lat = time_point_lookup(adapter, sample_node_ids,
                                 iterations=args.read_iterations, warmup=args.warmup)
        results["lookups"]["point"] = {"stats": summarize(lat).to_dict(), "raw_ms": lat}

        print("Timing indexed/filtered lookup (on 'region')...")
        lat = time_indexed_lookup(adapter, regions,
                                   iterations=args.read_iterations, warmup=args.warmup)
        results["lookups"]["indexed"] = {
            "indexed_property": "region",
            "stats": summarize(lat).to_dict(), "raw_ms": lat,
        }

        print("Timing aggregation (group by region, count)...")
        lat = time_aggregation(adapter, iterations=args.read_iterations, warmup=args.warmup)
        results["aggregation"] = {"stats": summarize(lat).to_dict(), "raw_ms": lat}

        if not args.skip_mixed:
            for c in [int(x) for x in args.mixed_concurrency.split(",")]:
                print(f"Mixed workload @ concurrency={c} for {args.mixed_duration}s "
                      f"(write_ratio={args.mixed_write_ratio})...")
                mr = run_mixed(adapter, sample_node_ids, regions, concurrency=c,
                                duration_s=args.mixed_duration, write_ratio=args.mixed_write_ratio)
                entry = {
                    "concurrency": mr.concurrency, "duration_s": mr.duration_s,
                    "write_ratio": mr.write_ratio, "total_ops": mr.total_ops,
                    "ok_ops": mr.ok_ops, "failed_ops": mr.failed_ops, "qps": mr.qps,
                    "latency_stats": summarize(mr.latencies_ms).to_dict(),
                }
                if mr.failed_ops:
                    results["caveats"].append(
                        f"{mr.failed_ops} of {mr.total_ops} ops failed during mixed "
                        f"workload at concurrency={c} (see raw logs / retry policy)."
                    )
                results["mixed_workload"].append(entry)
                print(f"  {mr.qps:,.1f} qps, {mr.ok_ops} ok / {mr.failed_ops} failed")

        print("Capturing storage footprint...")
        fp = adapter.storage_footprint()
        results["footprint"] = {
            "stored_bytes": fp.stored_bytes, "memory_bytes": fp.memory_bytes, "note": fp.note,
        }

        os.makedirs(args.results_dir, exist_ok=True)
        out_path = os.path.join(args.results_dir, f"{args.platform}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"\nWrote {out_path}")

    finally:
        adapter.close()


if __name__ == "__main__":
    main()
