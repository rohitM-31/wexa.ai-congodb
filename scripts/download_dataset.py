#!/usr/bin/env python3
"""
This dataset (Kaggle "Netflix Movies and TV Shows",
https://www.kaggle.com/datasets/shivamb/netflix-shows) requires a Kaggle
account and isn't fetchable with a plain anonymous download the way SNAP
datasets are, so this script just validates you've put the file where
prepare_dataset.py expects it, instead of downloading it for you.

Manual steps:
  1. Go to https://www.kaggle.com/datasets/shivamb/netflix-shows
  2. Click "Download" (Kaggle account required, free).
  3. Unzip it and place `netflix_titles.csv` at data/raw/netflix_titles.csv
     in this repo (create the data/raw/ folder if it doesn't exist).

Then run:
    python scripts/download_dataset.py --raw data/raw
to confirm the file is in place and has the expected columns, or just
skip straight to prepare_dataset.py -- it does the same check.
"""
import argparse
import csv
import os
import sys

EXPECTED_COLUMNS = {"show_id", "type", "title", "director", "cast",
                    "country", "date_added", "release_year", "rating",
                    "duration", "listed_in", "description"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--filename", default="netflix_titles.csv")
    args = ap.parse_args()

    path = os.path.join(args.raw, args.filename)
    if not os.path.exists(path):
        print(f"Not found: {path}\n", file=sys.stderr)
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    with open(path, encoding="utf-8", errors="replace") as f:
        header = set(next(csv.reader(f)))
    missing = EXPECTED_COLUMNS - header
    if missing:
        print(f"WARNING: {path} is missing expected columns: {missing}. "
              f"Are you sure this is the shivamb/netflix-shows CSV?", file=sys.stderr)
        sys.exit(1)

    print(f"OK: {path} found with the expected columns. "
          f"Run scripts/prepare_dataset.py next.")


if __name__ == "__main__":
    main()
