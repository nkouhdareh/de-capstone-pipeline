# Project Progress & Handoff

*A running snapshot of where the project is, so a fresh session (or a teammate) can pick up fast.*
**Status as of:** Silver layer coded & smoke-tested — issues #4/#5/#6 (Week 2). Full Run-All pending.

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
  reaction), cast/decode, **#4** dedup, **#5** tiered normalisation (resolution rate published),
  **#6** validation/quarantine; writes `silver/` + `quarantine/` Parquet. `docker-compose.yml` gains
  writable `silver`/`quarantine` mounts (bronze stays read-only). *Smoke-tested on 1 day; full
  Run-All pending.*

## Key data-quality findings (these drive the cleaning)
| Dimension | Result | Cleaning action |
|---|---|---|
| Uniqueness | 0 duplicate `safetyreportid` (2.69M unique) | #4: report-level dedup already done by openFDA; re-check the (report, drug, reaction) grain after flatten |
| Completeness | key fields 100% (id, dates, drug name, reaction); demographics partial (age 44%, sex 17%, country 11%) | #6: demographics → `Unknown` |
| Consistency | coded fields valid **except 18 rogue `drugcharacterization`** (codes 4/5) | #6: quarantine `drugcharacterization ∉ {1,2,3}` |
| Drug names | 97,789 distinct; ~83% resolved by `openfda.generic_name` | #5: Tier-1 `openfda.generic_name`/`substance_name`; Tier-2 clean/flag the ~17% tail |
| Fan-out / skew | ~3.9 drugs & ~3.0 reactions per report; **max 4,113 drugs / 518 reactions** | Silver: handle mega-report skew when flattening |
| Timeliness | exact 2023–2024 window; batch/quarterly source | note only |

## Silver layer — built (#4 / #5 / #6) — PySpark
`notebooks/02_build_silver_drug_event.ipynb`. Grain: one row per **(case, resolved drug,
characterization, reaction)**; columns shaped to feed `fct_report_drug_reaction` (TR §5.2).

- **Flatten** `patient.drug[]` × `patient.reaction[]`; mega-report skew handled — slim the drug
  struct *before* exploding, then repartition on `(safety_report_id, drug_idx)` before the reaction
  explode so one 4,113-drug report can't pile onto a single task.
- **Cast/decode** — dates from `YYYYMMDD`; coded fields decoded; demographics → `Unknown`; age
  **banded, never exact** (TR §9); seriousness → booleans (BR-12).
- **#4 dedup** — at the atomic grain. Report-level was 0 dup, but ~**38%** of atomic rows dedup on
  the sample day: reports repeat the same drug across dosage entries → collapsed to one row per
  case-drug-reaction (correct case counts). *A real finding the report-level check couldn't see.*
- **#5 normalisation** — Tier-1 `openfda.generic_name` → `substance_name`; Tier-2 cleaned raw
  (flagged `unresolved_raw`). **Resolution rate published** (~79% sample day; ~83% expected full).
- **#6 validation/quarantine** — `drugcharacterization ∈ {1,2,3}` enforced; rejects (~19: codes 4/5
  + null) routed to `quarantine/drug_event` with a reason, never dropped.
- **Output** — `D:/capstone/data/silver/drug_event/` (Parquet, partitioned by `receive_year`/`month`)
  + `D:/capstone/data/quarantine/drug_event/`. Run steps + baselines in `runbook.md` §2–§3.

*Smoke-tested end-to-end on 1 day (`receivedate=20240102`). Full Run-All still to do — the real
resolution / dedup / quarantine counts get filled into `runbook.md` §3 from that run.*

## NEXT: load Silver → Snowflake, then model in dbt
1. Land the Silver Parquet in Snowflake `RAW` (external stage — TR-09/10).
2. dbt: `stg_` (rename/cast, 1:1) → `int_` (modelling on the clean atomic Silver) → `dim_`/`fct_`
   marts: `fct_report_drug_reaction`, `dim_drug`, `dim_reaction`, `dim_reporter`, `dim_date` (TR §5).
3. `sem_signal_metrics` — PRR / ROR / χ² + signal flag, formulas in exactly one model (TR §5.3, TR-24).
4. dbt tests (**#7**) — key uniqueness/not-null, accepted-values on codes, the PRR/ROR worked-example
   test (TR-33…TR-38).
5. Consider **ADR-005** (drug-name resolution tiers) — referenced by TR §12 / TR-19, not yet written.

## How to run (quick)
- **Explore:** `docker compose up` → http://localhost:8888 → `work/01_explore_drug_event.ipynb`. First cache JSON→Parquet (`/home/jovyan/dq_cache`) for speed. Full detail + failure fixes in `runbook.md`.
- **Silver:** `docker compose up` (recreates for the new writable mounts) → `work/02_build_silver_drug_event.ipynb` → Run All. Writes `silver/` + `quarantine/` Parquet. Detail in `runbook.md` §2.
- **Ingestion:** see `runbook.md` §2.

## Board issues (github.com/nkouhdareh/de-capstone-pipeline)
- **Done:** #1 repo/env, #2 first API call, #3 bronze ingestion, #8 ADR-001
- **Code complete (Silver, full run pending):** #4 dedup, #5 normalisation, #6 validation/quarantine
- **Next:** load Silver → Snowflake + dbt marts; #7 dbt tests on staging

## Rules / reminders
- **Data never in git** (lives on D: drive). Secrets in `.env` only.
- Small, frequent commits; conventional prefixes. Write **ADRs at decision time**.
- ~100 build hours total; "clean data" was the Week-1 milestone.
