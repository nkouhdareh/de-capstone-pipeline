# Technical Requirements Document

## Pharmacovigilance Signal Detection & Label Intelligence Platform

| | |
|---|---|
| **Author** | Nastaran Kouhdareh |
| **Version** | 0.1 — draft for instructor review |
| **Date** | 3 August 2026 |
| **Depends on** | `business_requirements.md` v0.1 (Gate 1) |
| **Status** | ⬜ Awaiting Instructor / TA approval (Gate 2 of 3) |

Every requirement below traces to a business requirement (BR-nn) from Gate 1.

---

## 1. Technology selections

| Layer | Selection | Justification | Known to me |
|---|---|---|---|
| Ingestion | Python 3.11 + `requests` | Sufficient for a paginated REST source; no framework needed | ✅ week 4 |
| Object storage | AWS S3 | Bronze landing zone; $182 credits available | ✅ week 6 |
| Warehouse | Snowflake | Trial covers it (~$2 observed in cohort projects); matches reference architecture | ✅ week 5 |
| Transformation | dbt Core | SQL-shaped work; native testing, lineage and docs | ✅ week 5 |
| Orchestration | Apache Airflow 3 (Docker) | Highest-demand orchestrator in my job ad sample (31%) | ✅ week 5 |
| Containerisation | Docker Compose | Reproducible local environment | ✅ week 3 |
| CI | GitHub Actions | Free for public repos | ✅ week 11 |
| IaC | Terraform *(optional)* | S3 bucket + IAM only; first item to cut | ✅ week 11 |
| Data quality | dbt tests + `pytest` | dbt for data assertions, pytest for logic | ✅ weeks 5, 12 |
| Dashboard | Streamlit | Cohort standard; no auth layer required | ⚠️ light |
| Vector store | Postgres + `pgvector` | Reuses Airflow's Postgres; metadata filter and similarity search in one SQL query | ❌ new |
| Embeddings | `sentence-transformers` / `all-MiniLM-L6-v2` | Local, CPU, free, 384 dimensions | ❌ new |
| Generation | Ollama / `llama3.1:8b` | Local, free, no data leaves the environment | ❌ new |

**New-to-me learning cost:** pgvector ≈ 0.5 day, sentence-transformers ≈ 0.5 day,
Ollama ≈ 0.25 day. All confined to the extension phase (17–18 August).

**Rejected:** Spark (no distributed workload at this volume — ADR-004),
Kafka (no real-time source — ADR-007), Elasticsearch (operational weight;
rank fusion is Enterprise-tier — ADR-006), Databricks/Fabric (no credits).

---

## 2. Source system specification

| Endpoint | Purpose | Volume | Update | Key field |
|---|---|---|---|---|
| `/drug/event.json` | FAERS reports | 20M+ | Continuous | `safetyreportid` + `safetyreportversion` |
| `/drug/label.json` | Product labels | ~150k | Periodic | `id`, `openfda.spl_id` |
| `/drug/ndc.json` | Product directory | ~130k | Periodic | `product_ndc` |

**Access constraints (TR-01 … TR-04):**

| ID | Requirement | Source BR |
|---|---|---|
| TR-01 | An API key shall be obtained and supplied via the `api_key` parameter, raising limits to 240 req/min and 120,000 req/day | BR-01 |
| TR-02 | Pagination shall use `limit` (max 1000 for `drug/event`, 100 for `drug/ndc`) with `skip`, respecting the 26,000-record `skip` ceiling by partitioning queries on `receivedate` windows | BR-01 |
| TR-03 | Historical backfill shall use the quarterly bulk JSON files listed in `https://api.fda.gov/download.json`, not the paged API | BR-09 |
| TR-04 | Requests shall retry on HTTP 429/5xx with exponential backoff (base 2s, max 5 attempts) and fail the task after exhaustion | BR-19, BR-20 |

