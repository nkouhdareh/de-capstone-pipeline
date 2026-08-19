# Business Requirements Document

## Drug Safety Signal Detection — openFDA pharmacovigilance platform

| | |
|---|---|
| **Author** | Nastaran Kouhdareh |
| **Project** | Data Engineering Capstone — Spiced Academy / neue fische |
| **Version** | **1.0 — final, reconciled against what was delivered** |
| **Originally drafted** | 3 August 2026 (v0.1, Gate 1) |
| **This revision** | 19 August 2026 |
| **Delivery window** | 3 – 24 August 2026 |

> **What changed from v0.1.** The requirements themselves are unchanged — they were
> agreed at Gate 1 and are reproduced here with their original BR numbers intact. What is
> new is a **delivery status against every requirement**, an honest closing of the
> retrieval extension, and outcomes recorded against the assumptions and risks. Nothing
> that was agreed has been quietly removed; where a requirement was not met, it says so.

---

## 1. Executive summary

Pharmaceutical companies are legally required to monitor adverse events reported against
their products, detect emerging safety signals, and determine whether each signal is
already described in the approved product label. Regulators impose reporting deadlines on
this work.

The source data is public. The US FDA publishes adverse event reports through the FDA
Adverse Event Reporting System (FAERS) — more than 20 million in total — along with the
full text of every approved drug label, both free via the openFDA API. In practice this
data is difficult to use: drug names are recorded as free text with no controlled
vocabulary, the same case is submitted repeatedly in amended versions, and the decisive
information — whether an event is already labelled — exists only as prose inside label
documents.

**What was delivered.** An automated batch pipeline that ingests FAERS reports and the NDC
product directory, resolves them into a consistent analytical model, and computes the
standard disproportionality metrics used in signal detection, served through a dashboard
hosted inside the warehouse.

A **two-year working window (2023–2024)** was ingested rather than the full history:
**2,687,675 reports**, flattened and cleaned to **45,030,932 analytical rows** covering
**1,240,645 drug–reaction pairs**. The retrieval interface over label text was scoped from
the outset as a droppable extension and **was not built** — see §8.

---

## 2. Business context and problem statement

### 2.1 The workflow today

A pharmacovigilance team performs a recurring cycle:

1. **Collect** adverse event reports for products in their portfolio
2. **Detect** statistically disproportionate drug–event combinations
3. **Triage** each candidate signal by seriousness and case volume
4. **Assess labelledness** — is this reaction already described in the label?
5. **Escalate** unlabelled serious signals for regulatory action

**This platform supports steps 1–3.** Step 4 remains manual; see §8.

### 2.2 Why it is painful

| Problem | Consequence | How the platform addresses it |
|---|---|---|
| Drug names in FAERS are free text (`TYLENOL`, `acetaminophen`, `PARACETAMOL`, plus misspellings) | Case counts for the same substance are fragmented, so signals are missed or understated | Tiered exact matching against the NDC directory; **86.7 % of rows** resolved, unresolved names retained and counted, never guessed |
| The same safety case is resubmitted as amended versions | Naive counting inflates case volumes and produces false signals | Only the highest report version per case is retained; deduplication at the atomic grain removed **51.8 %** of flattened rows |
| Labelled status lives in prose inside label documents | Step 4 is manual document reading, and it is the slowest step in the cycle | **Not addressed.** The label corpus is ingested but not indexed — §8 |
| No integrated view across reports, products and labels | Analysts join data by hand in spreadsheets | A star schema with four conformed dimensions, served through a dashboard requiring no SQL |

### 2.3 Problem statement

> Safety analysts cannot reliably quantify adverse event signals or determine labelled
> status from public FAERS and label data, because drug identifiers are unnormalised,
> cases are duplicated, and labelling information is only available as unstructured text.

**The first two clauses are solved. The third is not.**

---

## 3. Stakeholders

| Stakeholder | Role | Interest |
|---|---|---|
| **Drug Safety Officer** | **Primary user** | Detect and triage signals; decide what escalates |
| Pharmacovigilance Analyst | Secondary user | Run periodic reviews; compile case series |
| Regulatory Affairs | Consumer | Evidence for label change submissions |
| Data Engineering (me) | Owner | Build, operate and document the platform |
| Instructor / TA | Approver | Assess process, decisions and execution |

