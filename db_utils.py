"""Fast DataFrame -> PostgreSQL writes using COPY (much faster than INSERT)."""
import csv
from io import StringIO

import pandas as pd
from sqlalchemy.engine import Engine


def _copy_method(table, conn, keys, data_iter):
    """pandas.to_sql `method=` callable that streams rows with COPY FROM STDIN."""
    dbapi_conn = conn.connection
    with dbapi_conn.cursor() as cur:
        buf = StringIO()
        csv.writer(buf).writerows(data_iter)
        buf.seek(0)
        columns = ", ".join(f'"{k}"' for k in keys)
        name = f'"{table.schema}"."{table.name}"' if table.schema else f'"{table.name}"'
        cur.copy_expert(f"COPY {name} ({columns}) FROM STDIN WITH CSV", buf)


def write_table(df: pd.DataFrame, engine: Engine, schema: str, table: str) -> int:
    """Replace `schema.table` with the contents of df. Returns rows written."""
    df.to_sql(
        table,
        engine,
        schema=schema,
        if_exists="replace",
        index=False,
        method=_copy_method,
        chunksize=50_000,
    )
    return len(df)


def read_table(engine: Engine, schema: str, table: str) -> pd.DataFrame:
    return pd.read_sql_table(table, engine, schema=schema)
