# Project Progress & Handoff

*A running snapshot of where the project is, so a fresh session (or a teammate) can pick up fast.*
**Status as of:** Silver layer built & verified — issues #4/#5/#6 done (Week 2). 45.0M clean atomic rows.

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
- **Done:** #1 repo/env, #2 first API call, #3 bronze ingestion, #8 ADR-001, **#4 dedup · #5 normalisation · #6 validation/quarantine** (Silver built & verified)
- **Next:** load Silver → Snowflake + dbt marts (incl. `int_drug_resolution` NDC join); #7 dbt tests on staging

## Rules / reminders
- **Data never in git** (lives on D: drive). Secrets in `.env` only.
- Small, frequent commits; conventional prefixes. Write **ADRs at decision time**.
- ~100 build hours total; "clean data" was the Week-1 milestone.