---

## 4. Business objectives — outcome

| ID | Objective | Measure of success | Outcome |
|---|---|---|---|
| **BO-1** | Produce a single trustworthy view of adverse event reports | One row per unique safety case; duplicates removed and counted | ✅ **Met.** Grain key unique across all 45,030,932 rows; 48,335,706 duplicates removed and reported per month |
| **BO-2** | Attribute reports to consistent product identities | Free-text drug names resolved to a normalised drug dimension | ✅ **Met.** `dim_drug` holds 4,368 identities; 86.7 % of rows resolved, rate published |
| **BO-3** | Quantify potential safety signals using accepted methods | PRR and ROR computed per drug–event pair with case counts | ✅ **Met.** 1,240,645 pairs scored; 315,270 flagged as candidates |
| **BO-4** | Reduce labelled-status assessment from document reading to a question | Analyst receives a cited answer from label text | ❌ **Not met.** Extension not built — §8, [ADR-015](adr/ADR-015-retrieval-extension-not-built.md) |
| **BO-5** | Deliver refreshed data without manual intervention | Scheduled pipeline runs unattended and reports its own status | ⚠️ **Partially met.** One trigger runs all eight tasks unattended in 3 h 57 m and logs what it produced — but the trigger is manual, not scheduled |

---

## 5. Business requirements — delivery status

Legend: ✅ met · ⚠️ partially met · ❌ not met

### 5.1 Data and information

| ID | Requirement | Priority | Status | Evidence / note |
|---|---|---|---|---|
| BR-01 | Ingest adverse event reports from FAERS via the openFDA API | Must | ✅ | 2,687,675 reports, 2023–2024, date-partitioned |
| BR-02 | Ingest drug label documents from openFDA | Must | ✅ | 261,258 label records in Bronze. **Ingested but not used downstream** — the only consumer would have been the extension |
| BR-03 | Ingest the National Drug Code directory as the reference product list | Must | ✅ | 136,520 products; drives drug resolution |
| BR-04 | Retain unmodified source records to allow reprocessing | Must | ✅ | Bronze is 64 GB of immutable NDJSON, never rewritten. Silver and the warehouse are rebuildable without touching the API |
| BR-05 | Identify and remove duplicate safety cases, retaining the most recent version | Must | ✅ | Highest `safetyreportversion` per case retained; 93,366,638 → 45,030,932 (51.8 % removed), counted per month |
| BR-06 | Resolve free-text drug names to normalised products, recording unresolved names rather than discarding them | Must | ✅ | Tiered exact matching; unresolved keep `drug_key = -1` and are counted. Both rates published: 86.7 % of rows, 10.0 % of distinct signatures |
| BR-07 | Preserve the distinction between suspect and concomitant drugs | Must | ✅ | `drug_characterisation` carried to the fact table and tested against accepted values. Signal metrics count **suspect only** |
| BR-08 | Load only new or changed records on each scheduled run | Must | ❌ | **Not met.** Each run reloads RAW in full via `TRUNCATE` + `COPY`. Silver *is* incremental at the month level via dynamic partition overwrite, but the warehouse load is not. The dataset is a frozen historical snapshot, so nothing new arrives |
| BR-09 | Support reprocessing of a specified historical period | Must | ✅ | `{"months":"2023-01"}` or `{"months":"all"}`; only the named partitions are rewritten |

### 5.2 Analysis and serving

