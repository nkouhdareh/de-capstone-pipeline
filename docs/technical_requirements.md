# Technical Requirements Document

## Drug Safety Signal Detection — openFDA pharmacovigilance platform

| | |
|---|---|
| **Author** | Nastaran Kouhdareh |
| **Version** | **1.0 — final, reconciled against what was built** |
| **Originally drafted** | 3 August 2026 (v0.1, Gate 2) |
| **This revision** | 19 August 2026 |
| **Depends on** | `business_requirements.md` v1.0 (Gate 1) |

> **What changed from v0.1.** Every TR keeps its original number — they are the grading
> spine and are referenced from `architecture.md`, the ADRs and the commit history. What
> is new is a **status against each requirement**, corrections where the spec named a tool
> or version that was not used, actual figures in place of estimates, and a reconciliation
> summary in §16 listing every deviation in one place.
>
> Legend: ✅ met · ⚠️ met with deviation · ❌ not met · ➖ not applicable

---

## 1. Technology selections — as built

| Layer | Selection | Justification | Status |
|---|---|---|---|
| Ingestion | Python 3.11 + `requests` | Three REST endpoints and one auth scheme; a framework would add a dependency without removing work | ✅ |
| Raw storage (Bronze) | **Local disk, NDJSON** | 64 GB with a single local consumer. Only the ~8 GB the warehouse needs is uploaded | ⚠️ **Changed from S3** — [ADR-009](adr/ADR-009-hybrid-deployment-bronze-local.md) |
| Semi-structured flattening | **PySpark in Docker** | Nested arrays with severe fan-out — up to 4,113 drugs on one report | ✅ *(absent from v0.1's table; it was specified only in ADR-004)* |
| Object storage | AWS S3, `eu-central-1`, private, SSE-S3 | Silver as an inspectable, independent artifact; region verified against Snowflake's | ✅ |
| Warehouse | Snowflake, `DE_CAPSTONE_WH` (XS, `AUTO_SUSPEND = 60`) | Cloud DWH skill; external stage reads S3 with no stored keys | ✅ — **cost $42 of a $400 trial**, not the ~$2 estimated in v0.1 |
| Transformation | dbt Core, `dbt-snowflake` **1.12.0** | SQL-shaped work; native testing, lineage and docs | ✅ |
| Orchestration | **Apache Airflow 2.10.5** in Docker | Pinned deliberately: `stable` now serves Airflow 3.x, whose operator import paths moved | ⚠️ **v0.1 specified "Airflow 3"** — corrected here |
| Containerisation | Docker Compose — **3 stacks, 8 containers** | Airflow triggers Spark and dbt over the Docker socket rather than hosting them | ✅ — [ADR-010](adr/ADR-010-airflow-triggers-containers.md) |
| CI | GitHub Actions — **4 workflows, 8 checks** | Converts documented claims into tests that run on every change | ✅ |
| IaC | Terraform, **scoped to the CI IAM role only** | Marked "optional, first item to cut" in v0.1; delivered, deliberately narrow | ✅ — [ADR-014](adr/ADR-014-terraform-ci-role-only.md) |
| Data quality | dbt tests + `pytest` | dbt for data assertions, pytest for logic | ✅ — 42 dbt tests, 21 pytest |
| Dashboard | Streamlit — local ×2 plus **hosted inside Snowflake** | The hosted version makes the demo a URL with no laptop dependency | ✅ — exceeded v0.1 |
| Vector store | Postgres + `pgvector` | — | ❌ **Not built** — [ADR-015](adr/ADR-015-retrieval-extension-not-built.md) |
| Embeddings | `sentence-transformers` / `all-MiniLM-L6-v2` | — | ❌ **Not built** |
| Generation | Ollama / `llama3.1:8b` | — | ❌ **Not built** |

**Rejected, and still rejected:** Kafka (no real-time source — [ADR-007](adr/ADR-007-no-streaming-layer.md)),
Elasticsearch/Qdrant (extension never built), Databricks/Fabric (no credits),
DuckDB and Postgres as the warehouse ([ADR-002](adr/ADR-002-warehouse-snowflake.md)),
Data Vault layering ([ADR-003](adr/ADR-003-medallion-layering.md)),
fuzzy drug matching ([ADR-005](adr/ADR-005-drug-name-resolution-tiers.md)).

---

## 2. Source system specification

| Endpoint | Purpose | Available | **Ingested** | Key field |
|---|---|---|---|---|
| `/drug/event.json` | FAERS reports | 20M+ | **2,687,675** (2023-01-01 → 2024-12-31) | `safetyreportid` + `safetyreportversion` |
| `/drug/label.json` | Product labels | ~150k | **261,258** — ingested, not used downstream | `id`, `openfda.spl_id` |
| `/drug/ndc.json` | Product directory | ~130k | **136,520** | `product_ndc` |

### Access constraints

| ID | Requirement | Status | As built |
|---|---|---|---|
| TR-01 | An API key shall be supplied via the `api_key` parameter, raising limits to 240 req/min and 120,000 req/day | ✅ | `OPENFDA_API_KEY` from a git-ignored `.env` |
| TR-02 | Pagination shall use `limit` with `skip`, respecting the 26,000-record `skip` ceiling by partitioning on `receivedate` windows | ⚠️ | Day-partitioned, 1,000 records/request. **`MAX_SKIP` is set to 25,000, not 26,000** — deliberately conservative, recorded here rather than left as an undocumented difference |
| TR-03 | Historical backfill shall use the quarterly bulk JSON files from `download.json`, not the paged API | ⚠️ | **Label and NDC ✅** use the bulk index. **FAERS ❌** uses the paged API day by day, and `backfill_days.py` re-fetches individual days the same way. Day-partitioning made the paged route workable, so bulk was never needed |
| TR-04 | Requests shall retry on 429/5xx with exponential backoff (base 2 s, max 5 attempts) and fail the task after exhaustion | ⚠️ | Backoff implemented as `2**attempt` capped at 30 s over **6** attempts. Failure **raises** rather than ending the day early — an earlier version silently produced short days, which is now a runbook entry |

> **Note on TR-02.** The `skip` ceiling remains the single most important constraint on
> ingestion. Because every query is date-partitioned, extraction is idempotent, resumable
> and backfillable for free — properties a streaming design would have had to rebuild.

---

## 3. Storage layer specification

### 3.1 Bronze

| ID | Requirement | Status | As built |
|---|---|---|---|
| TR-05 | Raw responses shall be written unmodified as **gzipped** newline-delimited JSON | ⚠️ | NDJSON ✅, **uncompressed ❌**. 64 GB on local disk. Compression was never implemented; the cost is disk, not correctness |
| TR-06 | Objects shall be laid out as `s3://<bucket>/bronze/endpoint=<name>/ingest_date=<YYYY-MM-DD>/part-<n>.json.gz` | ⚠️ | **Local, not S3**: `$DATA_DIR/bronze/drug_event/receivedate=YYYYMMDD/part-<n>.json`. Partitioned by *receive* date rather than *ingest* date, which is the more useful key for backfill. Decision recorded in [ADR-009](adr/ADR-009-hybrid-deployment-bronze-local.md) |
| TR-07 | Each file shall be accompanied by a manifest recording endpoint, query window, record count, retrieval timestamp and pipeline run id | ❌ | **Not implemented.** Counts are printed at ingestion time but not persisted per file. A genuine gap, not a decision |
| TR-08 | Bronze objects shall never be modified or deleted by the pipeline | ✅ | The Airflow ingest tasks check for presence and skip in ~1 second rather than re-downloading |

### 3.2 Warehouse

| ID | Requirement | Status | As built |
|---|---|---|---|
| TR-09 | Bronze shall be exposed to Snowflake via an external stage with storage integration | ⚠️ | **Delivered, but over Silver rather than Bronze.** `RAW.SILVER_PIPELINE_S3_STAGE` and `RAW.NDC_S3_STAGE` read S3 through a storage integration — no keys stored in Snowflake. Cut over from internal stages on 12 August; internal stages retained as the rollback path — [ADR-011](adr/ADR-011-s3-external-stages.md) |
| TR-10 | Schemas shall be `RAW`, `STAGING`, `INTERMEDIATE`, `MARTS` | ⚠️ | **`RAW` + `DBT_DEV` + `DBT_CI`.** All dbt models build into one schema; separation is by dbt layer folder and model prefix (`stg_`, `int_`, `dim_`/`fct_`, `sem_`). Four schemas would have added grant management without adding isolation, since one identity owns them all |
| TR-11 | All models shall be built by dbt; no manual DDL outside version control | ⚠️ | dbt models ✅. `scripts/ddl_raw.sql` creates the RAW objects and **is** in version control ✅. **Snowflake users, roles, grants and the storage integration were created by hand** in worksheets and are documented but not codified |
| TR-12 | The fact table shall be clustered on `receive_date` | ✅ | `{{ config(materialized='table', cluster_by=['receive_date']) }}` |

---

## 4. Transformation specification

### 4.1 dbt layer contract — as built

| Layer | Prefix | Materialisation | Models |
|---|---|---|---|
| Staging | `stg_` | view | `stg_drug_event`, `stg_drug_ndc` |
| Intermediate | `int_` | **table** | `int_drug_resolution` *(v0.1 said ephemeral/view; materialised as a table because it is read by four downstream models)* |
| Marts | `dim_`, `fct_` | table | `dim_drug`, `dim_reaction`, `dim_reporter`, `dim_date`, `fct_report_drug_reaction`, `fct_signal_metrics` |
| Semantic | `sem_` | view | `sem_signal_metrics` |

**10 models. `dbt build` → PASS=53, WARN=0, ERROR=0** (10 models + 1 seed + 42 tests).

### 4.2 Deduplication

| ID | Requirement | Status | As built |
|---|---|---|---|
| TR-13 | A unique case shall be the row with the highest `safetyreportversion` for a given `safetyreportid` | ✅ | Window function in the Silver job, applied before flattening |
| TR-14 | The count of rows removed as duplicates shall be persisted per run and exposed as a metric | ⚠️ | **Persisted ✅** to `silver/_silver_metrics` (Parquet, per month, per run, with `_run_id`). **Exposed as a live metric ❌** — the dashboard shows it as a documented figure, not a queried one, because the metrics Parquet was never loaded into the warehouse |
| TR-15 | Rows failing schema validation shall be routed to a `_quarantine` table with a failure reason, not dropped | ⚠️ | **Quarantined with a reason ✅** — 431,760 rows across three reasons. Written to a **Parquet dataset rather than a Snowflake table**, so it is inspectable locally but not queryable in the warehouse |

**Result:** 93,366,638 atomic rows → **45,030,932** Silver rows; 48,335,706 removed (51.8 %).
Grain key unique across all 45,030,932. Zero null reactions remain.

### 4.3 Drug name resolution

| ID | Requirement | Tier | Status | As built |
|---|---|---|---|---|
| TR-16 | Names shall be normalised by uppercasing, stripping punctuation, dosage strings and salt forms | 1 | ✅ | `macros/normalize_drug_name.sql`. **Known defect:** stripping mineral salts collapses `sodium chloride` and `calcium chloride` to `CHLORIDE` — measured, documented, not fixed during the freeze |
| TR-17 | Normalised names shall be matched exactly against `brand_name` and `generic_name` in the NDC directory | 1 | ✅ | Tiers 2 and 3 of four |
| TR-18 | Unmatched names shall be matched against `openfda.substance_name` and `openfda.rxcui` where present | 2 | ✅ | `rxcui` is tier 1 (most reliable); active ingredient is tier 4 |
| TR-19 | Names still unresolved shall be retained with `drug_key = -1` and counted; the resolution rate shall be published | 1 | ✅ | **86.7 % of rows** · **10.0 % of 84,039 distinct signatures**. Both published, because they answer different questions |

Full order: `rxcui` → normalised generic → brand → active ingredient → unresolved.
**Ambiguous matches are rejected, never guessed.** Fuzzy matching remains explicitly out of
scope — [ADR-005](adr/ADR-005-drug-name-resolution-tiers.md).

---

## 5. Dimensional model specification

### 5.1 Grain declarations — estimated vs actual

| Model | Grain | Estimated (v0.1) | **Actual** |
|---|---|---|---|
| `fct_report_drug_reaction` | case × drug × characterisation × reaction | ~10–50M | **45,030,932** |
| `fct_signal_metrics` | drug × reaction × **month** | ~1–5M | **5,069,399** |
| `sem_signal_metrics` | drug × reaction, **all time** | *(not in v0.1)* | **1,240,645** |
| `dim_drug` | one resolved product identity | ~50k | **4,368** |
| `dim_reaction` | one MedDRA preferred term | ~25k | **18,057** |
| `dim_reporter` | one (qualification, country) | ~1k | **726** |
| `dim_date` | one calendar day | ~10k | **731** |
| `int_drug_resolution` | one distinct drug signature | *(not in v0.1)* | **84,039** |

The dimension estimates were an order of magnitude high because they assumed the full
FAERS history rather than a two-year window. The fact table landed inside its range.

> **Correction to v0.1 §5.1.** The original grain declaration for
> `fct_report_drug_reaction` read "one row per (safety case, drug, reaction)". The
> implemented grain includes **drug characterisation**, because the same drug can appear on
> one report as both suspect and concomitant. This is the grain everything else depends on.

### 5.2 Column specification — `fct_report_drug_reaction`

| Column | Type | Note |
|---|---|---|
| `report_drug_reaction_key` | varchar | SHA-256 surrogate of the grain; tested unique |
| `safety_report_id` | varchar | Degenerate dimension |
| `drug_key` | number | FK → `dim_drug`; `-1` = Unknown |
| `reaction_key` | number | FK → `dim_reaction` |
| `reporter_key` | number | FK → `dim_reporter` |
| `receive_date_key` | number | FK → `dim_date` |
| `receive_date` | date | **Cluster key** |
| `drug_characterisation` | varchar | `SUSPECT` / `CONCOMITANT` / `INTERACTING` — BR-07 |
| `is_serious` | boolean | |
| `outcome_death`, `outcome_hospitalisation`, `outcome_life_threatening`, `outcome_disability`, `outcome_congenital_anomaly`, `outcome_other` | boolean | BR-12 |
| `patient_age_band`, `patient_sex` | varchar | Banded, never exact |
| `report_version` | number | Retained for audit |
| `_loaded_at`, `_run_id` | timestamp, varchar | Lineage |

### 5.3 Metric definitions

Computed on the 2×2 contingency table for drug *D* and reaction *E*, using **suspect drugs
only** and **unique cases only**:

|  | Reaction E | Not E |
|---|---|---|
| Drug D | `a` | `b` |
| Not D | `c` | `d` |

| ID | Requirement | Status | Definition |
|---|---|---|---|
| TR-20 | PRR | ✅ | `(a / (a + b)) / (c / (c + d))` |
| TR-21 | ROR | ✅ | `(a * d) / (b * c)` |
| TR-22 | 95 % CI lower bound of ROR | ✅ | `exp( ln(ROR) − 1.96 * sqrt(1/a + 1/b + 1/c + 1/d) )` |
| TR-23 | Signal flag | ✅ | `a >= 3 AND PRR >= 2 AND chi2_yates >= 4` |
| TR-24 | Formulas shall appear in exactly one dbt model; no consumer shall recompute them | ⚠️ | Formulas live in **one macro** (`macros/signal_metrics.sql`) called by **two** models. The intent — a single definition — holds end to end and was verified across warehouse, local app and hosted app. `tests/test_signal_metrics.py` re-implements them in Python **deliberately**, as a cross-check against the same seed the dbt test asserts on |
| TR-25 | Thresholds shall be dbt variables, not literals, and documented with their source | ✅ | `dbt_project.yml`: `signal_min_cases: 3`, `signal_min_prr: 2.0`, `signal_min_chi2: 4.0`, `signal_ror_ci_min: 1.0` |

where `chi2_yates = N * (|a*d − b*c| − N/2)^2 / ((a+b)(c+d)(a+c)(b+d))`, `N = a+b+c+d`.

**Two scoping rules applied in the metric models but absent from v0.1**, recorded here:
only `drug_characterisation = 'SUSPECT'` rows are counted, and `drug_key = -1` (Unknown) is
excluded. A concomitant drug is not the suspected cause, and an unidentified drug cannot be
scored.

**Beyond spec:** `is_signal_strict` adds `ror_ci_lower > 1.0` to `is_signal`. It prunes
0.09 % of all-time pairs — **269 of 315,270** — which is itself the evidence that a
stricter statistical threshold does not remove the artifacts at the top of the ranking.

**Acceptance signal:** clozapine → neutropenia, **PRR 35.94 · ROR 46.76 · ROR-CI 45.21 ·
χ² 142,896 · 5,571 cases**, present in all 24 months, with monthly counts summing back to
5,571.

---

## 6. Orchestration specification

| ID | Requirement | Status | As built |
|---|---|---|---|
| TR-26 | Three DAGs shall exist: `pv_daily_pipeline`, `pv_backfill`, `pv_index_labels` | ⚠️ | **One DAG, `pv_pipeline`**, parameterised by `--months`. Backfill is the same code with different parameters, so a second DAG would duplicate it; `pv_index_labels` belonged to the dropped extension |
| TR-27 | `pv_daily_pipeline` shall run at 04:00 UTC with `catchup=False` and `max_active_runs=1` | ⚠️ | `catchup=False` ✅ · `max_active_runs=1` ✅ · **`schedule=None` ❌** — manual trigger. The dataset is a frozen 2023–2024 snapshot, so a nightly run would reprocess unchanged data. `dim_date` derives itself from the data, so enabling a schedule needs no code change |
| TR-28 | Task order: `ingest_ndc → ingest_faers → load_to_snowflake → dbt_run → dbt_test → publish_metrics` | ✅ | **Expanded to eight**, adding the two steps the original order omitted: `ingest_ndc → ingest_faers → build_silver → upload_s3 → load_raw → dbt_build → dbt_test → publish_metrics` |
| TR-29 | Every task shall be idempotent | ✅ | Verified. `upload_s3` was **not** idempotent until fixed — `aws s3 sync` without `--delete` accumulated files, and an unfixed load would have inserted 46,580,195 rows. *Idempotency is a property of the whole chain* |
| TR-30 | Ingestion shall checkpoint the last successfully processed date window | ❌ | **Not implemented.** The guard is coarser — "Bronze present → skip". Manual resume is documented in the runbook: delete the last partial day, set `START`, re-run |
| TR-31 | `dbt_test` failure shall fail the DAG run and leave marts at their previous state | ✅ | Marts are materialised tables, so they keep serving throughout a failed rebuild |
| TR-32 | Task-level retries: 3 attempts, exponential backoff, 30-minute execution timeout | ⚠️ | **2 retries, fixed 3-minute delay.** Timeouts are per task rather than uniform: 12 h for `build_silver`, 2 h for `dbt_build`, 1 h for `load_raw`/`dbt_test`, 30 min for `publish_metrics`. `build_silver` has `retries=0` — a 4-hour job should not silently restart |

**Full-scale run, 15 August 2026:** `{"months":"all"}` → **success in 3 h 57 m 23 s**, all
8 tasks green **in dependency order**, each starting 1–2 seconds after its predecessor.

| Task | Duration | Result |
|---|---|---|
| `ingest_ndc`, `ingest_faers` | < 1 s each | Skipped — Bronze present |
| `build_silver` | 3 h 47 m 27 s | 24 months · 45,030,932 rows |
| `upload_s3` | 5 m 28 s | 486 objects mirrored with `--delete` |
| `load_raw` | 2 m 43 s | `SILVER_DRUG_EVENT` 45,030,932 · `DRUG_NDC` 136,520 |
| `dbt_build` | 1 m 08 s | PASS=53, WARN=0, ERROR=0 |
| `dbt_test` | 9.7 s | PASS=42 |
| `publish_metrics` | 15.7 s | `fct` 45,030,932 · `dim_drug` 4,368 · `dim_reaction` 18,057 |

---

## 7. Data quality specification

| ID | Requirement | Implementation | Status |
|---|---|---|---|
| TR-33 | Primary keys tested for uniqueness and non-nullity on every mart model | dbt `unique`, `not_null` | ✅ |
| TR-34 | Every foreign key tested for referential integrity | dbt `relationships` | ✅ — all four dimensions FK-tested from the fact |
| TR-35 | `drug_characterisation` and `patient_sex` tested against enumerated values | dbt `accepted_values` | ✅ |
| TR-36 | Row counts tested for plausible range per run, to detect silent source failure | `tests/assert_fct_rowcount_plausible.sql` | ✅ |
| TR-37 | The drug-name normalisation function shall have unit tests covering at least 10 real-world name variants | `tests/test_drug_normalisation.py` | ✅ — *tests a Python mirror of the SQL macro, so it validates the logic, not the SQL implementation. Stated rather than glossed* |
| TR-38 | PRR and ROR shall have a unit test against a hand-computed worked example | `tests/assert_signal_worked_example.sql` + `tests/test_signal_metrics.py` | ✅ — **both read the same seed** (`seeds/signal_worked_example.csv`), so the Python formulas, the committed fixture and the dbt macro must all agree |
| TR-39 | Schema drift in source payloads shall be detected and logged rather than causing task failure | JSON schema check in ingestion | ❌ **Not implemented** |

**Totals: 42 dbt tests, 21 pytest tests.** TR-38 remains the highest-value test in the
project — a hand-verified worked example for a statistical metric is what distinguishes a
tested pipeline from an asserted one.

> **Why pytest rather than a new dbt test for TR-37/38:** adding a dbt test would have moved
> the documented `42/42` and `PASS=53` figures during the pre-submission freeze.

---

## 8. Observability specification

| ID | Requirement | Status | As built |
|---|---|---|---|
| TR-40 | All pipeline logs shall be structured JSON with keys `run_id`, `dag_id`, `task_id`, `event`, `rows_in`, `rows_out`, `rows_rejected`, `duration_s` | ❌ | **Not implemented.** Airflow task logs are plain text. The child container's stdout is streamed into the task log, which preserves the information but not the structure |
| TR-41 | A `pipeline_run_log` table shall persist one row per run with status, timings, row counts and duplicates removed | ⚠️ | **No such table.** The auditable record exists in two other places: `publish_metrics` (a dbt macro run as the final task) logs the headline figures on every run, and `silver/_silver_metrics` persists per-month atomic/silver/duplicate/quarantine counts with `_run_id` and timestamp. The *intent* — every run leaves a record of what it produced — is met; the specified form is not |
| TR-42 | Estimated cost per run shall be computed and recorded in `pipeline_run_log` | ❌ | **Not implemented per run.** Cost was analysed once for the project as a whole: $0.25 paid, $42 of trial credit, with a 10× scaling table |
| TR-43 | A data quality summary (resolution rate, duplicate rate, rejection rate) shall be published to the dashboard | ✅ | "Data Quality & Methodology" tab. Warehouse-derived figures are labelled separately from documented Silver figures, so the user knows which is live |
| TR-44 | `dbt docs generate` output including the lineage graph shall be produced on every CI run | ❌ | **Not in CI.** Available manually on port 8081; the lineage graph is committed as `docs/assets/dbt-dag-refinement.png` |

**Observability is the weakest area against spec** — three of five requirements unmet.
What exists is sufficient to audit a run after the fact but not to monitor one
programmatically.

---

## 9. Security specification

| ID | Requirement | Status | As built |
|---|---|---|---|
| TR-45 | Secrets supplied via environment variables locally and GitHub Secrets in CI | ✅ | Plus a private key held **outside** the repository entirely |
| TR-46 | `.env` git-ignored; `.env.example` with placeholders committed | ✅ | `*.p8` also git-ignored |
| TR-47 | No credential in logs; a CI step shall grep for common secret patterns | ✅ | **Demonstrated turning red in 7 seconds** on a planted `SNOWFLAKE_PASSWORD`, printing file and line only, never the value |
| TR-48 | The AWS IAM user shall have write access only to the project bucket prefix | ✅ | `de-capstone-airflow-uploader`: `PutObject` + multipart + scoped `ListBucket`, **no `GetObject`**, and `DeleteObject` restricted to `silver_pipeline/*` so the protected artifact stays physically undeletable |
| TR-49 | An AWS Budget alert at €5 shall be configured **before any cloud resource is created** | ❓ | **Cannot be verified from the repository.** No evidence exists in code, config or documentation. Actual spend was $0.25, so no alert would have fired either way — but the control itself is unconfirmed and is flagged rather than claimed |

**Delivered beyond spec:**

- **Snowflake key-pair authentication** with a `TYPE = SERVICE` identity that *cannot hold a
  password* — [ADR-012](adr/ADR-012-snowflake-key-pair-service-identity.md)
- **A separate CI identity** with 8 grants, read-only on RAW and nothing on production,
  proven by a refused `SELECT` — [ADR-013](adr/ADR-013-separate-ci-identity.md)
- **AWS OIDC** for CI: short-lived tokens minted per job, capped by a permissions boundary

**Stated precisely:** there is **no Snowflake password anywhere in the project**, and **no
AWS access key in the repository or in GitHub Secrets**. The local `upload_s3` task does use
a long-lived access key for the scoped uploader identity, held in a git-ignored file outside
version control, because IAM roles cannot hold access keys and the Snowflake
storage-integration role is read-only.

No PII handling requirements apply: FAERS is de-identified public data. Patient age is
banded rather than stored exactly, as a defensive measure.

---

## 10. Retrieval extension specification *(BR-16, BR-17)*

**Conditional on all Must requirements being satisfied. Hard stop 18 August.**

| ID | Requirement | Status |
|---|---|---|
| TR-50 | Label documents chunked by SPL section, one chunk per section | ❌ |
| TR-51 | Chunks embedded with `all-MiniLM-L6-v2` (384 dimensions) | ❌ |
| TR-52 | Embeddings stored in Postgres `vector(384)` with an HNSW cosine index | ❌ |
| TR-53 | Retrieval pre-filters on structured metadata before similarity ranking | ❌ |
| TR-54 | Every answer cites the source label id and section | ❌ |
| TR-55 | Below a similarity threshold, return "outside indexed scope" and do not generate | ❌ |
| TR-56 | A gold set of ≥ 30 question/chunk pairs committed; recall@5 measured and published | ❌ |
| TR-57 | Index scope configurable, not hard-coded | ❌ |

**None built. The hard stop was honoured.** The label corpus (261,258 records) is ingested
and sits in Bronze, so the work remains startable rather than hypothetical. TR-56 was the
requirement that made this worth doing, and building the rest without it would have produced
a demo rather than engineering — which is why a partial build was rejected rather than
attempted. Full reasoning: [ADR-015](adr/ADR-015-retrieval-extension-not-built.md).

---

## 11. Non-functional requirements

| ID | Requirement | Target | Status | Actual |
|---|---|---|---|---|
| TR-58 | Daily incremental pipeline runtime | < 30 min | ➖ | No scheduled incremental exists (TR-27). The nearest analogue — a one-month trigger exercising the whole chain — runs in **~20 min** |
| TR-59 | Full historical backfill runtime | < 6 h, resumable | ✅ | **3 h 57 m 23 s.** "Resumable" means re-triggerable and idempotent, not checkpointed (TR-30) |
| TR-60 | Data freshness | ≤ 24 h behind source | ➖ | Not applicable to a frozen 2023–2024 snapshot with no scheduled run |
| TR-61 | Dashboard query response | < 5 s | ✅ | **~3.7 s** for the all-time view — fast enough that `sem_signal_metrics` was left as a view rather than materialised |
| TR-62 | Total project infrastructure cost | < $10 | ⚠️ | **$0.25 of real money** ✅ — plus **$42 of a $400 Snowflake trial** consumed. Under the letter of the requirement; stated in full rather than hidden behind "free tier" |
| TR-63 | Cold start from clean clone to running pipeline | one documented command, < 15 min | ❌ | **Not achieved.** Three Docker stacks, three virtual environments, two cloud accounts, a key pair to generate and register, and a 30–60 minute Bronze download. The README documents the real path honestly instead of claiming a single command |

> **TR-63 is the one to be up front about.** It was written expecting a fully cloud-hosted
> design; the hybrid decision ([ADR-009](adr/ADR-009-hybrid-deployment-bronze-local.md))
> made it unreachable, because 64 GB of Bronze cannot be part of a 15-minute setup. The
> trade was $0.25 of total spend against clone-and-run convenience.

---

## 12. Repository structure — as built

```
de-capstone/
├── README.md                       # project overview, setup
├── architecture.md                 # as-built architecture
├── runbook.md                      # operations and failure playbook
├── docker-compose.yml              # Spark/Jupyter + dbt containers
├── dbt.Dockerfile                  # dbt-snowflake 1.12.0, isolated from Airflow
├── .env.example
├── airflow/
│   ├── docker-compose.yaml         # Airflow 2.10.5, pinned
│   └── dags/pv_pipeline.py         # the 8-task DAG
├── scripts/
│   ├── ingest_drug_event.py        # date-windowed FAERS ingestion
│   ├── ingest_drug_label.py        # bulk download
│   ├── ingest_drug_ndc.py          # bulk download
│   ├── backfill_days.py            # re-fetch specific days
│   ├── build_silver.py             # headless PySpark job
│   ├── load_to_snowflake.py        # rollback loader (internal stage)
│   ├── load_raw.py                 # one-month smoke loader
│   └── ddl_raw.sql                 # RAW tables, stages, file formats
├── de_capstone/                    # the dbt project
│   ├── dbt_project.yml             # thresholds as vars
│   ├── profiles.yml                # env_var() only, no literals
│   ├── macros/
│   │   ├── normalize_drug_name.sql
│   │   ├── signal_metrics.sql      # the single metric definition
│   │   ├── load_raw_from_s3.sql    # TRUNCATE + COPY, called by the DAG
│   │   └── publish_metrics.sql     # headline figures into the run log
│   ├── models/{staging,intermediate,marts,semantic}/
│   ├── seeds/signal_worked_example.csv
│   └── tests/{assert_signal_worked_example,assert_fct_rowcount_plausible}.sql
├── app/
│   ├── db.py                       # key-pair connection + self-test
│   ├── dashboard.py                # port 8501 — rollback
│   ├── dashboard_enhanced.py       # port 8502 — Plotly
│   └── dashboard_snowflake.py      # hosted in Snowflake
├── tests/
│   ├── test_drug_normalisation.py  # TR-37
│   └── test_signal_metrics.py      # TR-38
├── terraform/{main,versions,imports}.tf
├── notebooks/                      # exploration + Silver reference notebooks
├── .github/workflows/{ci,dbt-ci,s3-contract,terraform}.yml
└── docs/
    ├── business_requirements.md
    ├── technical_requirements.md
    ├── PROGRESS.md
    ├── adr/
    ├── assets/                     # architecture diagram, dbt lineage, screenshots
    └── Metadata/                   # field dictionary, source schemas
```

> **Differences from v0.1 §12**, all consequences of decisions recorded elsewhere: DAGs
> live under `airflow/` (three-stack design, [ADR-010](adr/ADR-010-airflow-triggers-containers.md));
> the dbt project is `de_capstone/` at the root, not `dbt/`; there is no `ingestion/` package —
> the four ingestion scripts sit in `scripts/` alongside the Spark job; there is no `rag/`
> directory ([ADR-015](adr/ADR-015-retrieval-extension-not-built.md)); and the dashboard is
> three files rather than one `streamlit_app.py`.

---

## 13. CI specification

| ID | Requirement | Status | As built |
|---|---|---|---|
| TR-64 | On every pull request: lint (`ruff`), `pytest`, `dbt parse`, `dbt compile` | ⚠️ | ruff ✅ · pytest ✅ (21 tests) · `dbt parse` ✅ (all 10 models, no warehouse connection) · **`dbt compile` ❌** — not run separately; `dbt build` in `dbt-ci.yml` compiles as a side effect. Additional checks beyond spec: a Python syntax matrix on 3.11 and 3.12, and a secret scan |
| TR-65 | On merge to `main`: the above plus `dbt build` against a CI schema, then `dbt docs generate` | ⚠️ | **`dbt build` ✅** into an isolated `DBT_CI` schema under a separate identity — **PASS=53 in 1 m 17 s**, and it runs on pull requests too, not only on merge. **`dbt docs generate` ❌** |
| TR-66 | A secret-scanning step shall run on every push | ✅ | Demonstrated refusing a credential |
| TR-67 | CI shall fail the build on any test failure; no manual override | ⚠️ | Blocking checks fail the build ✅. Two qualifications: the full ruff rule set runs `--exit-zero` so style informs but never blocks (only `E9,F63,F7,F82` block), and **branch protection is configured but not enforced** — GitHub does not apply rulesets to private repositories on this plan. *The workflow detects; branch protection enforces.* Detection works and was demonstrated |

**Four workflows, eight checks**, and each gate was proven by making it refuse something:

| Workflow | Proof |
|---|---|
| `ci.yml` | Planted `SNOWFLAKE_PASSWORD` → red in 7 seconds |
| `dbt-ci.yml` | PASS=53 from a clean machine under an identity that cannot see production |
| `s3-contract.yml` | Red on a **2,698-byte** difference while the object count matched exactly — which is why it asserts both numbers |
| `terraform.yml` | `2 imported, 0 added, 0 changed, 0 destroyed`, then an **empty second plan** |

---

## 14. Traceability summary

| Business requirement | Technical requirements | Status |
|---|---|---|
| BR-01 … BR-04 (ingestion, retention) | TR-01 … TR-08 | ⚠️ TR-05/06/07 deviate |
| BR-05 (deduplication) | TR-13, TR-14, TR-33 | ✅ |
| BR-06, BR-07 (drug resolution, characterisation) | TR-16 … TR-19, TR-35, TR-37 | ✅ |
| BR-08, BR-09 (incremental, backfill) | TR-02, TR-03, TR-26, TR-29, TR-30 | ⚠️ BR-08 not met; backfill ✅ |
| BR-10 … BR-14 (metrics, semantic layer) | TR-20 … TR-25, TR-38 | ✅ |
| BR-15 (UI) | TR-43, TR-61 | ✅ |
| BR-16, BR-17 (retrieval) | TR-50 … TR-57 | ❌ Not built |
| BR-18 … BR-20 (orchestration, resilience) | TR-26 … TR-32, TR-39 | ⚠️ No schedule; no drift detection |
| BR-21, BR-22 (logging, lineage) | TR-40 … TR-44 | ⚠️ Lineage ✅; structured logging ❌ |
| BR-23 (secrets) | TR-45 … TR-48 | ✅ Exceeded |

---

## 15. Gate review record

| Gate | Document | Approver | Date | Status |
|---|---|---|---|---|
| 1 — Business requirements | `business_requirements.md` | Instructor / TA | | ⬜ |
| 2 — Technical requirements | *this document* | Instructor / TA | | ⬜ |
| 3 — Architecture | `architecture.md` | Instructor / TA | | ⬜ |

> **To be completed by the instructor / TA.**

### How the Gate-2 review questions were resolved

| Question raised at Gate 2 | Resolution |
|---|---|
| *"Should I build against Snowflake, or against Postgres so the repo stays runnable after the trial expires?"* | **Snowflake.** dbt keeps the SQL engine-portable, so the decision stays reversible; the trial covered the delivery window with 11 days to spare — [ADR-002](adr/ADR-002-warehouse-snowflake.md) |
| *"Is a 3-year window sufficient, or should I ingest everything?"* | **A 2-year window (2023–2024).** 2,687,675 reports → 45,030,932 analytical rows, which is ample for stable disproportionality statistics. The binding constraint turned out to be Spark runtime on a laptop, not data availability |
| *"Is IaC expected for the grade, or acceptable as documented future work?"* | **Built, deliberately narrow.** Terraform manages exactly two objects — the CI IAM role and its policy — imported rather than created, with an empty second plan as the acceptance gate — [ADR-014](adr/ADR-014-terraform-ci-role-only.md) |
| *"Is Streamlit sufficient, or is Power BI preferred?"* | **Streamlit, and then hosted inside Snowflake.** The hosted app removed the laptop from the demo entirely and runs as a read-only role, which Power BI would not have matched without licensing |

---

## 16. Reconciliation summary — every deviation in one place

**Met in full: 43 · Met with deviation: 14 · Not met: 9 · Not applicable: 1 · Unverifiable: 1**

| TR | Deviation | Recorded where |
|---|---|---|
| TR-02 | `MAX_SKIP` 25,000 rather than 26,000 (conservative) | §2 |
| TR-03 | FAERS backfill uses the paged API, not bulk files | §2 |
| TR-04 | 6 attempts capped at 30 s, not 5 attempts base 2 s | §2 |
| **TR-05** | Bronze is **not gzipped** | §3.1 — gap |
| **TR-06** | Bronze is **local, not in S3** | [ADR-009](adr/ADR-009-hybrid-deployment-bronze-local.md) |
| **TR-07** | **No per-file manifests** | §3.1 — gap |
| TR-09 | External stage serves Silver rather than Bronze | [ADR-011](adr/ADR-011-s3-external-stages.md) |
| TR-10 | `RAW` + `DBT_DEV`, not four schemas | §3.2 |
| TR-11 | Snowflake identities and grants created by hand | §3.2 |
| TR-14 | Duplicate counts persisted but not exposed as a live metric | §4.2 |
| TR-15 | Quarantine is a Parquet dataset, not a Snowflake table | §4.2 |
| TR-24 | Formulas in one *macro* used by two models | §5.3 |
| TR-26 | One DAG, not three | §6 |
| **TR-27** | **`schedule=None`** — manual trigger | §6 |
| **TR-30** | **No ingestion checkpoint** | §6 — gap |
| TR-32 | 2 retries, fixed delay, per-task timeouts | §6 |
| **TR-39** | **No schema-drift detection** | §7 — gap |
| **TR-40** | **No structured JSON logging** | §8 — gap |
| TR-41 | No `pipeline_run_log` table; equivalent record in two other places | §8 |
| **TR-42** | **No per-run cost recording** | §8 — gap |
| **TR-44** | **No `dbt docs generate` in CI** | §8 — gap |
| TR-49 | AWS Budget alert **unverifiable** | §9 |
| **TR-50 … TR-57** | **Retrieval extension not built** | [ADR-015](adr/ADR-015-retrieval-extension-not-built.md) |
| TR-58, TR-60 | Not applicable — no scheduled run, frozen snapshot | §11 |
| TR-62 | $0.25 paid **plus $42 of trial credit** | §11 |
| **TR-63** | **Cold start is not one command** | §11 |
| §12 | Repository structure differs | §12 |
| TR-64 | `dbt compile` not run separately | §13 |
| TR-65 | `dbt docs generate` not in CI | §13 |
| TR-67 | ruff style non-blocking; branch protection not enforced | §13 |

**The pattern.** Deviations cluster in two places: **Bronze storage** (TR-05/06/07),
which is one recorded decision with two unbuilt side-requirements, and **observability**
(TR-39/40/41/42/44), which is the genuine weak area — the pipeline can be audited after a
run but not monitored during one. Everything in the data path itself — ingestion,
deduplication, resolution, modelling, metrics, testing and security — is met or exceeded.
