# Project Progress & Handoff

*A running snapshot of where the project is, so a fresh session or a teammate can pick it
up fast.*

| | |
|---|---|
| **Status** | ✅ **Complete.** MVP delivered end to end, run at full scale under orchestration, gated by CI/CD, and frozen |
| **Build window** | 2 – 19 August 2026 · 88 commits |
| **Presentation** | 24 August 2026 |
| **Last updated** | 19 August 2026 |

> **A note on dates.** Earlier revisions of this document labelled phases "Week 2" … "Week 5".
> Those were **planned work-phase numbers**, not calendar weeks — five planned phases were
> delivered in twelve calendar days, and the numbering was abandoned once CI/CD began. This
> revision uses **actual dates** throughout, which are verifiable against the git history.

---

## 1. What this project is

A **Drug Safety Signal Pipeline** (pharmacovigilance). A **batch ELT** pipeline over openFDA
drug-safety data into an **OLAP** warehouse, computing disproportionality signals (PRR/ROR)
for a drug-safety analyst, served through a dashboard. Health domain.

Full business case: `business_requirements.md` · Architecture: `architecture.md` ·
Operations: `runbook.md` · Decisions: `adr/`

---

## 2. Final state — the numbers

| | |
|---|---|
| FAERS reports ingested (2023–2024) | **2,687,675** |
| Drug labels ingested *(not used downstream)* | 261,258 |
| NDC products ingested | 136,520 |
| Bronze on local disk | **64 GB**, immutable NDJSON |
| Flattened atomic rows | 93,366,638 |
| **Clean Silver rows** | **45,030,932** (51.8 % deduplicated) |
| Quarantined, not dropped | 431,760 |
| Null reactions in Silver | **0** |
| S3 (protected fallback) | 486 objects / 3,913,635,942 bytes |
| S3 (written by the pipeline) | 486 objects / 3,913,633,244 bytes |
| dbt models | **10** |
| dbt tests | **42 passing** · `dbt build` → **PASS=53, WARN=0, ERROR=0** |
| Python unit tests | **21 passing** |
| `int_drug_resolution` signatures | 84,039 |
| Row-level drug resolution | **86.7 %** · signature-level 10.0 % |
| `dim_drug` / `dim_reaction` / `dim_reporter` / `dim_date` | 4,368 / 18,057 / 726 / 731 |
| `fct_report_drug_reaction` | 45,030,932 |
| `fct_signal_metrics` (monthly grain) | 5,069,399 |
| `sem_signal_metrics` (all-time pairs) | 1,240,645 |
| Candidate signals | **315,270** (25.4 % of pairs) |
| Full pipeline, one trigger | **8 tasks, 3 h 57 m 23 s, all green** |
| CI/CD | 4 workflows, 8 checks |
| Credentials in the repository | **none** |
| Money actually paid | **$0.25** + $42 of a $400 Snowflake trial |

**The acceptance signal:** **clozapine → neutropenia · PRR 35.94 · ROR 46.76 ·
ROR-CI 45.21 · χ² 142,896 · 5,571 cases**, present in all 24 months, monthly counts summing
back to 5,571. Unchanged through the S3 cutover, the key-pair migration and the dashboard
rebuilds — which is what makes it a useful correctness check rather than a headline.

---

## 3. Stack

| Layer | Choice |
|---|---|
| Ingestion | Python (`requests`), date-windowed |
| Raw storage (Bronze) | Local disk, immutable NDJSON — [ADR-009](adr/ADR-009-hybrid-deployment-bronze-local.md) |
| Cleaning (Silver) | **PySpark** in Docker — [ADR-004](adr/ADR-004-dbt-and-spark-transformation.md) |
| Object storage | AWS S3, `eu-central-1` — [ADR-011](adr/ADR-011-s3-external-stages.md) |
| Warehouse | **Snowflake** — [ADR-002](adr/ADR-002-warehouse-snowflake.md) |
| Transform | **dbt** (`dbt-snowflake` 1.12.0) |
| Orchestration | **Airflow 2.10.5** in Docker, 3 stacks / 8 containers — [ADR-010](adr/ADR-010-airflow-triggers-containers.md) |
| Serving | **Streamlit**, hosted inside Snowflake |
| CI/CD | GitHub Actions — [ADR-013](adr/ADR-013-separate-ci-identity.md) |
| IaC | Terraform, CI IAM role only — [ADR-014](adr/ADR-014-terraform-ci-role-only.md) |

