"""Snowflake connection for the Streamlit dashboard.

Key-pair auth as DE_CAPSTONE_SVC - the same service identity dbt uses
(docs/Layer Explanation/Airflow.md Part F). There is no password.

Self-test:  .venv-app/Scripts/python.exe app/db.py
"""

import os
import time
from pathlib import Path

import snowflake.connector
from cryptography.hazmat.primitives import serialization
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(REPO_ROOT / ".env")

ROLE = "DE_CAPSTONE_DBT_ROLE"
WAREHOUSE = "DE_CAPSTONE_WH"
DATABASE = "DE_CAPSTONE"
SCHEMA = "DBT_DEV"


def load_private_key():
    """Read the PEM key and hand the connector the DER form it expects."""
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


def connect():
    """Open a read-only-in-practice connection to the dbt marts."""
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        private_key=load_private_key(),
        role=ROLE,
        warehouse=WAREHOUSE,
        database=DATABASE,
        schema=SCHEMA,
    )


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

        cursor.execute(
            "select current_user(), current_role(), current_warehouse()"
        )
        print("Connected as:", cursor.fetchone())

        started = time.perf_counter()
        cursor.execute(KNOWN_SIGNAL)
        row = cursor.fetchone()
        elapsed = time.perf_counter() - started

        print("Known signal:", row)
        print(f"sem_signal_metrics query: {elapsed:.1f}s")

    finally:
        connection.close()


if __name__ == "__main__":
    main()