# Project Progress & Handoff

*A running snapshot of where the project is, so a fresh session (or a teammate) can pick up fast.*
**Status as of:** Silver done (Week 2 — 45,030,932 clean rows). **Week 3: dbt on Snowflake — 24 months + full TR §5 star schema + 3 improvements ✅** — **10 models · 42/42 dbt tests** green (4 conformed dims all FK-tested; period-grain signals; ROR-CI strict flag; Airflow-ready calendar); real signals recovered (clozapine→neutropenia PRR 35.9, Paxlovid rebound PRR 228, opioid dependence). **Week 4: Airflow orchestration + S3 cutover ✅ COMPLETE** — 3 Docker stacks (Airflow 2.10.5 · PySpark · dbt); full **24-month run through Airflow = 45,030,932 rows** (5 h); **production RAW now loaded from S3**; **clozapine→neutropenia PRR 35.94 unchanged after the cutover** (same inputs, same maths, same answer, different infrastructure); and **one trigger now runs the entire pipeline** — 8 tasks green in 21 min, `dbt_build` PASS=53, `dbt_test` PASS=42. **NEXT: Streamlit — the only remaining MVP item.**

---

## What this project is
A **Drug Safety Signal Pipeline** (pharmacovigilance). A **batch ELT** pipeline over openFDA
drug-safety data → an **OLAP** warehouse, computing disproportionality signals (PRR/ROR) for a
drug-safety analyst, with a dashboard. Health domain. Full business case: `docs/business_requirements.md`.

## Stack (decided — see `docs/adr/`)
| Layer | Choice |
|---|---|
| Ingestion | Python (`requests`) |
| Raw storage (bronze) | local D: drive now → AWS S3 later |
| Explore / data quality | **PySpark + Jupyter in Docker** (`docker-compose.yml`) |
| Warehouse | **Snowflake** (ADR-002) |
| Transform | **dbt** (SQL modelling) + **PySpark** (flattening) (ADR-004) |
| Orchestration | Airflow in Docker (later) |
| Serving | Streamlit (later) |
| Stretch | RAG over drug labels (pgvector + Ollama) |

## Data — ingested & verified (in `D:/capstone/data/bronze/`, git-ignored)
| Dataset | Records | Notes |
|---|---|---|
| `drug_event` (FAERS) 2023–2024 | **2,687,675** | NDJSON, partitioned by `receivedate=`; verified vs openFDA |
| `drug_label` | 261,258 | bulk files |
| `drug_ndc` | 136,520 | bulk file |

## Done ✅
- Repo + venv + `.env` + GitHub (private) + project board (8 issues)
- ADRs: **001** (domain = openFDA drug safety), **002** (Snowflake), **004** (dbt + PySpark)
- Ingestion scripts: `ingest_drug_event.py` (date-windowed), `ingest_drug_label.py` / `ingest_drug_ndc.py` (bulk), `backfill_days.py`
- Metadata: `docs/Metadata/` — `metadata.md`, `field_dictionary.md`, `drug_event_schema.md` + openFDA specs
- **Exploration / data quality**: `notebooks/01_explore_drug_event.ipynb` — all 5 dimensions
- Week-1 coach answers: `scripts/PoC/week1_coach_answers.md`
- **Silver layer (PySpark)**: `notebooks/02_build_silver_drug_event.ipynb` — flatten → (case, drug,
  reaction), cast/decode, **#4** dedup, **#5** tiered normalisation (rate published), **#6**
  validation/quarantine. **Verified full run: 45,030,932 clean atomic rows** (from 93.4M pre-dedup,
  51.8% deduped), all 24 months, grain key unique, 0 null reactions. `docker-compose.yml` mounts
  `silver`/`quarantine`/`dq_cache`/`spark-tmp` on D: (all Spark scratch off C:); bronze stays read-only.

