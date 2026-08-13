#!/usr/bin/env bash
# Runs the full pipeline end-to-end against both platforms: dataset
# build + benchmark (CognoDB, then Neo4j AuraDB Free) + report
# generation. Requires data/raw/netflix_titles.csv already in place
# (see README "Dataset") and .env filled in for both platforms.
set -euo pipefail

python3 scripts/prepare_dataset.py --raw data/raw/netflix_titles.csv --out data/sample

for platform in cognodb neo4j_aura_free; do
  echo "=================================================="
  echo "Benchmarking: $platform"
  echo "=================================================="
  python3 -m src.harness.run_benchmark --platform "$platform" || {
    echo "WARNING: $platform failed -- see README caveats section, continuing.";
  }
done

python3 -m src.harness.report
echo "Done. See RESULTS.md and results/charts/*.png"