| ID | Requirement | Priority | Status | Evidence / note |
|---|---|---|---|---|
| BR-10 | Compute PRR and ROR for each drug–event pair | Must | ✅ | Plus the ROR confidence-interval lower bound and Yates-corrected χ² |
| BR-11 | Flag pairs meeting a documented signal threshold | Must | ✅ | `is_signal` (a ≥ 3, PRR ≥ 2.0, χ² ≥ 4.0) and `is_signal_strict` (adds ROR-CI > 1.0). Thresholds are dbt variables, documented |
| BR-12 | Classify reports by seriousness outcome | Must | ✅ | Death, hospitalisation, life-threatening, disability, congenital anomaly, other |
| BR-13 | Allow analysis by reporter type and reporting country | Should | ✅ | `dim_reporter`, 726 rows, FK-tested from the fact table |
| BR-14 | Express metric definitions once, so all consumers see identical figures | Must | ✅ | All formulas live in `macros/signal_metrics.sql`. The dashboards compute nothing. Verified: local app, hosted app and warehouse all return PRR 35.94 for clozapine → neutropenia |
| BR-15 | Present results through a user interface requiring no SQL | Must | ✅ | Three dashboards; the hosted one is a URL requiring no local setup |
| BR-16 | Answer natural-language questions about label content, citing the source section | Should | ❌ | **Not delivered** — §8, [ADR-015](adr/ADR-015-retrieval-extension-not-built.md) |
| BR-17 | State when a question falls outside indexed scope rather than answering speculatively | Must (if BR-16 delivered) | ➖ | **Not applicable** — conditional on BR-16 |

### 5.3 Operations

| ID | Requirement | Priority | Status | Evidence / note |
|---|---|---|---|---|
| BR-18 | The pipeline shall run on a defined schedule without manual steps | Must | ⚠️ | **Partially met.** One trigger runs all eight tasks with no further intervention, but `schedule=None` — the trigger is manual. `dim_date` derives itself from the data so a schedule would need no code change. Justified by the frozen snapshot; recorded as a deviation |
| BR-19 | The pipeline shall fail safely and be re-runnable without duplicating data | Must | ✅ | Every task idempotent; a non-zero child exit raises rather than passing silently. Proven by the `aws s3 sync` incident, which was caught by a baseline before it could corrupt anything |
| BR-20 | The pipeline shall tolerate malformed records, missing fields and source schema changes | Must | ⚠️ | Malformed records and missing fields ✅ — 431,760 rows quarantined **with a reason**, never dropped; demographics bucketed as `Unknown`. **Schema-change detection ❌** — not implemented |
| BR-21 | Record run status, row counts, duration and estimated cost | Must | ⚠️ | Status, row counts and duration ✅ via Airflow logs and the `publish_metrics` macro; per-month counts persisted to Parquet. **Structured logging and per-run cost recording ❌** |
| BR-22 | Document data origin and transformation lineage from source to serving layer | Must | ✅ | dbt lineage graph (`dbt docs generate`), `docs/Metadata/` field dictionary and source schemas, and `_run_id` / `_loaded_at` on every Silver row |
| BR-23 | Credentials shall never appear in source control, configuration or logs | Must | ✅ | No Snowflake password exists anywhere (service identity cannot hold one). No AWS key in the repository or GitHub Secrets — CI uses OIDC. Enforced by a CI secret scan **demonstrated turning red in 7 seconds** on a planted credential |

**Summary: 17 met, 4 partially met, 2 not met, 1 not applicable.**

---

## 6. Business questions the platform must answer

**Answerable by the analytical model — all delivered:**

| # | Question | Where it is answered |
|---|---|---|
| 1 | Which drug–event pairs show the strongest disproportionality this period? | `fct_signal_metrics`, monthly grain — dashboard period view |
| 2 | How many unique cases support a given signal, and how many were serious? | `a` shown beside every ratio; seriousness flags on the fact table |
| 3 | How has case volume for a pair changed over time? | 24-month trend chart, case counts and PRR overlaid |
| 4 | Which reactions are most frequently reported for a given active ingredient? | Drug profile view, ranked |
| 5 | Who reports these events, and from where? | `dim_reporter` — 726 combinations of qualification and country |

**Answerable only by retrieval over label text — none delivered** (questions 6–9). Question 6
*"Is this reaction already described in the product label?"* was identified at Gate 1 as the
platform's highest-value question, and it remains unanswered. That is the honest cost of the
scope decision in §8.

---

## 7. Scope — as delivered

### In scope, and delivered

- FAERS adverse event reports and the NDC directory from openFDA
- Deduplication, drug-name normalisation, validation and dimensional modelling
- Disproportionality metrics (PRR, ROR) with documented thresholds
- Orchestration, error handling, backfill, logging and monitoring
- A dashboard serving layer

### In scope, partially delivered