> **Note on TR-02.** The `skip` ceiling is the single most important technical
> constraint in this project. Any query returning more than 26,000 records must be
> split into narrower date windows. Ingestion is therefore date-partitioned by
> design, which conveniently also makes it idempotent and backfillable.

---

## 3. Storage layer specification

### 3.1 Bronze — S3

| ID | Requirement | Source BR |
|---|---|---|
| TR-05 | Raw responses shall be written unmodified as gzipped newline-delimited JSON | BR-04 |
| TR-06 | Objects shall be laid out as `s3://<bucket>/bronze/endpoint=<name>/ingest_date=<YYYY-MM-DD>/part-<n>.json.gz` | BR-04 |
| TR-07 | Each file shall be accompanied by a manifest recording endpoint, query window, record count, retrieval timestamp and pipeline run id | BR-21, BR-22 |
| TR-08 | Bronze objects shall never be modified or deleted by the pipeline | BR-09 |

### 3.2 Silver and Gold — Snowflake

| ID | Requirement | Source BR |
|---|---|---|
| TR-09 | Bronze shall be exposed to Snowflake via an external stage with storage integration | BR-01 |
| TR-10 | Schemas shall be `RAW`, `STAGING`, `INTERMEDIATE`, `MARTS` | BR-02 |
| TR-11 | All models shall be built by dbt; no manual DDL outside version control | BR-22 |
| TR-12 | The fact table shall be clustered on `receive_date` | BR-14 |

---

## 4. Transformation specification

### 4.1 dbt layer contract

| Layer | Prefix | Materialisation | Rules |
|---|---|---|---|
| Staging | `stg_` | view | One model per source; rename, cast, no joins, no filters |
| Intermediate | `int_` | ephemeral / view | Deduplication, explosion of nested arrays, name normalisation |
| Marts | `dim_`, `fct_` | table | Star schema; documented grain; tested keys |
| Semantic | `sem_` | view | Metric definitions; the only place formulas appear |

### 4.2 Deduplication (TR-13 … TR-15)

| ID | Requirement | Source BR |
|---|---|---|
| TR-13 | A unique case shall be the row with the highest `safetyreportversion` for a given `safetyreportid` | BR-05 |
| TR-14 | The count of rows removed as duplicates shall be persisted per run and exposed as a metric | BR-05, BR-21 |
| TR-15 | Rows failing schema validation shall be routed to a `_quarantine` table with a failure reason, not dropped | BR-20 |

### 4.3 Drug name resolution (TR-16 … TR-19)

**This is the highest-risk component. It is deliberately specified as tiered so a
partial result is still a deliverable result.**

| ID | Requirement | Tier | Source BR |
|---|---|---|---|
| TR-16 | Names shall be normalised by uppercasing, stripping punctuation, dosage strings and salt forms | 1 | BR-06 |
| TR-17 | Normalised names shall be matched exactly against `brand_name` and `generic_name` in the NDC directory | 1 | BR-06 |
| TR-18 | Unmatched names shall be matched against `openfda.substance_name` and `openfda.rxcui` where present on the report | 2 | BR-06 |
| TR-19 | Names still unresolved shall be retained with `drug_key = -1` (Unknown) and counted; the **resolution rate shall be published** | 1 | BR-06 |

> Fuzzy matching (trigram / Levenshtein) is explicitly **out of scope**. A measured
> 70% resolution rate that is documented is a better engineering outcome than an
> unbounded matching effort. See ADR-005.

---

## 5. Dimensional model specification

### 5.1 Grain declarations

| Model | Grain | Rows (est.) |
|---|---|---|
| `fct_report_drug_reaction` | One row per (safety case, drug, reaction) | ~10–50M |
| `fct_signal_metrics` | One row per (drug, reaction, period) | ~1–5M |
| `dim_drug` | One row per resolved product identity | ~50k |
| `dim_reaction` | One row per MedDRA preferred term | ~25k |
| `dim_reporter` | One row per (qualification, country) | ~1k |
| `dim_date` | One row per calendar day | ~10k |

### 5.2 Column specification — `fct_report_drug_reaction`

