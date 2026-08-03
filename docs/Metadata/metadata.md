# openFDA Drug Data — Metadata

Metadata ("data about data") for the three openFDA drug datasets used in this project:
**Event**, **Label**, and **NDC**.

The field specifications were grabbed from openFDA's *searchable fields* pages:

- **Event** — <https://open.fda.gov/apis/drug/event/searchable-fields/>
- **Label** — <https://open.fda.gov/apis/drug/label/searchable-fields/>
- **NDC** — <https://open.fda.gov/apis/drug/ndc/searchable-fields/>

The downloaded specs (`fields.yaml`, `fields.pdf`, `*_reference.xlsx`) live in `docs/Metadata/`.

Metadata is organised using the three types from week 12
(`de-week-12-Data-Governance-and-Quality/02_glue_catalog_lineage/01_metadata_types.md`):

| Type | Focus | Examples | Where it comes from here |
|---|---|---|---|
| **Business** | Meaning & context for users | Definitions, business rules, glossary, license | openFDA docs + field descriptions |
| **Technical** | Structure & implementation | Schema, data types, keys, formats, standards | the `fields.yaml` specs |
| **Operational** | Status & performance of data ops | Update frequency, record counts, freshness, load runs | openFDA `meta` section + this project's pipeline |

> **Sourcing note:** the `fields.yaml` specs are **technical** metadata. Business context
> (owner, purpose, license) and operational facts (update frequency, coverage) come from the
> openFDA documentation and each API response's `meta` section — sourced, not guessed.
> Where an exact count or cadence is not stated in the files, this doc points to
> `meta.results.total` / `meta.last_updated` instead of inventing a number.

**Full per-field tables** — every field, description, type, and codes for all three datasets:
see [`field_dictionary.md`](field_dictionary.md), generated directly from the `fields.yaml` specs.

---

## Common to all three datasets

| Aspect | Event | Label | NDC |
|---|---|---|---|
| Source / owner | US FDA (openFDA) | US FDA (openFDA) | US FDA (openFDA) |
| Endpoint | `/drug/event.json` | `/drug/label.json` | `/drug/ndc.json` |
| Format | JSON (`meta` + `results`) | JSON (`meta` + `results`) | JSON (`meta` + `results`) |
| Field data type | every field `string` | free-text `array` + string scalars | every field `string` |
| Dates | strings, `YYYYMMDD` | `effective_time` string `YYYYmmdd` | strings (`date`) |
| License | Public Domain / CC0 | Public Domain / CC0 | Public Domain / CC0 |
| `meta` block | disclaimer · license · last_updated · results{skip,limit,total} | same | same |

**The shared `openfda` block is the set of join keys.** All three datasets carry an `openfda`
object with the same identifier fields — this is how the datasets link together:

| `openfda` field | Meaning | Links |
|---|---|---|
| `spl_id` / `spl_set_id` | Structured Product Label IDs | Event/NDC ↔ Label |
| `product_ndc` | NDC product code | ↔ NDC |
| `rxcui` | RxNorm concept ID | drug identity |
| `unii` | Unique Ingredient Identifier | ingredient identity |
| `substance_name` | Active ingredient(s) | drug-name normalisation |
| `brand_name` / `generic_name` | Product names | drug-name normalisation |
| `pharm_class_epc` / `_moa` / `_cs` / `_pe` | Pharmacologic class | drug classification |

---

## 1. Event — `drug/event` (FAERS)

Source: <https://open.fda.gov/apis/drug/event/searchable-fields/> · ~69 fields in the reference
spreadsheet (plus the shared `openfda` sub-block) · nested JSON.

### Business metadata
| Item | Value |
|---|---|
| What it is | Adverse-event and medication-error reports submitted to the FDA (FAERS) |
| Purpose | Post-market drug-safety surveillance / signal detection |
| Owner / steward | US FDA |
| License | Public Domain / CC0 |
| Key definitions | `safetyreportid` = case report number · `medicinalproduct` = drug name (free text, not normalised) · `reactionmeddrapt` = the reaction as a MedDRA term |
| Business rules (from codes) | `serious`: 1 = serious (death/hospitalisation/etc.), 2 = not · `drugcharacterization`: 1 = Suspect, 2 = Concomitant, 3 = Interacting · `patientsex`: 0 = Unknown, 1 = Male, 2 = Female · `primarysource.qualification`: 1 = Physician … 5 = Consumer · `reactionoutcome`: 1 = Recovered … 5 = Fatal, 6 = Unknown |