- **Drug label documents** — ingested (261,258 records) but not modelled or served
- **Scheduling** — the DAG runs unattended from one trigger, but the trigger is manual

### In scope at Gate 1, not delivered

- **Retrieval over label text with source citation** — §8

### Out of scope, and confirmed out of scope

- Causality assessment of any kind
- Clinical or regulatory decision-making
- Non-US regulatory data sources (EudraVigilance, VigiBase)
- Real-time or streaming ingestion — [ADR-007](adr/ADR-007-no-streaming-layer.md)
- Patient-level or identifiable data
- Predictive modelling of adverse events

---

## 8. Delivery priorities — closing the extension

The Gate-1 commitment read:

> The retrieval capability (BR-16, BR-17) is an **extension**, not a core deliverable. It
> will be built only after all Must requirements in §5.1–5.3 are satisfied, and work on it
> stops on **18 August** regardless of state. **If it is not delivered, that will be
> recorded as a deliberate scope decision.**

**This section is that record. The extension was not built.**

| Phase | Contents | Target | Outcome |
|---|---|---|---|
| MVP | All Must requirements except BR-16/17 | 14 August | ✅ Complete 13 August, one day early |
| Extension | BR-16, BR-17 | 18 August (hard stop) | ❌ **Not started.** Stop date honoured |
| Hardening | Documentation, ADRs, runbook, demo | 21 August | ✅ Complete |

**Why.** The days reserved for the extension were consumed by work that was not in the
original plan and turned out to matter more: proving the orchestration at full scale, the
S3 external-stage cutover, migrating Snowflake authentication to key pairs ahead of a
hard vendor deadline on 18 August, hosting the dashboard inside Snowflake, four CI/CD
workflows, and Terraform.

Two of those were not optional. Snowflake deprecated password-only sign-in on
**18 August 2026**, which would have broken four of the eight pipeline tasks. Migrating
was survival, not scope creep.

The alternative — building a minimal retrieval layer in the remaining days — was rejected
because BR-16's value depends on a **measured** answer quality, and an unmeasured
retrieval demo built during a change freeze is worth less than an honest absence.

Full reasoning, including what would be built first if the project resumed:
[ADR-015](adr/ADR-015-retrieval-extension-not-built.md).

---

## 9. Success criteria — assessment

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | The pipeline runs end-to-end on a schedule from a single command, unattended | ⚠️ | Single trigger ✅, unattended ✅, **on a schedule ❌** — manual trigger |
| 2 | Duplicate cases are removed, and the number removed is reported | ✅ | 48,335,706 removed (51.8 %), persisted per month |
| 3 | Drug-name resolution rate is measured and stated | ✅ | 86.7 % of rows; 10.0 % of distinct signatures. Both published |
| 4 | PRR and ROR values are reproducible and their definitions documented in one place | ✅ | One macro; verified identical across warehouse, local app and hosted app |
| 5 | Data quality tests run automatically and fail the pipeline when violated | ✅ | 42 dbt tests as a DAG task; failure fails the run and leaves marts at their previous state |
| 6 | A failed run can be re-run without creating duplicate or partial data | ✅ | Idempotent throughout; the one gap (`aws s3 sync`) was found and fixed |
| 7 | A historical period can be reprocessed on demand | ✅ | `--months` parameter, dynamic partition overwrite |
| 8 | Estimated cost per run is recorded and published | ⚠️ | Cost **analysed** and published for the project as a whole ($0.25 paid, $42 of trial credit). **Not recorded per run** |
| 9 | `README.md`, `architecture.md`, `runbook.md` and ADRs are complete | ✅ | All four rewritten as-built; 15 ADRs |
| 10 | Every significant technical decision has a recorded rationale, including rejected alternatives | ✅ | 13 written ADRs, each with an options table and stated trade-offs |

**8 met, 2 partially met, 0 unmet.** The two partial items — scheduling and per-run cost —
are both recorded as deviations rather than left implicit.

---

## 10. Data sources and licensing

| Source | Content | Used | Licence |
|---|---|---|---|
| openFDA `drug/event` | FAERS adverse event reports | **2,687,675** (2023–2024) of 20M+ available | US Government public domain |
| openFDA `drug/label` | Full approved label text | 261,258 ingested; **not used downstream** | US Government public domain |
| openFDA `drug/ndc` | National Drug Code product directory | 136,520 | US Government public domain |