## Key data-quality findings (these drive the cleaning)
| Dimension | Result | Cleaning action |
|---|---|---|
| Uniqueness | 0 duplicate `safetyreportid` (2.69M unique) | #4: report-level dedup already done by openFDA; re-check the (report, drug, reaction) grain after flatten |
| Completeness | key fields 100% (id, dates, drug name, reaction); demographics partial (age 44%, sex 17%, country 11%) | #6: demographics → `Unknown` |
| Consistency | coded fields valid **except 18 rogue `drugcharacterization`** (codes 4/5) | #6: quarantine `drugcharacterization ∉ {1,2,3}` |
| Drug names | 97,789 distinct; ~83% resolved by `openfda.generic_name` | #5: Tier-1 `openfda.generic_name`/`substance_name`; Tier-2 clean/flag the ~17% tail |
| Fan-out / skew | ~3.9 drugs & ~3.0 reactions per report; **max 4,113 drugs / 518 reactions** | Silver: handle mega-report skew when flattening |
| Timeliness | exact 2023–2024 window; batch/quarterly source | note only |

## Silver layer — built & verified (#4 / #5 / #6) — PySpark
`notebooks/02_build_silver_drug_event.ipynb`. Grain: one row per **(case, resolved drug,
characterization, reaction)**; columns feed `fct_report_drug_reaction` (TR §5.2). Runs **month by
month** (no whole-dataset shuffle); **all Spark spill + cache on D:** (`SPARK_LOCAL_DIRS=/opt/spark-tmp`,
`dq_cache` mounted to D:) — never C:. Explicit `CLEAN_REBUILD` (logged, not silent).

**Verified full-run results (all 24 months, `_run_id` `silver_20260805…`):**
- **#4 dedup** — 93,366,638 atomic rows → **45,030,932** deduped (**51.8%** removed). Report-level was
  0 dup; the dupes are at the atomic grain (a report repeats the same drug across dosage lines →
  collapsed to one row per case-drug-reaction). Grain key unique (45,030,932 / 45,030,932).
- **#5 normalisation** — **78.46%** resolved via the report's **own** `generic_name`/`substance_name`
  (35.3M rows); 9.7M `unresolved_raw` keep a cleaned raw name, flagged. *Report-level only — the full
  NDC/rxcui resolution is the dbt step (`int_drug_resolution`);* `rxcui`/`product_ndc`/`package_ndc`/
  `brand_name` are carried through for it. Latest-version guard applied (max `safetyreportversion` per case).
- **#6 validation/quarantine** — 431,760 rejects, never dropped: **431,741 `reaction_pt_null`**, 18
  `drugcharacterization_out_of_range`, 1 `drugcharacterization_null`. Silver has **0 null reactions**.
  The 431,741 come from just **3 mega-reports** (23840947/23014826/22122822, `reporttype=1`,
  1,000–4,113 drugs) whose reactions are **all** blank — quarantine count = `n_drugs × n_reactions`
  exactly, so they are 100% quarantined and contribute **nothing** to Silver.
- **Observability** — per-month metrics persisted to `silver/_silver_metrics` (input/atomic/silver/
  dups/resolved/quarantined per month).
- **Output** — `D:/capstone/data/silver/drug_event/` (Parquet, partitioned by `receive_year`/`month`)
  + `quarantine/drug_event/` + `_silver_metrics/`. Run steps + baselines in `runbook.md` §2–§3.

**Watch for gold:** (1) drug resolution is report-level (78%) — the dbt NDC join must consolidate
identities before PRR/ROR are trustworthy, else case counts fragment across name variants; (2) the 3
mega-reports (and any bulk/study reports) can distort disproportionality — flag/exclude by drug-count
or `reporttype` in gold.

## dbt on Snowflake — SCALED TO 24 MONTHS + FULL TR §5 STAR SCHEMA (Week 3) ✅
Rebuilt hands-on in a new **`.venv-dbt`** (keeps `.venv` clean); dbt project in **`de_capstone/`**
(underscore) inside the repo. Snowflake: account `AAFWBCY-ZE61835`, user `NKOUH`, role
`DE_CAPSTONE_DBT_ROLE`, wh `DE_CAPSTONE_WH`, db `DE_CAPSTONE`, schemas **`RAW`** (source) + **`DBT_DEV`**
(models); creds in git-ignored `.env`, read by `profiles.yml` via `env_var()`.
**All run/build/scale commands: `runbook.md` → "Week 3 — dbt on Snowflake".**

