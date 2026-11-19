"""Step 1 — Extraction & Load.

Reads the Kaggle "US Accidents (2016-2023)" CSV and loads it, untouched, into
PostgreSQL table raw_data.us_accidents_march23.

If the CSV is not found locally, it is downloaded with the Kaggle API and the
first ROW_LIMIT rows are kept (the full file is ~3 GB / 7.7M rows).
"""
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import config
from db_utils import write_table

log = logging.getLogger("ingest")

FULL_FILE_NAME = "US_Accidents_March23.csv"


def download_from_kaggle(target: Path) -> None:
    """Download the dataset with the Kaggle API and cut a ROW_LIMIT-row sample."""
    log.info("CSV not found at %s - downloading '%s' from Kaggle ...", target, config.KAGGLE_DATASET)
    from kaggle.api.kaggle_api_extended import KaggleApi  # imported lazily: needs kaggle.json

    api = KaggleApi()
    api.authenticate()
    download_dir = target.parent
    download_dir.mkdir(parents=True, exist_ok=True)
    api.dataset_download_files(config.KAGGLE_DATASET, path=str(download_dir), unzip=True, quiet=False)

    full_csv = download_dir / FULL_FILE_NAME
    log.info("Cutting first %s rows from %s", f"{config.ROW_LIMIT:,}", full_csv.name)
    pd.read_csv(full_csv, nrows=config.ROW_LIMIT, dtype=str).to_csv(target, index=False)


def extract() -> pd.DataFrame:
    csv_path = config.CSV_PATH
    if not csv_path.exists():
        download_from_kaggle(csv_path)

    log.info("Reading %s", csv_path.name)
    # Raw layer keeps every value exactly as in the source file (all text);
    # data types are fixed in transform.py.
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=True)
    df["_source_file"] = csv_path.name
    df["_ingested_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log.info("Extracted %s rows x %s columns", f"{len(df):,}", df.shape[1])
    return df


def load(df: pd.DataFrame) -> int:
    engine = config.get_engine()
    config.ensure_schemas(engine)
    n = write_table(df, engine, config.RAW_SCHEMA, config.RAW_TABLE)
    log.info("Loaded %s rows into %s.%s", f"{n:,}", config.RAW_SCHEMA, config.RAW_TABLE)
    return n


def run() -> int:
    return load(extract())


if __name__ == "__main__":
    run()