No registration gate, no credentialing, no approval wait. Data may be published,
demonstrated publicly and committed as samples.

**MIMIC-IV was evaluated and rejected**: credentialing carries schedule risk on a
three-week timeline, and its data use agreement prohibits publishing samples and prohibits
sending text to third-party LLM services. See [ADR-001](adr/ADR-001-domain-and-data-source.md).

---

## 11. Data limitations and responsible use

These limitations are stated in the user interface and the README. They are a
requirement, not a disclaimer.

- FAERS is a **spontaneous reporting** system. Reports are submitted voluntarily and are
  neither verified nor validated by the FDA.
- A report **does not establish that the drug caused the event**.
- There is **no denominator** — exposure is unknown, so incidence and risk cannot be
  calculated.
- Reporting is subject to bias: media attention, litigation and market age all distort
  volumes.
- Disproportionality metrics identify **statistical signals for review only**. They are
  not measures of risk.
- Reaction terms originate from MedDRA. The terms as published in FDA data may be used;
  the MedDRA dictionary itself is licensed and is not redistributed.

**Confirmed by the delivered output.** Ranking the 1,240,645 scored pairs by raw PRR puts
artifacts at the top — confounding by indication (nitrates → cardiospasm), device and
product-use events (copper → foreign body in reproductive tract), and litigation-driven
reporting (talc → mesothelioma) — alongside genuine findings such as pentosan polysulfate
→ pigmentary maculopathy. A stricter statistical threshold does not fix this: the strict
flag prunes only **269 of 315,270** pairs.

The platform therefore presents a **ranked candidate list with the supporting counts
shown**, for expert triage. It does not present a binary verdict. This was a design
consequence of the limitation, not an afterthought.

---

## 12. Assumptions — outcome

| ID | Assumption | Held? | What happened |
|---|---|---|---|
| A-1 | openFDA remains available with current rate limits | ✅ | No availability problems. Two days needed re-fetching after individual page failures |
| A-2 | A free API key raises limits to 240 requests/min | ✅ | Key obtained and used throughout |
| A-3 | Snowflake and dbt trial accounts remain active for the project duration | ⚠️ | Active throughout — but Snowflake **deprecated password-only sign-in on 18 August**, mid-project. Not an expiry, but a breaking change the assumption did not anticipate. Resolved by migrating to key-pair auth ([ADR-012](adr/ADR-012-snowflake-key-pair-service-identity.md)) |
| A-4 | AWS credits remain sufficient (~$182 available) | ✅ | **$0.25 actually spent.** The credits were never materially used |
| A-5 | Public data means no PII handling obligations | ✅ | Confirmed. Patient age banded rather than stored exactly, as a defensive measure |

---

## 13. Constraints — outcome

| Constraint | Stated at Gate 1 | Actual |
|---|---|---|
| Timeline | 3–24 August 2026, ~100 effective build hours | Build 2–19 August; 88 commits |
| Milestone | Data ingested and cleaned by **7 August** | ✅ Silver verified **6 August**, one day early |
| Budget | Target under $10; ceiling $182 in AWS credits | ✅ **$0.25 paid**, plus $42 of a $400 Snowflake trial. Under the money target; the trial consumption is stated openly |
| Team | One engineer | Unchanged |
| Experience | Retrieval systems new to me — hence treatment as an extension | The constraint held. The extension was dropped ([ADR-015](adr/ADR-015-retrieval-extension-not-built.md)) |

---

## 14. Risks — outcome

| Risk | Predicted | What actually happened |
|---|---|---|
| Drug-name normalisation proves harder than expected | High impact, **high** likelihood | **Materialised as predicted.** Time-boxed and resolved with tiered exact matching and a published partial rate. A later audit found the true limit is *interpretation*, not name resolution — which retrospectively validated not spending more time on it ([ADR-005](adr/ADR-005-drug-name-resolution-tiers.md)) |
| API rate limits slow the backfill | Medium / medium | **Did not materialise.** Day-partitioned ingestion and bulk files for the reference data were sufficient |
| Retrieval extension overruns | Medium / medium | **Avoided by not starting it.** The hard stop worked exactly as designed |
| Trial account expires mid-project | High / low | **Did not materialise** — but a different vendor change did, and cost two days (A-3) |
| Scope creep across three data sources | High / medium | **Partially materialised.** `drug/label` was ingested and then never used, which is ingestion effort spent for no delivered value |
| Unexpected cloud cost | Medium / low | **Did not materialise.** $0.25 total |