- **Loaded (all 24 months):** `RAW.SILVER_DRUG_EVENT` = **45,030,932** · `RAW.DRUG_NDC` = 136,520.
  Loader `scripts/load_to_snowflake.py` (internal stage → PUT → COPY; `TRUNCATE`s + `REMOVE`s the stage itself;
  not S3 yet — documented deviation from TR-09). DDL `scripts/ddl_raw.sql`. *(1-month smoke first used
  `scripts/load_raw.py` → 1,549,263.)*
- **Models (10, all built):** `stg_drug_event`, `stg_drug_ndc` (views) → `int_drug_resolution` (table; NDC join
  rxcui→generic→brand→ingredient, exact-only, **ADR-005 written**; **84,039** signatures) → `dim_drug` (**4,368**;
  drug_key −1 = Unknown), `dim_reaction` (**18,057**), `dim_reporter` (**726**), `dim_date` (**731**; data-derived
  calendar, Airflow-ready), `fct_report_drug_reaction` (**45,030,932**, clustered on receive_date; **joins all 4 conformed dims → complete star lineage, all FK-tested**)
  → `sem_signal_metrics` (all-time view) + **`fct_signal_metrics`** (monthly-grain table, **5,069,399**); both compute PRR/ROR/ROR-CI/χ²
  via `macros/signal_metrics.sql` (formulas one place — TR-24), flags `is_signal` (TR-23) + `is_signal_strict` (adds ROR-CI > 1). Macros: `normalize_drug_name`, `signal_metrics`.
- **#7 tests: 42/42 pass** — key unique/not-null, FK `relationships` (fct → all 4 dims), `accepted_values`, row-count
  plausibility, and the **PRR/ROR hand-computed worked example** (seed `signal_worked_example.csv` +
  `tests/assert_signal_worked_example.sql`, TR-38).