---

## 4. Build log

### 2 – 3 August — foundations and ingestion

- Repo, virtual environment, `.env`, private GitHub repo, project board.
- **ADR-001** (domain = openFDA drug safety), **ADR-002** (Snowflake), **ADR-004** (dbt +
  PySpark) written at decision time.
- Ingestion scripts: `ingest_drug_event.py` (date-windowed), `ingest_drug_label.py` and
  `ingest_drug_ndc.py` (bulk index), `backfill_days.py`.
- Metadata catalogue: `docs/Metadata/` — `metadata.md`, `field_dictionary.md`,
  `drug_event_schema.md`, plus the openFDA field specifications.
- **Bronze verified:** 2,687,675 reports · 261,258 labels · 136,520 NDC products.

### 4 – 6 August — exploration and the Silver layer

Spark + Jupyter environment, then `notebooks/01_explore_drug_event.ipynb` across all five
data-quality dimensions.

**Findings that drove the cleaning rules:**

| Dimension | Result | Action taken |
|---|---|---|
| Uniqueness | 0 duplicate `safetyreportid` | Deduplicate at the *atomic* grain instead |
| Completeness | Key fields 100 %; demographics partial (age 44 %, sex 17 %, country 11 %) | Bucket missing demographics as `Unknown` |
| Consistency | Coded fields valid **except 18 rogue `drugcharacterization`** (codes 4/5) | Quarantine anything outside {1,2,3} |
| Drug names | 97,789 distinct; ~83 % carry `openfda.generic_name` | Tiered normalisation, unresolved retained and flagged |
| Fan-out / skew | ~3.9 drugs and ~3.0 reactions per report; **max 4,113 drugs / 518 reactions** | Repartition before the reaction explode; process month by month |

**Silver built and verified** (`notebooks/02_build_silver_drug_event.ipynb`, run
`silver_20260805…`) — grain: one row per **(case, resolved drug, characterisation,
reaction)**:

- **Deduplication** — 93,366,638 atomic rows → **45,030,932** (51.8 % removed). The
  duplicates are at the atomic grain: a report repeats the same drug across dosage lines.
  Grain key unique, 45,030,932 / 45,030,932.
- **Normalisation** — **78.46 %** resolved from the report's own
  `generic_name`/`substance_name`; 9.7M rows keep a cleaned raw name, flagged. `rxcui`,
  `product_ndc`, `package_ndc` and `brand_name` carried forward for the dbt NDC join.
- **Validation / quarantine** — 431,760 rejects, never dropped: 431,741 `reaction_pt_null`,
  18 `drugcharacterization_out_of_range`, 1 null. Silver has **0 null reactions**. The
  431,741 come from just **three mega-reports** (23840947 / 23014826 / 22122822,
  `reporttype=1`, 1,000–4,113 drugs) whose reactions are *all* blank — each fully
  quarantined, contributing nothing.
- **Observability** — per-month metrics persisted to `silver/_silver_metrics`.

All Spark spill and cache routed to the data drive, never C:.

### 7 – 9 August — dbt on Snowflake, scaled to 24 months

dbt project in `de_capstone/` with its own `.venv-dbt`. Snowflake: role
`DE_CAPSTONE_DBT_ROLE`, warehouse `DE_CAPSTONE_WH`, schemas `RAW` (source) and `DBT_DEV`
(models); credentials read from a git-ignored `.env` via `env_var()`.

- **Loaded all 24 months:** `RAW.SILVER_DRUG_EVENT` = **45,030,932** ·
  `RAW.DRUG_NDC` = 136,520, via `scripts/load_to_snowflake.py` (internal stage → PUT →
  COPY; truncates and removes the stage itself). At this point still a documented deviation
  from TR-09.