**The risk that was not on the register** — and the one that produced the most instructive
failure — was that a step which is individually correct can make the whole chain wrong.
`aws s3 sync` without `--delete` accumulated files, and an unfixed load would have inserted
**46,580,195** rows instead of 45,030,932, silently corrupting every ratio. It was caught
by a baseline captured on purpose before a destructive run.

---

## 15. Glossary

| Term | Definition |
|---|---|
| **FAERS** | FDA Adverse Event Reporting System — the FDA's database of spontaneously reported adverse events |
| **Adverse event** | Any untoward medical occurrence in a patient administered a medicinal product, whether or not related to it |
| **Signal** | Information suggesting a new potentially causal association, or a new aspect of a known association, warranting further investigation |
| **Pharmacovigilance** | The science and activities relating to the detection, assessment, understanding and prevention of adverse effects |
| **PRR** | Proportional Reporting Ratio — how much more frequently an event is reported for one drug than for all other drugs |
| **ROR** | Reporting Odds Ratio — the odds of an event being reported for one drug versus all other drugs |
| **ROR-CI lower** | The lower bound of the 95 % confidence interval on ROR — the pessimistic reading of the same evidence |
| **Labelled / unlabelled** | Whether a reaction is already described in the approved product label. Unlabelled serious events carry expedited reporting obligations |
| **Suspect vs concomitant drug** | Whether the reporter identified the drug as a suspected cause, or merely as also being taken. Signal metrics count suspect drugs only |
| **Seriousness** | Regulatory classification: death, life-threatening, hospitalisation, disability, congenital anomaly, or other medically significant |
| **NDC** | National Drug Code — the FDA's product identifier |
| **MedDRA** | Medical Dictionary for Regulatory Activities — the controlled vocabulary used to code reactions |
| **Atomic grain** | One row per safety case × resolved drug × drug characterisation × reaction — the level at which this platform counts |

---

## 16. Gate review record

| Gate | Document | Approver | Date | Status |
|---|---|---|---|---|
| 1 — Business requirements | *this document* | Instructor / TA | | ⬜ |
| 2 — Technical requirements | `technical_requirements.md` | Instructor / TA | | ⬜ |
| 3 — Architecture | `architecture.md` | Instructor / TA | | ⬜ |

> **To be completed by the instructor / TA.** The gate documents were reviewed in the
> scheduled coach meetings during the delivery window; the sign-off cells above are left
> for the approver to fill rather than being self-certified.

### How the Gate-1 review questions were resolved

| Question raised at Gate 1 | Resolution |
|---|---|
| *"My data is inherently batch. Is a contrived streaming layer preferable to an honest batch pipeline with a documented justification?"* | **Batch, documented.** No streaming layer was built. FAERS has no real-time feed, and a synthetic stream would have added risk without information — [ADR-007](adr/ADR-007-no-streaming-layer.md) |
| *"Cloud, local or hybrid — what have students realistically completed in three weeks?"* | **Hybrid.** Bronze (64 GB) and Spark stay local; only ~8 GB of Silver plus the warehouse are in the cloud. Total real spend $0.25 — [ADR-009](adr/ADR-009-hybrid-deployment-bronze-local.md) |
| *"Is the scope correct: full dataset in the warehouse, one product area indexed for retrieval?"* | **Half correct.** A two-year window (not the full history) went into the warehouse at full depth; no product area was indexed, because the retrieval extension was dropped — [ADR-015](adr/ADR-015-retrieval-extension-not-built.md) |
| *"Is treating the retrieval layer as a droppable extension with a hard cutoff acceptable?"* | **The mechanism worked.** The hard stop was honoured, the core was never destabilised, and the decision is recorded rather than silent — §8 |