- **Results (24 months):** report-row resolution **86.7%** (39,045,450 / 45,030,932; held vs smoke's 86.9%);
  distinct-drug resolution **10.0%** (8,444 / 84,039 signatures — the tail of rare raw names grew fastest, but
  the resolved head still covers 86.7% of rows). **315,270 signals / 1,240,645 pairs** (25.4% flagged; χ² grows
  with N, so the full-data flag rate rises even as each signal gains real support — a candidate set to rank by
  magnitude). Real signals recovered: **clozapine→neutropenia** (PRR 35.9, 5,571 cases, χ² 142,896),
  **Paxlovid→disease recurrence** (PRR 228), **opioid dependence** (oxycodone/acetaminophen PRR 370, tramadol
  PRR 61). *(1-month smoke: 32.3% distinct / 86.9% rows, 39,714 / 197,868 pairs.)* Lineage figure
  `docs/assets/dbt-dag-refinement.png` (9-model complete star); walk-through `docs/Layer Explanation/dbt steps.md`.
- **Reference "answer key":** verified copy of the whole build at **`dbt_reference/`** (read-only). The FULL
  24-month loader now lives in the project at **`scripts/load_to_snowflake.py`** (+ `scripts/ddl_raw.sql`).

## Scaled to 24 months ✅ (45,030,932 rows) — procedure in `runbook.md`
1. ✅ Loaded all 24 partitions into `RAW.SILVER_DRUG_EVENT` (**45,030,932**) via `scripts/load_to_snowflake.py`
   (+ `scripts/ddl_raw.sql`; `TRUNCATE`s + `REMOVE`s the stage itself). PUT ≈ 3.7 GB / 486 files.
2. ✅ `dbt build` (full rebuild) → `fct` = **45,030,932** → `dbt test` **27/27 green**.
3. ✅ Re-checked: report-row resolution **86.7%**, **315,270** signals / **1,240,645** pairs, clozapine→neutropenia PRR 35.9.

## TR §5 star schema ✅ (added `dim_reporter` + `dim_date`)
- **`dim_reporter`** (**726**; grain = reporter qualification/type + `occur_country`) and **`dim_date`** (**731**;
  complete 2023–2024 `date_spine`; `date_key` = yyyymmdd). fct **joins all 4 dims** to fetch their keys —
  `dim_reporter` via a NULL-safe `equal_null` join on the 3 natural cols, `dim_date` on `receive_date = full_date` —
  each with **not-null + FK `relationships` tests**; `reporter_type`/`occur_country` no longer degenerate,
  `receive_date_key` a real FK. **9 models · 36/36 green.**
- **Lineage refinement:** `reporter_key`/`receive_date_key` were first computed *inline* (surrogate hash /
  `to_char`) — FK-valid but leaving `dim_reporter`/`dim_date` **unlinked in the DAG**; refactored fct to fetch
  both via joins so the graph shows the **complete star** (keys identical, tests unchanged) —
  `docs/assets/dbt-dag-refinement.png`.

## dbt improvements ✅ (period metrics · ROR-CI · Airflow calendar)
- **#1 Period-grain signals** — new `fct_signal_metrics` (table, one row per drug×reaction×**month**, **5,069,399**),
  same metric macros; answers "strongest disproportionality **this period**" (TR §5.1). `sem_signal_metrics` stays all-time.
  Tests: not-null `period_key`/`year`/`month` + unique grain `(drug_key, reaction_key, period_key)`.
- **#2 ROR-CI condition** — `is_signal_strict` (= `is_signal` **and** `ror_ci_lower > signal_ror_ci_min` [1.0]) on **both**
  signal models; `is_signal` unchanged (TR-23). Prunes weakly-supported flags: **0.85%** monthly vs **0.09%** all-time.
- **#3 Airflow-ready `dim_date`** — calendar now **derived from the data** (distinct `receive_date`) instead of a hardcoded
  `date_spine`; a future scheduled load auto-extends it (same 731 rows today). fct→dim_date FK re-verified.

## S3 external stage (TR-09) — configured & validated ✅ (not cut over)
Snowflake external stages set up against a **private S3 bucket in `eu-central-1`** (verified to match the
Snowflake region via `CURRENT_REGION()`). Secure **storage integration** (no keys stored in Snowflake);
**least-privilege IAM** allowing read-only on only the `silver/` and `ndc/` prefixes; bucket **private + AES256
(SSE-S3) encrypted**, Block Public Access on. Validated **non-destructively**: `LIST` +
`SYSTEM$VALIDATE_STORAGE_INTEGRATION` passed, and scratch-table loads — **Silver 121,279 rows / 0 errors**,
**NDC 136,520 rows / 0 errors**.
**Not changed / not done:** the internal stages (`SILVER_STAGE`/`NDC_STAGE`) and the current loader
(`scripts/load_to_snowflake.py`) are **untouched** — production RAW is still loaded via the internal stages;
**no cutover** to S3 external stages yet, and **no cleanup** performed. Full guide:
`docs/Layer Explanation/S3 external-stage guide.md`.

## Silver job + Airflow phase — job converted & smoke-validated ✅ (Airflow next)
- **Silver notebook → `scripts/build_silver.py`** — headless, parameterized (`--months 2023-01 | all`), idempotent
  (dynamic partition overwrite); **transformations byte-identical** to `notebooks/02_build_silver_drug_event.ipynb`
  (kept as reference, untouched). Requires `SILVER_OUT`/`QUAR_OUT`/`SILVER_METRICS` env (no default → can't hit production).
- **Smoke-validated (2023-01):** **1,549,263** Silver rows, exit 0, 13 parquet files — matches the notebook.
  `docker-compose.yml` gained `./scripts:/home/jovyan/scripts`. Production `silver/drug_event` (45M) untouched.
- **Correct run** (Git Bash; the plain `python …` form fails — no pyspark): `MSYS_NO_PATHCONV=1 docker exec -e SILVER_OUT=… -e QUAR_OUT=… -e SILVER_METRICS=… capstone-spark-jupyter /usr/local/spark/bin/spark-submit --driver-memory 4g /home/jovyan/scripts/build_silver.py --months 2023-01`. **Key fix:** `spark-submit` needs `--driver-memory 4g` explicitly (it ignores the in-code driver memory → earlier OOM/137).
- **Next — Airflow** (Spark stays in its container; Airflow triggers it via `docker exec`): `airflow/.env` → `airflow/docker-compose.yaml` → `airflow/dags/pv_pipeline.py` → one-month DAG smoke (safe half `ingest→build_silver→upload_s3`) → cutover (`load_raw→dbt`) → full 24-month → Streamlit. Full plan: `docs/Layer Explanation/Airflow.md`.
- **`persist()` added** to the per-month loop and re-tested — same 1,549,263. The transformations are still identical to the notebook; only the **execution plan** is optimised (no recompute between `count` and `write`).

## Airflow orchestration (Week 4) — built, one-month smoke PASSED ✅
**Architecture — three Docker stacks; Airflow orchestrates, it does not host the tools.** The Airflow
stack (`airflow/docker-compose.yaml`, **pinned 2.10.5**: `stable` now serves Airflow 3.x, whose operator
import paths moved) triggers **`capstone-spark-jupyter`** and **`capstone-dbt`** over a mounted
`/var/run/docker.sock`. Credentials live in git-ignored `airflow/.env`; the compose file passes them
into the containers explicitly (a Compose `.env` only does variable interpolation).

- **DAG `airflow/dags/pv_pipeline.py`** — `ingest_ndc >> ingest_faers >> build_silver >> upload_s3`.
  `build_silver` and `run_dbt` share one `_exec_in_container()` helper that streams the child container's
  output into the task log and **raises on a non-zero exit** (so a Spark OOM fails the task instead of
  passing silently). A `BashOperator` running `docker exec` cannot work — there is **no docker CLI** in
  the Airflow image; the Python Docker SDK talks to the same socket.
- **Ingest tasks are guarded** (skip when Bronze is present) — Bronze is immutable, and an unconditional
  re-run would rewrite it over 30–60 minutes.
- **Writes only non-production paths:** Spark → `silver/pipeline`, upload → S3 `silver_pipeline/`.
  Production `silver/drug_event` (45M) and the validated 486-file S3 prefix are never written.
- **AWS identity (new):** IAM **user** `de-capstone-airflow-uploader` with least-privilege write
  (`PutObject` + multipart + scoped `ListBucket`; **no `DeleteObject`, no `GetObject`**). IAM *roles*
  cannot have access keys, and the Snowflake storage-integration role is read-only — so the uploader is a
  separate identity. Adding an S3 prefix means editing **two** policies: the writer and Snowflake's reader.
- **dbt runs in its own container** (`dbt.Dockerfile`, **dbt-snowflake pinned 1.12.0** to match `.venv-dbt`).
  Installing dbt into the Airflow image via `_PIP_ADDITIONAL_REQUIREMENTS` **crash-loops the celery worker**:
  dbt-core 1.12 needs `click>=8.3` / `cryptography>=46` / `protobuf>=6`, all above Airflow 2.10.5's pins,
  and the variable installs with no constraint file.
- **New Snowflake objects (additive):** `RAW.SILVER_PIPELINE_S3_STAGE` over `silver_pipeline/`, and the
  storage integration's allowed locations extended by `ALTER` (which does **not** rotate the external id,
  so no trust-policy rework). The internal stages, `SILVER_S3_STAGE`, `NDC_S3_STAGE` and
  `scripts/load_to_snowflake.py` are **untouched** — still the rollback path.

**Validated:**
| Check | Result |
|---|---|
| One-month DAG smoke (`{"months":"2023-01"}`) | all 4 tasks green; **1,549,263** rows; 13 parquet / 135,463,430 bytes in S3 |
| `dbt_test` driven by Airflow | **42/42** |
| Scratch rehearsal (1 month, temp table) | **1,549,263** = production's 1,549,263, and `MINUS` on the grain key = **0** → the S3 path yields *exactly the same rows*, not merely the same count |
| Production S3 prefix | `silver/drug_event/` **486 objects / 3,913,635,942 bytes — unchanged** |
| Snowflake RAW | **untouched** (cutover tasks not in the chain) |

**Two incidents, both in `runbook.md` §4:** (1) Spark `java.io.IOException: Cannot allocate memory` —
**native**, not heap: the six Airflow containers plus a 4 GB driver exceeded Docker's default ceiling
(50% of host RAM); fixed with `.wslconfig` `memory=10GB`, `--master local[4]` and disabling spill
read-ahead. (2) the worker crash loop above. Full phase guide (local only, folder git-ignored):
`docs/Layer Explanation/Airflow.md` — Part E has the current file contents and how to operate it.

## Full 24-month run + production S3 cutover ✅ (2026-08-11 / 12)

**Full run through Airflow:** `{"months":"all"}` → **success in 5 h 0 m**, 24/24 month partitions,
**`Requested-month Silver rows: 45030932`** — matching the notebook to the row, on a capped `local[4]`
Spark with the whole Airflow stack sharing the machine (~15 min/month).

**A bug the gates caught.** The S3 prefix afterwards held **499 objects, not 486**. Cause:
`aws s3 sync` **without `--delete` only adds**, and Spark names its output with a per-run UUID — so an
earlier one-month re-run's 13 files were left behind alongside the new ones. Unfixed, a `COPY` would
have loaded **46,580,195** rows (January twice) and silently corrupted every PRR/ROR value.
*The Spark job was idempotent; the upload task was not — idempotency is a property of the whole chain.*
Fixed with `sync --delete` plus `s3:DeleteObject` **scoped to `silver_pipeline/*` only**, so the
pipeline can mirror the prefix it owns while the validated artifact stays physically undeletable.
Prefix back to **486 / 3,913,633,244 bytes** — within **2,698 bytes** (Parquet metadata) of the
hand-uploaded copy, itself evidence the two Silvers are the same data.

**Full-scale comparison before touching production** (temporary table, read-only):
**45,030,932** = production's **45,030,932**, `MINUS` on the grain key = **0**, 24 months present.
Identical rows, not merely an identical count.

**Cutover.** `TRUNCATE` + `COPY` from `RAW.SILVER_PIPELINE_S3_STAGE` (and `RAW.DRUG_NDC` from
`NDC_S3_STAGE`). **`TRUNCATE` is a correctness requirement, not a preference:** Snowflake tracks load
metadata *per file path*, and `TRUNCATE` clears it while `DELETE` does not. The dbt marts are
materialised tables, so they kept serving throughout — no broken window.

**Results:** `dbt build` **through Airflow** → **PASS=53, WARN=0, ERROR=0** (10 models + seed + 42 tests);
`FCT_REPORT_DRUG_REACTION` = **45,030,932**; **clozapine → neutropenia PRR 35.94 · ROR 46.76 ·
ROR-CI 45.21 · χ² 142,896 · 5,571 cases — unchanged from before the cutover.**
Production RAW is now loaded from S3; the internal stages + `load_to_snowflake.py` remain as rollback.

## Reading the output critically — the top-20 by PRR
Ranking all-time signals by PRR (≥100 cases) shows **most of the largest values are artifacts**, which
is itself a finding worth reporting:

| Pattern | Examples | Why it appears |
|---|---|---|
| **Confounding by indication** | felodipine, isosorbide di/mononitrate, digoxin → **cardiospasm** | Nitrates and calcium-channel blockers *treat* oesophageal spasm — the drug co-occurs with the condition it is prescribed for |
| **Device/product-use events** | copper → *foreign body in reproductive tract*; etonogestrel → *pregnancy with implant contraceptive*; treprostinil → *device wireless communication issue* | IUDs, implants and pumps generate product-use reports inside the drug dataset |
| **Genuine label-level signals** | **pentosan polysulfate → pigmentary maculopathy** (real, led to an FDA label change); docetaxel → lacrimal structure injury; clozapine → neutropenia & **benign ethnic neutropenia (PRR 2,837)** | The signals the method is meant to find |
| **Reporting/notification bias** | talc → mesothelioma | Litigation-driven reporting inflates the ratio |

**Conclusion:** disproportionality is a **screening** tool, not causal evidence. The right product is a
**ranked candidate list with support shown** for a domain expert to triage — not a binary flag. It also
answers the "should I fuzzy-match the drug-name tail?" question: the top signals are limited by
**interpretation**, not by name resolution.

## Full chain in one trigger ✅ (2026-08-12)
`ingest_ndc → ingest_faers → build_silver → upload_s3 → load_raw → dbt_build → dbt_test → publish_metrics`
— **8 tasks green, DAG run `success` in 21 minutes.**

- **`load_raw` runs through dbt, not through Airflow's Python.** Using `snowflake.connector` in the
  Airflow worker would drag in `cryptography>=46` — above Airflow 2.10.5's pin, the same conflict that
  crash-looped the worker earlier. Instead a dbt macro (`macros/load_raw_from_s3.sql`) does the
  `TRUNCATE` + `COPY`, invoked as `dbt run-operation` in the dbt container. **The Snowflake connection
  exists in exactly one place.** A second macro (`publish_metrics.sql`) logs the headline numbers, so
  every run leaves an auditable record of what it produced.
- `DE_CAPSTONE_DBT_ROLE` granted `TRUNCATE`+`INSERT` on **only** the two RAW tables (it already owned
  them, so this was belt-and-braces — but it makes the intent legible).
- **Run with `{"months":"2023-01"}` and it still exercises everything:** dynamic partition overwrite
  rewrites only January locally, the other 23 months stay on disk, `sync --delete` removes nothing, S3
  keeps all 486 files, and `load_raw` still loads the full 45,030,932. 21 minutes instead of six hours,
  same final numbers.

**Verified:** `load_raw` → `RAW.SILVER_DRUG_EVENT rows: 45030932`, `RAW.DRUG_NDC rows: 136520` ·
`dbt_build` → **PASS=53 WARN=0 ERROR=0** · `dbt_test` → **PASS=42 WARN=0 ERROR=0** ·
`publish_metrics` → `fct_report_drug_reaction rows: 45030932`, `signals (is_signal): 315270`.

## NEXT
- **Streamlit — the only remaining MVP item.** Everything upstream of the dashboard is built, run at
  full scale, and verified end-to-end under orchestration.
- *Optional:* trim `build_silver`'s log volume (it forwards every Spark INFO line — invaluable for a
  10-minute job, unwieldy for a 5-hour one); a scheduled rather than manual trigger (`dim_date` already
  auto-extends for this); CI.