- **10 models built:** `stg_drug_event`, `stg_drug_ndc` → `int_drug_resolution`
  (NDC join, `rxcui` → generic → brand → ingredient, **exact-only**; 84,039 signatures) →
  `dim_drug` (4,368; `drug_key = -1` = Unknown), `dim_reaction` (18,057), `dim_reporter`
  (726), `dim_date` (731, derived from the data), `fct_report_drug_reaction` (45,030,932,
  clustered on `receive_date`, all four dimensions FK-tested) → `sem_signal_metrics`
  (all-time view) and `fct_signal_metrics` (monthly table, 5,069,399).
- **42 tests passing** — key uniqueness and non-nullity, FK `relationships`,
  `accepted_values`, row-count plausibility, and the **hand-computed PRR/ROR worked
  example** (TR-38).
- **Results:** row-level resolution **86.7 %** · signature-level **10.0 %** ·
  **315,270 signals / 1,240,645 pairs**. Real signals recovered: clozapine → neutropenia
  (PRR 35.9), Paxlovid → disease recurrence (PRR 228), the opioid dependence cluster.
- **Lineage refinement:** `reporter_key` and `receive_date_key` were first computed inline
  — FK-valid, but leaving `dim_reporter` and `dim_date` unlinked in the DAG. Refactored to
  fetch both via joins so the graph shows the complete star. Keys identical, tests
  unchanged (`docs/assets/dbt-dag-refinement.png`).
- **Three improvements:** monthly-grain `fct_signal_metrics`; `is_signal_strict` adding the
  ROR-CI condition; `dim_date` derived from the data so a future scheduled load extends it
  automatically.

### 9 August — S3 external stage configured

