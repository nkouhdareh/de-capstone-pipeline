# ADR-010: Airflow triggers Spark and dbt in their own containers

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-11 |
| **Deciders** | Nastaran Kouhdareh |

## Context

Airflow had to orchestrate two tools it does not host: a PySpark job producing 45 million
Silver rows, and dbt building the warehouse. The obvious first move was to put both
inside the Airflow image using `_PIP_ADDITIONAL_REQUIREMENTS`.

That failed in an unusually opaque way. **Only the Celery worker crash-looped** — the
scheduler and webserver stayed healthy — with `RestartCount` climbing, health stuck at
`starting`, and **no traceback at all**; the log simply ended at `BACKEND=redis`.

The cause: `dbt-core` 1.12 requires `click>=8.3`, `cryptography>=46` and `protobuf>=6`,
all **above** apache-airflow 2.10.5's pins. `_PIP_ADDITIONAL_REQUIREMENTS` installs with
no constraint file, so it silently upgraded Airflow's own dependencies underneath it. The
worker died first because `celery worker` imports a wider surface than the other
components.

Two further constraints emerged:

- A `BashOperator` running `docker exec` **cannot work** — there is no Docker CLI inside
  the Airflow image.
- A Spark out-of-memory kill must **fail** the task. A naive `docker exec` wrapper that
  ignores the child's exit code would let a partial Silver flow into production while the
  task showed green.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **A — Spark and dbt each in their own container; Airflow triggers them over a mounted Docker socket via the Python Docker SDK (chosen)** | Each tool keeps its own dependency tree; Airflow stays on its pinned versions; the child's stdout streams into the Airflow task log and a non-zero exit raises | Airflow needs the Docker socket mounted, which is real coupling to the host; the target containers must already be running |
| B — dbt and PySpark inside the Airflow image | One stack, fewer containers | **Tried and it crash-looped the worker.** Airflow 2.10.5 and dbt-core 1.12 have genuinely incompatible pins |
| C — `BashOperator` + `docker exec` | Simple to read | Impossible — no Docker CLI in the Airflow image |
| D — `KubernetesPodOperator` | The production-grade answer to exactly this problem | Requires a Kubernetes cluster. Enormous machinery for one developer on one laptop |
| E — `DockerOperator` | Purpose-built, no custom helper | Starts a *new* container per task. The Spark container carries mounted data volumes and a warm Parquet cache; the value is in `exec`-ing into the long-lived container, not spawning fresh ones |

## Decision

We chose **A**. The architectural principle is:

> **Airflow does not process 45 million rows. It triggers the tools that do, and records
> the result.**

Three Docker stacks, eight containers: the Airflow stack (webserver, scheduler, worker,
triggerer, postgres, redis), `capstone-spark-jupyter`, and `capstone-dbt`. Airflow reaches
the other two over `/var/run/docker.sock` using the Python Docker SDK, which is already a
dependency and needs no CLI.

`build_silver` and the three dbt tasks share one `_exec_in_container()` helper that
streams the child container's output into the Airflow task log and **raises on a non-zero
exit** — so a Spark OOM fails the task loudly instead of passing silently.

A consequence that was not planned: **`load_raw` runs as a dbt macro** (`dbt run-operation`
in the dbt container) rather than through `snowflake.connector` in the Airflow worker,
because importing that connector would drag in `cryptography>=46` — the same conflict
again. That accident means **the Snowflake credential exists in exactly one place** in the
entire system. A dependency decision turned into a security property.

## Consequences

**Positive:** Dependency isolation is structural, not negotiated — dbt can be upgraded
without touching Airflow and vice versa. The credential surface collapsed to a single
container. The pattern is uniform: Airflow triggers Spark exactly the way it triggers dbt.
Eight tasks ran green in dependency order for 3 h 57 m 23 s at full scale.

**Negative / accepted trade-offs:**

- Mounting the Docker socket gives the Airflow worker effective root on the host. This is
  acceptable for a single-developer local project and would **not** be acceptable in
  production, where `KubernetesPodOperator` is the right answer.
- The target containers must already be running. Starting the Airflow stack does **not**
  start the repo stack, so a forgotten `docker compose up -d` produces
  `docker.errors.APIError: 409 … container is not running` one second into `build_silver`.
  This is now a runbook entry.
- Eight containers to keep track of instead of six.

**Revisit if:** the pipeline moves off the laptop. On managed Airflow (MWAA, Astronomer)
the Docker socket is unavailable, and each task would become a `KubernetesPodOperator` or
an ECS/Fargate task. The DAG's shape would not change — only the operator.