- pytest TR-37 (normalisation) / TR-38 (metrics) — dbt covers TR-38 in-warehouse; Python copies in `dbt_reference/tests/`.

## How to run (quick)
- **Explore:** `docker compose up` → http://localhost:8888 → `work/01_explore_drug_event.ipynb`. First cache JSON→Parquet (`/home/jovyan/dq_cache`) for speed. Full detail + failure fixes in `runbook.md`.
- **Silver:** `docker compose up` (recreates for the new writable mounts) → `work/02_build_silver_drug_event.ipynb` → Run All. Writes `silver/` + `quarantine/` Parquet. Detail in `runbook.md` §2.
- **Ingestion:** see `runbook.md` §2.
- **Airflow:** `docker compose up -d` in the repo root (Spark + dbt containers), then in `airflow/`
  → UI http://localhost:8080 (`airflow`/`airflow`). Trigger with config `{"months":"2023-01"}` or
  `{"months":"all"}`. Stop with `docker compose stop` — **never `down -v`**, which deletes Airflow's
  metadata DB (login, DAG history).

## Board issues (github.com/nkouhdareh/de-capstone-pipeline)
- **Done:** #1 repo/env, #2 first API call, #3 bronze ingestion, #8 ADR-001, **#4 dedup · #5 normalisation · #6 validation/quarantine** (Silver built & verified)
- **Done (Week 3):** dbt on Snowflake — staging → `int_drug_resolution` → **full TR §5 star schema (4 conformed dims)** → `sem_signal_metrics`, **#7 tests 36/36**, **scaled to all 24 months (45,030,932 rows)**.
- **Done (Week 4):** Airflow orchestration — 3 Docker stacks, DAG `pv_pipeline`, one-month smoke **1,549,263** end-to-end to S3, `dbt_test` **42/42** through Airflow, scratch rehearsal `MINUS` = 0; production untouched.
- **Next:** full 24-month run + production cutover; Streamlit; pytest TR-37/38.

## Rules / reminders
- **Data never in git** (lives on D: drive). Secrets in `.env` only.
- Small, frequent commits; conventional prefixes. Write **ADRs at decision time**.
- ~100 build hours total; "clean data" was the Week-1 milestone.
