# We loaded Netflix's entire cast list into two "same protocol, different vendor" graph databases. Here's where they diverged.

_Draft for a public technical audience (dev.to / Hashnode / personal
blog). Written to be finished in ~20 minutes once `RESULTS.md` has real
numbers — replace every `[[bracketed]]` placeholder, then delete this
note and the placeholders' brackets._

---

CognoDB Cloud makes a specific claim: point the official Neo4j driver
at it and it just works, no code changes. That's a testable claim, and
the most direct way to test it is to run the *exact same client code*
against CognoDB and against Neo4j's own managed offering, AuraDB Free,
on the same dataset, same queries, same hardware ceiling. So we did.

We turned Netflix's public title catalog into a graph — actors as
nodes, "co-starred in a title" as edges — and ran six workloads against
both platforms enough times to trust the percentiles: ingest, 1/2/3-hop
traversal, point and indexed lookups, group-by aggregation, and
sustained mixed read/write throughput at three concurrency levels.

This is not a "CognoDB wins" or "Neo4j wins" post. Two platforms is a
comparison, not a verdict — the honest framing is "here's exactly where
these two diverged and where they didn't, here's the code, reproduce it
yourself."

## The setup, in one paragraph

We derived a graph from Kaggle's [Netflix Movies and TV Shows
dataset](https://www.kaggle.com/datasets/shivamb/netflix-shows): every
distinct actor credited across ~8,800 titles becomes a node (36,439 of
them), every pair of actors sharing a title's cast becomes an edge
(305,471 of them — a multigraph, so co-starring in three different
titles means three edges, not one). Loaded into both CognoDB's free
`c0` tier and Neo4j AuraDB's Free tier over the identical official Bolt
driver code — literally the same Python adapter class, just pointed at
a different URI. Same six things measured on both: ingest throughput,
1/2/3-hop traversal latency, point and indexed lookups (by primary
production country), group-by aggregation, and mixed read/write
throughput at 1, 10, and 40 concurrent clients. All scripted —
[[link to repo]] — reproducible against your own free-tier accounts.

## What we expected going in

[[1-2 sentences: e.g. "Since both platforms speak the same protocol
and query language, we expected differences to come down to resource
tier and server-side engine implementation rather than anything
protocol-level -- and we expected Aura Free's typically larger resource
allocation to show up most in the CPU/RAM-sensitive workloads
(aggregation, high-concurrency mixed reads/writes)."]]

## What actually happened

### Loading

[[Report actual nodes/s and relationships/s for both, and whether the
gap (if any) tracks the resource-spec gap between the two free tiers.
Link results/charts/ingest_throughput.png.]]

### Traversals: does a hub-heavy graph stress the two engines differently?

[[results/charts/traversal_p95.png -- did the latency gap between the
two platforms grow, shrink, or stay flat from 1 to 3 hops?]]

### Lookups and aggregation

[[Point lookup should be close to identical on both if the primary-key
constraint is doing its job on both -- confirm or flag it. Aggregation
is the workload most likely to reflect the raw resource-tier gap
between the two free tiers, if there is one.]]

### Mixed workload: does the resource ceiling show up the same way on both?

[[results/charts/mixed_qps_vs_concurrency.png -- did QPS scaling look
similar on both platforms from 1 to 10 to 40 concurrent clients, or did
one plateau earlier? Report failed_ops verbatim, per platform.]]

## What we'd tell a friend deciding between the two

[[Honest, non-hedging synthesis based on these two data points --
where they were indistinguishable, where one had a real edge, and
whether that edge tracked the resource-tier difference (see
config/platforms.yaml fairness table) or looked like a genuine engine
difference.]]

## The methodology mistakes we tried hard not to make

We didn't compare a free tier against a paid tier. We used the exact
same adapter code against both platforms — no per-platform query
tuning that could tilt the result. We didn't average away the tail:
every number above is a p50 *and* a p95. Where either platform's real
resource spec turned out to have more headroom than the other's (see
the fairness table in the repo README), we say so rather than letting a
bigger free tier masquerade as a better engine. Where a run failed or
looked throttled on either platform, it's reported here, not dropped
from the average.

Full harness, raw JSON results, and instructions to reproduce every
number in this post against your own CognoDB and Neo4j Aura free-tier
accounts: **[[GitHub repo URL]]**.

---

_This compares two platforms, not the four-plus a full survey would
cover. The adapter interface (`src/adapters/base.py`) is built to make
adding self-hosted Memgraph, ArangoDB, TigerGraph, or others
straightforward if you want to extend it._
