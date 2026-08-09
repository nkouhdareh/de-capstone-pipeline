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
- **Creds:** git-ignored `.env` at repo root — `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD` (single-quote the values). `de_capstone/profiles.yml` reads all three via `env_var()`. Load them into the shell (needed by loader AND dbt):
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

### Still TODO (not built - core-first)
- pytest TR-37 (normalisation) / TR-38 (metrics) — dbt covers TR-38 in-warehouse; Python copies live in `dbt_reference/tests/`.
- S3 external stage (TR-09; currently internal stage — documented deviation), Airflow DAGs, Streamlit.

### Reference "answer key"
`dbt_reference/` (read-only) is a verified copy of the whole implementation — diff against it. (The 24-month loader now lives in the project at `scripts/load_to_snowflake.py` + `scripts/ddl_raw.sql`.)
