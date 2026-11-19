"""Shared settings and database connection for every pipeline step."""
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

POSTGRES_USER = os.getenv("POSTGRES_USER", "de_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "de_password")
POSTGRES_DB = os.getenv("POSTGRES_DB", "us_accidents")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5433")

CSV_PATH = BASE_DIR / os.getenv("CSV_PATH", "data/US_Accidents_March23_120k.csv")
KAGGLE_DATASET = os.getenv("KAGGLE_DATASET", "sobhanmoosavi/us-accidents")
ROW_LIMIT = int(os.getenv("ROW_LIMIT", "120000"))

GOOGLE_CREDENTIALS_FILE = BASE_DIR / os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")

RAW_SCHEMA = "raw_data"
PROD_SCHEMA = "production"
RAW_TABLE = "us_accidents_march23"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)


def get_engine() -> Engine:
    url = (
        f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )
    return create_engine(url, pool_pre_ping=True)


def ensure_schemas(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {RAW_SCHEMA}"))
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {PROD_SCHEMA}"))
