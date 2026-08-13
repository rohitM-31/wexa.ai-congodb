`data/raw/netflix_titles.csv` and everything in `data/sample/` are
git-ignored, since the raw file comes from Kaggle (requires a login to
download, so it isn't fetched automatically) and the sample is fully
regenerated from it:

```bash
# 1. Manually download netflix_titles.csv from
#    https://www.kaggle.com/datasets/shivamb/netflix-shows
#    and place it at data/raw/netflix_titles.csv

# 2. Validate it landed correctly (optional)
python scripts/download_dataset.py --raw data/raw

# 3. Build the actor co-appearance graph
python scripts/prepare_dataset.py --raw data/raw/netflix_titles.csv --out data/sample --seed 42
```

`data/sample/manifest.json` and `data/sample/start_nodes.json` (small,
not the raw CSVs) are safe and useful to commit once generated, since
they document exactly which graph was benchmarked and pin the fixed
start-node set every traversal query used.
