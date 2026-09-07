"""Data access for the Streamlit dashboards, live or offline.

Two sources behind one interface:

  Snowflake (default)  key-pair auth as DE_CAPSTONE_SVC, the same service
                       identity dbt uses (ADR-012). There is no password.
  Offline              the Parquet export in DATA_DIR/offline/, queried with
                       DuckDB. No warehouse, no credentials, no network.

The dashboards do not know which one they got. Both return an object exposing
connection.cursor() -> execute(sql, params) / description / fetchall(), so
app/dashboard.py and app/dashboard_enhanced.py are unchanged.

Selecting a source:
    DASHBOARD_OFFLINE=1     force offline
    (unset)                 try Snowflake, fall back to offline if it fails

Refresh the offline copy with:  scripts/export_marts_offline.py

Self-test:  .venv-app/Scripts/python.exe app/db.py
"""

import os
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(REPO_ROOT / ".env")

ROLE = "DE_CAPSTONE_DBT_ROLE"
WAREHOUSE = "DE_CAPSTONE_WH"
DATABASE = "DE_CAPSTONE"
SCHEMA = "DBT_DEV"

OFFLINE_DIR = Path(os.environ.get("DATA_DIR", "D:/capstone/data")) / "offline"

# Set by connect() so a caller can report which source is live.
source = None


# ---------------------------------------------------------------------
# Snowflake
# ---------------------------------------------------------------------

def load_private_key():
    """Read the PEM key and hand the connector the DER form it expects."""
    import snowflake.connector  # noqa: F401  (kept next to its only user)
    from cryptography.hazmat.primitives import serialization

    key_path = Path(os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"])

    with key_path.open("rb") as handle:
        private_key = serialization.load_pem_private_key(
            handle.read(),
            password=None,
        )

    return private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def connect_snowflake():
    """Open a read-only-in-practice connection to the dbt marts."""
    import snowflake.connector

    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        private_key=load_private_key(),
        role=ROLE,
        warehouse=WAREHOUSE,
        database=DATABASE,
        schema=SCHEMA,
    )


# ---------------------------------------------------------------------
# Offline (DuckDB over the Parquet export)
# ---------------------------------------------------------------------

class OfflineCursor:
    """The slice of the Snowflake cursor API the dashboards actually use."""

    def __init__(self, duck):
        self._duck = duck
        self.description = None

    def execute(self, sql, params=()):
        # The dashboards were written against the Snowflake connector, which
        # uses pyformat placeholders. DuckDB uses qmark. No dashboard query
        # contains a literal per cent sign, so a plain swap is safe.
        self._duck.execute(sql.replace("%s", "?"), list(params or []))
        self.description = self._duck.description
        return self

    def fetchall(self):
        return self._duck.fetchall()

    def fetchone(self):
        return self._duck.fetchone()

    def close(self):
        self._duck.close()


class OfflineConnection:
    def __init__(self, duck):
        self._duck = duck

    def cursor(self):
        # A DuckDB cursor is an independent handle on the same database, so
        # concurrent Streamlit reruns do not trample each other's results.
        return OfflineCursor(self._duck.cursor())

    def close(self):
        self._duck.close()


def connect_offline():
    """Expose every Parquet file in OFFLINE_DIR as a view named after it."""
    import duckdb

    if not OFFLINE_DIR.is_dir():
        raise FileNotFoundError(
            f"No offline export at {OFFLINE_DIR}. "
            "Run scripts/export_marts_offline.py while Snowflake is reachable."
        )

    files = sorted(OFFLINE_DIR.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No .parquet files in {OFFLINE_DIR}.")

    duck = duckdb.connect(database=":memory:")
    for parquet in files:
        location = str(parquet).replace("'", "''")
        duck.execute(
            f'create view "{parquet.stem}" as '
            f"select * from read_parquet('{location}')"
        )

    return OfflineConnection(duck)


# ---------------------------------------------------------------------

def connect():
    """Snowflake unless told otherwise, with offline as the safety net."""
    global source

    if os.environ.get("DASHBOARD_OFFLINE", "").lower() in ("1", "true", "yes"):
        source = "offline"
        return connect_offline()

    try:
        connection = connect_snowflake()
        source = "snowflake"
        return connection
    except Exception as error:
        if not OFFLINE_DIR.is_dir():
            raise
        print(
            f"WARNING: Snowflake unavailable ({type(error).__name__}: {error}). "
            f"Falling back to the offline export in {OFFLINE_DIR}.",
            flush=True,
        )
        source = "offline"
        return connect_offline()


KNOWN_SIGNAL = """
select drug_name, reaction_pt, a, prr, ror, ror_ci_lower, chi2_yates,
       is_signal, is_signal_strict
from sem_signal_metrics
where drug_name = 'CLOZAPINE'
  and upper(reaction_pt) = 'NEUTROPENIA'
"""


def main():
    connection = connect()

    try:
        cursor = connection.cursor()

        if source == "snowflake":
            cursor.execute(
                "select current_user(), current_role(), current_warehouse()"
            )
            print("Connected as:", cursor.fetchone())
        else:
            print(f"Connected to the offline export at {OFFLINE_DIR}")
            cursor.execute("select count(*) from fct_report_drug_reaction")
            print("Fact rows:", f"{cursor.fetchone()[0]:,}")

        started = time.perf_counter()
        cursor.execute(KNOWN_SIGNAL)
        row = cursor.fetchone()
        elapsed = time.perf_counter() - started

        print("Known signal:", row)
        print(f"sem_signal_metrics query: {elapsed:.1f}s  (source: {source})")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
