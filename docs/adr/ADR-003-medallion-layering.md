# ADR-003: Medallion layering rather than Data Vault

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-02 |
| **Deciders** | Nastaran Kouhdareh |

## Context

The capstone guide requires data layers organised with an explicit framework, naming
Medallion and Data Vault as examples. The pipeline has **one source system** (openFDA),
three endpoints from that one system, a three-week window, and a single developer. The
raw data is deeply nested JSON that must be flattened before anything can be counted,
and the serving layer is a star schema feeding disproportionality statistics.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **A — Medallion: Bronze → Silver → Marts → Semantic (chosen)** | Each layer has one job and can be rebuilt independently; maps cleanly onto the tools already chosen (Spark writes Silver, dbt builds the rest); immediately legible to a reviewer; the immutable Bronze layer is what makes reprocessing free | Less flexible if many sources with conflicting definitions arrive later; no built-in historisation |
| B — Data Vault (hubs, links, satellites) | Excellent at absorbing multiple sources with conflicting business keys; auditable history built into the model | Adds a whole modelling layer and a join penalty for a problem that does not exist here — there is one source and one business key (`safetyreportid`). Would consume days of the three-week budget on structure rather than on data quality |
| C — No formal layering; load and transform ad hoc | Fastest to start | Nothing is rebuildable in isolation; a transformation bug means re-downloading from the API; ungradable against the guide's criterion |

## Decision

We chose **A**. Data Vault solves a problem this project does not have: reconciling
conflicting definitions across many source systems. With one source, one business key
and one developer, its hubs and links would be pure overhead — a join layer added for
structure's sake, paid for out of a three-week budget that was better spent on
deduplication, drug resolution and validation.

Medallion also matches the tool split that was already decided: PySpark owns Bronze →
Silver, dbt owns everything above it. A fourth **Semantic** layer was added beyond the
standard three so that the PRR/ROR formulas live in exactly one place, separate from the
dimensional marts.

## Consequences

**Positive:** Every layer is independently rebuildable — a threshold change re-runs two
minutes of dbt, not four hours of Spark. Bronze immutability means a transformation bug
never costs an API re-download. The layer boundaries also gave the failure playbook its
structure: a wrong number can be traced down the layers until it stops being wrong.

**Negative / accepted trade-offs:** No historisation of changed records — the pipeline
keeps only the latest `safetyreportversion` per case and discards superseded versions.
Adding a second source with a different drug identifier would require real modelling work
that Data Vault would have absorbed structurally.

**Revisit if:** a second regulatory source is added (EudraVigilance, VigiBase) with its
own business keys and conflicting reaction dictionaries — that is the point at which Data
Vault's cost starts buying something.
