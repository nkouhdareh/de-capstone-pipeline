# Project Progress & Handoff

*A running snapshot of where the project is, so a fresh session (or a teammate) can pick up fast.*
**Status as of:** Silver done (Week 2 — 45,030,932 clean rows). **Week 3: dbt on Snowflake — 24 months + full TR §5 star schema + 3 improvements ✅** — **10 models · 42/42 dbt tests** green (4 conformed dims all FK-tested; period-grain signals; ROR-CI strict flag; Airflow-ready calendar); real signals recovered (clozapine→neutropenia PRR 35.9, Paxlovid rebound PRR 228, opioid dependence). **Week 4: Airflow orchestration + S3 cutover + Snowflake key-pair auth ✅ COMPLETE** — 3 Docker stacks (Airflow 2.10.5 · PySpark · dbt); full **24-month run through Airflow = 45,030,932 rows** (5 h); **production RAW now loaded from S3**; **clozapine→neutropenia PRR 35.94 unchanged after the cutover** (same inputs, same maths, same answer, different infrastructure); and **one trigger now runs the entire pipeline** — 8 tasks green in 21 min, `dbt_build` PASS=53, `dbt_test` PASS=42. **Week 5: Streamlit dashboard ✅ COMPLETE** — `app/dashboard.py` on port 8501 reads the marts directly (computes nothing; the dbt macros stay the single definition of every metric), all-time + monthly views, and reproduces **clozapine → neutropenia PRR 35.94 / 5,571 cases** with the monthly counts summing back to 5,571. **The MVP is complete end to end: ingest → Silver → S3 → Snowflake → dbt → Airflow → dashboard.**

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

### Precision worth stating: two proofs, combined on 2026-08-15 (audited the same day)

> **Resolved.** The gap described below was closed at **13:29 UTC on 2026-08-15** — see
> "Full chain at full scale" further down. The audit is kept because the orphan-task discovery is a
> real finding about Airflow, and because the gap is what motivated the run.


- **Full scale** was proven on **2026-08-11**: 24 months, 45,030,932 rows — but the DAG had only
  **four** tasks in dependency order at the time (`ingest_ndc → ingest_faers → build_silver → upload_s3`).
- **The full eight-task chain** was proven on **2026-08-12** and again on **08-13** — but only ever
  with `{"months":"2023-01"}`.

**No single run has done both.** The 2026-08-11 run *does* show green ticks on `dbt_build` and
`dbt_test`, but they were **orphan tasks** then: defined in the DAG with no upstream edge, so Airflow
scheduled them in the same tick as `ingest_ndc` — `dbt_build` finished at **11:36:03** while
`upload_s3` did not start until **16:28:44**. They ran correctly, against `RAW` as loaded earlier via
the internal stages, but *not* against the Silver that run produced. `load_raw` and `publish_metrics`
had no task instances at all (`airflow tasks states-for-dag-run` returns **six** rows, not eight).

This does not invalidate anything: D.9 explains why a one-month trigger still loads the full
45,030,932, so the end state is identical either way. It is stated here so the claim stays exact.

## Full chain at full scale ✅ (2026-08-15) — the gap closed

`{"months":"all"}` through the current eight-task DAG: **`success` in 3 h 57 m 23 s, all 8 tasks
green, in dependency order.** Run `manual__2026-08-15T09:31:59+00:00`.

| Task | Duration | Result |
|---|---|---|
| `ingest_ndc` · `ingest_faers` | < 1 s each | SKIP — Bronze present |
| `build_silver` | **3 h 47 m 27 s** | 24/24 months · **`Requested-month Silver rows: 45030932`** |
| `upload_s3` | 5 m 28 s | 486 objects mirrored with `--delete` |
| `load_raw` | 2 m 43 s | `RAW.SILVER_DRUG_EVENT` **45,030,932** · `RAW.DRUG_NDC` **136,520** |
| `dbt_build` | 1 m 08 s | **PASS=53 WARN=0 ERROR=0** |
| `dbt_test` | 9.7 s | **PASS=42 WARN=0 ERROR=0** |
| `publish_metrics` | 15.7 s | `fct_report_drug_reaction` **45,030,932** · `dim_drug` 4,368 · `dim_reaction` 18,057 |

**Every task started 1–2 seconds after its predecessor finished** — the scheduler picking up each
newly-unblocked task on the next tick. Contrast 2026-08-11, where `dbt_build` began four hours
*before* `upload_s3`.

**Baselines captured before the run, re-checked after:**

