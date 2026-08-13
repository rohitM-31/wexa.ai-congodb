# Analysis

_Fill this in after `RESULTS.md` has real numbers from `make bench-all
report`. Two platforms, not four+ -- keep conclusions scoped to what
two data points actually support (don't generalize "CognoDB beats
managed graph databases" from a sample of one comparator). Delete this
italic instruction block when done._

## Summary (2-3 sentences)

State the headline finding plainly: did one platform separate itself
from the other, or were they within noise of each other for most
workloads? Resist declaring an overall "winner" from two data points.

## Loading

- Which platform ingested faster, and by roughly how much?
- Is the gap explained by batching strategy (both use the same driver
  and batch size, so this should mostly isolate to server-side
  ingest performance), or by CognoDB's burstable-CPU credit budget
  running out partway through a ~305k-edge load?

## Traversals (1 / 2 / 3-hop)

- This graph has hub actors (prolific cast members), so 2-/3-hop
  traversal fan-out can be large. Does the latency gap between the two
  platforms grow, shrink, or stay flat as hop depth increases?
- Note any platform whose p95 diverges sharply from its p50 at higher
  hop counts -- a sign of throttling or connection contention, not
  necessarily a query-engine difference.

## Lookups

- Point lookup should be near-identical on both platforms if the
  uniqueness constraint on `id` got created on both -- verify this
  rather than assuming it.
- Indexed lookup on `primary_country`: this property is skewed (US
  dominates the underlying catalog) -- note that a skewed index lookup
  is a different access pattern than group-by aggregation over the
  same property, even though they touch the same data.

## Aggregation

- A full-scan group-by over ~36k nodes is the workload least likely to
  be sensitive to Cypher-planner differences between two same-protocol
  platforms, and most sensitive to available RAM -- expect this number
  to track the fairness table (vCPU/RAM) more than anything else.

## Mixed workload / concurrency

- Plot shape at concurrency 1 -> 10 -> 40
  (`results/charts/mixed_qps_vs_concurrency.png`): does QPS keep
  scaling with concurrency on both platforms, plateau, or fall?
- Report any `failed_ops` at higher concurrency verbatim, and on which
  platform they occurred.

## Footprint

- Report whatever each platform's `footprint` block captured, plus
  anything the consoles show that Bolt doesn't expose.

## Fairness analysis of free-tier limits

- Fill in Neo4j AuraDB Free's actual vCPU/RAM/disk (from
  `config/platforms.yaml` once you've confirmed them) next to
  CognoDB's 0.5 vCPU / 256MB / 1GB. If Aura Free has materially more
  headroom -- historically true -- explicitly discount its raw ranking
  on CPU/RAM-sensitive metrics (loading, aggregation, high-concurrency
  mixed workload) in your written conclusion. A win driven by more RAM
  isn't a win for the query engine.

## What this does *not* tell you

Two platforms is not "graph databases in general." A single free-tier
instance benchmark doesn't predict multi-node/production behavior, the
multigraph edge model makes degree/fan-out higher than a deduplicated
version of the same data would show, and 100 iterations bounds
confidence on p50/p95 more than p99 -- say so rather than over-claiming
precision you don't have.
