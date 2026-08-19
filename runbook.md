# Runbook

Operational manual: how to run this, and what to do when it breaks.

> Fill this in **as you hit each problem**, not at the end. Every failure you debug
> during the build is a runbook entry you have already earned.

---

## 1. Environment

### Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.11 |
| Disk space | ~25 GB free for raw data (stored on the D: drive) |
| Docker Desktop | Needed later for Airflow, not for ingestion |

### First-time setup (data ingestion)

Run these **once**, from inside the `de-capstone` folder in Git Bash:

```bash
python -m venv .venv
```

```bash
source .venv/Scripts/activate
```

```bash
pip install requests python-dotenv
```

After activating, you will see `(.venv)` at the start of the terminal line.

Then create a file named `.env` inside `de-capstone` with:

```
OPENFDA_API_KEY=your_key_here
DATA_DIR=D:/capstone/data
```

*(Docker / Airflow setup comes later, when we orchestrate the pipeline.)*

### Required environment variables

| Variable | Purpose | Where to get it |
|---|---|---|
| `OPENFDA_API_KEY` | Raises the API limit to 120,000 requests/day | Free from open.fda.gov (emailed to you) |
| `DATA_DIR` | Where raw data is saved (never in the repo) | Your own path, e.g. `D:/capstone/data` |

---

## 2. Running the pipeline

### Normal scheduled run

```bash
# schedule, entry point, expected duration
```

### Manual trigger — download raw drug/event data

**What the script does** (`scripts/ingest_drug_event.py`):

- Downloads drug adverse-event reports (FAERS) from the openFDA API.
- Goes **day by day** and pulls **1,000 records per request**, so it never hits openFDA's 26,000-per-query limit.
- Saves the **raw** JSON to the bronze layer — one folder per date, one record per line.
- Stops at `TARGET` records (3,000,000) or the `END` date. For 2023–2024 that is about **2.69 million** records.

**Run it** (virtual environment activated):

```bash
python scripts/ingest_drug_event.py
```

**Where the data is saved:**

```
D:/capstone/data/bronze/drug_event/receivedate=YYYYMMDD/part-<n>.json
```

**To change what you pull:** edit `START`, `END`, or `TARGET` near the top of the script.

### Manual trigger — download drug/label and drug/ndc (bulk files)

**What the scripts do** (`scripts/ingest_drug_label.py`, `scripts/ingest_drug_ndc.py`):

- Both datasets are past the API's 26,000 paging limit, so they use openFDA's **bulk download files** (no API key needed).
- Each `.json.zip` is downloaded and its records saved as **raw** NDJSON in the bronze layer.

**Run them** (virtual environment activated):

```bash
python scripts/ingest_drug_ndc.py
```

```bash
python scripts/ingest_drug_label.py
```

**Where the data is saved:**

```
D:/capstone/data/bronze/drug_ndc/part-<n>.json
D:/capstone/data/bronze/drug_label/part-<n>.json
```

**Note:** label is large (261k full label texts, several GB). For a quick sample, set `MAX_FILES = 1` near the top of `ingest_drug_label.py`.

### Backfill / re-fetch specific days

If a day comes up short (a page failed mid-download), re-fetch just those days with
`scripts/backfill_days.py` (edit the `DAYS` list at the top; uses your API key):

```bash
python scripts/backfill_days.py
```

### Verifying a run succeeded

While running, the script prints one line per 1,000 records, for example:

```
20230101  skip=0  got=1000  total=1,000
20230101  skip=1000  got=1000  total=2,000
```

- `total` climbs toward ~2,687,675 for 2023–2024.
- It ends with `DONE. 2,687,675 records saved to ...`.
- Healthy runtime: roughly 30–60 minutes.
- Check that `D:/capstone/data/bronze/drug_event/` contains `receivedate=...` folders with `.json` files inside.

### Ingested so far (verified)

Each count was checked against openFDA's own totals.

| Dataset | Records | How verified |
|---|---|---|
| `drug_event` (2023–2024) | **2,687,675** | matches openFDA range total exactly |
| `drug_label` | **261,258** | matches the bulk-file record count |
| `drug_ndc` | **136,520** | matches the bulk-file record count |

**Count records on disk for any dataset:**

```bash
find /d/capstone/data/bronze/<dataset> -name "*.json" -exec cat {} + | wc -l
```

### Explore the data (Spark + Jupyter)

Exploration and the data-quality checks run in **PySpark inside Jupyter**, via Docker
(`docker-compose.yml`, reusing the week-12 setup). Everything runs **locally** on this
laptop — nothing is in the cloud.

```bash
docker compose up
```

Then open **http://localhost:8888** → `work/01_explore_drug_event.ipynb` → **Run All Cells**.
First run pulls the image (~2–4 min). On Windows, share the **D:** drive in Docker Desktop →
Settings → Resources → File Sharing.

**Why Spark, not pandas, to explore this data?**

The bronze `drug_event` data is **~2.69M nested JSON records** (a few GB). On a 16 GB laptop:

- **pandas** loads the whole dataset into RAM at once. At this size it does not fit in 16 GB,
  so it runs out of memory and crashes — pandas is all-in-memory or nothing.
- **Spark** processes the data in small **chunks (partitions)**, a few at a time, and **spills
  the overflow to disk** when memory is tight. It only needs RAM for the chunk it is working on,
  never the whole dataset — so it can handle data **bigger than memory**. It also spreads the
  work across all CPU **cores**, so it is faster too.

The point is **not** that "Spark is faster" — on a small sample pandas is actually faster (no
startup overhead). The point is that **Spark scales to data bigger than memory**: it can process
the full 2.69M-record dataset on one 16 GB machine, which pandas cannot. pandas stays useful for
a quick look at a small sample; Spark is the tool for the full dataset (and the Silver-layer
cleaning).

*On one laptop Spark parallelises across CPU **cores**, not **nodes** — nodes are separate
machines in a cloud cluster, the same idea at bigger scale. The overall Spark decision is
recorded in `docs/adr/ADR-004`.*

**Speed: cache the raw JSON as Parquet**

Reading the raw **nested JSON** repeatedly is slow — every Spark check re-reads and re-parses
all 3,043 files (one completeness cell took **over an hour**). Cache it once as **Parquet**
(binary, schema stored, columnar, compressed), then read that instead:

```python
df.write.mode('overwrite').parquet('/home/jovyan/dq_cache/drug_event')   # one-time, slow
df = spark.read.parquet('/home/jovyan/dq_cache/drug_event')              # fast from here on
```

Reads then drop from **minutes to seconds**. This cache lives inside the container (temporary —
rebuild with the write line if you `docker compose down`); the permanent Parquet lands in the
Silver layer. Pattern: **JSON to land, Parquet to work**.

### Build the Silver layer (clean atomic data)

Flattens bronze to the atomic **(case, drug, reaction)** grain and applies the three cleaning
issues — **#4** dedup, **#5** drug-name normalisation, **#6** validation/quarantine — writing
permanent Parquet. Notebook: `notebooks/02_build_silver_drug_event.ipynb`.

> **Why this design (and why PySpark, not pandas)?** See `docs/silver_layer_notes.md` — the
> provenance of each choice plus the tooling trade-off, in defensible form.

