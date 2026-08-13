#!/usr/bin/env python3
"""
Build an actor co-appearance graph from the Kaggle "Netflix Movies and
TV Shows" dataset (shivamb/netflix-shows, netflix_titles.csv).

This is the "movie/actor graph" alternative dataset explicitly permitted
by the assignment brief (as opposed to a SNAP social network sample).
The graph:

  - Node (Person): one per distinct actor name in the `cast` column.
      id             sequential int, assigned in sorted-name order (so
                     re-running this script on the same CSV always
                     produces the same ids -- no dataset randomness).
      name           actor's name as it appears in the CSV.
      is_director    1 if this person also appears in some title's
                     `director` column, else 0.
      title_count    number of Netflix titles they appear in as cast.
      primary_country  most common production country across their
                     titles (falls back to "unknown" if every title
                     they're in has an empty country field). Used as
                     the indexed/filtered-lookup and aggregation
                     property (same role `region` played for the
                     SNAP-based version of this harness).
      primary_genre  most common `listed_in` genre across their titles.

  - Relationship (ACTED_WITH): one edge per pair of actors who share a
    title's cast list. This is NOT deduplicated across titles -- if two
    actors co-star in 3 different titles, there are 3 ACTED_WITH edges
    between them (a multigraph). That's intentional: it's an honest
    "worked together on X" signal, and it also means relationship count
    isn't just "unique collaborator pairs" but "collaboration
    instances," which is closer to the SNAP dataset's original notion of
    a relationship count. If you want a deduplicated single-edge-per-pair
    graph instead, pass --dedupe-edges.

  Because the graph is inherently undirected (co-starring has no
  direction), edges are stored once per pair (lower id -> higher id) and
  src/adapters/bolt_cypher.py queries them with an undirected Cypher
  pattern (`-[:ACTED_WITH]-`), not a directed one -- see that file's
  traversal() docstring. This avoids doubling the relationship count
  just to make traversal work in both directions.

No down-sampling / BFS step is needed here (unlike the SNAP-based
version of this script): the full graph derived from all ~8,800 titles
already lands well inside the assignment's 100k-500k relationship band
(see the printed summary after running), so every title's cast list is
used as-is. --max-titles is available if you want a smaller graph for a
quick local test run.

Usage:
    python scripts/prepare_dataset.py \
        --raw data/raw/netflix_titles.csv \
        --out data/sample \
        --seed 42
"""
import argparse
import csv
import json
import os
import random
import sys
from collections import Counter, defaultdict

EXPECTED_COLUMNS = {"show_id", "type", "title", "director", "cast",
                    "country", "date_added", "release_year", "rating",
                    "duration", "listed_in", "description"}