### Technical metadata
| Item | Value |
|---|---|
| Structure | Nested JSON: report → `patient` → `drug[]`, `reaction[]`; plus `primarysource`, `sender`, `receiver`, `reportduplicate`, `openfda` |
| Data types | Every field `type: string` (numbers and dates are stored as strings) |
| Key fields | `safetyreportid` (pattern `^[0-9]{7}-[0-9]{1,2}$`) + `safetyreportversion` |
| Dates | `receivedate`, `receiptdate`, `transmissiondate` = `YYYYMMDD`; each has a `*format` field always set to `102` |
| Coded fields | `serious`, 6 × `seriousness*`, `patientsex`, `patientonsetageunit` (800–805), `drugcharacterization`, `actiondrug` (1–6), `drugadministrationroute` (001–067), `reactionoutcome` (1–6), `reporttype` (1–4) |
| Standards | ICH E2B (report structure), MedDRA (reaction terms) |
| Search flag | each field marked `is_exact` (exact-match vs full-text) |
| Stored as (this project) | NDJSON in `bronze/drug_event/receivedate=YYYYMMDD/part-<n>.json` |

### Operational metadata
| Item | Value |
|---|---|
| Update frequency | Quarterly (data may lag ~3 months) |
| Coverage | 2004 → present |
| Record count (`meta.results.total`) | 20,328,575 (all) · **2,687,675** for 2023–2024 |
| Freshness | `meta.last_updated` (e.g. `2026-04-28`) |
| Delivery | REST API (240/min, 120k/day with key) + quarterly bulk download files |
| This project's load | 2023–2024 window · ~2.69M records · date-windowed · ~30–60 min |

---

## 2. Label — `drug/label` (SPL)

Source: <https://open.fda.gov/apis/drug/label/searchable-fields/> · 100+ fields, mostly free text.

### Business metadata
| Item | Value |
|---|---|
| What it is | The official FDA Structured Product Labeling (SPL) — the full text of drug labels (prescription and OTC) |
| Purpose | Authoritative drug-labeling reference. In this project: the retrieval (RAG) corpus for "is this event already labelled?" |
| Owner / steward | US FDA |
| License | Public Domain / CC0 |
| Key sections | `indications_and_usage`, `warnings`, `boxed_warning`, `adverse_reactions`, `contraindications`, `dosage_and_administration`, `drug_interactions`, `pregnancy` |
| Applicability flag | most sections carry an `area` note (e.g. "prescription / OTC") |

### Technical metadata
| Item | Value |
|---|---|
| Structure | Mostly `type: array` of free-text strings — one array per label section; **each section also has a `_table` twin** (HTML-table version) |
| Scalar fields | `id` (document GUID), `set_id` (GUID, stable across versions), `version`, `effective_time` (`YYYYmmdd`), `spl_id` |
| Data types | arrays of `string` (sections) + `string` scalars |
| Key fields | `id` (document version), `set_id` (stable label ID), `spl_set_id` |
| Structured sub-blocks | `openfda` (identifiers), `meta` (disclaimer, license, last_updated, results) |
| Standards | SPL; openfda identifiers (`rxcui`, `unii`, `product_ndc`, `spl_id`) |

### Operational metadata
| Item | Value |
|---|---|
| Update frequency | Periodic — confirm via `meta.last_updated` |
| Record count | Reported in `meta.results.total` (query `/drug/label.json?limit=1`) |
| Delivery | REST API + bulk download files |
| This project's load | Not yet ingested — planned for the RAG extension |

---

## 3. NDC — `drug/ndc` (National Drug Code Directory)

Source: <https://open.fda.gov/apis/drug/ndc/searchable-fields/> · ~30–35 fields · mostly flat.

### Business metadata
| Item | Value |
|---|---|
| What it is | The National Drug Code Directory — the FDA's list of drug products marketed in the US (finished and unfinished) |
| Purpose | Authoritative product / identifier reference. In this project: the lookup used to **normalise free-text drug names** from Event |
| Owner / steward | US FDA |
| License | Public Domain / CC0 |
| Business rules (from codes) | `dea_schedule`: 1–5 → CI, CII, CIII, CIV, CV · `finished`: whether the product is FDA-reviewed · `marketing_category`: NDA / ANDA / BLA / OTC Monograph / Unapproved |

### Technical metadata
| Item | Value |
|---|---|
| Structure | Product-level, mostly flat, with nested `active_ingredients` (name, strength), `packaging` (package_ndc, description, dates, sample), and `openfda` |
| Data types | Every field `type: string` (dates as `date`) |
| Key fields | `product_ndc` (pattern `^[0-9]{5,4}-[0-9]{4,3}$`), `product_id` (NDC + SPL doc id), `spl_id`, `application_number` |
| Coded fields | `dea_schedule` (1–5 → CI–CV) |
| Standards | NDC; openfda identifiers (`rxcui`, `unii`, `spl_id`) |

### Operational metadata
| Item | Value |
|---|---|
| Update frequency | Periodic — confirm via `meta.last_updated` |
| Record count | Reported in `meta.results.total` (query `/drug/ndc.json?limit=1`) |
| Delivery | REST API + bulk download files |
| This project's load | Reference table for drug-name resolution — planned in the silver layer |

---

*Field definitions and codes above are taken directly from the openFDA `fields.yaml` specs in
`docs/Metadata/`. Business context and update cadence are from the openFDA documentation pages
linked at the top and each response's `meta` section.*