| Column | Type | Note |
|---|---|---|
| `report_drug_reaction_key` | varchar | Surrogate hash of the grain |
| `safety_report_id` | varchar | Degenerate dimension |
| `drug_key` | number | FK → `dim_drug`; `-1` = Unknown |
| `reaction_key` | number | FK → `dim_reaction` |
| `reporter_key` | number | FK → `dim_reporter` |
| `receive_date_key` | number | FK → `dim_date`; cluster key |
| `drug_characterisation` | varchar | `SUSPECT` / `CONCOMITANT` / `INTERACTING` — **BR-07** |
| `is_serious` | boolean | |
| `outcome_death`, `outcome_hospitalisation`, `outcome_life_threatening`, `outcome_disability` | boolean | **BR-12** |
| `patient_age_band`, `patient_sex` | varchar | Banded, never exact |
| `report_version` | number | Retained for audit |
| `_loaded_at`, `_run_id` | timestamp, varchar | Lineage |

### 5.3 Metric definitions (TR-20 … TR-23)

Computed on the 2×2 contingency table for drug *D* and reaction *E*, using
**suspect drugs only** and **unique cases only**:

|  | Reaction E | Not E |
|---|---|---|
| Drug D | `a` | `b` |
| Not D | `c` | `d` |

| ID | Requirement | Definition |
|---|---|---|
| TR-20 | PRR shall be computed as | `(a / (a + b)) / (c / (c + d))` |
| TR-21 | ROR shall be computed as | `(a * d) / (b * c)` |
| TR-22 | The 95% CI lower bound of ROR shall be computed as | `exp( ln(ROR) − 1.96 * sqrt(1/a + 1/b + 1/c + 1/d) )` |
| TR-23 | A pair shall be flagged as a signal when | `a >= 3 AND PRR >= 2 AND chi2_yates >= 4` |

where `chi2_yates = N * (|a*d − b*c| − N/2)^2 / ((a+b)(c+d)(a+c)(b+d))`, `N = a+b+c+d`.

**TR-24:** These formulas shall appear in exactly one dbt model (`sem_signal_metrics`).
No consumer shall recompute them. *(BR-14)*

**TR-25:** Thresholds shall be dbt variables, not literals, and the chosen values
shall be documented with their source. *(BR-11)*

---

## 6. Orchestration specification

| ID | Requirement | Source BR |
|---|---|---|
| TR-26 | Three DAGs shall exist: `pv_daily_pipeline`, `pv_backfill` (manual, parameterised on start/end date), `pv_index_labels` (extension) | BR-08, BR-09, BR-18 |
| TR-27 | `pv_daily_pipeline` shall run at 04:00 UTC with `catchup=False` and `max_active_runs=1` | BR-18 |
| TR-28 | Task order shall be: `ingest_ndc → ingest_faers → load_to_snowflake → dbt_run → dbt_test → publish_metrics` | BR-18 |
| TR-29 | Every task shall be idempotent: re-running for the same logical date shall produce the same result and no duplicates | BR-19 |
| TR-30 | Ingestion shall checkpoint the last successfully processed date window, so a resumed run does not restart from the beginning | BR-19 |
| TR-31 | `dbt_test` failure shall fail the DAG run and leave marts at their previous state | BR-19 |
| TR-32 | Task-level retries: 3 attempts, exponential backoff, 30-minute execution timeout | BR-19, BR-20 |

---

## 7. Data quality specification

| ID | Requirement | Implementation | Source BR |
|---|---|---|---|
| TR-33 | Primary keys shall be tested for uniqueness and non-nullity on every mart model | dbt `unique`, `not_null` | BR-05 |
| TR-34 | Every foreign key shall be tested for referential integrity | dbt `relationships` | BR-06 |
| TR-35 | `drug_characterisation` and `patient_sex` shall be tested against enumerated values | dbt `accepted_values` | BR-07 |
| TR-36 | Row counts shall be tested for plausible range per run to detect silent source failure | dbt custom test | BR-21 |
| TR-37 | The drug-name normalisation function shall have unit tests covering at least 10 real-world name variants | `pytest` | BR-06 |
| TR-38 | The PRR and ROR calculations shall have a unit test against a hand-computed worked example | `pytest` + dbt seed fixture | BR-10 |
| TR-39 | Schema drift in source payloads shall be detected and logged rather than causing task failure | JSON schema check in ingestion | BR-20 |