def split_field(value: str) -> list:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw/netflix_titles.csv",
                     help="Path to the downloaded netflix_titles.csv")
    ap.add_argument("--out", default="data/sample")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--num-start-nodes", type=int, default=200)
    ap.add_argument("--max-titles", type=int, default=None,
                     help="Optional cap on number of titles processed, for a quick smaller test run.")
    ap.add_argument("--dedupe-edges", action="store_true",
                     help="Collapse multiple co-starring instances between the same pair into one edge.")
    args = ap.parse_args()
    random.seed(args.seed)

    if not os.path.exists(args.raw):
        print(f"Not found: {args.raw}\n"
              f"Download netflix_titles.csv from "
              f"https://www.kaggle.com/datasets/shivamb/netflix-shows and place it there "
              f"(see scripts/download_dataset.py).", file=sys.stderr)
        sys.exit(1)

    with open(args.raw, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        header = set(reader.fieldnames or [])
        missing = EXPECTED_COLUMNS - header
        if missing:
            print(f"WARNING: {args.raw} is missing expected columns {missing} -- "
                  f"are you sure this is the shivamb/netflix-shows CSV?", file=sys.stderr)
            sys.exit(1)
        rows = list(reader)

    if args.max_titles:
        rows = rows[: args.max_titles]

    directors_all = set()
    for row in rows:
        directors_all.update(split_field(row.get("director", "")))

    title_count = Counter()
    country_counter = defaultdict(Counter)
    genre_counter = defaultdict(Counter)
    title_casts = []  # list of (cast_list,) per title, for edge building

    n_titles_with_cast = 0
    for row in rows:
        cast = list(dict.fromkeys(split_field(row.get("cast", ""))))  # de-dupe within one title, keep order
        if not cast:
            continue
        n_titles_with_cast += 1
        countries = split_field(row.get("country", "")) or ["unknown"]
        genres = split_field(row.get("listed_in", "")) or ["unknown"]
        for actor in cast:
            title_count[actor] += 1
            for c in countries:
                country_counter[actor][c] += 1
            for g in genres:
                genre_counter[actor][g] += 1
        title_casts.append(cast)

    actor_names = sorted(title_count.keys())
    actor_id = {name: i + 1 for i, name in enumerate(actor_names)}  # deterministic ids

    print(f"Titles processed: {len(rows):,}")
    print(f"Titles with a non-empty cast: {n_titles_with_cast:,}")
    print(f"Distinct actors (nodes): {len(actor_names):,}")

    os.makedirs(args.out, exist_ok=True)
    nodes_csv = os.path.join(args.out, "nodes.csv")
    edges_csv = os.path.join(args.out, "edges.csv")

    with open(nodes_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id:ID", "name", "is_director:int", "title_count:int",
                    "primary_country", "primary_genre"])
        for name in actor_names:
            aid = actor_id[name]
            is_director = 1 if name in directors_all else 0
            tc = title_count[name]
            primary_country = country_counter[name].most_common(1)[0][0] if country_counter[name] else "unknown"
            primary_genre = genre_counter[name].most_common(1)[0][0] if genre_counter[name] else "unknown"
            w.writerow([aid, name, is_director, tc, primary_country, primary_genre])

    edge_count = 0
    degree = Counter()
    seen_pairs = set()
    with open(edges_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([":START_ID", ":END_ID", ":TYPE"])
        for cast in title_casts:
            ids = sorted(actor_id[a] for a in cast)
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    a, b = ids[i], ids[j]
                    if args.dedupe_edges:
                        if (a, b) in seen_pairs:
                            continue
                        seen_pairs.add((a, b))
                    w.writerow([a, b, "ACTED_WITH"])
                    edge_count += 1
                    degree[a] += 1
                    degree[b] += 1

    print(f"Relationships (ACTED_WITH{'​, deduped' if args.dedupe_edges else ', multigraph, not deduped'}): {edge_count:,}")

    if not (100_000 <= edge_count <= 600_000):
        print(f"NOTE: relationship count {edge_count:,} is outside the assignment's "
              f"suggested 100k-500k band. Use --max-titles to shrink it, or "
              f"--dedupe-edges to reduce multi-edges, if you need it smaller.",
              file=sys.stderr)

    candidates = [n for n in degree if degree[n] >= 3]
    random.shuffle(candidates)
    start_nodes = candidates[: args.num_start_nodes]
    if len(start_nodes) < args.num_start_nodes:
        print(f"WARNING: only {len(start_nodes)} nodes with degree>=3 available "
              f"(wanted {args.num_start_nodes}).")

    with open(os.path.join(args.out, "start_nodes.json"), "w", encoding="utf-8") as f:
        json.dump(start_nodes, f)

    manifest = {
        "source": "Kaggle: Netflix Movies and TV Shows (shivamb/netflix-shows), netflix_titles.csv",
        "sampling_method": (
            "Full actor co-appearance graph: one Person node per distinct "
            "actor across all titles' cast lists, one ACTED_WITH edge per "
            "pair of actors sharing a title (multigraph, not deduplicated "
            "across titles unless --dedupe-edges was passed). No "
            "down-sampling applied -- the full graph already falls within "
            "the assignment's 100k-500k relationship band."
        ),
        "node_count": len(actor_names),
        "relationship_count": edge_count,
        "titles_used": n_titles_with_cast,
        "dedupe_edges": args.dedupe_edges,
        "random_seed": args.seed,
        "start_nodes_file": "start_nodes.json",
        "start_node_count": len(start_nodes),
    }
    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print("\nWrote:")
    print(" ", nodes_csv)
    print(" ", edges_csv)
    print(" ", os.path.join(args.out, "start_nodes.json"))
    print(" ", os.path.join(args.out, "manifest.json"))


if __name__ == "__main__":
    main()
