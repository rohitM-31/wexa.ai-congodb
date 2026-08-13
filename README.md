# CognoDB Cloud vs. Neo4j AuraDB Free — a reproducible benchmark (Netflix actor graph)

This repo runs a scripted benchmark suite comparing two platforms —
[CognoDB Cloud](https://console.cognodb.com) and [Neo4j AuraDB
Free](https://console.neo4j.io) — on identical hardware tiers, an
identical derived dataset, and identical logical queries. Both speak
Bolt + Cypher over the official Neo4j Python driver, so they're
benchmarked with the exact same adapter code
(`src/adapters/bolt_cypher.py`) — no per-platform query rewriting to
introduce inconsistency.

## Scope — read this first

This harness was originally built to benchmark CognoDB against **at
least four** other managed graph database platforms, as the core of a
full comparison exercise. **This version compares two** (CognoDB +
Neo4j AuraDB Free). If this is going toward something graded on
"completeness of metrics" / breadth of comparison against a 4+-platform
requirement, two platforms is a real but partial comparison — it will
score better than a solo CognoDB run, but still short of the original
bar.

The harness is built so more comparators can be dropped in without a
rewrite: `src/adapters/base.py` defines the platform-neutral interface,
`src/adapters/bolt_cypher.py` already works unmodified for any
Bolt+Cypher platform (self-hosted Memgraph, for instance — just point
it at a different URI), and `config/platforms.yaml` is a list you can
extend with one more entry per platform. Non-Cypher platforms
(ArangoDB, TigerGraph, etc.) need a new adapter class implementing the
same interface — see `base.py`'s abstract methods.

## Platforms compared

| Platform | Why it's here |
|---|---|
| **CognoDB Cloud** (`c0` free tier) | Subject of the benchmark. |
| **Neo4j AuraDB Free** | CognoDB is explicitly Bolt/Cypher + Neo4j-driver compatible, so Aura Free is the most direct apples-to-apples comparison — same protocol, same query language, same official driver, different vendor's managed runtime. |

## Fairness: same resources everywhere

| Platform | Tier | vCPU | RAM | Disk |
|---|---|---|---|---|
| CognoDB Cloud | `c0` (free) | 0.5 (burstable) | 256 MB | 1 GB |
| Neo4j AuraDB Free | Free | *(fill in from console — see setup below)* | *(fill in)* | *(fill in)* |

`config/platforms.yaml` has this machine-readable, and
`run_benchmark.py` **refuses to run** while any `specs` field is still
`TODO` — Aura Free's exact current specs need to be confirmed at
instance-creation time (Neo4j has changed the Free tier's advertised
resources before), so they're deliberately left as TODO rather than a
guessed number. If Aura Free's real spec turns out to be larger than
CognoDB's 0.5 vCPU / 256MB (historically true — Aura Free has generally
had more headroom), that's disclosed here and in `RESULTS.md`, not
hidden — see "Fairness analysis" in `docs/ANALYSIS_TEMPLATE.md`.

## Dataset: a Netflix actor co-appearance graph

Rather than a SNAP social-network sample, this uses the **"Netflix
Movies and TV Shows" Kaggle dataset** (`shivamb/netflix-shows`,
`netflix_titles.csv`) — a per-title catalog with cast, director,
country, and genre fields. This is the "movie/actor graph" alternative
dataset explicitly permitted by the original assignment brief. It's
**not** itself a graph — it's a flat table of ~8,800 titles — so
`scripts/prepare_dataset.py` derives one:

- **Node (`Person`):** one per distinct actor name appearing in any
  title's `cast` column: `id`, `name`, `is_director` (0/1),
  `title_count`, `primary_country` (most common production country
  across their titles — the indexed/aggregated property), `primary_genre`.
- **Relationship (`ACTED_WITH`):** one edge per pair of actors who
  share a title's cast list. **Not deduplicated across titles** — two
  actors who co-star in 3 different titles get 3 `ACTED_WITH` edges (an
  intentional multigraph). The relationship is inherently undirected,
  so it's matched with an undirected Cypher pattern
  (`-[:ACTED_WITH]-`) everywhere — see `bolt_cypher.py`'s docstring.

**Actual size from the full dataset:** **36,439 actor nodes**,
**305,471 `ACTED_WITH` relationships**, from 7,982 titles with a
non-empty cast — inside the assignment's 100k–500k relationship
guidance with no down-sampling needed (see `data/sample/manifest.json`
once generated).

### Getting the CSV

Kaggle requires a free account and doesn't allow anonymous downloads:

1. Go to https://www.kaggle.com/datasets/shivamb/netflix-shows
2. Click **Download**, unzip it.
3. Place `netflix_titles.csv` at **`data/raw/netflix_titles.csv`**.
4. Optionally validate: `python scripts/download_dataset.py --raw data/raw`

## What this repo measures

| Category | Metric | What's reported |
|---|---|---|
| Loading | Ingest throughput | nodes/s, relationships/s, total wall-clock |
| Traversal | 1-hop / 2-hop / 3-hop | p50 + p95 latency, from the same fixed set of 200 random start actors (degree ≥ 3) |
| Lookup | Point lookup by `id` | p50 + p95 |
| Lookup | Indexed/filtered lookup by `primary_country` | p50 + p95, indexed on both platforms |
| Aggregation | `COUNT` grouped by `primary_country` | p50 + p95 |
| Mixed workload | Concurrent read/write | sustained QPS at concurrency 1 / 10 / 40, 80% read / 20% write |
| Footprint | Storage / memory | whatever each platform's console/Bolt surface exposes; "not observable" where it doesn't |

