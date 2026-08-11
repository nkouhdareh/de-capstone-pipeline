# dbt runs in its own container so its dependencies never collide with Airflow's.
# (dbt-core 1.12 needs click>=8.3 / cryptography>=46 / protobuf>=6 — all above
#  apache-airflow 2.10.5's pins; sharing one interpreter crash-loops the celery worker.)
FROM python:3.11-slim

# git is required by `dbt deps` to fetch hub packages (dbt_utils)
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "dbt-snowflake==1.12.0"

WORKDIR /dbt