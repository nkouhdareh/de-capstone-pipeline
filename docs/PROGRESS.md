# Project Progress & Handoff

*A running snapshot of where the project is, so a fresh session (or a teammate) can pick up fast.*
**Status as of:** end of data exploration (Week 1).

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

## Key data-quality findings (these drive the cleaning)
| Dimension | Result | Cleaning action |
|---|---|---|
| Uniqueness | 0 duplicate `safetyreportid` (2.69M unique) | #4: report-level dedup already done by openFDA; re-check the (report, drug, reaction) grain after flatten |
| Completeness | key fields 100% (id, dates, drug name, reaction); demographics partial (age 44%, sex 17%, country 11%) | #6: demographics → `Unknown` |
| Consistency | coded fields valid **except 18 rogue `drugcharacterization`** (codes 4/5) | #6: quarantine `drugcharacterization ∉ {1,2,3}` |
| Drug names | 97,789 distinct; ~83% resolved by `openfda.generic_name` | #5: Tier-1 `openfda.generic_name`/`substance_name`; Tier-2 clean/flag the ~17% tail |
| Fan-out / skew | ~3.9 drugs & ~3.0 reactions per report; **max 4,113 drugs / 518 reactions** | Silver: handle mega-report skew when flattening |
| Timeliness | exact 2023–2024 window; batch/quarterly source | note only |

## NEXT: build the Silver layer (issues #4 / #5 / #6) — in PySpark
1. **Flatten** `patient.drug[]` × `patient.reaction[]` → atomic grain **(report, drug, reaction)**. Watch mega-report skew.
2. **Cast** strings → types (dates from `YYYYMMDD`; decode coded fields).
3. **#4 dedup** — report-level already clean; check/handle atomic-grain duplicates.
4. **#5 normalisation** — Tier-1 `openfda.generic_name`/`substance_name` (~83%); Tier-2 clean or flag the rest; **publish the resolution rate**.
5. **#6 validation + quarantine** — enforce `drugcharacterization ∈ {1,2,3}` (18 rogue → quarantine), demographics → `Unknown`; route rejects to a `_quarantine` table.
6. **Write clean silver as Parquet** (permanent, in the data dir — will need the Docker data mount made writable).

## How to run (quick)
- **Explore:** `docker compose up` → http://localhost:8888 → `work/01_explore_drug_event.ipynb`. First cache JSON→Parquet (`/home/jovyan/dq_cache`) for speed. Full detail + failure fixes in `runbook.md`.
- **Ingestion:** see `runbook.md` §2.

## Board issues (github.com/nkouhdareh/de-capstone-pipeline)
- **Done:** #1 repo/env, #2 first API call, #3 bronze ingestion, #8 ADR-001
- **Next (Silver):** #4 dedup, #5 normalisation, #6 validation/quarantine
- **Later:** #7 dbt tests on staging

## Rules / reminders
- **Data never in git** (lives on D: drive). Secrets in `.env` only.
- Small, frequent commits; conventional prefixes. Write **ADRs at decision time**.
- ~100 build hours total; "clean data" was the Week-1 milestone.
