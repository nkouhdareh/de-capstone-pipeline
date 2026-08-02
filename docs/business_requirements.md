# Business Requirements Document

## Pharmacovigilance Signal Detection & Label Intelligence Platform

| | |
|---|---|
| **Author** | Nastaran Kouhdareh |
| **Project** | Data Engineering Capstone — Spiced Academy / neue fische |
| **Version** | 0.1 — draft for instructor review |
| **Date** | 3 August 2026 |
| **Delivery window** | 3 – 24 August 2026 |
| **Status** | ⬜ Awaiting Instructor / TA approval (Gate 1 of 3) |

> **Scope of this document.** This covers *business* requirements only.
> Technical requirements and architecture are deliberately deferred to
> Gates 2 and 3, per the capstone process. Tooling is mentioned only where a
> business requirement depends on it.

---

## 1. Executive summary

Pharmaceutical companies are legally required to monitor adverse events reported
against their products, detect emerging safety signals, and determine whether each
signal is already described in the approved product label. Regulators impose
reporting deadlines on this work.

The source data is public. The US FDA publishes over 20 million adverse event
reports through the FDA Adverse Event Reporting System (FAERS) and the full text
of every approved drug label, both free via the openFDA API. In practice this data
is difficult to use: drug names are recorded as free text with no controlled
vocabulary, the same case is submitted repeatedly in amended versions, and the
decisive information — whether an event is already labelled — exists only as prose
inside label documents.

This project delivers an automated data platform that ingests FAERS reports and
drug labels, resolves them into a consistent analytical model, computes standard
disproportionality metrics used in signal detection, and provides a retrieval
interface over label text so an analyst can determine labelled status without
reading the document.

---

## 2. Business context and problem statement

### 2.1 The workflow today

A pharmacovigilance team performs a recurring cycle:

1. **Collect** adverse event reports for products in their portfolio
2. **Detect** statistically disproportionate drug–event combinations
3. **Triage** each candidate signal by seriousness and case volume
4. **Assess labelledness** — is this reaction already described in the label?
5. **Escalate** unlabelled serious signals for regulatory action

### 2.2 Why it is painful

| Problem | Consequence |
|---|---|
| Drug names in FAERS are free text (`TYLENOL`, `acetaminophen`, `PARACETAMOL`, plus misspellings) | Case counts for the same substance are fragmented, so signals are missed or understated |
| The same safety case is resubmitted as amended versions | Naive counting inflates case volumes and produces false signals |
| Labelled status lives in prose inside label documents | Step 4 is manual document reading, and it is the slowest step in the cycle |
| No integrated view across reports, products and labels | Analysts join data by hand in spreadsheets |

### 2.3 Problem statement

> Safety analysts cannot reliably quantify adverse event signals or determine
> labelled status from public FAERS and label data, because drug identifiers are
> unnormalised, cases are duplicated, and labelling information is only available
> as unstructured text.

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

## 4. Business objectives

| ID | Objective | Measure of success |
|---|---|---|
| **BO-1** | Produce a single trustworthy view of adverse event reports | One row per unique safety case; duplicates removed and counted |
| **BO-2** | Attribute reports to consistent product identities | Free-text drug names resolved to a normalised drug dimension |
| **BO-3** | Quantify potential safety signals using accepted methods | PRR and ROR computed per drug–event pair with case counts |
| **BO-4** | Reduce labelled-status assessment from document reading to a question | Analyst receives a cited answer from label text |
| **BO-5** | Deliver refreshed data without manual intervention | Scheduled pipeline runs unattended and reports its own status |

---

## 5. Business requirements

### 5.1 Data and information

| ID | Requirement | Priority |
|---|---|---|
| BR-01 | The platform shall ingest adverse event reports from FAERS via the openFDA API | Must |
| BR-02 | The platform shall ingest drug label documents from openFDA | Must |
| BR-03 | The platform shall ingest the National Drug Code directory as the reference product list | Must |
| BR-04 | The platform shall retain unmodified source records to allow reprocessing | Must |
| BR-05 | The platform shall identify and remove duplicate safety cases, retaining the most recent version | Must |
| BR-06 | The platform shall resolve free-text drug names to normalised products, and record unresolved names rather than discarding them | Must |
| BR-07 | The platform shall preserve the distinction between suspect and concomitant drugs on each report | Must |
| BR-08 | The platform shall load only new or changed records on each scheduled run | Must |
| BR-09 | The platform shall support reprocessing of a specified historical period | Must |