**TR-38 is the highest-value test in the project.** A hand-verified worked example
for a statistical metric is exactly the kind of evidence that distinguishes a
tested pipeline from an asserted one.

---

## 8. Observability specification

| ID | Requirement | Source BR |
|---|---|---|
| TR-40 | All pipeline logs shall be structured JSON with keys: `run_id`, `dag_id`, `task_id`, `event`, `rows_in`, `rows_out`, `rows_rejected`, `duration_s` | BR-21 |
| TR-41 | A `pipeline_run_log` table shall persist one row per run with status, timings, row counts and duplicates removed | BR-21 |
| TR-42 | Estimated cost per run shall be computed from Snowflake credit consumption and recorded in `pipeline_run_log` | BR-21 |
| TR-43 | A data quality summary (resolution rate, duplicate rate, rejection rate) shall be published to the dashboard | BR-15, BR-21 |
| TR-44 | dbt `docs generate` output including the lineage graph shall be produced on every CI run | BR-22 |

---

## 9. Security specification

| ID | Requirement | Source BR |
|---|---|---|
| TR-45 | Secrets shall be supplied via environment variables locally and GitHub Secrets in CI | BR-23 |
| TR-46 | `.env` shall be git-ignored; an `.env.example` with placeholder values shall be committed | BR-23 |
| TR-47 | No credential shall appear in logs; a CI step shall grep the diff for common secret patterns | BR-23 |
| TR-48 | The AWS IAM user shall have write access only to the project bucket prefix | BR-23 |
| TR-49 | An AWS Budget alert at €5 shall be configured **before any cloud resource is created** | Constraint §13 |

No PII handling requirements apply: FAERS is de-identified public data. Patient age
is banded rather than stored exactly, as a defensive measure.

---

## 10. Retrieval extension specification *(BR-16, BR-17)*

**Conditional on all Must requirements above being satisfied. Hard stop 18 August.**

| ID | Requirement |
|---|---|
| TR-50 | Label documents shall be chunked by SPL section (indications, warnings, contraindications, adverse reactions), one chunk per section — no sliding-window chunking |
| TR-51 | Chunks shall be embedded with `all-MiniLM-L6-v2` (384 dimensions); the identical model shall embed queries |
| TR-52 | Embeddings shall be stored in Postgres `vector(384)` with an HNSW index using cosine distance (`<=>`) |
| TR-53 | Retrieval shall pre-filter on structured metadata (drug key, section type) in SQL before similarity ranking |
| TR-54 | Every answer shall cite the source label id and section |
| TR-55 | Where no chunk exceeds a configured similarity threshold, the system shall return "outside indexed scope" and shall not invoke the generator |
| TR-56 | A gold evaluation set of at least 30 question/expected-chunk pairs shall be committed, and retrieval recall@5 shall be measured and published |
| TR-57 | The index scope shall be a single therapeutic area defined in configuration, not hard-coded |

**TR-56 is the requirement that makes this worth doing.** An unmeasured retrieval
layer is a demo; a measured one is engineering.

---

## 11. Non-functional requirements

| ID | Requirement | Target |
|---|---|---|
| TR-58 | Daily incremental pipeline runtime | < 30 minutes |
| TR-59 | Full historical backfill runtime | < 6 hours, resumable |
| TR-60 | Data freshness | ≤ 24 hours behind source |
| TR-61 | Dashboard query response | < 5 seconds |
| TR-62 | Total project infrastructure cost | < $10 |
| TR-63 | Cold start from clean clone to running pipeline | one documented command, < 15 minutes |

