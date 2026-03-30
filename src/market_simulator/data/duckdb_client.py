from __future__ import annotations

import duckdb

def create_connection(database: str = ":memory:", s3_region: str = "us-west-2"):
    conn = duckdb.connect(database=database)
    conn.execute("INSTALL httpfs;")
    conn.execute("LOAD httpfs;")
    conn.execute(f"SET s3_region='{s3_region}';")
    conn.execute("SET s3_url_style='path';")
    conn.execute("SET s3_use_ssl=true;")
    try:
        conn.execute("CALL load_aws_credentials();")
    except Exception:
        pass
    return conn