### 5.2 Analysis and serving

| ID | Requirement | Priority |
|---|---|---|
| BR-10 | The platform shall compute PRR and ROR for each drug–event pair | Must |
| BR-11 | The platform shall flag pairs meeting a documented signal threshold | Must |
| BR-12 | The platform shall classify reports by seriousness outcome (death, hospitalisation, life-threatening, disability) | Must |
| BR-13 | The platform shall allow analysis by reporter type and reporting country | Should |
| BR-14 | The platform shall express metric definitions once, so all consumers see identical figures | Must |
| BR-15 | The platform shall present results through a user interface requiring no SQL | Must |
| BR-16 | The platform shall answer natural-language questions about label content, citing the source label section | Should |
| BR-17 | The platform shall state when a question falls outside its indexed scope rather than answering speculatively | Must (if BR-16 delivered) |

### 5.3 Operations

| ID | Requirement | Priority |
|---|---|---|
| BR-18 | The pipeline shall run on a defined schedule without manual steps | Must |
| BR-19 | The pipeline shall fail safely and be re-runnable without duplicating data | Must |
| BR-20 | The pipeline shall tolerate malformed records, missing fields and source schema changes | Must |
| BR-21 | The pipeline shall record run status, row counts, duration and estimated cost | Must |
| BR-22 | The platform shall document data origin and transformation lineage from source to serving layer | Must |
| BR-23 | Credentials shall never appear in source control, configuration or logs | Must |

---

## 6. Business questions the platform must answer

**Answerable by the analytical model:**

1. Which drug–event pairs show the strongest disproportionality this period?
2. How many unique cases support a given signal, and how many were serious?
3. How has the case volume for a drug–event pair changed over time?
4. Which reactions are most frequently reported for a given active ingredient?
5. Who reports these events — physicians, pharmacists or consumers — and from where?

**Answerable only by retrieval over label text:**

6. Is this reaction already described in the product label, and in which section?
7. What contraindications apply to patients with renal impairment for this drug?
8. Which labels in this drug class mention QT prolongation?
9. What is the labelled adverse-reaction profile for this active ingredient?

Question 6 is the platform's core value: it is the decision point of the
pharmacovigilance triage cycle, and it cannot be expressed as a database query
because the answer exists only as prose.

---

## 7. Scope

### In scope

- FAERS adverse event reports, drug labels and the NDC directory from openFDA
- Deduplication, drug-name normalisation, validation and dimensional modelling
- Disproportionality metrics (PRR, ROR) with documented thresholds
- Scheduled orchestration, error handling, backfill, logging and monitoring
- A dashboard serving layer
- Retrieval over label text with source citation *(extension — see §8)*

### Out of scope

- Causality assessment of any kind
- Clinical or regulatory decision-making
- Non-US regulatory data sources (EudraVigilance, VigiBase)
- Real-time or streaming ingestion — no genuine real-time source exists for this data
- Patient-level or identifiable data
- Predictive modelling of adverse events

---

## 8. Delivery priorities

The retrieval capability (BR-16, BR-17) is an **extension**, not a core
deliverable. It will be built only after all Must requirements in §5.1–5.3 are
satisfied, and work on it stops on **18 August** regardless of state. If it is not
delivered, that will be recorded as a deliberate scope decision.

| Phase | Contents | Target |
|---|---|---|
| MVP | All Must requirements except BR-16/17 | 14 August |
| Extension | BR-16, BR-17 | 18 August (hard stop) |
| Hardening | Documentation, ADRs, runbook, demo | 21 August |

---

## 9. Success criteria

The project is successful when all of the following hold:

1. The pipeline runs end-to-end on a schedule from a single command, unattended
2. Duplicate cases are removed, and the number removed is reported
3. Drug-name resolution rate is measured and stated
4. PRR and ROR values are reproducible and their definitions documented in one place
5. Data quality tests run automatically and fail the pipeline when violated
6. A failed run can be re-run without creating duplicate or partial data
7. A historical period can be reprocessed on demand
8. Estimated cost per run is recorded and published
9. `README.md`, `architecture.md`, `runbook.md` and ADRs are complete
10. Every significant technical decision has a recorded rationale, including rejected alternatives