| Prefix | Before | After |
|---|---|---|
| `silver_pipeline/` (rewritten by this run) | 486 / 3,913,633,244 | **486 / 3,913,633,244** |
| `silver/drug_event/` (the untouchable fallback) | 486 / 3,913,635,942 | **486 / 3,913,635,942** |

The first is the strongest test the D.7 `sync --delete` fix has had: Spark renamed all 486 files with
new UUIDs, so the sync had to delete 486 objects and upload 486 replacements. No accumulation — and
the byte total matched **exactly**, confirming the Spark output is deterministic. The second proves
least-privilege IAM held through a run that truncated production RAW.

**Reproducibility:** all 24 per-month lines — atomic and quarantined counts — were **identical** to
the 2026-08-11 run, including the three mega-report quarantine spikes (25,000 · 61,249 · 345,495).

**An hour faster, and the reason is documented.** 3 h 57 m against 5 h 00 m for the same work. The
entire difference is three months (2024-02/03/04) that took 26–30 minutes each on 11 August and
**9.2 minutes each** today. The other 21 months were unchanged. Cause: **CPU contention**, not data.
Spark runs on `--master local[4]`, and WSL shares all logical processors with Windows — so anything
else using the laptop steals cycles. Memory could not be the cause: `.wslconfig` gives Docker a hard
10 GB reservation. `Airflow.md` D.6 predicted exactly this ("Zoom competes only for CPU"); this run
was the accidental controlled experiment that confirmed it.

## Snowflake key-pair authentication ✅ (2026-08-13)
Snowflake deprecates **password-only sign-ins on 18 Aug 2026**, which would have broken `load_raw`,
`dbt_build`, `dbt_test` and `publish_metrics`. Migrated ahead of the deadline — and used it to separate
the human identity from the machine one:

| Identity | Purpose | Auth |
|---|---|---|
| `NKOUH` | Snowsight UI, administration | password + **TOTP MFA** |
| **`DE_CAPSTONE_SVC`** (new) | dbt, Airflow, both loaders | **key-pair only** — `TYPE = SERVICE` users cannot have a password |

Before this, the pipeline authenticated as a user whose default role was `ACCOUNTADMIN`. It now runs as
a service identity limited to `DE_CAPSTONE_DBT_ROLE`, with a 2048-bit RSA key held **outside the repo**
(`D:/capstone/.keys/`) and mounted read-only into the dbt container. `profiles.yml` reads
`SNOWFLAKE_PRIVATE_KEY_PATH` from the environment, so one profile serves both the container
(`/keys/rsa_key.p8`) and the host `.venv-dbt` (`D:/…`). Both loaders — including
`scripts/load_to_snowflake.py`, the documented rollback — were migrated too: a rollback is only worth
claiming if it still runs.

**Small blast radius, by earlier accident:** because `load_raw` runs through the dbt container rather
than `snowflake.connector` in the Airflow worker, the Snowflake credential existed in exactly one place.
A decision taken for dependency reasons turned out to be a security property.

**Verified:** `dbt debug` in-container and on the host · rollback loader connects as
`('DE_CAPSTONE_SVC', 'DE_CAPSTONE_DBT_ROLE', 'DE_CAPSTONE_WH')` · `grep` for `SNOWFLAKE_PASSWORD` finds
**no hits in live code** · **full DAG run `success` in 14 m 36 s, 8 tasks green**.
**There is no Snowflake password anywhere in the project.** Full procedure:
`docs/Layer Explanation/Airflow.md` Part F.

## Streamlit dashboard ✅ (2026-08-13) — MVP COMPLETE

`app/dashboard.py` + `app/db.py`, own venv `.venv-app`, port **8501**. Reads `DBT_DEV` directly and
**computes nothing** — PRR/ROR/ROR-CI/χ² all come from the dbt macros, so there is exactly one
definition of each metric in the project (TR-24 holds end-to-end, warehouse to screen).

- **Connection:** key-pair as `DE_CAPSTONE_SVC`, same three env vars as dbt. No password. Running
  `app/db.py` directly is a self-test that prints the identity and the known signal.
- **All-time view** — `SEM_SIGNAL_METRICS` filtered by drug / reaction / minimum cases / strict flag,
  ranked by PRR, ROR, cases or χ², with `a` and χ² shown beside every ratio. **The view answers in
  ~3.7 s**, so it was left as a view — no materialisation, no dbt change, no pipeline re-run.