External stages against a private S3 bucket in `eu-central-1` (region verified against
Snowflake's with `CURRENT_REGION()`), via a **storage integration** — no keys stored in
Snowflake. Least-privilege IAM: read-only on the `silver/` and `ndc/` prefixes. Bucket
private, SSE-S3, Block Public Access on.

Validated non-destructively — `LIST` and `SYSTEM$VALIDATE_STORAGE_INTEGRATION` passed,
scratch-table loads clean. **Not yet cut over** at this point.

### 10 – 12 August — Airflow, and the full chain

**Three Docker stacks; Airflow orchestrates, it does not host the tools.** The Airflow
stack (pinned **2.10.5** — `stable` now serves 3.x) triggers `capstone-spark-jupyter` and
`capstone-dbt` over a mounted Docker socket.

- Silver notebook → **`scripts/build_silver.py`**: headless, parameterised
  (`--months 2023-01 | all`), idempotent via dynamic partition overwrite, transformations
  byte-identical to the notebook. Requires `SILVER_OUT`/`QUAR_OUT`/`SILVER_METRICS` with no
  defaults, so it cannot hit production by accident.
- **DAG `pv_pipeline`** — eight tasks. `build_silver` and the dbt tasks share one
  `_exec_in_container()` helper that streams the child's output into the task log and
  **raises on a non-zero exit**, so a Spark OOM fails the task instead of passing silently.
- **Ingest tasks are guarded** — they skip when Bronze is present.
- **dbt runs in its own container.** Installing it into the Airflow image via
  `_PIP_ADDITIONAL_REQUIREMENTS` **crash-looped the Celery worker with no traceback**:
  dbt-core 1.12 needs `click>=8.3`, `cryptography>=46` and `protobuf>=6`, all above Airflow
  2.10.5's pins — [ADR-010](adr/ADR-010-airflow-triggers-containers.md).
- **`load_raw` runs through dbt, not Airflow's Python** — a dbt macro does the `TRUNCATE` +
  `COPY`, invoked with `dbt run-operation`. **The Snowflake credential therefore exists in
  exactly one place.** A dependency decision that turned into a security property.
- **AWS uploader identity:** IAM user `de-capstone-airflow-uploader` with least-privilege
  write, no `GetObject`, and `DeleteObject` scoped to the pipeline's own prefix only.

**Full 24-month run through Airflow, 11 August:** success in 5 h 00 m, 24/24 months,
`Requested-month Silver rows: 45030932`.

**A bug the gates caught.** Afterwards the S3 prefix held **499 objects, not 486**.
`aws s3 sync` **without `--delete` only adds**, and Spark names output with a per-run UUID,
so an earlier run's 13 files survived alongside the new ones. Unfixed, the next `COPY` would
have loaded **46,580,195** rows — January twice — and silently corrupted every PRR.
*The Spark job was idempotent; the upload task was not. Idempotency is a property of the
whole chain.* Fixed with `sync --delete` plus `DeleteObject` scoped to `silver_pipeline/*`.

**Production S3 cutover, 12 August.** Before touching production, the S3 path was loaded
into a temporary table and compared three ways: total count (45,030,932 = 45,030,932), a
known month, and a **`MINUS` on the grain key = 0**. Identical rows, not merely an identical
count. Then `TRUNCATE` + `COPY` — **`TRUNCATE` is a correctness requirement, not a
preference: Snowflake tracks load metadata per file path, and `TRUNCATE` clears it while
`DELETE` does not.**

**Result:** `dbt build` **PASS=53** · `fct_report_drug_reaction` = 45,030,932 ·
**clozapine → neutropenia PRR 35.94 unchanged from before the cutover.** The internal stages
and `load_to_snowflake.py` remain as the rollback path.

**Full chain in one trigger, 12 August:** all eight tasks green, DAG run `success` in
21 minutes with `{"months":"2023-01"}` — which still loads the full 45,030,932, because
dynamic partition overwrite rewrites only January while the other 23 months stay on disk.

### 13 August — Snowflake key-pair authentication

Snowflake deprecated password-only sign-ins on **18 August 2026**, which would have broken
four of the eight tasks. Migrated ahead of the deadline, and used it to separate the human
identity from the machine one:

| Identity | Purpose | Auth |
|---|---|---|
| `NKOUH` | Snowsight UI, administration | password + TOTP MFA |
| **`DE_CAPSTONE_SVC`** | dbt, Airflow, both loaders, the dashboards | **key-pair only** — `TYPE = SERVICE` users cannot hold a password |

Previously the pipeline authenticated as a user whose default role was `ACCOUNTADMIN`; it
now runs as a service identity limited to `DE_CAPSTONE_DBT_ROLE`, with a 2048-bit RSA key
held **outside the repository**. Both loaders were migrated, including the rollback path —
a rollback is only worth claiming if it still runs.

**There is no Snowflake password anywhere in the project.**
[ADR-012](adr/ADR-012-snowflake-key-pair-service-identity.md)

### 13 - 14 August — Streamlit dashboard · MVP complete

`app/dashboard.py` + `app/db.py`, own venv, port 8501. Reads the marts directly and
**computes nothing** — every metric comes from the dbt macros, so there is exactly one
definition from warehouse to screen.

All-time view over `SEM_SIGNAL_METRICS` (answers in **~3.7 s**, so it was left as a view)
and a period view over `FCT_SIGNAL_METRICS` with a 24-month trend.

**Verified:** clozapine → neutropenia PRR 35.94 / 5,571 cases; 24 months present; monthly
counts summing to 5,571; **2024-12 alone gives PRR 34.78 on 222 cases** — one month
reproducing the all-time ratio within ~3 %, so the signal is not carried by a reporting
spike.

**A defect the data caught.** The first ranked row was `Neutrophil count normal` with a
**blank** PRR: that term is reported *only* with clozapine, so `c = 0` and the ratio is
**undefined**, which the macros correctly return as NULL rather than fabricating infinity —
but Snowflake sorts NULLs **first** under `ORDER BY … DESC`. Fixed with `nulls last`.
*Same shape as the `aws s3 sync` bug: the computation was right and the layer presenting it
was wrong.*

### 15 August — full chain at full scale

An audit found that the 11 August full-scale run had proven *scale* but not the *chain*:
`dbt_build` and `dbt_test` were **orphan tasks** then, defined with no upstream edge, so
Airflow scheduled them in the same tick as the first task — `dbt_build` finished at 11:36
while `upload_s3` did not start until 16:28. They ran correctly, but against data loaded
earlier. `airflow tasks states-for-dag-run` returned **six** task instances, not eight.

*(Related: Airflow 2.x has no per-run DAG versioning, so the UI renders today's graph over
every historical run. The task-instance list is the truth; the graph is not.)*

**The gap was closed the same day.** `{"months":"all"}` through the current eight-task DAG:
**success in 3 h 57 m 23 s, all 8 tasks green, in dependency order**, each starting 1–2
seconds after its predecessor.

| Task | Duration | Result |
|---|---|---|
| `ingest_ndc` · `ingest_faers` | < 1 s each | Skipped — Bronze present |
| `build_silver` | **3 h 47 m 27 s** | 24/24 months · 45,030,932 rows |
| `upload_s3` | 5 m 28 s | 486 objects mirrored with `--delete` |
| `load_raw` | 2 m 43 s | 45,030,932 · 136,520 |
| `dbt_build` | 1 m 08 s | **PASS=53 WARN=0 ERROR=0** |
| `dbt_test` | 9.7 s | **PASS=42** |
| `publish_metrics` | 15.7 s | `fct` 45,030,932 · `dim_drug` 4,368 · `dim_reaction` 18,057 |

**Baselines held exactly:** `silver_pipeline/` 486 / 3,913,633,244 before and after —
Spark renamed all 486 files with new UUIDs, so the sync deleted 486 objects and uploaded
486 replacements with the byte total matching to the byte, confirming Spark's output is
deterministic. `silver/drug_event/` 486 / 3,913,635,942 untouched, proving least-privilege
IAM held through a run that truncated production RAW.

**An hour faster than 11 August, and the reason is documented:** three months took 26–30
minutes each on 11 August and 9.2 minutes each on 15 August. Cause is **CPU contention**,
not data — Spark runs `local[4]` and WSL shares logical processors with Windows. Memory
could not be the cause; `.wslconfig` gives Docker a hard 10 GB reservation.

### 16 August — Streamlit in Snowflake · the dashboard becomes a URL

`app/dashboard_snowflake.py`, deployed as `DE_CAPSTONE.DBT_DEV."Drug Safety Signals"`,
running with the rights of `DE_CAPSTONE_DBT_ROLE`. **The demo no longer needs the laptop.**

Three dashboards, all working: `dashboard.py` (8501, rollback) · `dashboard_enhanced.py`
(8502, local demo) · `dashboard_snowflake.py` (hosted).

One privilege granted — the only account change made for the dashboard:
`grant create streamlit on schema DE_CAPSTONE.DBT_DEV to role DE_CAPSTONE_DBT_ROLE`.
`CREATE STREAMLIT` is a distinct schema privilege and is **not** implied by owning the
schema.

**Verified identical to the local app:** `dim_drug` 4,368 / 4,368 · Silver 45,030,932 ·
pairs 1,240,645 · signals 315,270 · clozapine + Neutropenia 24 months / 5,571 cases.

### 17 - 18 August — CI/CD and Terraform

Four workflows, a Snowflake CI identity that **cannot reach production**, an AWS OIDC role
that **cannot write to S3**, and a Terraform role that **cannot modify itself**.

- **`ci.yml`** — ruff · Python syntax (3.11 + 3.12, via `ast.parse` so the DAG is validated
  without installing Airflow) · secret scan · dbt parse (all 10 models, no warehouse) ·
  pytest (21 tests). **The secret scan was demonstrated refusing a credential:** a
  deliberate `SNOWFLAKE_PASSWORD` on a branch turned it **red in 7 seconds**, naming
  file and line and printing nothing. *A gate you have watched stop something is evidence;
  a green tick is decoration.*
- **`dbt-ci.yml`** — `dbt build --target ci` → **PASS=53 in 1 m 17 s**, under
  `DE_CAPSTONE_CI`: a separate identity with **8 grants**, read-only on RAW, **nothing** on
  `DBT_DEV`. **Proven, not asserted:** `SELECT` on RAW succeeded, `SELECT` on
  `DBT_DEV.DIM_DRUG` failed "not authorized" — [ADR-013](adr/ADR-013-separate-ci-identity.md).
- **`s3-contract.yml`** — verifies the protected prefix holds exactly 486 objects /
  3,913,635,942 bytes, read-only by construction. **Demonstrated refusing a wrong number:**
  temporarily expecting the pipeline prefix's total turned it red **while the object count
  matched**, which is why it asserts both.
- **`terraform.yml`** — plan on PR, manual apply. Two objects, **imported not created**:
  plan `2 to import, 0 to add, 0 to change, 0 to destroy` → apply `2 imported, 0 added,
  0 changed, 0 destroyed` → **second plan `No changes.`** The empty second plan is the one
  that matters — [ADR-014](adr/ADR-014-terraform-ci-role-only.md).

**AWS access uses OIDC only.** The first trust policy used the documented
`repo:owner/repo:*` subject and would have matched **nothing**: GitHub's immutable subject
claims (enforced for repositories created after 15 July 2026 — this one dates from
2 August) embed numeric ids. **IAM validates syntax, not reachability.** The workflow now
decodes the token and prints the subject before assuming.

**One failure worth keeping:** the first `terraform plan` died on
`AccessDenied: iam:ListOpenIDConnectProviders` — a data source resolving the provider *by
URL*, an action AWS does not support resource-level permissions for. The fix was to
**remove the dependency**, not widen the policy.

**A recurring lesson, three times over:** privileges are not implied by ownership —
`CREATE STREAMLIT` not implied by owning the schema; `ACCOUNTADMIN` unable to read `DBT_CI`
because *owning* a role is not being a *member* of it; `CREATE TABLE` needing its own grant.

**pytest TR-37 / TR-38** moved into `tests/` and now run as a CI job: **21 passed**, no
warehouse, no credentials. TR-38's fixture is the **same seed the dbt test asserts on in
Snowflake**, so the Python formulas, the committed fixture and the dbt macro must all agree.
pytest rather than a new dbt test **on purpose** — a new dbt test would have moved the
frozen `42/42` and `PASS=53` figures.

### 19 August — presentation and documentation

Presentation assets built (`docs/capstone_presentation.pptx`, architecture diagram, four
real dashboard captures). **No model, macro, table or figure was changed to produce any of
them.**

Full documentation set rewritten as-built: `README.md`, `architecture.md`, `runbook.md`,
`business_requirements.md`, `technical_requirements.md`, this document, and **10 new ADRs**
covering every major decision taken after 3 August.

---

## 5. Reading the output critically

Ranking all-time signals by PRR shows **most of the largest values are artifacts** — which
is itself a finding worth reporting, not a defect:

| Pattern | Examples | Why it appears |
|---|---|---|
| **Confounding by indication** | felodipine, isosorbide di/mononitrate, digoxin → **cardiospasm** | Nitrates and calcium-channel blockers *treat* oesophageal spasm |
| **Device / product-use events** | copper → *foreign body in reproductive tract*; etonogestrel → *pregnancy with implant contraceptive* | IUDs, implants and pumps generate product reports inside a drug dataset |
| **Genuine label-level signals** | **pentosan polysulfate → pigmentary maculopathy** (led to a real FDA label change); clozapine → neutropenia | The signals the method is meant to find |
| **Reporting / notification bias** | talc → mesothelioma | Litigation-driven reporting inflates the ratio |

A stricter statistical threshold does **not** fix this — `is_signal_strict` prunes only
**269 of 315,270**.

**Nor is the method simply counting volume.** From the same output:
`CLOZAPINE → Death` is **1,848 cases at PRR 1.92 and is not flagged**, and `Off label use`
is 1,294 cases at PRR 0.77, also not flagged — while `Neutropenia`, on far fewer reports as
a share of all drugs, clears every threshold at PRR 35.94.

**Conclusion:** disproportionality is a **screening** tool, not causal evidence. The right
product is a **ranked candidate list with support shown** for a domain expert to triage —
not a binary flag. It also answers the "should I fuzzy-match the drug-name tail?" question:
the top signals are limited by **interpretation**, not by name resolution.

---

## 6. Known limitations

Measured and ranked, worst first.

| Issue | Scale | Cause | Decision |
|---|---|---|---|
| **Non-drug names from salt stripping** | ~350,000 rows | Normalisation removes `SODIUM`/`CALCIUM`/`MAGNESIUM` even when the mineral *is* the drug → `CHLORIDE`, `CARBONATE`, `OXIDE`. Wrongly **merges** distinct substances | One-line fix, but it regenerates every drug key and therefore every documented figure. Measured, not fixed during the freeze |
| **MedDRA term fragmentation** | Clozapine's blood signal split across several preferred terms | One clinical event, several PTs | Needs the licensed MedDRA hierarchy (SMQ) |
| **Duplicate drug spellings** | < 4,000 rows (< 0.01 %) | Typos and spacing variants **in the FDA's own NDC directory** (`ZINC OXIDE` / `ZINCOXIDE`) | Measured, not fixed |
| **Drug resolution tail** | 86.7 % of rows, 10.0 % of signatures | Exact matching only, no fuzzy match | Deliberate — [ADR-005](adr/ADR-005-drug-name-resolution-tiers.md) |
| **Observability gaps** | TR-39/40/41/42/44 | No structured logging, no `pipeline_run_log` table, no per-run cost, no dbt docs in CI | The weakest area against spec; auditable after a run, not monitorable during one |
| **No schedule** | — | `schedule=None` | The dataset is a frozen snapshot; `dim_date` already auto-extends |
| **Branch protection not enforced** | — | GitHub does not apply rulesets to private repos on this plan | *The workflow detects; branch protection enforces.* Detection works and was demonstrated |

**None of these move the headline signals.** Clozapine → neutropenia, Paxlovid → rebound
and the opioid cluster are unaffected.

Full reconciliation of all 67 technical requirements: `technical_requirements.md` §16.

---

## 7. How to run it — quick reference

```bash
cd /d/capstone/de-capstone && docker compose up -d
```

```bash
cd /d/capstone/de-capstone/airflow && docker compose up -d
```

```bash
cd /d/capstone/de-capstone/airflow && docker compose exec airflow-scheduler airflow dags trigger pv_pipeline -c '{"months":"2023-01"}'
```

UI at <http://localhost:8080> (`airflow`/`airflow`). Stop with `docker compose stop` —
**never `down -v`** on the Airflow stack, which deletes its metadata database.

Full operations, expected gates and the failure playbook: `runbook.md`.

---

## 8. Deliberately not done

Recorded as decisions, not omissions.

- **The retrieval / RAG extension over label text** — scoped as droppable at Gate 1 with a
  hard stop of 18 August, which was honoured —
  [ADR-015](adr/ADR-015-retrieval-extension-not-built.md)
- **No streaming layer** — FAERS has no real-time feed —
  [ADR-007](adr/ADR-007-no-streaming-layer.md)
- **No fuzzy drug matching** — [ADR-005](adr/ADR-005-drug-name-resolution-tiers.md)
- **Bronze not in the cloud** — [ADR-009](adr/ADR-009-hybrid-deployment-bronze-local.md)
- **Terraform deliberately narrow** — [ADR-014](adr/ADR-014-terraform-ci-role-only.md)

Optional tidy-ups left open during the freeze: delete the spent `imports.tf`; tighten the
CI role's trust policy to the two exact subjects through Terraform as a reviewed plan;
drop the now-unused `iam:GetOpenIDConnectProvider`; add a second MFA method to `NKOUH`;
trim `build_silver`'s log volume.

---

## 9. Rules and reminders

- **Data never in git** — it lives on the data drive. Secrets in `.env` only, which is
  git-ignored.
- **The frozen figures.** These appear across the documentation, the deck and the tests.
  Anything that changes a dbt model, macro or `dbt_project.yml` moves them:
  45,030,932 rows · 1,240,645 pairs · 315,270 signals · 4,368 drugs · 18,057 reactions ·
  PRR 35.94 · 42 dbt tests · PASS=53 · 486 objects · 3,913,635,942 bytes.
- Small, frequent commits with conventional prefixes. **Write ADRs at decision time** —
  10 of the 13 in this project were not, and say so at the top.
- Work on a branch and merge by pull request, never straight to `main`.
