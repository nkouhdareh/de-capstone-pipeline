"""
pv_pipeline — openFDA drug-safety (pharmacovigilance) signal pipeline.

Bronze (ingest) -> Silver (PySpark) -> S3 -> Snowflake RAW -> dbt.

Spark does NOT run inside Airflow. The existing pyspark container does the work and
Airflow triggers it over the mounted Docker socket (docker exec -> spark-submit).

Trigger with config, e.g. {"months": "2023-01"} (default) or {"months": "all"}.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator


REPO = "/opt/airflow/repo"
SPARK_CONTAINER = "capstone-spark-jupyter"
DBT_CONTAINER = "capstone-dbt"
DBT_PROJECT = "/dbt"

# Paths INSIDE the Spark container. Deliberately NOT silver/drug_event:
# production Silver (45,030,932 rows) is never written by this DAG.
SILVER_OUT = "/home/jovyan/silver/pipeline"
QUAR_OUT = "/home/jovyan/quarantine/pipeline"
SILVER_METRICS = "/home/jovyan/silver/_pipeline_metrics"

# The same Silver output, as the Airflow worker sees it (D:/capstone/data -> /data).
SILVER_OUT_LOCAL = "/data/silver/pipeline"

# Smoke prefix — keeps the validated silver/drug_event/ prefix (486 files,
# read by RAW.SILVER_S3_STAGE) untouched until cutover.
# S3_SILVER_PREFIX = "silver_smoke"

# The Airflow-produced Silver gets its own prefix, read by RAW.SILVER_PIPELINE_S3_STAGE.
# The hand-uploaded silver/drug_event/ (486 files, read by RAW.SILVER_S3_STAGE) stays
# untouched as the fallback artifact — the two must never be mixed, since the DAG's
# files carry different UUID names and would add to that prefix rather than replace it.
S3_SILVER_PREFIX = "silver_pipeline"

DEFAULT_ARGS = {
    "owner": "nasta",
    "retries": 2,
    "retry_delay": timedelta(minutes=3),
}


def _exec_in_container(container, command, environment=None):
    """Run a command in another container over the mounted Docker socket.

    Streams the command's output into this task's log and raises on a
    non-zero exit, so a failure inside the other container fails the task.
    """
    import docker

    print("Container:", container)
    print("Command:", " ".join(command))

    client = docker.APIClient(base_url="unix://var/run/docker.sock")

    exec_id = client.exec_create(
        container,
        cmd=command,
        environment=environment or {},
    )["Id"]

    for chunk in client.exec_start(exec_id, stream=True):
        print(chunk.decode("utf-8", errors="replace"), end="")

    exit_code = client.exec_inspect(exec_id)["ExitCode"]
    print("exit code:", exit_code)

    if exit_code != 0:
        raise RuntimeError(
            f"{command[0]} failed in {container} with exit code {exit_code}"
        )


def run_build_silver(**context):
    """Run build_silver.py inside the pyspark container."""
    months = context["params"]["months"]

    command = [
        "/usr/local/spark/bin/spark-submit",
        "--master",
        "local[4]",
        "--driver-memory",
        "4g",
        "--conf",
        "spark.unsafe.sorter.spill.read.ahead.enabled=false",
        "/home/jovyan/scripts/build_silver.py",
        "--months",
        months,
    ]

    environment = {
        "SILVER_OUT": SILVER_OUT,
        "QUAR_OUT": QUAR_OUT,
        "SILVER_METRICS": SILVER_METRICS,
    }

    print("Months:", months)

    _exec_in_container(SPARK_CONTAINER, command, environment)


def run_dbt(dbt_command, **_):
    """Run a dbt command inside the dbt container."""
    command = ["dbt"] + dbt_command + ["--profiles-dir", DBT_PROJECT]
    _exec_in_container(DBT_CONTAINER, command)


with DAG(
    dag_id="pv_pipeline",
    description="openFDA drug-safety signal pipeline",
    start_date=datetime(2025, 1, 1),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    params={"months": "2023-01"},
    tags=["capstone"],
) as dag:

    # Idempotent: Bronze is immutable, so re-download only if it is missing.
    ingest_ndc = BashOperator(
        task_id="ingest_ndc",
        bash_command=(
            "if [ -f /data/bronze/drug_ndc/part-0000.json ]; then "
            "echo 'SKIP: bronze drug_ndc already ingested'; "
            f"else cd {REPO} && python scripts/ingest_drug_ndc.py; fi"
        ),
    )

    ingest_faers = BashOperator(
        task_id="ingest_faers",
        bash_command=(
            "if [ -n \"$(ls -A /data/bronze/drug_event 2>/dev/null)\" ]; then "
            "echo 'SKIP: bronze drug_event already ingested'; "
            f"else cd {REPO} && python scripts/ingest_drug_event.py; fi"
        ),
    )

    build_silver = PythonOperator(
        task_id="build_silver",
        python_callable=run_build_silver,
        execution_timeout=timedelta(hours=12),
        retries=0,
    )

    upload_s3 = BashOperator(
        task_id="upload_s3",
        bash_command=(
            f"aws s3 sync {SILVER_OUT_LOCAL}/ "
            f"s3://$PV_S3_BUCKET/{S3_SILVER_PREFIX}/ "
            "--exclude '*' --include '*.parquet' "
            "--exclude '*_temporary*' --exclude '*.spark-staging*'"
        ),
    )

    # ---- PRODUCTION-CUTOVER TASKS — commented out for the one-month smoke ----
    # load_raw   = PythonOperator(task_id="load_raw_s3", python_callable=load_raw_s3)
    dbt_build = PythonOperator(
        task_id="dbt_build",
        python_callable=run_dbt,
        op_kwargs={"dbt_command": ["build"]},
        execution_timeout=timedelta(hours=2),
    )

    dbt_test = PythonOperator(
        task_id="dbt_test",
        python_callable=run_dbt,
        op_kwargs={"dbt_command": ["test"]},
        execution_timeout=timedelta(hours=1),
    )
    # metrics    = PythonOperator(task_id="publish_metrics", python_callable=publish_metrics)

    # Safe smoke chain:
    ingest_ndc >> ingest_faers >> build_silver >> upload_s3

    # Full chain (cutover):
    # ingest_ndc >> ingest_faers >> build_silver >> upload_s3 >> load_raw >> dbt_build >> dbt_test >> metrics