- **Period view** — `FCT_SIGNAL_METRICS`: "strongest this period" for a chosen month, plus a 24-month
  PRR and case-count trend for a selected pair.

**Verified:** clozapine → neutropenia **PRR 35.94 · ROR 46.76 · ROR-CI 45.21 · χ² 142,896 ·
5,571 cases** — identical to the warehouse figures. Monthly: **24 months present**, monthly `a`
summing to **5,571** (each case has one `receive_date`, so the sum must close), and **2024-12 alone
gives PRR 34.78 on 222 cases** — a single month reproducing the all-time ratio within ~3%, so the
signal is not carried by one reporting spike.

**A defect the data caught.** The first ranked row was `Neutrophil count normal` (318 cases) with a
**blank** PRR and ROR. Cause: that PT is reported *only* with clozapine, so `c = 0` and the ratio is
**undefined**, which the macros correctly return as NULL rather than fabricating infinity — but
Snowflake sorts NULLs **first** under `ORDER BY … DESC`, putting undefined pairs at the top of a
magnitude ranking. Fixed with `nulls last`, and the blank is now explained in the UI.
*Same shape as the `aws s3 sync` incident: the computation was right and the layer presenting it was
wrong.* With that fixed the clozapine head is `Differential white blood cell count abnormal`
(PRR 1,260 on 212 cases) — and the top-20 artifact analysis above is exactly why the page ranks with
support shown for triage instead of flagging a binary answer.

Run it: `runbook.md` → "Serve the dashboard (Streamlit)".

## Streamlit in Snowflake ✅ (2026-08-16) — the dashboard is now a URL

`app/dashboard_snowflake.py`, deployed as **`DE_CAPSTONE.DBT_DEV."Drug Safety Signals"`** and running
with the rights of **`DE_CAPSTONE_DBT_ROLE`** on `DE_CAPSTONE_WH`. **The demo no longer needs the
laptop** — no Docker, no venv, no terminal, nothing to fail live.

**Three dashboards, all working:** `dashboard.py` (8501, rollback) · `dashboard_enhanced.py` (8502,
local demo) · `dashboard_snowflake.py` (hosted). The two local files were not modified.

