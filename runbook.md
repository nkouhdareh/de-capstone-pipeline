# Runbook

Operational manual for the openFDA drug-safety signal pipeline: how to start it, run it,
verify it, recover it, and shut it down safely.

**Read §0 before running anything.**

---

## 0. Never do this

| Command | What it destroys | Do this instead |
|---|---|---|
| `docker compose down -v` **in `airflow/`** | Deletes `postgres-db-volume` — Airflow's metadata database. Your login, every DAG run record and all task history. | `docker compose stop` |
| `docker compose down -v` in the repo root | Removes the Spark container's named volumes; the Parquet cache must be rebuilt (~16 min). | `docker compose stop` |
| `DELETE FROM RAW.SILVER_DRUG_EVENT` before a `COPY` | Leaves Snowflake's per-file load metadata intact, so the next `COPY` loads the same files **again** and doubles the row count. | `TRUNCATE TABLE` — it clears the load metadata |
| `aws s3 sync` without `--delete` | Accumulates files. Spark names output with a per-run UUID, so an old run's 13 files survive alongside 486 new ones — and the next load inserts 46,580,195 rows instead of 45,030,932. | Always `sync --delete`, scoped to `silver_pipeline/` |
| Anything that writes to `s3://.../silver/drug_event/` | That prefix is the **protected fallback artifact** — 486 objects / 3,913,635,942 bytes, verified by `s3-contract.yml` on every push. | Write only to `silver_pipeline/` |
| `docker compose up/down/stop/restart`, `wsl --shutdown`, or letting the laptop sleep **while a run is in progress** | Kills a 4-hour Spark job. | Wait. Editing docs, Zoom and read-only `docker` commands are safe. |

---

## 1. Environment

### Prerequisites

| Requirement | Version / note |
|---|---|
| Python | 3.11 |
| Docker Desktop | With a WSL2 memory reservation of ≥ 10 GB — see §1.3 |
| Disk space | **~70 GB free** on the data drive (64 GB Bronze + Silver Parquet + Spark spill) |
| AWS account | S3 bucket in the **same region** as the Snowflake account |
| Snowflake account | Warehouse `DE_CAPSTONE_WH` (XS, `AUTO_SUSPEND = 60`) |

### 1.1 Environment variables

All live in a git-ignored `.env` at the repo root, except the Airflow stack's own copy.

| Variable | Used by | Purpose |
|---|---|---|
| `DATA_DIR` | ingestion, Spark | Where Bronze and Silver live. **Never inside the repo.** |
| `OPENFDA_API_KEY` | ingestion | Raises the API limit to 120,000 requests/day |
| `SNOWFLAKE_ACCOUNT` | dbt, loaders, dashboards | Account identifier |
| `SNOWFLAKE_USER` | dbt, loaders, dashboards | `DE_CAPSTONE_SVC` — the service identity, not a human login |
| `SNOWFLAKE_PRIVATE_KEY_PATH` | dbt, loaders, dashboards | Path to the RSA private key, **outside the repo** |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | `upload_s3` only | The scoped uploader identity |
| `AWS_REGION`, `S3_BUCKET` | `upload_s3` | Bucket and region |

Load them into a shell:

```bash
cd /d/capstone/de-capstone && set -a && source .env && set +a
```

`airflow/.env` holds the same values again — a Compose `.env` only does variable
interpolation, so the compose file passes them into the containers explicitly.

**There is no Snowflake password anywhere in this project.** `DE_CAPSTONE_SVC` is a
`TYPE = SERVICE` user, which cannot have one. CI checks this on every commit.

### 1.2 The three Python environments

They are separate on purpose — Streamlit's dependencies must never touch dbt's.

| Venv | Purpose | Install |
|---|---|---|
| `.venv` | Ingestion scripts | `pip install requests python-dotenv` |
| `.venv-dbt` | dbt on the host, and the rollback loader | `pip install "dbt-snowflake==1.12.0"` |
| `.venv-app` | Streamlit dashboards | `pip install streamlit snowflake-connector-python python-dotenv` |

In Git Bash, activation can leave `python` pointing at the system interpreter. **Call the
executable by path** rather than activating:

```bash
alias dbt="/d/capstone/de-capstone/.venv-dbt/Scripts/dbt.exe"
```

### 1.3 Docker memory

Create or edit `%UserProfile%\.wslconfig`:

```
[wsl2]
memory=10GB
```

Then `wsl --shutdown` and restart Docker Desktop. Without this, Spark fails with a
**native** memory error while the same job passes when run manually — see §6.

### 1.4 Ports