TR-63 is tested by the instructor at the pre-submission review. It must actually work.

---

## 12. Repository structure

```
pv-signal-platform/
├── README.md
├── architecture.md
├── runbook.md
├── docker-compose.yaml
├── .env.example
├── docs/
│   ├── business_requirements.md
│   ├── technical_requirements.md
│   └── adr/
│       ├── ADR-001-domain-and-data-source.md
│       ├── ADR-002-warehouse-snowflake.md
│       ├── ADR-003-medallion-architecture.md
│       ├── ADR-004-dbt-over-spark.md
│       ├── ADR-005-drug-name-resolution-tiers.md
│       ├── ADR-006-vector-store-pgvector.md
│       ├── ADR-007-no-streaming-layer.md
│       └── ADR-008-local-llm-over-hosted.md
├── dags/
│   ├── pv_daily_pipeline.py
│   ├── pv_backfill.py
│   └── pv_index_labels.py
├── ingestion/
│   ├── openfda_client.py        # pagination, backoff, checkpointing
│   ├── extractors.py
│   └── schemas.py               # JSON schema validation
├── dbt/
│   ├── dbt_project.yml
│   ├── profiles.yml
│   └── models/
│       ├── staging/
│       ├── intermediate/
│       ├── marts/
│       └── semantic/
├── rag/
│   ├── chunk.py
│   ├── embed.py
│   ├── retrieve.py
│   └── eval/gold_questions.yaml
├── app/streamlit_app.py
├── tests/
│   ├── test_drug_normalisation.py
│   ├── test_signal_metrics.py
│   └── test_retrieval_guardrail.py
├── terraform/                   # optional
└── .github/workflows/ci.yml
```

---

## 13. CI specification

| ID | Requirement |
|---|---|
| TR-64 | On every pull request: lint (`ruff`), `pytest`, `dbt parse`, `dbt compile` |
| TR-65 | On merge to `main`: the above plus `dbt build` against a CI schema, then `dbt docs generate` |
| TR-66 | A secret-scanning step shall run on every push |
| TR-67 | CI shall fail the build on any test failure; no manual override |

---

## 14. Traceability summary

| Business requirement | Technical requirements |
|---|---|
| BR-01 … BR-04 (ingestion, retention) | TR-01 … TR-08 |
| BR-05 (deduplication) | TR-13, TR-14, TR-33 |
| BR-06, BR-07 (drug resolution, characterisation) | TR-16 … TR-19, TR-35, TR-37 |
| BR-08, BR-09 (incremental, backfill) | TR-02, TR-03, TR-26, TR-29, TR-30 |
| BR-10 … BR-14 (metrics, semantic layer) | TR-20 … TR-25, TR-38 |
| BR-15 (UI) | TR-43, TR-61 |
| BR-16, BR-17 (retrieval) | TR-50 … TR-57 |
| BR-18 … BR-20 (orchestration, resilience) | TR-26 … TR-32, TR-39 |
| BR-21, BR-22 (logging, lineage) | TR-40 … TR-44 |
| BR-23 (secrets) | TR-45 … TR-48 |

---

## 15. Approval

### Open technical questions for review

1. **Snowflake dependency.** The trial expires after one month, which covers the
   project but not later portfolio demonstrations. Should I build against Snowflake,
   or against Postgres so the project remains runnable indefinitely by anyone
   cloning the repo?
2. **Backfill depth.** Full FAERS history is 20M+ reports. Is a 3-year window
   sufficient to demonstrate the capability, or should I ingest everything?
3. **Terraform.** Is IaC expected for the grade, or acceptable as documented
   future work if time is short?
4. **Dashboard.** Is Streamlit sufficient, or is Power BI preferred given its
   higher presence in job advertisements?

| Gate | Approver | Date | Status |
|---|---|---|---|
| Business requirements | | | ⬜ |
| Technical requirements *(this document)* | | | ⬜ |
| Architecture | | | ⬜ |