**Runs month by month, with all scratch on D:.** The notebook processes one month at a time (no
whole-dataset shuffle) and keeps **all Spark scratch on D:** — spill via `SPARK_LOCAL_DIRS=/opt/spark-tmp`
and the Parquet cache under `dq_cache`, both D: mounts. This is deliberate: an earlier single-shot
version OOM'd the driver mid-write and stranded tens of GB of Spark spill inside the Docker disk on
**C:**, filling it. Scratch must never land on C: again — see the failure playbook.

```bash
docker compose up -d
```

`docker compose up -d` recreates the container to pick up all the writable mounts — `silver/`,
`quarantine/`, `dq_cache/` and `spark-tmp/` (bronze stays read-only). Then open
**http://localhost:8888** → `work/02_build_silver_drug_event.ipynb` → **Run All Cells**.

- **First run builds the Parquet cache on D:** from the bronze JSON, month by month (~15 min,
  one-time). It lives at `D:/capstone/data/dq_cache` (not inside the container), so it survives
  `docker compose down` and never grows the C: drive. Later runs read it in seconds.
- **Outputs** (permanent, on the D: drive):
  - `D:/capstone/data/silver/drug_event/` — clean atomic table, Parquet, partitioned by
    `receive_year`/`receive_month`.
  - `D:/capstone/data/quarantine/drug_event/` — rejected drug entries (#6) with a `_reject_reason`.
- **The notebook reports its own numbers** — rows in/out, duplicates removed, drug resolution rate,
  quarantine counts — and the final cells verify the grain key is unique and no rejects leaked through.

Bronze is never written: it is reachable only through the read-only mount, while Silver and
Quarantine are separate writable mounts pointing at sibling folders.

### Run the whole pipeline with Airflow

Three Docker stacks: **Airflow** orchestrates, **`capstone-spark-jupyter`** does the Spark work,
**`capstone-dbt`** talks to Snowflake. Airflow triggers the other two over the mounted Docker socket —
it never runs Spark or dbt itself.

**Start everything** (both compose files — the Airflow stack does *not* start the other two):

```bash
cd /d/capstone/de-capstone && docker compose up -d
```

```bash
cd /d/capstone/de-capstone/airflow && docker compose up -d
```

Wait 1–2 min (each Airflow container pip-installs on start), then confirm **8 containers**:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```

UI: **http://localhost:8080**, login `airflow` / `airflow` (not an OS user).

**Trigger a run:**

```bash
cd /d/capstone/de-capstone/airflow && docker compose exec airflow-scheduler airflow dags trigger pv_pipeline -c '{"months":"2023-01"}'
```

`{"months":"all"}` rebuilds all 24 months (~5 h). **One month still exercises the whole chain**: dynamic
partition overwrite rewrites only January locally, the other 23 stay on disk, `sync --delete` removes
nothing, S3 keeps all 486 files, and `load_raw` still loads the full 45,030,932. ~15–21 min.

**Chain:** `ingest_ndc → ingest_faers → build_silver → upload_s3 → load_raw → dbt_build → dbt_test → publish_metrics`

**Run a single task** (no DAG run, no dependencies) — useful for `upload_s3` (re-upload without Spark)
and `dbt_test` (read-only):

```bash
cd /d/capstone/de-capstone/airflow && MSYS_NO_PATHCONV=1 docker compose exec airflow-scheduler airflow tasks test pv_pipeline dbt_test 2026-08-13
```

**Check progress without the UI** (the Grid view can hang on the huge `build_silver` log):

```bash
cd /d/capstone/de-capstone/airflow && MSYS_NO_PATHCONV=1 docker compose exec airflow-scheduler airflow dags list-runs -d pv_pipeline
```

```bash
MSYS_NO_PATHCONV=1 docker exec capstone-spark-jupyter sh -c 'ls -d /home/jovyan/silver/pipeline/receive_year=*/receive_month=* | wc -l'
```

**Expected gates:** `build_silver` → `Requested-month Silver rows: 1549263` (one month) or `45030932`
(all) · `load_raw` → `RAW.SILVER_DRUG_EVENT rows: 45030932`, `RAW.DRUG_NDC rows: 136520` ·
`dbt_build` → `PASS=53` · `dbt_test` → `PASS=42` · `publish_metrics` → `fct… 45030932`, `signals… 315270`.

**dbt directly** (bypassing Airflow):

```bash
MSYS_NO_PATHCONV=1 docker exec capstone-dbt dbt build --profiles-dir /dbt
MSYS_NO_PATHCONV=1 docker exec capstone-dbt dbt run-operation publish_metrics --profiles-dir /dbt
```

**dbt lineage docs** — from the host `.venv-dbt`, **on port 8081** (Airflow owns 8080):

```bash
cd /d/capstone/de-capstone && set -a; source .env; set +a && cd de_capstone && /d/capstone/de-capstone/.venv-dbt/Scripts/dbt.exe docs generate && /d/capstone/de-capstone/.venv-dbt/Scripts/dbt.exe docs serve --port 8081
```

**Stop:**

```bash
cd /d/capstone/de-capstone/airflow && docker compose stop
```

```bash
cd /d/capstone/de-capstone && docker compose stop
```

⚠️ **Never `docker compose down -v` on the Airflow stack** — it deletes `postgres-db-volume`, i.e.
Airflow's metadata DB: your login, DAG history and run records.

**While a long run is in progress:** editing docs, Zoom, and read-only Docker commands are all safe (the
WSL VM has a hard memory reservation, so Windows apps cannot starve Spark). Do **not**
`docker compose up/down/stop/restart`, `wsl --shutdown`, let the laptop sleep, start Jupyter or another
Spark job, or edit `pv_pipeline.py` (`upload_s3` is parsed when *it* starts).

**Ports:** Jupyter `8888` · Airflow `8080` · dbt docs `8081` (default 8080 clashes with Airflow) ·
Streamlit `8501`. Snowflake is **not** localhost — it's `app.snowflake.com`.

### CI/CD — GitHub Actions

**Four workflows. None can alter production.** Full detail: `docs/Layer Explanation/CI_CD.md`.

| Workflow | Runs on | Jobs |
|---|---|---|
| `ci.yml` | every push to `main` and every PR | `ruff` · `python syntax (3.11)` · `python syntax (3.12)` · `secret scan` · `dbt parse` · `pytest` |
| `dbt-ci.yml` | PR/push **only when `de_capstone/**` changes**, plus manual dispatch | `dbt build into DBT_CI` |
| `s3-contract.yml` | every PR, every push to `main`, plus manual dispatch (**no paths filter** — the artifact lives in S3, not in the repo) | `verify the protected S3 prefix` |
| `terraform.yml` | PR when `terraform/**` changes; **apply only via manual dispatch** with `action=apply` | `terraform` (fmt · init · validate · plan · optional apply) |

**Working method — always via a branch and PR:**

```bash
git checkout -b ci/<what-changed>
```

```bash
git push -u origin ci/<what-changed>
```

Open the PR, wait for the checks, merge only when green. Pushing to `main` works (the ruleset is not
enforced on a private repo) but bypasses the gate.

**Validate workflow YAML before pushing:**

```bash
.venv-dbt/Scripts/python.exe -c "import yaml; yaml.safe_load(open('.github/workflows/dbt-ci.yml')); print('YAML OK')"
```

Catches indentation. **Does not catch GitHub expression errors** — it accepted a file GitHub later
rejected. First filter, not the gate.

**Confirm CI touched nothing in production** (Snowsight, `ACCOUNTADMIN`):

```sql
SELECT max(_loaded_at) FROM DE_CAPSTONE.DBT_DEV.FCT_SIGNAL_METRICS;
```

Unchanged from the last Airflow run = `DBT_DEV` was not rebuilt. That is the check that matters.

```sql
SELECT count(*) FROM DE_CAPSTONE.DBT_CI.FCT_REPORT_DRUG_REACTION;   -- 45,030,932
```

*If `ACCOUNTADMIN` gets "insufficient privileges" on `DBT_CI`, the CI role owns those tables and was
never granted upward:* `GRANT ROLE DE_CAPSTONE_CI_ROLE TO ROLE ACCOUNTADMIN;` — gives CI nothing
extra, only lets you inspect its work.

**Revoke CI access** (production unaffected):

```sql
ALTER USER DE_CAPSTONE_CI UNSET RSA_PUBLIC_KEY;   -- disable
DROP USER DE_CAPSTONE_CI;                          -- remove entirely
```

**Expected gates:** `ci.yml` six checks green in under a minute · `pytest` **21 passed** ·
`dbt build` **PASS=53** in ~1 m 20 s · schemas targeted `['DBT_CI', 'DBT_CI_DBT_TEST__AUDIT']`.

**Run the unit tests locally** — pytest lives in `.venv` (not `.venv-dbt`, which has no pytest):

```bash
cd /d/capstone/de-capstone && .venv/Scripts/python.exe -m pytest tests -q
```

`tests/test_drug_normalisation.py` (TR-37) checks the normalisation logic over real FAERS variants;
`tests/test_signal_metrics.py` (TR-38) checks PRR/ROR/ROR-CI/χ² against
`de_capstone/seeds/signal_worked_example.csv` — the same seed the dbt test asserts on in Snowflake.
Neither needs a warehouse, Docker or credentials.

**CI secrets live in the GitHub environment `ci`** — `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_CI_USER`,
`SNOWFLAKE_CI_PRIVATE_KEY`. The CI key pair is `D:/capstone/.keys-ci/` — **never** the production key
in `D:/capstone/.keys/`.

### AWS access from CI — OIDC, no stored keys

**There is no `AWS_ACCESS_KEY_ID` secret in this repository.** GitHub Actions mints an OIDC token per
job and exchanges it for short-lived STS credentials.

| Identity | Purpose | May do |
|---|---|---|
| `de-capstone-github-actions` | the S3 contract check | `ListBucket` + `GetObject` on `silver/drug_event/` only, capped by a permissions boundary |
| `de-capstone-terraform` | `terraform plan` / `apply` | the state bucket, and IAM on the **one** role ARN above. Cannot create or delete any identity, cannot modify itself |
| `de-capstone-airflow-uploader` (pre-existing IAM **user**) | Airflow's upload | write `silver_pipeline/` only |

**Run the S3 contract check on demand:**

```bash
gh workflow run "S3 contract" --ref main
```

```bash
gh run view $(gh run list --workflow "S3 contract" --branch main --limit 1 --json databaseId --jq '.[0].databaseId') --log | grep -E "sub:|objects:|bytes:|OK -|AccessDenied"
```

**Expected gates:** `objects: 486` · `bytes: 3,913,635,942` · `OK - the fallback Silver artifact is
byte-for-byte unchanged` · no `AccessDenied`. Runs in 9–17 s.

The subject printed before the assume should read
`repo:nkouhdareh@263947291/de-capstone-pipeline@1320110552:` followed by `pull_request` or
`ref:refs/heads/main`. **That `@`-with-numbers form is GitHub's immutable subject claim, not a typo** —
see the failure playbook.

### Presentation assets — where they are and how to regenerate them

| Asset | Path |
|---|---|
| Slide deck (17 slides, 16:9, dark) | `docs/capstone_presentation.pptx` |
| Architecture diagram (1920×1080, **dark**) | `docs/assets/architecture.png` |
| Dashboard captures | `docs/assets/dashboard_0_kpis.png` · `dashboard_1_signals.png` · `dashboard_2_table.png` · `dashboard_3_trend.png` |
| Title image (transparent) | `docs/assets/FDA.png` |
| Cost analysis | `docs/Layer Explanation/costs.md` |

**Re-taking the dashboard screenshots.** They come from the **hosted** app — Snowsight → Projects →
Streamlit → *Drug Safety Signals* — with Snowsight in dark mode, so they sit on a dark slide without
a panel. Press `F11` for fullscreen, then `Win`+`Shift`+`S` to crop. Exact settings:

| Image | Tab | Sidebar | Capture |
|---|---|---|---|
| `dashboard_0_kpis` | any | — | the four-number strip at the top |
| `dashboard_1_signals` | Signal Explorer | Drug `CLOZAPINE` · Reaction `(any)` · Rank by **`Cases (a)`** | the bar chart with its title |
| `dashboard_2_table` | Signal Explorer | same, **scroll past the chart** | header row + first 6–8 rows; `Neutropenia 5571 / 35.94` must be row 1 |
| `dashboard_3_trend` | Drug Profile | Drug `CLOZAPINE` · Reaction **`Neutropenia`** · monthly min `5` | the line chart, scroll to the bottom |

⚠️ **Rank by `Cases (a)`, not PRR.** Ranked by PRR the clozapine head is *Differential white blood
cell count abnormal* (PRR 1,260 on 212 cases) and Neutropenia falls well down the list — the
screenshot would then contradict the headline. Also note **Drug Profile always sorts by PRR**
regardless of the sidebar, which is why the table shot must come from Signal Explorer.

⚠️ **If the monthly trend is empty**, lower **"Minimum cases (a) – monthly"**. The all-time floor
(100) applied at monthly grain empties the table — a typical monthly `a` is single digits.

**One crop per image.** Do not try to fit the sidebar and a chart into the same capture; the page is
taller than the screen and the result is a chart cut in half. Keep each image ≥ 950 px wide and do
not scale it beyond ~1.3× in the deck, or the text inside blurs.

**Rebuilding the deck.** It was generated with `python-pptx`. Verify programmatically before
presenting: every figure present in `PROGRESS.md`, nothing outside the 0.6" margin, no text box
overlapping an image, image aspect ratios unchanged, and speaker notes on all 17 slides.

### Terraform — the CI role only

Managed objects: `de-capstone-github-actions` and its inline policy. **Nothing else** — not the data
bucket, production IAM, the Snowflake storage integration, dbt or Airflow.

**Before pushing** (no AWS credentials needed — `-backend=false` skips the S3 backend):

```bash
cd /d/capstone/de-capstone/terraform && terraform fmt && terraform init -backend=false && terraform validate
```

**Read the plan from a PR run:**

```bash
gh run view $(gh run list --workflow "Terraform" --limit 1 --json databaseId --jq '.[0].databaseId') --log | grep -E "Plan:|will be imported|must be replaced|will be destroyed|Error"
```

**Expected gate:** `Plan: 2 to import, 0 to add, 0 to change, 0 to destroy.` Anything else means the
**code** is wrong, not the role — fix the config, never the live resource.

**Apply — manual only, never on merge:**

```bash
gh workflow run "Terraform" --ref main -f action=apply
```

Then re-plan (must be empty) and re-run the S3 contract (must be green). State lives in
`s3://de-capstone-tfstate-617371012792/ci-role/terraform.tfstate`, versioned, with `use_lockfile`
(no DynamoDB). Terraform **1.15.8**, AWS provider pinned by `terraform/.terraform.lock.hcl` to
**6.60.0**.

---

### Before a destructive run — capture baselines

A `{"months":"all"}` run is destructive downstream: `upload_s3` mirrors with `--delete` and
`load_raw` does `TRUNCATE` + `COPY`. **`build_silver` exits 0 even if it produced a partial Silver**,
so a bad build would propagate into production RAW unchallenged. Capture these first — they take
seconds and they are what lets you prove afterwards that nothing was damaged.

```bash
aws s3 ls s3://de-capstone-pv-617371012792/silver_pipeline/ --recursive --summarize --profile de-capstone | tail -3
```

```bash
aws s3 ls s3://de-capstone-pv-617371012792/silver/drug_event/ --recursive --summarize --profile de-capstone | tail -3
```

Both should read **486 objects**; `silver/drug_event/` should be **3,913,635,942 bytes**. Re-run both
after the DAG finishes:

- `silver_pipeline/` back to **486** proves `sync --delete` mirrored rather than accumulated (the D.7 bug).
- `silver/drug_event/` **unchanged** proves least-privilege IAM held — the pipeline credential cannot
  reach the fallback artifact.

Also pre-flight: Windows sleep set to **Never**, `df -h /d` for headroom, and
`ls /d/capstone/data/dq_cache/drug_event` showing both `receive_year=2023` and `receive_year=2024`
(otherwise `build_cache` spends ~15 extra minutes rebuilding from Bronze).

**The gate to watch:** `build_silver` must end on `Requested-month Silver rows: 45030932`. Progress
without opening the huge log in a browser:

```bash
grep -h "Silver written:" /d/capstone/de-capstone/airflow/logs/dag_id=pv_pipeline/run_id=manual__<TIMESTAMP>/task_id=build_silver/*.log
```

One line per completed month; 24 is the finish. Expect ~9–13 min/month on an idle machine.

### Serve the dashboard (Streamlit)

The dashboard is **not** part of the orchestrated pipeline — it reads the finished dbt marts in
`DE_CAPSTONE.DBT_DEV` and computes nothing. It has its own venv (`.venv-app`) so Streamlit's
dependencies never touch `.venv-dbt`.

```bash
cd /d/capstone/de-capstone && .venv-app/Scripts/streamlit.exe run app/dashboard.py --server.port 8501
```

Then http://localhost:8501. First launch asks for an email in the terminal — press Enter to skip.
Call the exe by path rather than activating the venv (Git Bash activation can leave `python` on the
system interpreter — the same reason the dbt commands use `.venv-dbt/Scripts/`).

**One-time setup:**

```bash
python -m venv .venv-app
```

```bash
.venv-app/Scripts/python.exe -m pip install streamlit snowflake-connector-python python-dotenv
```

**Files:** `app/db.py` (key-pair connection as `DE_CAPSTONE_SVC`, reading `SNOWFLAKE_ACCOUNT` /
`SNOWFLAKE_USER` / `SNOWFLAKE_PRIVATE_KEY_PATH` from the repo `.env`) and `app/dashboard.py` (the UI).
`app/db.py` run directly is a self-test: it prints the connected identity and the known clozapine signal.

```bash
.venv-app/Scripts/python.exe app/db.py
```

**Expected gates:** `('DE_CAPSTONE_SVC', 'DE_CAPSTONE_DBT_ROLE', 'DE_CAPSTONE_WH')` ·
`CLOZAPINE / Neutropenia / 5571 / PRR 35.94` · all-time query ~3.7 s against the
`sem_signal_metrics` **view** (fast enough that no materialisation was needed).
In the UI, `CLOZAPINE` + `Neutropenia` must show **24 months** and **5,571 cases across months** —
each case has one `receive_date`, so the monthly counts must sum to the all-time count.

### Open the hosted dashboard (Streamlit in Snowflake)

**No laptop setup required** — no Docker, no venv, no terminal.

Snowsight → **Projects → Streamlit → Drug Safety Signals**
(`DE_CAPSTONE.DBT_DEV`, warehouse `DE_CAPSTONE_WH`, running as `DE_CAPSTONE_DBT_ROLE`).
Use **Share** to hand the URL to someone else.

**Editing:** the Snowsight code editor, then **Run**. `environment.yml` in the same Files panel holds
the package list (currently just `plotly`). The canonical copy is `app/dashboard_snowflake.py` —
paste between the two after editing either side, so they do not drift.

**One-time setup, already done:**

```sql
grant create streamlit on schema DE_CAPSTONE.DBT_DEV to role DE_CAPSTONE_DBT_ROLE;
```

`CREATE STREAMLIT` is a distinct schema privilege, not implied by schema ownership. Without it the
database does not appear in the app-creation picker.

**Gates:** Streamlit **1.52.2** · Plotly **6.7.0** · `dim_drug` **4,368 / 4,368** · KPI row
**45,030,932 / 1,240,645 / 315,270** · `CLOZAPINE` + `Neutropenia` **24 months / 5,571 cases** —
identical to the local app.

The local dashboards on 8501 and 8502 remain the fallback if Snowsight is slow or the network
misbehaves. Full write-up: `docs/Layer Explanation/Streamlit.md` Part K.

---

## 3. Monitoring

| What | Where to look | Healthy range |
|---|---|---|
| Run status | Silver nb runs top-to-bottom; final "verify" cell reads all `True` / `0` | green |
| Rows ingested | `reports in` (Silver nb) | 2,687,675 reports |
| Duplicates removed (#4) | Silver-nb Results cell | **~52%** (verified 48.3M of 93.4M; a report repeats a drug across dosage lines → collapsed to one row per case-drug-reaction) |
| Rejected rows (#6) | Silver-nb Results cell | **~431,760** (431,741 `reaction_pt_null` from 3 mega-reports + 18 rogue `drugcharacterization` + 1 null) |
| Runtime | wall clock, Run-All | month-by-month; ~1–3 h on this laptop (I/O-bound on nested reads; cache already built) |
| Cost per run | local only, no cloud | $0 |

### Data quality baseline — bronze `drug_event` (from exploration)

Known-good numbers from exploring the 2,687,675-record bronze. Use these to tell a **real problem
from a normal, expected gap**. Full detail: `notebooks/01_explore_drug_event.ipynb`.

| Check | Expected / healthy | Note |
|---|---|---|
| Duplicate `safetyreportid` | **0** | openFDA returns latest-version only |
| Key fields null (`safetyreportid`, `receivedate`, `serious`) | ~0% | `serious` ~0.01% |
| Drug name & reaction present | **100%** | `medicinalproduct`, `reactionmeddrapt` never null/blank |
| Demographics missing | age ~44%, sex ~17%, country ~11% | **expected** — bucket as `Unknown`, not a bug |
| Drug-name resolution (`openfda.generic_name`) | ~83% present | Tier-1 source for #5 normalisation |
| Fan-out per report | ~3.9 drugs, ~3.0 reactions | 10.4M drug rows, 8.0M reaction rows |

### Data quality baseline — Silver `drug_event` (verified full run)

What a healthy Silver run produces, from the verified full run (all 24 months, `_run_id`
`silver_20260805…`). Use these to tell a **real problem from a normal, expected result**.

| Check | Verified (all 24 months) | Note |
|---|---|---|
| Grain | one row per (case, resolved drug, characterization, reaction) | grain key `report_drug_reaction_key` **unique** (45,030,932 / 45,030,932) |
| Silver rows | **45,030,932** | from 93,366,638 atomic (pre-dedup) |
| Duplicates removed (#4) | **48,335,706 (51.8%)** | dupes are at the atomic grain (repeated dosage lines / synonym collapse) |
| Drug resolution rate (#5) | **78.46%** via report `generic_name`/`substance_name` | report-level only; full NDC/rxcui resolution is the dbt step (`int_drug_resolution`) |
| Quarantine (#6) | **431,760** | 431,741 `reaction_pt_null` (3 mega-reports) + 18 `drugcharacterization_out_of_range` + 1 null |
| Null `resolved_drug` / `reaction_pt` in Silver | **0 / 0** | grain integrity — no null reaction ever enters Silver |
| Month partitions | **24** | all present; per-month metrics persisted to `silver/_silver_metrics` |

**Mega-report note:** the 431,741 `reaction_pt_null` rejects are **3 reports** (23840947, 23014826,
22122822 — `reporttype=1`, 1,000–4,113 drugs) whose reactions are **all** blank, so they are fully
quarantined (`n_drugs × n_reactions` each) and contribute nothing to Silver. Watch for similar
bulk/mega-reports (they can distort PRR/ROR) — handle in gold by drug-count or `reporttype`.

**Drug resolution — completed later in dbt (next stage):** Silver resolves names only via the report's
own `generic_name`/`substance_name` (78.46%). The full resolution runs in **dbt** (`int_drug_resolution`
→ `dim_drug`) by joining the **NDC directory** (`drug_ndc`, 136,520 products, already ingested), using
the event-level ids Silver carries (`rxcui`, `product_ndc`, `package_ndc`, `brand_name`). **Match order:**
`rxcui` → normalised generic name → brand name → active-ingredient name. **Ambiguous matches are not
guessed** — they stay unresolved (`drug_key = -1`) and are counted. This must run before PRR/ROR are
trusted, or case counts fragment across name variants.

*(Earlier smoke test, 1 day `receivedate=20240102`: 4,053 reports → 63,928 Silver rows, used only to
validate the transform before the full run.)*

---

## 4. Failure playbook

*One row per failure you actually encounter. This section is the real deliverable.*

| Symptom | Likely cause | Fix | Safe to re-run? |
|---|---|---|---|
| Task fails with HTTP 429 | Rate limit exceeded | Wait; backoff handles it automatically | Yes |
| `venv` ends in `KeyboardInterrupt`, venv half-made | Ctrl+C pressed during setup | `rm -rf .venv`, then `python -m venv .venv` and let it finish | Yes |
| `bash: ...activate: command not found` | Backslashes used in Git Bash | Use `source .venv/Scripts/activate` (forward slashes) | Yes |
| Fewer records on disk than openFDA's count | A page request failed and the old script treated the empty reply as "day finished" | Compare per-day API count vs disk, re-fetch the short day(s); script now **raises** on a failed page instead of skipping | Yes |
| `SSL: CERTIFICATE_VERIFY_FAILED` on a bulk download | `urllib` couldn't verify the certificate (Windows / antivirus scanning HTTPS) | Use `requests` (it ships the certifi CA bundle) — the label/ndc scripts now do | Yes |
| HTTP 403 on the API | Keyless request hit the low rate limit | Use your API key (`OPENFDA_API_KEY` in `.env`) | Yes |
| A Spark cell takes ~1 hour | Re-reading + re-parsing nested JSON on every check (no cache) | Cache once to Parquet (`df.write.parquet(...)`), then read the Parquet — seconds, not minutes | Yes |
| Silver write fails: `Read-only file system` / `Permission denied` on `/home/jovyan/silver` | The `silver`/`quarantine` mounts aren't present — container wasn't recreated after the compose edit | `docker compose up --force-recreate`; confirm the two host dirs (`D:/capstone/data/silver`, `.../quarantine`) exist and the mounts are in `docker-compose.yml` | Yes |
| Silver run: one reaction-explode task stalls near 100% / executor OOM | Mega-report skew (max 4,113 drugs × 518 reactions on a single report) piled on one task | The notebook repartitions on `(safety_report_id, drug_idx)` before the reaction explode; processing month-by-month also keeps each batch small | Yes |
| **C: drive fills up; driver dies mid-`.parquet()` write** (`py4j` "Answer from Java side is empty" / "py4j does not exist in the JVM") | Single-shot whole-dataset `dropDuplicates`+`partitionBy` OOM'd the driver, and each crashed run left orphaned Spark spill (`blockmgr-*`, `spark-*`) stacking up inside `docker_data.vhdx` on **C:** — retrying/rebooting made it worse | **Root fix applied:** spill routed to D: (`SPARK_LOCAL_DIRS=/opt/spark-tmp`), cache on D:, notebook runs **month by month** (no giant shuffle). **Never** retry/reboot a crashed run without spill-on-D: + a memory fix first — that is exactly what filled C: | Yes (idempotent) |
| Silver read: `Cannot reserve additional contiguous bytes in the vectorized reader` / `OutOfMemoryError: Java heap space` | Spark's vectorized Parquet reader batches 4,096 rows of the wide, deeply-nested `patient.drug[]` column at once (× many cores) → heap blows | Disable it: `spark.sql.parquet.enableVectorizedReader=false` (already set in the notebook); row-based reading is far lighter on nested data | Yes |
| A Silver run crashed and you want to retry | Orphaned Spark spill may remain (now on **D:**, so it cannot fill C:) | Delete everything in `D:/capstone/data/spark-tmp/` (host) or `docker exec capstone-spark-jupyter rm -rf /opt/spark-tmp/*`; check `docker system df`; then re-run — month-by-month writes are idempotent (dynamic partition overwrite) | Yes |
| Airflow `build_silver` fails with `java.io.IOException: Cannot allocate memory` (in `ReadAheadInputStream` / `FileDispatcherImpl.read0`), while the **same job passes when run manually** | **Native (off-heap), not heap**, exhaustion — `--driver-memory 4g` was working. The Airflow stack (6 containers, ~2.3 GiB idle) plus a 4 GB Spark driver exceeds Docker's memory, which defaults to 50% of host RAM (7.58 GiB here); `local[*]` multiplies per-task native buffers | Raise the ceiling: `%UserProfile%\.wslconfig` → `[wsl2]` / `memory=10GB`; `docker compose stop` both stacks (**never `down -v`**), `wsl --shutdown`, restart Docker Desktop. Then add `--master local[4]` and `--conf spark.unsafe.sorter.spill.read.ahead.enabled=false` to `spark-submit`. *(Do **not** try `--conf spark.sql.shuffle.partitions` — the job sets it in code and a builder option overrides a `--conf` at submit time.)* | Yes — per-month dynamic partition overwrite is idempotent; failed attempts leave nothing to clean up |
| S3 prefix has **more objects than the run produced** (e.g. 499 where 486 expected), and a `COPY` from that stage would load too many rows | `aws s3 sync` **without `--delete` only adds**, and Spark names its output files with a **per-run UUID** — so a re-run's files land *alongside* the previous run's instead of replacing them. The Spark job is idempotent; the upload task is not | Add `--delete` to the sync (makes the destination an exact mirror) and grant `s3:DeleteObject` **scoped to the pipeline's own prefix only**, never the validated artifact or NDC prefixes. Then re-run just the upload task (`airflow tasks test … upload_s3`) — no Spark needed. Verify the object count and total bytes | Yes |
| `COPY INTO` a table that already holds data **doubles the row count** | Snowflake tracks load metadata **per file path**. Files from a *different* stage are paths the table has never seen, so they load again on top of the existing rows | `TRUNCATE TABLE` before the `COPY`. **`TRUNCATE` clears the load metadata; `DELETE` does not** — so `DELETE` is not a substitute. Always compare a scratch-table load against the current production count (and a `MINUS` on the grain key) *before* truncating anything | Yes — after `TRUNCATE` |
| `build_silver` fails after ~1 second with `docker.errors.APIError: 409 … container is not running` | Airflow **triggers** Spark rather than hosting it, so `capstone-spark-jupyter` must already be running. Easy to miss after a restart, because starting the Airflow stack does not start the repo stack | `docker compose up -d` from the repo root, then `docker ps` — expect **8** containers (6 Airflow + spark-jupyter + dbt) before triggering. Then re-trigger, or clear the failed task in the UI to resume the existing run | Yes |
| Snowflake auth fails: `Could not deserialize key data` / `JWT token is invalid` / `No such file or directory: /keys/rsa_key.p8` | Key-pair problems, in order: the `.p8` is not PKCS#8; the registered public key doesn't match the private key (or wrong user); the key mount isn't applied | Regenerate with `openssl pkcs8 -topk8 … -nocrypt`; check `DESC USER DE_CAPSTONE_SVC` → `RSA_PUBLIC_KEY_FP`; `docker compose up -d --force-recreate dbt` (a plain restart does not add a new mount) | Yes |
| Only `airflow-worker` crash-loops after adding dbt to `_PIP_ADDITIONAL_REQUIREMENTS` — `RestartCount` climbing, `health` stuck at `starting`, **no traceback**, log ends at `BACKEND=redis` | `dbt-core` 1.12 requires `click>=8.3` / `cryptography>=46` / `protobuf>=6`, all above apache-airflow 2.10.5's pins; the variable installs with **no constraint file** and silently upgrades Airflow's own dependencies. Scheduler/webserver survive because `celery worker` imports a wider surface | Remove the dbt packages from the pip line, then `docker compose up -d --force-recreate airflow-worker` — a plain restart keeps the bad `/home/airflow/.local`. Run dbt in its own container (`capstone-dbt`, `dbt.Dockerfile`) and have Airflow exec into it, same pattern as Spark. **Diagnosis tip:** `{{.State.ExitCode}}` is meaningless while a container runs — sample `{{.RestartCount}}` twice, 60 s apart | Yes |
| Streamlit's ranked table is topped by rows with **blank PRR / ROR** | The reaction was reported *only* with that drug, so `c = 0`: `metric_prr` divides by `nullif(c/(c+d), 0)` and returns NULL — undefined, not infinite. Snowflake sorts **NULLs first** under `ORDER BY … DESC`, so undefined pairs head a list meant to rank by magnitude | `order by <col> desc nulls last` in `build_signal_query` / `build_period_query`. The dbt side was already correct — `coalesce(…, false)` keeps `is_signal` FALSE | Yes |
| The monthly table is empty while the all-time table has rows | The all-time case floor (default **100**) was applied at monthly grain, where a typical `a` is single digits | Use the separate **"Minimum cases (a) - monthly"** input (default 5). Two different floors for two different grains is deliberate, not a duplicate control | Yes |
| The Airflow Graph/Grid view shows tasks that never ran in the run you are inspecting (empty cells, or tasks whose timestamps make the dependency order impossible) | **Airflow 2.x has no per-run DAG versioning.** The scheduler stores one serialised DAG — the latest parse — and the UI renders that structure over *every* historical run. A run from before a DAG edit is displayed with today's graph | Ignore the graph for historical runs. Use `docker compose exec airflow-scheduler airflow tasks states-for-dag-run pv_pipeline "<run_id>"` — it lists only the task **instances** that actually existed, with start/end times. Cross-check against the run's Event Log. Per-run versioning arrives in Airflow 3 | Yes |
| Streamlit crashes with `StreamlitDuplicateElementId: There are multiple plotly_chart elements with the same auto-generated ID` | **Tabs are not lazy** — every tab's code runs on every rerun, so charts in different tabs coexist. Streamlit derives an element's ID from its type *and* parameters, so two charts that happen to receive identical data collide. Hit on the enhanced dashboard when Drug=CLOZAPINE + Reaction=(any) + Rank by=PRR made the Signal Explorer and Drug Profile bar charts byte-identical | Give every chart and table an explicit `key="..."`, so the ID no longer depends on the data. Applied to all 10 `st.plotly_chart` / `st.dataframe` calls in `app/dashboard_enhanced.py`, not only the two that collided | Yes |
| A GitHub Actions job fails with `Not authorized to perform sts:AssumeRoleWithWebIdentity`, on a trust policy that saved without error and looks correct | **GitHub's immutable subject claims.** Since 15 July 2026 every *new* repository issues a `sub` containing numeric ids — `repo:<owner>@<owner_id>/<repo>@<repo_id>:<ref>` — so a policy written as `repo:owner/repo:*` matches nothing. This repo was created 2026-08-02, so it is affected. **IAM validates syntax, not reachability** | Read the real subject rather than guessing: the `Show the OIDC subject` step in `s3-contract.yml` decodes the token and prints `sub`/`aud` **before** the assume. Get the ids with `gh api user --jq .id` (263947291) and `gh api repos/nkouhdareh/de-capstone-pipeline --jq .id` (1320110552). Note the subject differs by event — `:pull_request` vs `:ref:refs/heads/main` — so a policy pinned to one fails on the other | Yes |
| An S3 read from CI fails with `AccessDenied` although the inline policy looks right | Either the ARN shape (`s3:ListBucket` acts on the **bucket** ARN with no `/*`; `s3:GetObject` on the **object** ARN with `/*`), the `s3:prefix` condition not matching the prefix the CLI actually sends, or the **permissions boundary** capping an action the inline policy grants | Check with the **IAM policy simulator** (IAM → Roles → the role → Simulate) — it evaluates the identity policy *and* the boundary, entirely inside AWS, with no workflow run needed. **Always paste an explicit resource ARN**; an empty or `*` resource makes correctly-scoped allows come back denied | Yes |
| `gh run view <id> --log` returns `HTTP 404` on `/actions/runs/<id>/jobs`, or the browser shows "This workflow does not exist" for a file that is on `main`, or the API returns `503` with a unicorn page | A **GitHub-side incident**. Endpoints degrade independently, so the runs API can answer while the jobs API 404s. The red text of a `gh` error reads like a red *check* and is not one | Trust the `conclusion` field, not the CLI's error: `gh run list --workflow "<name>" --limit 1 --json databaseId,conclusion,event --jq '.[0]'`. Check <https://www.githubstatus.com>. If a run never starts once GitHub recovers, re-trigger with `git commit --allow-empty -m "ci: re-trigger" && git push`. **Verify on the other system meanwhile** — the IAM policy simulator confirms AWS-side behaviour with GitHub down | Yes |
| `terraform plan` fails with `AccessDenied: iam:ListOpenIDConnectProviders` | A `data "aws_iam_openid_connect_provider"` block looks the provider up **by URL**, and resolving a URL to an ARN calls `ListOpenIDConnectProviders` — not `GetOpenIDConnectProvider`. That action **does not support resource-level permissions**, so granting it means `"Resource": "*"` in an Allow statement | **Remove the dependency, don't widen the policy.** Reference the provider by ARN in a `locals` block (`arn:aws:iam::617371012792:oidc-provider/token.actions.githubusercontent.com`) and delete the data source. The string is identical, so an imported trust policy still matches and the plan stays `0 to change` | Yes |
| `terraform plan` shows `1 to change` on an imported resource that nobody edited | The config does not match the live resource exactly. Usual culprits: a `tags` block the role does not have (or missing one it does), `max_session_duration` written out when 3600 is the provider default, a `description` that differs by a character, or an omitted `permissions_boundary` | **Fix the code, never the live resource.** Author the config from the console's actual values — trust policy JSON, inline policy body, boundary ARN, description, tags — then re-plan. The acceptance gate is `Plan: 2 to import, 0 to add, 0 to change, 0 to destroy` | Yes |

---

## 5. Recovery procedures

### A run failed partway through

**Ingestion has no auto-checkpoint yet** — it restarts from `START`. To resume an interrupted
`ingest_drug_event.py`:

1. Note the **last `receivedate=` folder** written (e.g. `20241018`).
2. **Delete that day's folder** — it may be half-written: `rm -rf .../drug_event/receivedate=20241018`.
3. Set `START` in the script to that date, save, and re-run — it fills only the remaining days.
4. Afterwards, set `START` back to the full range.

For **specific short days** (a page failed mid-day), use `scripts/backfill_days.py` instead
(edit its `DAYS` list) — it re-fetches just those days with your key. Verify with per-day
API count vs disk.

### Data looks wrong in the marts

*How to trace back through the layers to find where it broke.*

### Rebuilding from raw

*Bronze is immutable, so silver and gold can be rebuilt without re-ingesting.*

### Reloading Snowflake RAW (and rolling back the S3 cutover)

Production RAW is loaded from **S3** (`RAW.SILVER_PIPELINE_S3_STAGE` / `RAW.NDC_S3_STAGE`). The
**internal stages and `scripts/load_to_snowflake.py` are deliberately kept intact as the rollback
path** — they rebuild RAW from the local Parquet on D: in ~10 minutes:

```bash
.venv-dbt/Scripts/python.exe scripts/load_to_snowflake.py --what silver
```

**Before any reload or cutover, always run the comparison first** — load into a `TEMPORARY` table and
check three things against the current production table: the row count, the row count for a known
month, and a `MINUS` on `report_drug_reaction_key` (must be **0**). Equal counts alone are not enough;
the `MINUS` is what proves the rows are identical rather than merely equinumerous.

Then, and only then:

```sql
TRUNCATE TABLE RAW.SILVER_DRUG_EVENT;   -- clears load metadata; DELETE does NOT
COPY INTO RAW.SILVER_DRUG_EVENT FROM @RAW.SILVER_PIPELINE_S3_STAGE
  FILE_FORMAT = (FORMAT_NAME = 'DE_CAPSTONE.RAW.FF_PARQUET')
  MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
  PATTERN = '.*[.]parquet' ON_ERROR = 'ABORT_STATEMENT';
```

Verify **45,030,932**, then rebuild the models (`dbt build` → PASS=53) and re-check a known signal —
**clozapine → neutropenia, PRR 35.94, 5,571 cases**. If a known-answer signal is unchanged after a
reload, the load path is faithful.

*The dbt models are materialised tables, so they keep serving their previous contents throughout a
reload — there is no window where the marts are broken.*

---

## 6. Teardown

```bash
docker compose down -v
```

- **`docker compose stop`** — pauses the container and **keeps** the Parquet cache. Use this between sessions.
- **`docker compose down`** — removes the container; the **Parquet cache is lost** (rebuild it with the write cell). `-v` additionally removes named volumes.
- **Your data and notebooks are never deleted** by any of these — they live in host folders (bind mounts), not inside Docker.

*Cloud-side to destroy to avoid cost: none yet (everything is local so far).*


---

## Week 3 — dbt on Snowflake (build, test, and scale to 24 months)

**Status:** built & tested on a **1-month smoke** (2023-01). Everything below also drives the 24-month scale-up.

### Environment (Git Bash / MINGW64)
- **Two venvs** at the repo root: `.venv` (ingestion) and **`.venv-dbt`** (dbt — created Week 3, keeps `.venv` clean).
  `python -m venv .venv-dbt` → `source .venv-dbt/Scripts/activate` → `pip install dbt-snowflake` (pulls dbt-core + snowflake-connector).
- **dbt project:** `de_capstone/` (underscore) inside the `de-capstone/` (hyphen) repo. **Run all `dbt` commands from inside `de_capstone/`.**
- **Reliable `dbt`:** in Git Bash, activation can leave `python` on the *system* Python — safest is an alias to the exe:
  `alias dbt="/d/capstone/de-capstone/.venv-dbt/Scripts/dbt.exe"`
- **Snowflake:** account `AAFWBCY-ZE61835` · user `NKOUH` · role `DE_CAPSTONE_DBT_ROLE` · wh `DE_CAPSTONE_WH` · db `DE_CAPSTONE` · schemas `RAW` (source data) + `DBT_DEV` (dbt models).
- **Creds:** git-ignored `.env` at repo root — `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PRIVATE_KEY_PATH` (single-quote the values). `de_capstone/profiles.yml` reads all three via `env_var()`. Load them into the shell (needed by loader AND dbt):
  > **Key-pair authentication since 2026-08-13** (Snowflake deprecated password-only sign-ins on 2026-08-18). The pipeline connects as the service user **`DE_CAPSTONE_SVC`** (`TYPE = SERVICE`, no password possible) with an RSA key held **outside the repo** at `D:/capstone/.keys/rsa_key.p8`. `NKOUH` remains a human account with password + TOTP MFA for the Snowsight UI only. There is **no Snowflake password anywhere in the project**. Full procedure: `docs/Layer Explanation/Airflow.md` Part F.
  `set -a; source .env; set +a`   (from repo root; from inside `de_capstone/` use `source ../.env`).

### Fresh-terminal setup (every new shell)
```bash
cd /d/capstone/de-capstone
set -a; source .env; set +a
alias dbt="/d/capstone/de-capstone/.venv-dbt/Scripts/dbt.exe"
cd de_capstone
dbt debug            # expect: All checks passed!
```

### Load raw -> Snowflake RAW
- **DDL** (once, Snowflake worksheet): `scripts/ddl_raw.sql` — creates `RAW.SILVER_DRUG_EVENT` (35 cols), `RAW.DRUG_NDC` (VARIANT), stages `SILVER_STAGE`/`NDC_STAGE`, file formats `FF_PARQUET`/`FF_JSON`.
- **Loader** `scripts/load_raw.py` (connects via the 3 env vars; PUT -> COPY):
  `.venv-dbt/Scripts/python.exe scripts/load_raw.py`  (from repo root, after `source .env`).
  As written it loads **ONE month (2023-01)** + the **full NDC**. Expect `NDC 136520`, `Silver 1549263`.
- **On-disk sources:** Silver Parquet `D:/capstone/data/silver/drug_event/receive_year=YYYY/receive_month=M/*.parquet` (24 partitions 2023-01..2024-12, **45,030,932** rows total). NDC `D:/capstone/data/bronze/drug_ndc/part-0000.json` (NDJSON, 136,520).
- **Why 35 cols:** Spark partition cols `receive_year`/`receive_month` are path-encoded (not in the Parquet files) -> recomputed from `receive_date` downstream. COPY uses `MATCH_BY_COLUMN_NAME=CASE_INSENSITIVE`.

### Build & test
```bash
dbt deps                                # once - installs dbt_utils
dbt build                               # 10 models + seed + 42 tests, in DAG order
dbt test                                # tests only
dbt docs generate && dbt docs serve     # lineage at localhost:8080 (graph icon, bottom-right); Ctrl+C to stop
```
Models (`de_capstone/models/`): `staging/{stg_drug_event,stg_drug_ndc}` (views) -> `intermediate/int_drug_resolution` (table) -> `marts/{dim_drug,dim_reaction,dim_reporter,dim_date,fct_report_drug_reaction,fct_signal_metrics}` -> `semantic/sem_signal_metrics` (view). Macros: `normalize_drug_name`, `signal_metrics`. Seed: `seeds/signal_worked_example.csv`. Thresholds: `vars:` in `dbt_project.yml` (`signal_min_cases:3, signal_min_prr:2.0, signal_min_chi2:4.0, signal_ror_ci_min:1.0`).

### >>> SCALE TO ALL 24 MONTHS (45,030,932 rows)
1. **Load all 24 months** with **`scripts/load_to_snowflake.py`** (its DDL, `scripts/ddl_raw.sql`, runs automatically). It loops every `receive_year=*/receive_month=*` partition (PUT into `@RAW.SILVER_STAGE/y=<y>/m=<m>/`, then one `COPY INTO`), **`TRUNCATE`s + `REMOVE`s the stage itself**, and has a `--max-partitions` smoke flag. From the repo root: `.venv-dbt/Scripts/python.exe scripts/load_to_snowflake.py --what silver`.
2. **Clear the smoke first** (worksheet, or the full loader does it): `TRUNCATE TABLE RAW.SILVER_DRUG_EVENT;` and `REMOVE @RAW.SILVER_STAGE;` — otherwise COPY skips already-loaded files. NDC can stay.
3. Run the loader — PUT ~= **3.7 GB / 486 files**, several minutes. Verify `SELECT COUNT(*) FROM RAW.SILVER_DRUG_EVENT` ~= **45,030,932**.
4. `dbt build` — models are `table`/`view`, so this fully rebuilds on the new data (no `--full-refresh` needed). `fct_report_drug_reaction` ~= 45M.
5. `dbt test` (42 green — 24-month load + star schema + 3 improvements). Re-check resolution rate + top signals (full data cuts the 1-month sparsity -> trustworthy signals). Re-publish the resolution rate.

### TR §5 star schema — DONE ✅
Added `dim_reporter` (**726**; grain = reporter qualification/type + `occur_country`) and `dim_date` (**731**; complete 2023–2024 `date_spine`; `date_key` = yyyymmdd). fct **joins all 4 dims** to fetch their keys — `dim_reporter` via a NULL-safe `equal_null` join on the 3 natural cols, `dim_date` on `receive_date = full_date` — dropping the degenerate `reporter_type`/`occur_country`; **4 conformed dims, all not-null + FK `relationships` tested — 9 models · 36/36 green.** *(Refinement: keys were first computed inline (hash / `to_char`) — FK-valid but left the two dims unlinked in the DAG; refactored to joins so the lineage shows the complete star — `docs/assets/dbt-dag-refinement.png`. Keys identical, tests unchanged.)*

### dbt improvements — DONE ✅ (period metrics · ROR-CI · Airflow calendar)
- **Period-grain signals:** `marts/fct_signal_metrics` (table, drug×reaction×**month**, **5,069,399**) — same macros, answers "this period" (TR §5.1); `sem_signal_metrics` stays all-time. Tests: not-null `period_key`/`year`/`month` + unique `(drug_key, reaction_key, period_key)`.
- **ROR-CI flag:** `is_signal_strict` (= `is_signal` and `ror_ci_lower > signal_ror_ci_min` [1.0]) on both signal models; `is_signal` unchanged (TR-23). Prunes 0.85% monthly / 0.09% all-time.
- **Airflow-ready `dim_date`:** calendar derived from distinct `receive_date` (via `stg_drug_event`), not a hardcoded 2023–2024 `date_spine` — a future scheduled load auto-extends it (same 731 rows today). fct→dim_date FK re-verified. **10 models · 42/42 tests.**

### S3 external stage (TR-09) — CONFIGURED & VALIDATED ✅ (not cut over)
External stages against a **private S3 bucket in `eu-central-1`** (matches Snowflake region), via a secure **storage integration** (no keys in Snowflake). **Least-privilege IAM** = read-only on only the `silver/` + `ndc/` prefixes; bucket **private + AES256 (SSE-S3)**, Block Public Access on. Validated non-destructively: `LIST` + `SYSTEM$VALIDATE_STORAGE_INTEGRATION` pass; scratch-table loads **Silver 121,279 / 0 errors**, **NDC 136,520 / 0 errors**. Internal stages (`SILVER_STAGE`/`NDC_STAGE`) + `scripts/load_to_snowflake.py` **unchanged**; **no cutover**, **no cleanup**. Full guide: `docs/Layer Explanation/S3 external-stage guide.md`.

### Silver job + Airflow (TR-28) — job converted & smoke-validated ✅ (Airflow next)
`notebooks/02_build_silver_drug_event.ipynb` → **`scripts/build_silver.py`** (headless, `--months 2023-01|all`, idempotent dynamic overwrite; transformations identical; requires `SILVER_OUT`/`QUAR_OUT`/`SILVER_METRICS` env so it can't hit production). Smoke-validated: 2023-01 = **1,549,263** rows, exit 0, 13 parquet files. `docker-compose.yml` gained `./scripts:/home/jovyan/scripts`.

**Run the Silver job** (Git Bash — NOT plain `python`, which has no pyspark; `spark-submit` needs explicit memory or it OOMs / exit 137):
```bash
MSYS_NO_PATHCONV=1 docker exec -e SILVER_OUT=/home/jovyan/silver/smoke_2023_01 -e QUAR_OUT=/home/jovyan/quarantine/smoke_2023_01 -e SILVER_METRICS=/home/jovyan/silver/_smoke_metrics_2023_01 capstone-spark-jupyter /usr/local/spark/bin/spark-submit --driver-memory 4g /home/jovyan/scripts/build_silver.py --months 2023-01
```
Next: Airflow — `airflow/.env` → `airflow/docker-compose.yaml` → `airflow/dags/pv_pipeline.py` → one-month DAG smoke → cutover → full 24-month → Streamlit. Full guide: `docs/Layer Explanation/Airflow.md`.

### Still TODO (not built - core-first)
- ✅ **pytest TR-37 / TR-38 — done.** Now in `tests/`, run by the `pytest` job in `ci.yml` (**21 passed**). `dbt_reference/tests/` keeps the original copies.
- S3 external stage (TR-09; currently internal stage — documented deviation), Airflow DAGs, Streamlit.

### Reference "answer key"
`dbt_reference/` (read-only) is a verified copy of the whole implementation — diff against it. (The 24-month loader now lives in the project at `scripts/load_to_snowflake.py` + `scripts/ddl_raw.sql`.)
