CognoDB Cloud — a reproducible benchmark (Netflix actor graph)

This repo runs a scripted benchmark suite for CognoDB Cloud, measured on a fixed hardware tier against an identical derived dataset and a fixed set of logical queries. CognoDB speaks Bolt + Cypher over the official Neo4j Python driver, so it's benchmarked with a single adapter (src/adapters/bolt_cypher.py) — no ad-hoc query rewriting between runs to introduce inconsistency.

Scope — read this first

This harness was originally built to benchmark CognoDB against several other managed graph database platforms, as part of a broader comparison exercise. This version reports CognoDB Cloud only — no other platform's numbers are included here. If this is going toward something graded on "completeness of metrics" / breadth of comparison against other platforms, a single-platform run is a real but partial result — it establishes CognoDB's own baseline numbers, but makes no comparative claim against any competitor.

The harness is still built so comparators can be dropped in later without a rewrite: src/adapters/base.py defines the platform-neutral interface, src/adapters/bolt_cypher.py already works unmodified for any Bolt+Cypher platform (Neo4j AuraDB, self-hosted Memgraph, etc. — just point it at a different URI), and config/platforms.yaml is a list you can extend with one more entry per platform. Non-Cypher platforms (ArangoDB, TigerGraph, etc.) would need a new adapter class implementing the same interface — see base.py's abstract methods.

Platform benchmarked
Platform	Why it's here
CognoDB Cloud (c0 free tier)	Subject of the benchmark.
Resources used
Platform	Tier	vCPU	RAM	Disk
CognoDB Cloud	c0 (free)	0.5 (burstable)	256 MB	1 GB

config/platforms.yaml has this machine-readable, and run_benchmark.py refuses to run while the specs field is still TODO.

Dataset: a Netflix actor co-appearance graph

Rather than a SNAP social-network sample, this uses the "Netflix Movies and TV Shows" Kaggle dataset (shivamb/netflix-shows, netflix_titles.csv) — a per-title catalog with cast, director, country, and genre fields. This is the "movie/actor graph" alternative dataset explicitly permitted by the original assignment brief. It's not itself a graph — it's a flat table of ~8,800 titles — so scripts/prepare_dataset.py derives one:

Node (Person): one per distinct actor name appearing in any title's cast column: id, name, is_director (0/1), title_count, primary_country (most common production country across their titles — the indexed/aggregated property), primary_genre.
Relationship (ACTED_WITH): one edge per pair of actors who share a title's cast list. Not deduplicated across titles — two actors who co-star in 3 different titles get 3 ACTED_WITH edges (an intentional multigraph). The relationship is inherently undirected, so it's matched with an undirected Cypher pattern (-[:ACTED_WITH]-) everywhere — see bolt_cypher.py's docstring.

Actual size from the full dataset: 36,439 actor nodes, 305,471 ACTED_WITH relationships, from 7,982 titles with a non-empty cast — inside the assignment's 100k–500k relationship guidance with no down-sampling needed (see data/sample/manifest.json once generated).

Getting the CSV

Kaggle requires a free account and doesn't allow anonymous downloads:

Go to https://www.kaggle.com/datasets/shivamb/netflix-shows
Click Download, unzip it.
Place netflix_titles.csv at data/raw/netflix_titles.csv.
Optionally validate: python scripts/download_dataset.py --raw data/raw
What this repo measures
Category	Metric	What's reported
Loading	Ingest throughput	nodes/s, relationships/s, total wall-clock
Traversal	1-hop / 2-hop / 3-hop	p50 + p95 latency, from the same fixed set of 200 random start actors (degree ≥ 3)
Lookup	Point lookup by id	p50 + p95
Lookup	Indexed/filtered lookup by primary_country	p50 + p95, indexed
Aggregation	COUNT grouped by primary_country	p50 + p95
Mixed workload	Concurrent read/write	sustained QPS at concurrency 1 / 10 / 40, 80% read / 20% write
Footprint	Storage / memory	whatever CognoDB's console/Bolt surface exposes; "not observable" where it doesn't