- **Runtime:** Streamlit **1.52.2**, Plotly **6.7.0** (declared in the app's `environment.yml`).
  Created through **"Create on warehouse (legacy)"** — the newer Workspaces/container path needs
  `pyproject.toml` + `uv` + an artifact repository or External Access Integration, which is a dead
  end for a short job.
- **One privilege granted, the only account change:**
  `grant create streamlit on schema DE_CAPSTONE.DBT_DEV to role DE_CAPSTONE_DBT_ROLE`.
  `CREATE STREAMLIT` is a distinct schema privilege and is not implied by owning the schema — until
  it was granted, `DE_CAPSTONE` did not appear in the database picker.
- **Least privilege held:** the app runs as the same read-only role dbt uses, not `ACCOUNTADMIN`.
- **Five code differences** from the local version: `get_active_session()` instead of key-pair auth
  (**no credentials in the file**), `session.sql(...).to_pandas()` instead of a cursor, `?` instead
  of `%s` for the 18 bind parameters, lowercased column names, and a light Plotly template. Every
  chart, tab, filter and SQL string is otherwise identical.
- **Two rendering fixes:** `render_mode="svg"` on the volcano, because `px.scatter` switches to
  **WebGL above ~1,000 points** and WebGL is unavailable inside the Snowsight iframe; and more top
  margin in `style()`, because the horizontal legend was colliding with the chart title.

**Verified:** `dim_drug` **4,368 / 4,368** · Silver rows **45,030,932** · scored pairs **1,240,645** ·
candidate signals **315,270** · `CLOZAPINE` + `Neutropenia` **24 months / 5,571 cases**. Same numbers
as the local app.

**The local apps remain the fallback** — the same pattern as `load_to_snowflake.py` behind the S3
cutover and `dashboard.py` behind the Plotly rebuild. Full write-up:
`docs/Layer Explanation/Streamlit.md` Part K.

## CI/CD — GitHub Actions ✅ phases 1–5 · phase 6 built (2026-08-17)

Four workflows, a Snowflake CI identity that **cannot reach production**, an AWS OIDC role that
**cannot write to S3**, and a Terraform role that **cannot modify itself**. No AWS access key and no
Snowflake password exists anywhere in the project. Full write-up: `docs/Layer Explanation/CI_CD.md`.

### `.github/workflows/ci.yml` — the static gate (no secrets)

| Job | Catches |
|---|---|
| `ruff` | undefined names and real errors. Blocks on `E9,F63,F7,F82`; the full rule set runs with `--exit-zero` so style informs but never blocks |
| `python syntax` (3.11 + 3.12 matrix) | a broken `pv_pipeline.py` — via `ast.parse`, so the DAG is validated **without installing Airflow** |
| `secret scan` | private-key blocks, `AKIA…` ids, and assigned secret values. Reports **file and line only**, never the text |
| `dbt parse` | broken SQL or Jinja in all 10 models — with **no warehouse connection** |
| `pytest` | drift in normalisation (TR-37) or the metric formulas (TR-38) — **21 tests**, pure Python, no warehouse |

**The secret scan was demonstrated refusing a credential:** a deliberate `SNOWFLAKE_PASSWORD = "…"`
committed to a branch turned the check **red in 7 seconds**, naming `file:line` and printing nothing.
Removing it turned it green. *A gate you have watched stop something is evidence; a green tick is
decoration.*

This converts the project's strongest security claim — *"no Snowflake password anywhere"*, previously
proven by one hand-run `grep` — into a test that runs on every change.

### `.github/workflows/dbt-ci.yml` — the warehouse gate

`dbt build --target ci` → **PASS=53 WARN=0 ERROR=0 in 1 m 17 s**, the same result production produces,
reproduced by a different identity in a different schema from a clean machine.

**A separate Snowflake identity, not a second key on `DE_CAPSTONE_SVC`:**

| | `DE_CAPSTONE_CI` |
|---|---|
| Auth | own key pair in `D:/capstone/.keys-ci/`, `TYPE = SERVICE` |
| Grants | **8 total** — `USAGE` on warehouse/database/`RAW`, `SELECT` on the two RAW tables, `USAGE`+`CREATE TABLE`+`CREATE VIEW` on `DBT_CI` |
| On `DBT_DEV` | **nothing** |
| On RAW | **read only** — no `INSERT`, no `TRUNCATE` |

`DE_CAPSTONE_SVC` owns `DBT_DEV` and can truncate RAW, so reusing it would have made isolation a
*configuration* guarantee — one `schema:` line. With a separate role it is a **privilege** guarantee:
a profile typo returns a permission error instead of overwriting the marts.

**Proven, not asserted:** acting as `DE_CAPSTONE_CI_ROLE`, `SELECT` on `RAW.SILVER_DRUG_EVENT`
succeeded (45,030,932) and `SELECT` on `DBT_DEV.DIM_DRUG` **failed with "not authorized"**.

Revocation is independent: `DROP USER DE_CAPSTONE_CI` removes CI entirely and leaves Airflow, both
loaders and the Streamlit app working.

### Pull-request workflow

Two PRs, both merged after green checks. A branch ruleset `protect main` requires all six checks —
**configured but not enforced**, because GitHub does not apply rulesets to private repositories
without a Team plan. It would activate unchanged if the repo became public or moved to an org.

> *The workflow **detects**; branch protection **enforces**. Detection works today and was
> demonstrated; enforcement is a plan constraint, not a design gap.*

### Recurring lesson: privileges are not implied by ownership

Three separate times — `CREATE STREAMLIT` not implied by owning `DBT_DEV`; `ACCOUNTADMIN` unable to
read `DBT_CI` because **owning a role is not being a member of it**; `CREATE TABLE` needing its own
grant. Snowflake separates ownership, membership and privilege.

### Phase 4 — a capstone-owned AWS OIDC role ✅

`arn:aws:iam::617371012792:role/de-capstone-github-actions` — trusted **only** by this repository,
allowed **only** `s3:ListBucket` + `s3:GetObject` on `silver/drug_event/`. No write, no delete, no
other prefix. The account's existing OIDC provider was **reused, not duplicated** (one per account);
the broad bootcamp roles were not reused; `de-capstone-airflow-uploader` and the Snowflake
storage-integration role were not touched. **There is no AWS access key in the repo or its secrets** —
every credential is minted per job by OIDC and expires with it.

**A permissions boundary** (`de-capstone-github-actions-boundary`) caps the role at read-only on that
prefix whatever its own policy says — attached, then the contract workflow was re-run to prove the cap
does not break it.

**The trap this phase turned on.** The first trust policy used the documented
`repo:owner/repo:*` subject and would have matched **nothing**: GitHub's *immutable subject claims*
(enforced for all repositories created after 15 July 2026 — this one dates from 2026-08-02) embed
numeric ids, so the real subject is
`repo:nkouhdareh@263947291/de-capstone-pipeline@1320110552:…`. IAM validates syntax, not
reachability. The workflow therefore **decodes the token and prints the subject before assuming**, so
a failure names the exact string to fix. Proven:
`arn:aws:sts::617371012792:assumed-role/de-capstone-github-actions/GitHubActions`.

### Phase 5 — the S3 contract check ✅

`.github/workflows/s3-contract.yml` verifies the protected fallback prefix still holds **exactly 486
objects / 3,913,635,942 bytes**, on every PR, every push to `main`, and on demand. Read-only by
construction: the role has no `PutObject` or `DeleteObject`, so **the check cannot alter what it
verifies**. What was a hand-run `aws s3 ls` before and after the destructive 15 August run is now
automatic.

**Demonstrated refusing a wrong number.** `silver/drug_event/` (486 / 3,913,635,942) and
`silver_pipeline/` (486 / 3,913,633,244) have **identical object counts and differ by 2,698 bytes**.
Temporarily expecting the pipeline's total turned the check **red** — while the object count matched.
That single failure justifies asserting both numbers, and it is why the check would catch the
fallback artifact being silently replaced by the pipeline's own output.

### Phase 6 — Terraform for the CI role only ✅

`terraform/` manages **exactly two objects**: the phase-4 role and its inline policy. Not the data
bucket, not production IAM, not the Snowflake storage integration, not dbt or Airflow.

- **Imported, never created.** Declarative `import` blocks so the takeover appears in the plan on the
  PR; `prevent_destroy = true` on both resources; `iam:CreateRole`/`iam:DeleteRole` explicitly denied
  to the executor. Acceptance is `Plan: 2 to import, 0 to add, 0 to change, 0 to destroy`.
- **`de-capstone-terraform`**, OIDC — not the undocumented bootcamp user `terraform-demo`, and not an
  IAM user at all. Trust pinned with `StringEquals` to the two subjects phase 5 *measured*. Its policy
  scopes eleven IAM actions to one role ARN and denies everything else; **every `*` in it sits inside
  a `Deny`.** Policy-simulator verified: it can update that role, **cannot delete it, cannot attach a
  managed policy to it, and cannot write policy onto itself**.
- **State** in a dedicated private, versioned, SSE-S3 bucket in `eu-central-1` with
  `use_lockfile = true` (no DynamoDB), bootstrapped by hand — a backend must exist before
  `terraform init`.
- **`apply` is manual** (`workflow_dispatch`), not on merge: the first apply is one to watch.

**Verified (PR #35):** plan `2 to import, 0 to add, 0 to change, 0 to destroy` → apply
**`2 imported, 0 added, 0 changed, 0 destroyed`** → **second plan `No changes. Your infrastructure
matches the configuration.`** → S3 contract re-run **486 / 3,913,635,942 green**. The empty second
plan is the one that matters: it proves the import recorded reality faithfully, not merely
successfully. Terraform now owns the role **without having changed a byte of it**.

**One failure worth keeping.** The first plan died on
`AccessDenied: iam:ListOpenIDConnectProviders` — a data source looking the provider up *by URL* needs
that action, and AWS does not support resource-level permissions for it, so granting it would have
meant `"Resource": "*"` in an Allow. The fix was to remove the dependency (reference the ARN as a
literal), not to widen the policy. *The least-privilege policy caught an over-broad dependency in my
own code.*

**Still to do (optional):** delete `imports.tf` now the import has run; tighten the CI role's trust
policy from `StringLike "…:*"` to the two exact subjects **through Terraform**, as a reviewed plan
diff; drop the now-unused `iam:GetOpenIDConnectProvider`. **Branch-protection enforcement remains
blocked by GitHub's private-repo plan limit** — detection works and was demonstrated.

## Presentation and handover assets ✅ (2026-08-19)

Built for the presentation on **24 August 2026**. None of this touches the pipeline — no model,
macro, table or figure was changed to produce any of it.

| Asset | Path | What it is |
|---|---|---|
| Slide deck | `docs/capstone_presentation.pptx` | 17 slides, 16:9, dark mode. Every figure taken from this document |
| Architecture diagram | `docs/assets/architecture.png` | 1920×1080, dark. Six stages left→right, Airflow above, CI/CD below; solid arrows = data, dashed = control |
| Dashboard captures | `docs/assets/dashboard_0_kpis.png`<br>`dashboard_1_signals.png`<br>`dashboard_2_table.png`<br>`dashboard_3_trend.png` | Real screenshots from the **hosted** Streamlit app, not mock-ups. How to reproduce them: `runbook.md` → "Presentation assets" |
| Title image | `docs/assets/FDA.png` | 750×563, transparent |
| Cost analysis | `docs/Layer Explanation/costs.md` | What the project cost and how it scales (local-only, not committed) |
| Coach report | `…/capstone_meetings/fourth meeting_Mi_19082026/4th Coach Meeting.md` | What was built since the previous meeting (local only) |

**The one number this section adds:** the whole build cost about **$0.25** of real money plus
**$42** of Snowflake trial credit. dbt, Airflow, Spark, Docker, Terraform and GitHub Actions are
$0, because everything that can run locally does — only ~8 GB of the 64 GB Bronze is in the cloud.
Full breakdown and the 10× scaling table: `costs.md`.

**Two figures worth having at hand for questions**, both visible in the captured screenshots:
`CLOZAPINE → Death` is **1,848 cases at PRR 1.92 and is *not* flagged**, and `Off label use` is
1,294 cases at PRR 0.77, also not flagged. That is the evidence the method discriminates rather
than ranking by volume.

## NEXT — Streamlit (the only remaining MVP item)

> ✅ **Completed 2026-08-13 (local) and 2026-08-16 (hosted in Snowflake).** This section is kept as
> the original specification and acceptance criteria; see "Streamlit dashboard" and "Streamlit in
> Snowflake" above for what was actually delivered.

Everything upstream is built, run at full scale, and verified end-to-end under orchestration. The
dashboard reads tables that **already exist**; nothing new has to be computed.

**What it reads** (schema `DE_CAPSTONE.DBT_DEV`):

| Model | Grain | Rows | Use |
|---|---|---|---|
| `SEM_SIGNAL_METRICS` (view) | drug × reaction, **all-time** | 1,240,645 pairs | The main ranked table |
| `FCT_SIGNAL_METRICS` (table) | drug × reaction × **month** | 5,069,399 | "Strongest this period" / trend over time |
| `DIM_DRUG` / `DIM_REACTION` | one row each | 4,368 / 18,057 | Filter dropdowns |

Columns on the signal models: `drug_key`, `drug_name`, `reaction_key`, `reaction_pt`, `a`, `b`, `c`, `d`,
`prr`, `ror`, `ror_ci_lower`, `chi2_yates`, `is_signal`, `is_signal_strict`. **`a` is the case count.**

**The design point to build around:** ranking by raw PRR puts artifacts on top (confounding by
indication, device product-use events — see the top-20 analysis above), and a stricter statistical
threshold does **not** fix it (`is_signal_strict` prunes only 269 of 315,270). So the dashboard should
present a **ranked candidate list with support shown** — filter by minimum case count, sort by magnitude,
show `a` and χ² next to every PRR — for an expert to triage. Not a binary flag.

**Connection:** key-pair as `DE_CAPSTONE_SVC` (see the Snowflake section above) — `SNOWFLAKE_ACCOUNT`,
`SNOWFLAKE_USER`, `SNOWFLAKE_PRIVATE_KEY_PATH` from the repo `.env`. **No password exists.**

**Acceptance:** an analyst can filter by drug / reaction / period and see ranked signals, and the app
reproduces **clozapine → neutropenia, PRR 35.9, 5,571 cases**. Port **8501** (8080 is Airflow, 8081 dbt docs).
- *Small:* add a second MFA method to `NKOUH` (only user, only `ACCOUNTADMIN` — a lost phone means
  Snowflake support).
- *Optional:* trim `build_silver`'s log volume (it forwards every Spark INFO line — invaluable for a
  10-minute job, unwieldy for a 5-hour one); a scheduled rather than manual trigger (`dim_date` already
  auto-extends for this); CI.
- ✅ **pytest TR-37 / TR-38 — done (issue #24 closed).** The Python tests moved out of the git-ignored
  `dbt_reference/tests/` into **`tests/`** and now run as a sixth `ci.yml` check: **21 passed**, no
  warehouse and no credentials. TR-38's fixture is `de_capstone/seeds/signal_worked_example.csv` — the
  **same seed the dbt test asserts on in Snowflake**, so the Python formulas, the seed and the macro
  must all agree. **pytest rather than a dbt test on purpose:** a new dbt test would have moved
  `42/42` and `PASS=53`, both frozen figures. *(TR-37 tests a Python mirror of the macro: it proves the
  logic, not the SQL implementation.)*

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