Every read workload runs 10 warm-up calls + 100 measured iterations by
default. Raw per-call latencies are saved in each platform's
`results/<platform>.json`, so percentiles can be recomputed without
re-running anything.

## How to run

```bash
git clone <this-repo-url>
cd cognodb-netflix-benchmark
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cp .env.example .env
```

**CognoDB Cloud:**
1. Sign up at https://console.cognodb.com/signup (no credit card).
2. Create a free `c0` instance, pick a region, wait ~1 minute.
3. Copy the `bolt+s://...` URI and one-time-shown `cognodb` password into `.env`.
4. Set `cognodb.region` in `config/platforms.yaml` to the region you picked.

**Neo4j AuraDB Free:**
1. Sign up at https://console.neo4j.io, create a **Free** instance.
2. Save the generated password immediately (also shown once).
3. Fill `NEO4J_AURA_URI` / `NEO4J_AURA_PASSWORD` in `.env`.
4. Fill `neo4j_aura_free.region` **and** the real Aura Free vCPU/RAM/disk into `config/platforms.yaml` from the console's instance details page — the runner will refuse to start until these are filled in.

**Dataset:** see "Getting the CSV" above.

**Run:**
```bash
python scripts/prepare_dataset.py --raw data/raw/netflix_titles.csv --out data/sample
python -m src.harness.run_benchmark --platform cognodb
python -m src.harness.run_benchmark --platform neo4j_aura_free
python -m src.harness.report
```
or `make prepare-data bench-all report`, or `./run_all.sh` for all of
it in one shot.

## Results

See **[RESULTS.md](RESULTS.md)** (generated by `python -m src.harness.report`
after both platforms have been benchmarked) — a full comparison table
across both platforms for every metric above, plus charts in
`results/charts/`.

## Analysis

See **[docs/ANALYSIS_TEMPLATE.md](docs/ANALYSIS_TEMPLATE.md)**.

## Methodology notes and caveats

- **Multigraph, not deduplicated:** relationship count (305,471) counts
  co-starring *instances*, not unique collaborator pairs (289,207
  unique pairs). Pass `--dedupe-edges` to `prepare_dataset.py` for the
  deduplicated version — re-run the whole benchmark on both platforms
  if you switch modes, don't mix results from the two.
- **Undirected traversal:** `ACTED_WITH` is matched with an undirected
  Cypher pattern on purpose, identically on both platforms — see
  `src/adapters/bolt_cypher.py`.
- **`region` naming is a code artifact, not a data claim:** the
  harness's generic interface uses the parameter/variable name `region`
  for the indexed/aggregated categorical property; the actual graph
  property for this dataset is `primary_country` on both platforms.
- **Same client, same region:** both benchmarks run from the same
  machine; pick a CognoDB/Aura region close to that machine and record
  it in `config/platforms.yaml` so network RTT differences are visible
  rather than hidden.
- **Warm-up vs. cold start:** the harness always warms up before
  measuring. For cold-start numbers, run with `--warmup 0
  --read-iterations 1` right after reset/index-creation as a separate
  pass and record manually.
- **Free-tier throttling / burstable CPU:** CognoDB's `c0` is
  explicitly burstable. Aura Free's throttling behavior isn't
  documented the same way — note anything you observe. Re-run either
  benchmark more than once and report the spread (coefficient of
  variation, `src/common/stats.py`) if you want to speak to this
  directly.
- **Failures / timeouts:** any exception during the mixed workload is
  counted in `failed_ops` and surfaced as an automatic caveat in
  `RESULTS.md` — nothing is silently dropped from the QPS denominator.
- **Storage footprint:** neither platform's Bolt surface exposes
  `apoc.monitor.store()`-style byte counts on the free tier (that's a
  self-hosted-only APOC procedure); the adapter falls back to
  `apoc.meta.stats()` for node/relationship/label counts on both, and
  reports "not observable" honestly otherwise. Check each platform's
  console for any displayed storage figure and record manually.
- **No secrets in the repo:** every credential is read from `.env`
  (git-ignored). `results/*.json` and `RESULTS.md` never contain
  connection URIs or passwords.

## Repo layout

```
config/platforms.yaml           "cognodb" + "neo4j_aura_free" entries with resource specs
scripts/download_dataset.py     validates data/raw/netflix_titles.csv is in place
scripts/prepare_dataset.py      builds the actor co-appearance graph -> nodes.csv / edges.csv
src/adapters/base.py             platform-neutral interface
src/adapters/bolt_cypher.py      shared Bolt+Cypher adapter (CognoDB + Neo4j Aura)
src/workloads/                    timed read workloads + mixed workload
src/harness/run_benchmark.py     CLI runner -> results/<platform>.json
src/harness/report.py            results/*.json -> RESULTS.md + charts
tests/                             unit tests for the stats helpers
docs/ANALYSIS_TEMPLATE.md          structure for the written analysis
docs/ARTICLE_DRAFT.md              public-facing write-up draft
```

## Verification

`tests/test_stats.py` unit-tests the percentile/variance math the
report relies on — run `python -m pytest tests/ -v`. All Python modules
are syntax-checked with `python -m py_compile` in CI
(`.github/workflows/ci.yml`).

## License

MIT — see `LICENSE`.