Every read workload runs 10 warm-up calls + 100 measured iterations by default. Raw per-call latencies are saved in results/cognodb.json, so percentiles can be recomputed without re-running anything.

How to run
bash
git clone <this-repo-url>
cd cognodb-netflix-benchmark
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cp .env.example .env

CognoDB Cloud:

Sign up at https://console.cognodb.com/signup (no credit card).
Create a free c0 instance, pick a region, wait ~1 minute.
Copy the bolt+s://... URI and one-time-shown cognodb password into .env.
Set cognodb.region in config/platforms.yaml to the region you picked.

Dataset: see "Getting the CSV" above.

Run:

bash
python scripts/prepare_dataset.py --raw data/raw/netflix_titles.csv --out data/sample
python -m src.harness.run_benchmark --platform cognodb
python -m src.harness.report

or make prepare-data bench report, or ./run_all.sh for all of it in one shot.

Results

See RESULTS.md (generated by python -m src.harness.report after CognoDB has been benchmarked) — a full results table for every metric above, plus charts in results/charts/.

Analysis

See docs/ANALYSIS_TEMPLATE.md.

Methodology notes and caveats
Multigraph, not deduplicated: relationship count (305,471) counts co-starring instances, not unique collaborator pairs (289,207 unique pairs). Pass --dedupe-edges to prepare_dataset.py for the deduplicated version — re-run the whole benchmark if you switch modes, don't mix results from the two.
Undirected traversal: ACTED_WITH is matched with an undirected Cypher pattern on purpose — see src/adapters/bolt_cypher.py.
region naming is a code artifact, not a data claim: the harness's generic interface uses the parameter/variable name region for the indexed/aggregated categorical property; the actual graph property for this dataset is primary_country.
Warm-up vs. cold start: the harness always warms up before measuring. For cold-start numbers, run with --warmup 0 --read-iterations 1 right after reset/index-creation as a separate pass and record manually.
Free-tier throttling / burstable CPU: CognoDB's c0 is explicitly burstable. Re-run the benchmark more than once and report the spread (coefficient of variation, src/common/stats.py) if you want to speak to this directly.
Failures / timeouts: any exception during the mixed workload is counted in failed_ops and surfaced as an automatic caveat in RESULTS.md — nothing is silently dropped from the QPS denominator.
Storage footprint: CognoDB's Bolt surface doesn't expose apoc.monitor.store()-style byte counts on the free tier (that's a self-hosted-only APOC procedure); the adapter falls back to apoc.meta.stats() for node/relationship/label counts, and reports "not observable" honestly otherwise. Check the console for any displayed storage figure and record manually.
No secrets in the repo: every credential is read from .env (git-ignored). results/*.json and RESULTS.md never contain connection URIs or passwords.
Repo layout
config/platforms.yaml           "cognodb" entry with resource specs
scripts/download_dataset.py     validates data/raw/netflix_titles.csv is in place
scripts/prepare_dataset.py      builds the actor co-appearance graph -> nodes.csv / edges.csv
src/adapters/base.py             platform-neutral interface
src/adapters/bolt_cypher.py      Bolt+Cypher adapter (works for CognoDB or any other Bolt+Cypher platform)
src/workloads/                    timed read workloads + mixed workload
src/harness/run_benchmark.py     CLI runner -> results/<platform>.json
src/harness/report.py            results/*.json -> RESULTS.md + charts
tests/                             unit tests for the stats helpers
docs/ANALYSIS_TEMPLATE.md          structure for the written analysis
docs/ARTICLE_DRAFT.md              public-facing write-up draft
Verification

tests/test_stats.py unit-tests the percentile/variance math the report relies on — run python -m pytest tests/ -v. All Python modules are syntax-checked with python -m py_compile in CI (.github/workflows/ci.yml).