| Port | Service |
|---|---|
| 8080 | Airflow UI (`airflow` / `airflow`) |
| 8081 | dbt docs (8080 is taken) |
| 8501 | Streamlit — original dashboard |
| 8502 | Streamlit — enhanced dashboard |
| 8888 | Jupyter (Spark container) |

Snowflake is not localhost — it is `app.snowflake.com`.

---

## 2. Run the pipeline

### 2.1 Start

Both compose files. **The Airflow stack does not start the other two.**

```bash
cd /d/capstone/de-capstone && docker compose up -d
```

```bash
cd /d/capstone/de-capstone/airflow && docker compose up -d
```

Wait 1–2 minutes — each Airflow container pip-installs on start — then confirm
**8 containers**:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```

Expect 6 Airflow containers plus `capstone-spark-jupyter` and `capstone-dbt`. If Spark
is missing, `build_silver` fails after one second with a 409.

### 2.2 Trigger

```bash
cd /d/capstone/de-capstone/airflow && docker compose exec airflow-scheduler airflow dags trigger pv_pipeline -c '{"months":"2023-01"}'
```

| Config | What it does | Runtime |
|---|---|---|
| `{"months":"2023-01"}` | Rebuilds January only — **but still exercises the entire chain** | ~20 min |
| `{"months":"all"}` | Rebuilds all 24 months | ~4 h |

A one-month run is the right default. Dynamic partition overwrite rewrites only January
locally, the other 23 months stay on disk, `sync --delete` removes nothing, S3 keeps all
486 files, and `load_raw` still loads the full 45,030,932 rows. Same final numbers,
twelve times faster.

**The chain:**

```
ingest_ndc → ingest_faers → build_silver → upload_s3 → load_raw → dbt_build → dbt_test → publish_metrics
```

### 2.3 Watch progress without the UI

The Grid view can hang on the very large `build_silver` log.

```bash
cd /d/capstone/de-capstone/airflow && MSYS_NO_PATHCONV=1 docker compose exec airflow-scheduler airflow dags list-runs -d pv_pipeline
```

```bash
MSYS_NO_PATHCONV=1 docker exec capstone-spark-jupyter sh -c 'ls -d /home/jovyan/silver/pipeline/receive_year=*/receive_month=* | wc -l'
```

To see which task instances actually existed in a historical run — the graph view is not
trustworthy for this, see §6:

```bash
cd /d/capstone/de-capstone/airflow && MSYS_NO_PATHCONV=1 docker compose exec airflow-scheduler airflow tasks states-for-dag-run pv_pipeline "<run_id>"
```

### 2.4 Run one task on its own

No DAG run, no dependencies. Useful for `upload_s3` (re-upload without re-running Spark)
and `dbt_test` (read-only).

```bash
cd /d/capstone/de-capstone/airflow && MSYS_NO_PATHCONV=1 docker compose exec airflow-scheduler airflow tasks test pv_pipeline dbt_test 2026-08-13
```

### 2.5 Stop

```bash
cd /d/capstone/de-capstone/airflow && docker compose stop
```

```bash
cd /d/capstone/de-capstone && docker compose stop
```

`stop` pauses the containers and keeps everything. See §0 for what `down -v` destroys.

---

## 3. Verify a run — the expected gates

A run is correct when **all** of these hold. Anything else means stop and investigate.

| Gate | Where | Expected |
|---|---|---|
| Silver rows produced | `build_silver` log | `Requested-month Silver rows: 45030932` (all) or `1549263` (2023-01) |
| S3 object count | `upload_s3` log / `aws s3 ls` | **486 objects** in `silver_pipeline/` |
| RAW loaded | `load_raw` log | `RAW.SILVER_DRUG_EVENT rows: 45030932` · `RAW.DRUG_NDC rows: 136520` |
| Models built | `dbt_build` log | **`PASS=53 WARN=0 ERROR=0`** |
| Tests | `dbt_test` log | **`PASS=42 WARN=0 ERROR=0`** |
| Published metrics | `publish_metrics` log | `fct_report_drug_reaction rows: 45030932` · `signals (is_signal): 315270` |
| Protected artifact | `s3-contract.yml` | **486 objects / 3,913,635,942 bytes** in `silver/drug_event/` |
| **The known-answer check** | Dashboard or SQL | **clozapine → neutropenia · PRR 35.94 · ROR 46.76 · ROR-CI 45.21 · χ² 142,896 · 5,571 cases** |

The last one matters most. **If a known-answer signal is unchanged after a reload, the
load path is faithful.** It is what proved the S3 cutover did not alter the data: same
inputs, same maths, same answer, different infrastructure.

Two further checks that must close arithmetically:

- Monthly case counts for clozapine → neutropenia **sum to 5,571** across **24 months**.
  Each case has exactly one `receive_date`, so the sum *must* close.
- `dim_drug` shows **4,368 / 4,368**; the KPI row reads **45,030,932 / 1,240,645 / 315,270**.

---

## 4. Component operations

### 4.1 Ingestion — Bronze

Run once. Bronze is immutable; the Airflow ingest tasks skip when it is present.

```bash
source .venv/Scripts/activate && python scripts/ingest_drug_ndc.py
```

```bash
python scripts/ingest_drug_label.py
```

```bash
python scripts/ingest_drug_event.py
```

`ingest_drug_event.py` goes **day by day**, 1,000 records per request, so it never hits
openFDA's `skip` ceiling. It **raises** on a failed page rather than treating an empty
reply as "day finished" — an earlier version did, and silently produced short days.

Label and NDC use the openFDA bulk download index rather than the paged API.

**Expected:** 2,687,675 event reports · 261,258 labels · 136,520 NDC products.
Runtime for the event download: 30–60 minutes.

To re-fetch specific days, edit the `DAYS` list in `scripts/backfill_days.py` and run it.

### 4.2 Silver — the Spark job by hand

Normally Airflow does this. To run it directly:

```bash
MSYS_NO_PATHCONV=1 docker exec -e SILVER_OUT=/home/jovyan/silver/smoke_2023_01 -e QUAR_OUT=/home/jovyan/quarantine/smoke_2023_01 -e SILVER_METRICS=/home/jovyan/silver/_smoke_metrics_2023_01 capstone-spark-jupyter /usr/local/spark/bin/spark-submit --driver-memory 4g /home/jovyan/scripts/build_silver.py --months 2023-01
```

Three things about that command are not optional:

- **`spark-submit`, not `python`** — there is no pyspark on the plain interpreter.
- **`--driver-memory 4g` explicitly** — `spark-submit` ignores the in-code driver memory,
  and without it the job OOMs with exit 137.
- **`SILVER_OUT` / `QUAR_OUT` / `SILVER_METRICS` have no defaults** — the job refuses to
  start without them, so it cannot accidentally overwrite production Silver.

### 4.3 dbt — directly, bypassing Airflow

```bash
MSYS_NO_PATHCONV=1 docker exec capstone-dbt dbt build --profiles-dir /dbt
```

```bash
MSYS_NO_PATHCONV=1 docker exec capstone-dbt dbt run-operation publish_metrics --profiles-dir /dbt
```

From the host instead:

```bash
cd /d/capstone/de-capstone && set -a && source .env && set +a && cd de_capstone && dbt debug
```

Expect `All checks passed!`. Then `dbt build` (10 models + seed + 42 tests, in DAG order)
or `dbt test` for tests only.

**Lineage docs** — on port 8081, because Airflow owns 8080:

```bash
cd /d/capstone/de-capstone/de_capstone && dbt docs generate && dbt docs serve --port 8081
```

### 4.4 Dashboards

**Hosted (no local setup):** Snowsight → **Projects → Streamlit → Drug Safety Signals**
(`DE_CAPSTONE.DBT_DEV`, warehouse `DE_CAPSTONE_WH`, running as `DE_CAPSTONE_DBT_ROLE`).
Use **Share** to hand someone the URL.

Editing is through the Snowsight code editor. The canonical copy is
`app/dashboard_snowflake.py` — paste between the two after editing either side so they
do not drift. `environment.yml` in the Files panel holds the package list.

**Local:**

```bash
cd /d/capstone/de-capstone && .venv-app/Scripts/streamlit.exe run app/dashboard.py --server.port 8501
```

First launch asks for an email in the terminal — press Enter to skip.

**Connection self-test** — `app/db.py` run directly prints the identity and the known
signal:

```bash
.venv-app/Scripts/python.exe app/db.py
```

Expect `('DE_CAPSTONE_SVC', 'DE_CAPSTONE_DBT_ROLE', 'DE_CAPSTONE_WH')` and
`CLOZAPINE / Neutropenia / 5571 / PRR 35.94`. The all-time query answers in ~3.7 s
against the `sem_signal_metrics` **view** — fast enough that no materialisation was
needed.

### 4.5 CI/CD

Four workflows. **None can alter production.**

| Workflow | Runs on | Checks |
|---|---|---|
| `ci.yml` | every push to `main`, every PR | `ruff` · `python syntax (3.11)` · `python syntax (3.12)` · `secret scan` · `dbt parse` · `pytest` |
| `dbt-ci.yml` | push / PR | `dbt build --target ci` into `DBT_CI` → PASS=53 |
| `s3-contract.yml` | push / PR / manual | 486 objects / 3,913,635,942 bytes in the protected prefix |
| `terraform.yml` | `plan` on PR, `apply` manual only | `2 to import, 0 to add, 0 to change, 0 to destroy` |

Check the latest run:

```bash
gh run list --workflow "CI" --limit 1 --json databaseId,conclusion,event --jq '.[0]'
```

CI connects to Snowflake as `DE_CAPSTONE_CI` — 8 grants, read-only on `RAW`, build rights
on `DBT_CI`, **nothing** on `DBT_DEV`. It reaches AWS by OIDC with no stored key.
Revocation is independent: `DROP USER DE_CAPSTONE_CI` removes CI entirely and leaves
Airflow, both loaders and the dashboards working.

### 4.6 Terraform — the CI IAM role only

Manages exactly two objects: the GitHub Actions CI role and its inline policy.

`plan` runs on every pull request. **`apply` is manual** (`workflow_dispatch`) — the first
apply is one to watch. The acceptance gate is an **empty second plan**:

```
No changes. Your infrastructure matches the configuration.
```

An apply that reports success proves Terraform did something. An empty plan afterwards
proves it recorded reality faithfully, with no hidden drift. Never fix a `1 to change` by
editing the live resource — fix the code to match what is actually deployed.

---

## 5. Monitoring and data-quality baselines

Use these to tell a **real problem** from a **normal, expected gap**.

### 5.1 Bronze baseline — `drug_event`

| Check | Expected / healthy | Note |
|---|---|---|
| Duplicate `safetyreportid` | **0** | openFDA returns latest-version only |
| Key fields null (`safetyreportid`, `receivedate`, `serious`) | ~0 % | `serious` ~0.01 % |
| Drug name and reaction present | **100 %** | `medicinalproduct`, `reactionmeddrapt` never null/blank |
| Demographics missing | age ~44 %, sex ~17 %, country ~11 % | **Expected.** Bucket as `Unknown` — not a bug |
| `openfda.generic_name` present | ~83 % | Tier-1 source for normalisation |
| Fan-out per report | ~3.9 drugs, ~3.0 reactions | 10.4M drug rows, 8.0M reaction rows |
| Coded field validity | valid **except 18 rogue `drugcharacterization`** (codes 4/5) | Quarantined by design |

### 5.2 Silver baseline — verified full run, all 24 months

| Check | Verified | Note |
|---|---|---|
| Grain key unique | **45,030,932 / 45,030,932** | `report_drug_reaction_key` |
| Silver rows | **45,030,932** | from 93,366,638 atomic rows |
| Duplicates removed | **48,335,706 (51.8 %)** | at the atomic grain — repeated dosage lines |
| Drug resolution (Silver stage) | **78.46 %** | report-level only; the NDC join happens in dbt |
| Quarantine | **431,760** | 431,741 `reaction_pt_null` + 18 out-of-range + 1 null |
| Null `resolved_drug` / `reaction_pt` in Silver | **0 / 0** | grain integrity |
| Month partitions | **24** | per-month metrics in `silver/_silver_metrics` |

**Mega-report note.** The 431,741 null-reaction rejects come from exactly **three**
reports (23840947, 23014826, 22122822 — `reporttype=1`, 1,000–4,113 drugs each) whose
reactions are all blank. Each is fully quarantined (`n_drugs × n_reactions`) and
contributes nothing to Silver. Watch for similar bulk reports: they can distort
disproportionality, and would be handled in the marts by drug-count or `reporttype`.

### 5.3 Warehouse baseline

| Model | Expected rows |
|---|---|
| `fct_report_drug_reaction` | 45,030,932 |
| `fct_signal_metrics` | 5,069,399 |
| `sem_signal_metrics` | 1,240,645 |
| `dim_drug` / `dim_reaction` / `dim_reporter` / `dim_date` | 4,368 / 18,057 / 726 / 731 |
| `int_drug_resolution` signatures | 84,039 |
| Row-level drug resolution | 86.7 % |
| Candidate signals (`is_signal`) | 315,270 (25.4 % of pairs) |

---

## 6. Failure playbook

One row per failure actually encountered during the build. **This section is the real
deliverable.**

| Symptom | Likely cause | Fix | Safe to re-run? |
|---|---|---|---|
| Task fails with HTTP 429 | Rate limit exceeded | Wait; backoff handles it automatically | Yes |
| HTTP 403 on the API | Keyless request hit the low rate limit | Use your API key (`OPENFDA_API_KEY` in `.env`) | Yes |
| `venv` ends in `KeyboardInterrupt`, venv half-made | Ctrl+C during setup | `rm -rf .venv`, then `python -m venv .venv` and let it finish | Yes |
| `bash: ...activate: command not found` | Backslashes used in Git Bash | `source .venv/Scripts/activate` — forward slashes | Yes |
| Fewer records on disk than openFDA's count | A page request failed and the old script treated the empty reply as "day finished" | Compare per-day API count vs disk, re-fetch the short day(s). The script now **raises** on a failed page | Yes |
| `SSL: CERTIFICATE_VERIFY_FAILED` on a bulk download | `urllib` could not verify the certificate (Windows / antivirus scanning HTTPS) | Use `requests` — it ships the certifi CA bundle. The label/ndc scripts now do | Yes |
| A Spark cell takes ~1 hour | Re-reading and re-parsing nested JSON on every check, with no cache | Cache once to Parquet, then read the Parquet — seconds, not minutes | Yes |
| Silver write fails: `Read-only file system` / `Permission denied` on `/home/jovyan/silver` | The `silver`/`quarantine` mounts are absent — the container was not recreated after the compose edit | `docker compose up --force-recreate`; confirm both host dirs exist and the mounts are in `docker-compose.yml` | Yes |
| One reaction-explode task stalls near 100 % / executor OOM | Mega-report skew — up to 4,113 drugs × 518 reactions on a single report piled onto one task | Repartition on `(safety_report_id, drug_idx)` before the reaction explode; process month by month | Yes |
| **C: fills up; driver dies mid-`.parquet()` write** (`py4j` "Answer from Java side is empty") | A whole-dataset `dropDuplicates`+`partitionBy` OOM'd the driver, and each crashed run left orphaned Spark spill stacking up inside `docker_data.vhdx` on **C:** — retrying made it worse | Route spill to D: (`SPARK_LOCAL_DIRS=/opt/spark-tmp`), cache on D:, run month by month. **Never retry or reboot a crashed run without the spill fix first** — that is exactly what filled C: | Yes (idempotent) |
| `Cannot reserve additional contiguous bytes in the vectorized reader` / `OutOfMemoryError: Java heap space` | Spark's vectorized Parquet reader batches 4,096 rows of the wide nested `patient.drug[]` column at once, across many cores | `spark.sql.parquet.enableVectorizedReader=false` (already set). Row-based reading is far lighter on nested data | Yes |
| A Silver run crashed and you want to retry | Orphaned Spark spill may remain (now on D:, so it cannot fill C:) | Delete `D:/capstone/data/spark-tmp/*`, check `docker system df`, then re-run — month-by-month writes are idempotent | Yes |
| `build_silver` fails with `java.io.IOException: Cannot allocate memory`, **while the same job passes when run manually** | **Native (off-heap), not heap.** The six Airflow containers plus a 4 GB Spark driver exceed Docker's default ceiling of 50 % of host RAM; `local[*]` multiplies per-task native buffers | Raise the ceiling in `%UserProfile%\.wslconfig` → `[wsl2]` / `memory=10GB`; `docker compose stop` both stacks (**never `down -v`**), `wsl --shutdown`, restart Docker Desktop. Then add `--master local[4]` and `--conf spark.unsafe.sorter.spill.read.ahead.enabled=false`. *(Do not try `--conf spark.sql.shuffle.partitions` — the job sets it in code, and a builder option overrides a `--conf` at submit time.)* | Yes — per-month dynamic overwrite leaves nothing to clean up |
| `build_silver` fails after ~1 second with `docker.errors.APIError: 409 … container is not running` | Airflow **triggers** Spark rather than hosting it, so `capstone-spark-jupyter` must already be running. Easy to miss after a restart, because starting the Airflow stack does not start the repo stack | `docker compose up -d` from the repo root, then `docker ps` — expect **8** containers before triggering. Re-trigger, or clear the failed task in the UI to resume the run | Yes |
| S3 prefix has **more objects than the run produced** (e.g. 499 where 486 expected) | `aws s3 sync` **without `--delete` only adds**, and Spark names output files with a per-run UUID — so a re-run's files land *alongside* the previous run's. The Spark job is idempotent; the upload task was not | Add `--delete`, and grant `s3:DeleteObject` **scoped to the pipeline's own prefix only** — never the validated artifact or NDC prefixes. Re-run just `upload_s3`; no Spark needed. Verify object count **and** total bytes | Yes |
| `COPY INTO` a table that already holds data **doubles the row count** | Snowflake tracks load metadata **per file path**. Files from a *different* stage are paths the table has never seen, so they load again on top | `TRUNCATE TABLE` before the `COPY`. **`TRUNCATE` clears the load metadata; `DELETE` does not.** Always compare a scratch-table load against production first — count, and a `MINUS` on the grain key | Yes — after `TRUNCATE` |
| Snowflake auth fails: `Could not deserialize key data` / `JWT token is invalid` / `No such file or directory: /keys/rsa_key.p8` | Key-pair problems, in order: the `.p8` is not PKCS#8; the registered public key does not match the private key (or wrong user); the key mount is not applied | Regenerate with `openssl pkcs8 -topk8 … -nocrypt`; check `DESC USER DE_CAPSTONE_SVC` → `RSA_PUBLIC_KEY_FP`; `docker compose up -d --force-recreate dbt` — a plain restart does not add a new mount | Yes |
| Only `airflow-worker` crash-loops after adding dbt to `_PIP_ADDITIONAL_REQUIREMENTS` — `RestartCount` climbing, health stuck at `starting`, **no traceback**, log ends at `BACKEND=redis` | `dbt-core` 1.12 requires `click>=8.3` / `cryptography>=46` / `protobuf>=6`, all above apache-airflow 2.10.5's pins. The variable installs with **no constraint file** and silently upgrades Airflow's own dependencies. Scheduler and webserver survive because `celery worker` imports a wider surface | Remove the dbt packages from the pip line, then `docker compose up -d --force-recreate airflow-worker` — a plain restart keeps the bad `/home/airflow/.local`. Run dbt in its own container and have Airflow exec into it, same pattern as Spark. **Diagnosis tip:** `{{.State.ExitCode}}` is meaningless while a container runs — sample `{{.RestartCount}}` twice, 60 s apart | Yes |
| Streamlit's ranked table is topped by rows with **blank PRR / ROR** | The reaction was reported *only* with that drug, so `c = 0`: the macro divides by `nullif(c/(c+d), 0)` and returns NULL — undefined, not infinite. Snowflake sorts **NULLs first** under `ORDER BY … DESC` | `order by <col> desc nulls last`. The dbt side was already correct — `coalesce(…, false)` keeps `is_signal` FALSE | Yes |
| The monthly table is empty while the all-time table has rows | The all-time case floor (default **100**) was applied at monthly grain, where a typical `a` is single digits | Use the separate **"Minimum cases (a) — monthly"** input (default 5). Two floors for two grains is deliberate, not a duplicate control | Yes |
| Streamlit: `StreamlitDuplicateElementId … multiple plotly_chart elements with the same auto-generated ID` | **Tabs are not lazy** — every tab's code runs on every rerun, so charts in different tabs coexist. Streamlit derives an element ID from its type *and* parameters, so two charts receiving identical data collide | Give every chart and table an explicit `key="..."` so the ID no longer depends on the data. Applied to all 10 `st.plotly_chart` / `st.dataframe` calls, not only the two that collided | Yes |
| The Airflow Graph/Grid view shows tasks that never ran in the run you are inspecting | **Airflow 2.x has no per-run DAG versioning.** The scheduler stores one serialised DAG — the latest parse — and the UI renders that structure over *every* historical run | Ignore the graph for historical runs. Use `airflow tasks states-for-dag-run pv_pipeline "<run_id>"` — it lists only the task **instances** that actually existed, with start/end times. Cross-check the run's Event Log | Yes |
| A GitHub Actions job fails with `Not authorized to perform sts:AssumeRoleWithWebIdentity`, on a trust policy that saved without error | **GitHub's immutable subject claims.** Since 15 July 2026 every *new* repository issues a `sub` containing numeric ids — `repo:<owner>@<owner_id>/<repo>@<repo_id>:<ref>` — so `repo:owner/repo:*` matches nothing. **IAM validates syntax, not reachability** | Read the real subject rather than guessing: the `Show the OIDC subject` step decodes the token and prints `sub`/`aud` **before** the assume. Note the subject differs by event — `:pull_request` vs `:ref:refs/heads/main` — so a policy pinned to one fails on the other | Yes |
| An S3 read from CI fails with `AccessDenied` although the inline policy looks right | Either the ARN shape (`s3:ListBucket` acts on the **bucket** ARN with no `/*`; `s3:GetObject` on the **object** ARN with `/*`), the `s3:prefix` condition not matching what the CLI sends, or the **permissions boundary** capping an action the inline policy grants | Use the **IAM policy simulator** — it evaluates the identity policy *and* the boundary inside AWS, with no workflow run needed. **Always paste an explicit resource ARN**; an empty or `*` resource makes correctly-scoped allows come back denied | Yes |
| `gh run view <id> --log` returns `HTTP 404`, or the browser shows "This workflow does not exist" for a file that is on `main` | A **GitHub-side incident**. Endpoints degrade independently, so the runs API can answer while the jobs API 404s. The red text of a `gh` error reads like a red *check* and is not one | Trust the `conclusion` field: `gh run list --workflow "<name>" --limit 1 --json databaseId,conclusion,event --jq '.[0]'`. Check <https://www.githubstatus.com>. Re-trigger with an empty commit if a run never starts. **Verify on the other system meanwhile** — the IAM simulator confirms AWS-side behaviour with GitHub down | Yes |
| `terraform plan` fails with `AccessDenied: iam:ListOpenIDConnectProviders` | A `data "aws_iam_openid_connect_provider"` block looks the provider up **by URL**, and resolving a URL to an ARN calls `ListOpenIDConnectProviders`. That action **does not support resource-level permissions**, so granting it means `"Resource": "*"` in an Allow | **Remove the dependency, do not widen the policy.** Reference the provider by ARN in a `locals` block and delete the data source. The string is identical, so an imported trust policy still matches and the plan stays `0 to change` | Yes |
| `terraform plan` shows `1 to change` on an imported resource nobody edited | The config does not match the live resource exactly. Usual culprits: a `tags` block the role does not have, `max_session_duration` written out when 3600 is the default, a `description` differing by a character, or an omitted `permissions_boundary` | **Fix the code, never the live resource.** Author the config from the console's actual values, then re-plan. The acceptance gate is `Plan: 2 to import, 0 to add, 0 to change, 0 to destroy` | Yes |

---

## 7. Recovery procedures

### 7.1 A run failed partway through

Airflow tasks are individually re-runnable. Clear the failed task in the UI to resume the
existing run, or re-trigger the DAG — every task is idempotent.

**Ingestion has no automatic checkpoint.** To resume an interrupted
`ingest_drug_event.py`:

1. Note the **last `receivedate=` folder** written, e.g. `20241018`.
2. **Delete that day's folder** — it may be half-written:
   `rm -rf $DATA_DIR/bronze/drug_event/receivedate=20241018`.
3. Set `START` in the script to that date, save, and re-run — it fills only the remaining
   days.
4. Afterwards, set `START` back to the full range.

For **specific short days** where one page failed mid-day, edit the `DAYS` list in
`scripts/backfill_days.py` and run that instead. Verify with per-day API count vs disk.

### 7.2 Data looks wrong in the marts

Trace backwards, layer by layer. Each step tells you whether the problem is above or
below it.

1. **Is the fact table the right size?**
   `SELECT COUNT(*) FROM DBT_DEV.FCT_REPORT_DRUG_REACTION` — expect **45,030,932**.
   Wrong here → the problem is in RAW or the load, not in dbt. Go to step 2.
   Right here → the problem is in the marts or the metrics. Go to step 4.
2. **Is RAW the right size?**
   `SELECT COUNT(*) FROM RAW.SILVER_DRUG_EVENT` — expect **45,030,932**.
   Too *many* rows, usually a clean multiple → a `COPY` ran without `TRUNCATE`, or S3
   accumulated files. Check the object count in `silver_pipeline/` (**486**).
3. **Is Silver on disk right?**
   Count month partitions (**24**) and check `silver/_silver_metrics` for the per-month
   atomic / quarantined counts. They are reproducible: a correct run produces identical
   per-month numbers every time, including the three mega-report quarantine spikes
   (25,000 · 61,249 · 345,495).
4. **Are the dimensions right?**
   `dim_drug` **4,368**, `dim_reaction` **18,057**, `dim_reporter` **726**,
   `dim_date` **731**. A changed `dim_drug` count means drug resolution changed, which
   moves every signal.
5. **Is the known signal right?**
   clozapine → neutropenia, **PRR 35.94 / 5,571 cases**. If the fact table is correct but
   this is not, the problem is in the metric macros or their thresholds.
6. **Do the tests pass?** `dbt test` → **PASS=42**. The grain-uniqueness, FK and
   worked-example tests localise most failures on their own.

### 7.3 Rebuilding from Bronze

Bronze is immutable, so everything downstream can be rebuilt without touching the API.

```
build_silver  (~4 h)  →  upload_s3  (~5 m)  →  load_raw  (~3 m)  →  dbt_build  (~1 m)
```

Trigger the DAG with `{"months":"all"}` and it does all four. Only re-run what changed:

| What changed | What to re-run | Time |
|---|---|---|
| A PRR threshold in `dbt_project.yml` | `dbt_build` only | ~2 min |
| A dbt model or a new metric | `dbt_build` only | ~2 min |
| The dashboard | Nothing — refresh the browser | seconds |
| The Silver flattening logic | The whole chain | ~4 h |
| openFDA publishes a new month | `{"months":"2025-01"}` — one month, not 24 | ~10 min |

`dim_date` derives itself from the data, so a new month needs no code change.

### 7.4 Reloading Snowflake RAW, and the rollback path

Production RAW is loaded from **S3** (`RAW.SILVER_PIPELINE_S3_STAGE` /
`RAW.NDC_S3_STAGE`). The internal stages and `scripts/load_to_snowflake.py` are
**deliberately kept intact as the rollback path** — they rebuild RAW from the local
Parquet in about 10 minutes and were migrated to key-pair auth along with everything
else, because a rollback is only worth claiming if it still runs.

```bash
.venv-dbt/Scripts/python.exe scripts/load_to_snowflake.py --what silver
```

**Before any reload or cutover, always run the comparison first.** Load into a
`TEMPORARY` table and check three things against the current production table: the total
row count, the row count for one known month, and a **`MINUS` on
`report_drug_reaction_key`, which must be 0**. Equal counts alone are not enough — the
`MINUS` is what proves the rows are identical rather than merely equinumerous.

Then, and only then:

```sql
TRUNCATE TABLE RAW.SILVER_DRUG_EVENT;   -- clears load metadata; DELETE does NOT
COPY INTO RAW.SILVER_DRUG_EVENT FROM @RAW.SILVER_PIPELINE_S3_STAGE
  FILE_FORMAT = (FORMAT_NAME = 'DE_CAPSTONE.RAW.FF_PARQUET')
  MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
  PATTERN = '.*[.]parquet' ON_ERROR = 'ABORT_STATEMENT';
```

Verify **45,030,932**, rebuild the models (`dbt build` → PASS=53), then re-check the
known signal — **clozapine → neutropenia, PRR 35.94, 5,571 cases**.

*The dbt models are materialised tables, so they keep serving their previous contents
throughout a reload. There is no window where the marts are broken.*

### 7.5 Capture baselines before a destructive run

```bash
aws s3 ls s3://$S3_BUCKET/silver/drug_event/ --recursive --summarize | tail -3
```

```bash
aws s3 ls s3://$S3_BUCKET/silver_pipeline/ --recursive --summarize | tail -3
```

| Prefix | Expected |
|---|---|
| `silver/drug_event/` (protected fallback) | 486 objects / **3,913,635,942** bytes |
| `silver_pipeline/` (rewritten by each run) | 486 objects / **3,913,633,244** bytes |

The two differ by **2,698 bytes** of Parquet metadata across 3.9 GB. Re-check both after
the run. `s3-contract.yml` now automates the first one on every push, but capture them by
hand before anything genuinely destructive.

---

## 8. Teardown

**Between sessions — the normal case:**

```bash
cd /d/capstone/de-capstone/airflow && docker compose stop
```

```bash
cd /d/capstone/de-capstone && docker compose stop
```

Keeps containers, volumes, the Parquet cache, and Airflow's history. This is almost
always what you want.

**Removing the containers** (keeps named volumes):

```bash
cd /d/capstone/de-capstone && docker compose down
```

**⚠️ Destructive — `-v` also removes named volumes:**

- On the **Airflow stack** this deletes `postgres-db-volume`: your login, DAG history and
  every run record. There is no recovery.
- On the **repo stack** it removes the Parquet cache, which then takes ~16 minutes to
  rebuild.

Bronze, Silver, quarantine and the notebooks are **never** deleted by any of these — they
live in host bind mounts, not inside Docker.

**Cloud resources that cost money if left running:**

| Resource | Action |
|---|---|
| S3 bucket (~8 GB) | ~$0.20/month. Delete the bucket to stop it. |
| Snowflake warehouse | `AUTO_SUSPEND = 60` — idles at $0. `ALTER WAREHOUSE … SUSPEND` to be certain. |
| Snowflake storage | A couple of GB. Drop the database to stop it. |
| Terraform state bucket | ~50 KB, negligible. |
| IAM roles, OIDC provider, permissions boundary | **Free**, always. |

Nothing here bills by the hour while idle.