---

## 10. Data sources and licensing

| Source | Content | Access | Licence |
|---|---|---|---|
| openFDA `drug/event` | FAERS adverse event reports, 20M+ | REST API, free key | US Government public domain |
| openFDA `drug/label` | Full approved label text | REST API, free key | US Government public domain |
| openFDA `drug/ndc` | National Drug Code product directory | REST API, free key | US Government public domain |

No registration gate, no credentialing, no approval wait. Data may be published,
demonstrated publicly and committed as samples.

**MIMIC-IV was evaluated and rejected**: credentialing carries schedule risk on a
three-week timeline, and its data use agreement prohibits publishing samples and
prohibits sending text to third-party LLM services.

---

## 11. Data limitations and responsible use

These limitations must be stated in the user interface and the README. They are a
requirement, not a disclaimer.

- FAERS is a **spontaneous reporting** system. Reports are submitted voluntarily
  and are neither verified nor validated by the FDA.
- A report **does not establish that the drug caused the event**.
- There is **no denominator** — exposure is unknown, so incidence and risk cannot
  be calculated.
- Reporting is subject to bias: media attention, litigation and market age all
  distort volumes.
- Disproportionality metrics identify **statistical signals for review only**.
  They are not measures of risk.
- Reaction terms originate from MedDRA. The terms as published in FDA data may be
  used; the MedDRA dictionary itself is licensed and will not be redistributed.

---

## 12. Assumptions

| ID | Assumption | If false |
|---|---|---|
| A-1 | openFDA remains available with current rate limits | Fall back to quarterly bulk downloads |
| A-2 | A free API key raises limits to 240 requests/min | Extend ingestion window; reduce scope |
| A-3 | Snowflake and dbt trial accounts remain active for the project duration | Substitute Postgres; ADR already drafted |
| A-4 | AWS credits remain sufficient (~$182 available) | Run fully locally |
| A-5 | Public data means no PII handling obligations | Re-scope governance requirements |

---

## 13. Constraints

- **Timeline:** 3–24 August 2026; approximately 100 effective build hours
- **Milestone:** data ingested and cleaned by **7 August** (instructor requirement)
- **Budget:** target under $10; hard ceiling $182 in AWS credits
- **Team:** one engineer
- **Experience:** retrieval systems are new to me — hence their treatment as an extension

---

## 14. Risks

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| Drug-name normalisation proves harder than expected | High | **High** | Time-box to two days; accept a measured partial resolution rate and report it rather than chasing completeness |
| API rate limits slow the backfill | Medium | Medium | Request key immediately; use quarterly bulk files for history, API for increments |
| Retrieval extension overruns | Medium | Medium | Hard stop 18 August; architecturally separable |
| Trial account expires mid-project | High | Low | Postgres fallback identified in advance |
| Scope creep across three data sources | High | Medium | `drug/label` is droppable; `drug/event` + `drug/ndc` alone satisfy the MVP |
| Unexpected cloud cost | Medium | Low | AWS Budget alert at €5 before any cloud code is written |

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
| **Labelled / unlabelled** | Whether a reaction is already described in the approved product label. Unlabelled serious events carry expedited reporting obligations |
| **Suspect vs concomitant drug** | Whether the reporter identified the drug as a suspected cause, or merely as also being taken |
| **Seriousness** | Regulatory classification: death, life-threatening, hospitalisation, disability, congenital anomaly, or other medically significant |
| **NDC** | National Drug Code — the FDA's product identifier |
| **MedDRA** | Medical Dictionary for Regulatory Activities — the controlled vocabulary used to code reactions |

---

## 16. Approval

| Gate | Approver | Date | Status |
|---|---|---|---|
| Business requirements *(this document)* | Instructor / TA | | ⬜ |
| Technical requirements | Instructor / TA | | ⬜ |
| Architecture | Instructor / TA | | ⬜ |

### Questions for this review

1. My data is inherently batch. Is a contrived streaming layer preferable to an
   honest batch pipeline with a documented justification?
2. Cloud, local or hybrid — what have students realistically completed in three weeks?
3. Is the scope correct: full dataset in the warehouse, one product area indexed
   for retrieval?
4. Is treating the retrieval layer as a droppable extension with a hard cutoff
   acceptable, or would you rather I omit it entirely and deepen the pipeline?
