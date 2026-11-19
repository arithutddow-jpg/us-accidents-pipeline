"""Step 3 — The Publication.

Reads the final tables from the `production` schema and writes each one to its
own worksheet in a Google Sheet (via a Google Cloud service account).

Google Sheets allows at most 10,000,000 cells per spreadsheet, so the row-level
fact table is published with a reduced set of columns (FACT_SHEET_COLUMNS) and
written in chunks.
"""
import logging
import math

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
from gspread_dataframe import set_with_dataframe

import config
from db_utils import read_table

log = logging.getLogger("publish")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
SHEETS_CELL_LIMIT = 10_000_000
CHUNK_ROWS = 10_000

# production table -> worksheet name (order = tab order in the spreadsheet)
TABLES = [
    "kpi_summary",
    "fact_accidents",
    "agg_hour_weekday",
    "agg_daily",
    "agg_monthly",
    "agg_state",
    "agg_county",
    "agg_city",
    "agg_weather",
    "agg_weather_condition",
    "agg_weather_bands",
    "agg_road_feature",
    "agg_day_night",
    "agg_severity_impact",
    "agg_risk_combo",
]

FACT_SHEET_COLUMNS = [
    "accident_id", "severity", "severity_label", "is_severe",
    "start_time", "start_date", "year_month", "day_of_week", "is_weekend", "hour", "time_of_day",
    "duration_min_capped", "distance_mi_capped",
    "city", "county", "state_name", "lat_lng",
    "temperature_f", "visibility_mi", "wind_speed_mph",
    "weather_group", "is_wet", "day_night",
    "junction", "traffic_signal", "crossing", "stop", "poi_count", "risk_combo",
]


def get_client() -> gspread.Client:
    if not config.GOOGLE_CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"Service-account key not found: {config.GOOGLE_CREDENTIALS_FILE}. "
            "See README section 'Google API credentials'."
        )
    creds = Credentials.from_service_account_file(str(config.GOOGLE_CREDENTIALS_FILE), scopes=SCOPES)
    return gspread.authorize(creds)


def to_sheet_values(df: pd.DataFrame) -> pd.DataFrame:
    """Make every value JSON-safe for the Sheets API."""
    out = df.copy()
    for col in out.columns:
        s = out[col]
        if pd.api.types.is_datetime64_any_dtype(s):
            date_only = (s.dropna().dt.normalize() == s.dropna()).all()
            out[col] = s.dt.strftime("%Y-%m-%d" if date_only else "%Y-%m-%d %H:%M:%S")
        elif s.dtype == object:
            out[col] = s.map(lambda v: v.isoformat() if hasattr(v, "isoformat") else v)
    return out.astype(object).where(out.notna(), "")


def get_or_create_ws(sh: gspread.Spreadsheet, title: str, rows: int, cols: int) -> gspread.Worksheet:
    try:
        ws = sh.worksheet(title)
        ws.clear()
        ws.resize(rows=max(rows, 2), cols=max(cols, 1))
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=max(rows, 2), cols=max(cols, 1))
    return ws


def write_large(ws: gspread.Worksheet, df: pd.DataFrame) -> None:
    """Write header + rows in chunks so each API request stays small."""
    ws.update(values=[list(df.columns)], range_name="A1", value_input_option="RAW")
    values = df.values.tolist()
    n_chunks = math.ceil(len(values) / CHUNK_ROWS)
    for i in range(n_chunks):
        start = i * CHUNK_ROWS
        chunk = values[start:start + CHUNK_ROWS]
        ws.update(values=chunk, range_name=f"A{start + 2}", value_input_option="RAW")
        log.info("    %s: chunk %d/%d (%s rows)", ws.title, i + 1, n_chunks, f"{start + len(chunk):,}")


def run(dry_run: bool = False) -> dict[str, int]:
    if not dry_run and not config.GOOGLE_SHEET_ID:
        raise ValueError("GOOGLE_SHEET_ID is empty - set it in .env")

    engine = config.get_engine()
    frames = {}
    for name in TABLES:
        df = read_table(engine, config.PROD_SCHEMA, name)
        if name == "fact_accidents":
            df = df[FACT_SHEET_COLUMNS]
        frames[name] = to_sheet_values(df)

    total_cells = sum((len(f) + 1) * f.shape[1] for f in frames.values())
    log.info("Total cells to publish: %s (limit %s)", f"{total_cells:,}", f"{SHEETS_CELL_LIMIT:,}")
    if total_cells > SHEETS_CELL_LIMIT * 0.95:
        raise ValueError("Too many cells for one Google Sheet - reduce FACT_SHEET_COLUMNS or ROW_LIMIT")
    if dry_run:
        for name, df in frames.items():
            log.info("  [dry-run] %-24s %8s rows x %d cols", name, f"{len(df):,}", df.shape[1])
        return {n: len(f) for n, f in frames.items()}

    client = get_client()
    sh = client.open_by_key(config.GOOGLE_SHEET_ID)
    log.info("Opened spreadsheet: %s", sh.title)

    published = {}
    for name, df in frames.items():
        ws = get_or_create_ws(sh, name, rows=len(df) + 1, cols=df.shape[1])
        if len(df) > CHUNK_ROWS:
            write_large(ws, df)
        else:
            set_with_dataframe(ws, df, include_index=False, resize=True)
        ws.freeze(rows=1)
        published[name] = len(df)
        log.info("  sheet %-24s %8s rows", name, f"{len(df):,}")

    # remove the default empty tab if it is still there
    for ws in sh.worksheets():
        if ws.title in ("Sheet1", "แผ่น1", "ชีต1") and len(sh.worksheets()) > 1:
            sh.del_worksheet(ws)

    log.info("Done: https://docs.google.com/spreadsheets/d/%s", config.GOOGLE_SHEET_ID)
    return published


if __name__ == "__main__":
    import sys

    run(dry_run="--dry-run" in sys.argv)
