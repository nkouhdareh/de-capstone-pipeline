import os
import sys
import snowflake.connector
from cryptography.hazmat.primitives import serialization

# Key-pair auth (Snowflake deprecated password-only sign-ins 2026-08-18).
# Env vars only; the key file lives outside the repo.
_key_path = os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"]
with open(_key_path, "rb") as _f:
    _private_key = serialization.load_pem_private_key(_f.read(), password=None).private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

conn = snowflake.connector.connect(
    account=os.environ["SNOWFLAKE_ACCOUNT"],
    user=os.environ["SNOWFLAKE_USER"],
    private_key=_private_key,
    role="DE_CAPSTONE_DBT_ROLE", warehouse="DE_CAPSTONE_WH",
    database="DE_CAPSTONE", schema="RAW",
)
cur = conn.cursor()
DATA = "D:/capstone/data"

# 1) NDC directory: upload the JSON file to the stage, then COPY it into the table
cur.execute(f"PUT 'file://{DATA}/bronze/drug_ndc/part-0000.json' @RAW.NDC_STAGE AUTO_COMPRESS=TRUE OVERWRITE=TRUE")
cur.execute("COPY INTO RAW.DRUG_NDC FROM @RAW.NDC_STAGE FILE_FORMAT=(FORMAT_NAME=RAW.FF_JSON) ON_ERROR='ABORT_STATEMENT'")
print("NDC rows   :", cur.execute("SELECT COUNT(*) FROM RAW.DRUG_NDC").fetchone()[0])

# 2) Silver — ONE month (smoke test): upload the Parquet files, then COPY by column name
month = f"{DATA}/silver/drug_event/receive_year=2023/receive_month=1"
cur.execute(f"PUT 'file://{month}/*.parquet' @RAW.SILVER_STAGE AUTO_COMPRESS=FALSE OVERWRITE=TRUE")
cur.execute("COPY INTO RAW.SILVER_DRUG_EVENT FROM @RAW.SILVER_STAGE "
            "FILE_FORMAT=(FORMAT_NAME=RAW.FF_PARQUET) MATCH_BY_COLUMN_NAME=CASE_INSENSITIVE "
            "PATTERN='.*[.]parquet' ON_ERROR='ABORT_STATEMENT'")
print("Silver rows:", cur.execute("SELECT COUNT(*) FROM RAW.SILVER_DRUG_EVENT").fetchone()[0])

conn.close()
print("done.")